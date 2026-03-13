"""Main pipeline orchestrator with subprocess isolation.

Architecture:
  - Transcription: runs in-process using persistent WhisperX model (~4 GB VRAM)
  - Everything else: spawns isolated subprocess that exits when done (VRAM freed)

The persistent WhisperX model is loaded once at startup (see whisper_model.py)
and serves both pipeline jobs AND the OpenAI-compatible API on port 9000.
"""

import os
import sys
import json
import subprocess
import threading
import time

from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_redis():
    return Redis.from_url(REDIS_URL)


def _publish_log(job_id: str, line: str, redis_conn=None):
    """Publish a log line to Redis pub/sub and append to a short-lived list for late joiners."""
    try:
        conn = redis_conn or _get_redis()
        key = f"job:{job_id}:logs"
        conn.publish(key, line)
        # Also append to a list so late-connecting clients get recent history
        list_key = f"job:{job_id}:log_history"
        conn.rpush(list_key, line)
        conn.ltrim(list_key, -200, -1)  # Keep last 200 lines
        conn.expire(list_key, 600)  # Expire after 10 min
    except Exception:
        pass  # Never let log publishing break the pipeline


def _log(job_id: str, msg: str, redis_conn=None):
    """Print to stdout AND publish to Redis."""
    print(msg, flush=True)
    _publish_log(job_id, msg, redis_conn)


def log_vram(label: str, job_id: str = None, redis_conn=None):
    """Log VRAM usage via nvidia-smi (no torch import needed)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            used, total = result.stdout.strip().split(", ")
            msg = f"[VRAM] {label}: {used}MB / {total}MB"
            print(msg, flush=True)
            if job_id:
                _publish_log(job_id, msg, redis_conn)
    except Exception:
        pass


def run_pipeline(job_id: str, input_path: str):
    """Entry point called by RQ. Transcribes in-process, rest in subprocess."""
    redis_conn = _get_redis()

    _log(job_id, f"\n{'='*60}", redis_conn)
    _log(job_id, f"[pipeline] Starting job {job_id}", redis_conn)
    _log(job_id, f"[pipeline] Input: {input_path}", redis_conn)
    _log(job_id, f"[pipeline] Mode: hybrid (transcription in-process, rest in subprocess)", redis_conn)
    _log(job_id, f"{'='*60}\n", redis_conn)

    log_vram("before_job", job_id, redis_conn)

    # Mark job as processing
    from sqlalchemy import text
    from db_helper import get_db_session
    db = get_db_session()
    db.execute(
        text("UPDATE jobs SET status = 'PROCESSING', progress = 1, pipeline_stage = 'starting' WHERE id = :id"),
        {"id": job_id}
    )
    db.commit()

    # ── Step 1: Transcribe in-process (persistent WhisperX) ──────────
    db.execute(
        text("UPDATE jobs SET progress = 10, pipeline_stage = 'transcription' WHERE id = :id"),
        {"id": job_id}
    )
    db.commit()
    db.close()

    _log(job_id, "[pipeline] Transcribing with persistent WhisperX model...", redis_conn)
    from whisper_model import transcribe_audio
    tx_result = transcribe_audio(input_path)
    _log(job_id, f"[pipeline] Transcription done: {len(tx_result['segments'])} segments, "
          f"lang={tx_result['language']}", redis_conn)

    log_vram("after_transcription", job_id, redis_conn)

    # ── Step 2: Spawn subprocess for alignment + diarization + rest ───
    # Pass transcription results via stdin to avoid CLI arg limits
    tx_json = json.dumps(tx_result)

    worker_script = os.path.join(os.path.dirname(__file__), "_gpu_worker.py")

    # Stream subprocess stdout line-by-line to both terminal and Redis
    proc = subprocess.Popen(
        [sys.executable, "-u", worker_script, job_id, input_path, "--tx-stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ},
    )

    # Send transcription data to stdin, then close it
    proc.stdin.write(tx_json)
    proc.stdin.close()

    # Stream stdout line by line, filter noise for Redis
    _LOG_PREFIXES = ("[pipeline]", "[speakers]", "[persist]",
                     "[VRAM]", "[GPU]", "[WhisperX]", "[artifacts]",
                     "[whisper]", "[emotion]", "[audio]")
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line:
            print(line, flush=True)
            # Only publish meaningful pipeline lines to Redis (skip DEBUG/INFO/tqdm)
            if any(line.startswith(p) for p in _LOG_PREFIXES) or "COMPLETED" in line or "FAILED" in line:
                _publish_log(job_id, line, redis_conn)

    proc.wait(timeout=3600)

    log_vram("after_job", job_id, redis_conn)

    if proc.returncode != 0:
        # Subprocess failed - update job status if not already failed
        db = get_db_session()
        row = db.execute(
            text("SELECT status FROM jobs WHERE id = :id"),
            {"id": job_id}
        ).fetchone()
        if row and row.status != "FAILED":
            db.execute(
                text("UPDATE jobs SET status = 'FAILED', error_message = 'Pipeline subprocess crashed (exit code: ' || :code || ')' WHERE id = :id"),
                {"id": job_id, "code": str(proc.returncode)}
            )
            db.commit()
        db.close()
        _log(job_id, f"[pipeline] FAILED (exit code {proc.returncode})", redis_conn)
        raise RuntimeError(f"Pipeline subprocess exited with code {proc.returncode}")

    _log(job_id, f"\n{'='*60}", redis_conn)
    _log(job_id, f"[pipeline] Job {job_id} COMPLETED", redis_conn)
    _log(job_id, f"{'='*60}\n", redis_conn)
