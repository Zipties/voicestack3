"""RQ job that spawns verify subprocess and stores result in Redis.

The subprocess pattern ensures VRAM is fully freed after each verification.
Result is stored in Redis with a 2-minute TTL for the backend to poll.
"""

import os
import sys
import json
import subprocess

from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def run_verify_job(job_key: str, audio_path: str, threshold: float = None,
                   min_duration: float = 2.0):
    """Called by RQ worker. Spawns subprocess, stores result in Redis."""
    redis_conn = Redis.from_url(REDIS_URL)

    try:
        worker_script = os.path.join(os.path.dirname(__file__), "_verify_worker.py")
        args = [sys.executable, "-u", worker_script, audio_path]
        if threshold is not None:
            args.append(str(threshold))
            args.append(str(min_duration))

        print(f"[verify-job] Starting subprocess for {job_key}", flush=True)

        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=300,
            env={**os.environ},
        )

        if proc.returncode != 0:
            error_msg = proc.stderr[-500:] if proc.stderr else "Unknown error"
            print(f"[verify-job] Subprocess failed: {error_msg}", flush=True)
            redis_conn.set(job_key, json.dumps({
                "error": f"Verify subprocess failed: {error_msg}"
            }), ex=120)
            return

        # Last line of stdout is the JSON result
        lines = proc.stdout.strip().split("\n")
        result_json = lines[-1]

        # Validate it's actual JSON
        json.loads(result_json)

        redis_conn.set(job_key, result_json, ex=120)  # TTL 2 min
        print(f"[verify-job] Result stored for {job_key}", flush=True)

    except subprocess.TimeoutExpired:
        print(f"[verify-job] Timeout for {job_key}", flush=True)
        redis_conn.set(job_key, json.dumps({
            "error": "Verification timed out (300s)"
        }), ex=120)
    except Exception as e:
        print(f"[verify-job] Error for {job_key}: {e}", flush=True)
        redis_conn.set(job_key, json.dumps({
            "error": str(e)
        }), ex=120)
