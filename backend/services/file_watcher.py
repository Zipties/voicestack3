"""File watcher service - polls a directory for new audio files and auto-ingests them.

Runs as a background thread in the FastAPI process. Hot-reloadable: checks settings
each cycle so enable/disable/path changes take effect without restart.
"""

import os
import shutil
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from redis import Redis
from rq import Queue
from sqlalchemy import text

from db.session import SessionLocal
from services.settings import get_settings

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

_watcher_thread: threading.Thread | None = None
_last_scan_time: float = 0
_files_processed: int = 0


def _get_queue() -> Queue:
    conn = Redis.from_url(REDIS_URL)
    return Queue("voicestack", connection=conn)


def _scan_directory() -> list[dict]:
    """Scan the watched directory for new files. Returns list of ingested file info."""
    global _last_scan_time, _files_processed

    settings = get_settings()
    if not settings.get("file_watcher_enabled"):
        return []

    watch_path = settings.get("file_watcher_path", "").strip()
    if not watch_path:
        return []

    watch_dir = Path(os.path.expanduser(watch_path))
    if not watch_dir.is_dir():
        print(f"[watcher] Directory not found: {watch_dir}", flush=True)
        return []

    extensions = {
        e.strip().lower()
        for e in settings.get("file_watcher_extensions", "").split(",")
        if e.strip()
    }
    min_size = settings.get("file_watcher_min_size_kb", 10) * 1024
    cooldown = settings.get("file_watcher_cooldown_seconds", 120)
    now = time.time()

    ingested = []
    db = SessionLocal()
    try:
        for filepath in watch_dir.iterdir():
            if not filepath.is_file():
                continue

            suffix = filepath.suffix.lower()
            if suffix not in extensions:
                continue

            stat = filepath.stat()
            if stat.st_size < min_size:
                continue

            if (now - stat.st_mtime) < cooldown:
                continue  # Still being written

            # Check if already processed
            abs_path = str(filepath.resolve())
            existing = db.execute(
                text("SELECT id FROM watched_files WHERE file_path = :path"),
                {"path": abs_path},
            ).fetchone()
            if existing:
                continue

            # Ingest: copy to data dir, create job + asset, enqueue pipeline
            try:
                input_dir = DATA_DIR / "inputs"
                input_dir.mkdir(parents=True, exist_ok=True)

                job_id = uuid.uuid4()
                safe_filename = f"{job_id}_{filepath.name}"
                dest = input_dir / safe_filename
                shutil.copy2(filepath, dest)

                # Create job record
                db.execute(
                    text("""
                        INSERT INTO jobs (id, status, progress)
                        VALUES (:id, 'QUEUED', 0)
                    """),
                    {"id": str(job_id)},
                )

                # Create asset record
                asset_id = uuid.uuid4()
                db.execute(
                    text("""
                        INSERT INTO assets (id, job_id, filename, mimetype, size_bytes, input_path)
                        VALUES (:id, :job_id, :filename, :mimetype, :size_bytes, :input_path)
                    """),
                    {
                        "id": str(asset_id),
                        "job_id": str(job_id),
                        "filename": filepath.name,
                        "mimetype": _guess_mimetype(suffix),
                        "size_bytes": stat.st_size,
                        "input_path": str(dest),
                    },
                )

                # Track as processed
                db.execute(
                    text("""
                        INSERT INTO watched_files (file_path, file_size, file_mtime, job_id)
                        VALUES (:path, :size, :mtime, :job_id)
                    """),
                    {
                        "path": abs_path,
                        "size": stat.st_size,
                        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        "job_id": str(job_id),
                    },
                )

                db.commit()

                # Enqueue pipeline
                queue = _get_queue()
                queue.enqueue(
                    "pipeline.run.run_pipeline",
                    str(job_id),
                    str(dest),
                    job_timeout="1h",
                )

                _files_processed += 1
                ingested.append({"file": filepath.name, "job_id": str(job_id)})
                print(f"[watcher] Ingested: {filepath.name} → job {job_id}", flush=True)

            except Exception as e:
                db.rollback()
                print(f"[watcher] Error ingesting {filepath.name}: {e}", flush=True)

    finally:
        db.close()

    _last_scan_time = now
    return ingested


def _guess_mimetype(suffix: str) -> str:
    return {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".opus": "audio/opus",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }.get(suffix, "application/octet-stream")


def _watcher_loop():
    """Main loop: poll directory at configured interval."""
    print("[watcher] Background thread started", flush=True)
    while True:
        try:
            settings = get_settings()
            interval = settings.get("file_watcher_poll_interval_seconds", 30)

            if settings.get("file_watcher_enabled") and settings.get("file_watcher_path"):
                _scan_directory()

            time.sleep(interval)
        except Exception as e:
            print(f"[watcher] Error in poll loop: {e}", flush=True)
            time.sleep(30)


def start_watcher():
    """Start the file watcher background thread (idempotent)."""
    global _watcher_thread
    if _watcher_thread is not None and _watcher_thread.is_alive():
        return

    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True, name="file-watcher")
    _watcher_thread.start()


def get_watcher_status() -> dict:
    """Return current watcher status for the API."""
    settings = get_settings()
    return {
        "enabled": settings.get("file_watcher_enabled", False),
        "path": settings.get("file_watcher_path", ""),
        "files_processed": _files_processed,
        "last_scan": datetime.fromtimestamp(_last_scan_time, tz=timezone.utc).isoformat() if _last_scan_time else None,
        "thread_alive": _watcher_thread is not None and _watcher_thread.is_alive() if _watcher_thread else False,
    }


def force_scan() -> list[dict]:
    """Force an immediate scan (called from API). Returns list of ingested files."""
    return _scan_directory()
