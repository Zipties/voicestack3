"""VoiceStack3 Worker - WhisperX stays hot, other models unload per job.

Architecture:
  - WhisperX loaded once at startup (~4 GB VRAM, ~6 GB peak)
  - Pipeline jobs: transcription in-process, everything else in subprocess
  - OpenAI + Wyoming compatible transcription endpoints on port 9000
  - RQ worker processes pipeline jobs from Redis queue

Port 9000 serves:
  POST /v1/audio/transcriptions  (OpenAI Whisper API compatible)
  Wyoming protocol (TODO: separate port for HA integration)
"""

import os
import sys
import json
import threading
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from redis import Redis
from rq import SimpleWorker, Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
API_PORT = int(os.getenv("WHISPER_API_PORT", "9000"))


def start_transcription_api():
    """Start the OpenAI-compatible transcription API in a background thread."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import cgi

    class TranscriptionHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/v1/audio/transcriptions":
                self._handle_transcription()
            elif self.path == "/audio/transcriptions":
                # Also accept without /v1 prefix (whisper.cpp compat)
                self._handle_transcription()
            else:
                self.send_error(404)

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "model": "whisperx"}).encode())
            else:
                self.send_error(404)

        def _handle_transcription(self):
            """Handle OpenAI-compatible audio transcription request."""
            import time as _time
            t_req_start = _time.time()
            try:
                content_type = self.headers.get("Content-Type", "")

                if "multipart/form-data" in content_type:
                    # Parse multipart form (file upload)
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={
                            "REQUEST_METHOD": "POST",
                            "CONTENT_TYPE": content_type,
                        },
                    )

                    file_field = form["file"]
                    audio_data = file_field.file.read()
                    filename = file_field.filename or "audio.wav"

                    # Parse optional parameters (OpenAI Whisper API compatible + extensions)
                    response_format = form.getvalue("response_format", "json")
                    language = form.getvalue("language", None)
                    initial_prompt = form.getvalue("prompt", None)

                    # Extended params (not in OpenAI spec, but useful for tuning)
                    beam_size_str = form.getvalue("beam_size", None)
                    beam_size = int(beam_size_str) if beam_size_str else None
                    cond_prev_str = form.getvalue("condition_on_previous_text", None)
                    condition_on_previous_text = cond_prev_str in ("true", "1", "yes") if cond_prev_str else None
                else:
                    self.send_error(400, "Expected multipart/form-data")
                    return

                # Save to temp file
                t_parse_done = _time.time()
                suffix = Path(filename).suffix or ".wav"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as f:
                    f.write(audio_data)
                    tmp_path = f.name
                t_save_done = _time.time()

                try:
                    # Transcribe using persistent model
                    from whisper_model import transcribe_audio
                    result = transcribe_audio(
                        tmp_path,
                        language=language,
                        initial_prompt=initial_prompt,
                        beam_size=beam_size,
                        condition_on_previous_text=condition_on_previous_text,
                    )
                    t_transcribe_done = _time.time()

                    text = " ".join(
                        seg.get("text", "").strip()
                        for seg in result["segments"]
                    ).strip()

                    # OpenAI-compatible response
                    if response_format == "verbose_json":
                        response = {
                            "text": text,
                            "language": result["language"],
                            "segments": [
                                {
                                    "id": i,
                                    "start": seg.get("start", 0),
                                    "end": seg.get("end", 0),
                                    "text": seg.get("text", "").strip(),
                                }
                                for i, seg in enumerate(result["segments"])
                            ],
                        }
                    else:
                        response = {"text": text}

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(response).encode())
                    t_resp = _time.time()
                    print(f"[whisper-api] Timing: parse={t_parse_done - t_req_start:.1f}s, "
                          f"save={t_save_done - t_parse_done:.1f}s, "
                          f"transcribe={t_transcribe_done - t_save_done:.1f}s, "
                          f"respond={t_resp - t_transcribe_done:.1f}s, "
                          f"total={t_resp - t_req_start:.1f}s", flush=True)

                finally:
                    os.unlink(tmp_path)

            except Exception as e:
                print(f"[whisper-api] Error: {e}", flush=True)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, format, *args):
            print(f"[whisper-api] {args[0]}", flush=True)

    server = HTTPServer(("0.0.0.0", API_PORT), TranscriptionHandler)
    print(f"[whisper-api] OpenAI-compatible endpoint on :{API_PORT}", flush=True)
    print(f"[whisper-api]   POST /v1/audio/transcriptions", flush=True)
    print(f"[whisper-api]   POST /audio/transcriptions", flush=True)
    print(f"[whisper-api]   GET  /health", flush=True)
    server.serve_forever()


def cleanup_stale_jobs():
    """Mark any jobs stuck in PROCESSING for >30 min as FAILED on startup.

    This handles the case where the worker crashed (OOM, segfault, etc.)
    without updating job status.
    """
    try:
        from db_helper import get_db_session
        from sqlalchemy import text
        db = get_db_session()
        result = db.execute(
            text("""UPDATE jobs
                    SET status = 'FAILED',
                        error_message = 'Worker restarted while job was processing (likely OOM or crash)'
                    WHERE status = 'PROCESSING'
                    AND updated_at < NOW() - INTERVAL '30 minutes'
                    RETURNING id""")
        )
        stale = result.fetchall()
        db.commit()
        db.close()
        if stale:
            ids = [str(row[0])[:8] for row in stale]
            print(f"[cleanup] Marked {len(stale)} stale jobs as FAILED: {', '.join(ids)}", flush=True)
        else:
            print("[cleanup] No stale jobs found", flush=True)
    except Exception as e:
        print(f"[cleanup] Warning: could not clean stale jobs: {e}", flush=True)


def main():
    # Load WhisperX model into VRAM before anything else
    print("=" * 60, flush=True)
    print("VoiceStack3 Worker", flush=True)
    print("  WhisperX: persistent (stays in VRAM)", flush=True)
    print("  Other models: per-job subprocess (unload after use)", flush=True)
    print("=" * 60, flush=True)

    # Clean up any jobs left in PROCESSING from a previous crash
    cleanup_stale_jobs()

    from whisper_model import warmup
    warmup()

    # Start transcription API server in background thread
    api_thread = threading.Thread(target=start_transcription_api, daemon=True)
    api_thread.start()

    # Start RQ worker for pipeline jobs
    conn = Redis.from_url(REDIS_URL)
    queues = [Queue("voicestack", connection=conn)]
    worker = SimpleWorker(queues, connection=conn, name="vs3-gpu-worker")
    print("[rq] Listening on voicestack queue...", flush=True)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
