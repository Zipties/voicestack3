"""VoiceStack3 Worker - WhisperX stays hot, other models unload per job.

Architecture:
  - Persistent mode: WhisperX loaded once at startup (~4 GB VRAM, ~6 GB peak)
  - One-shot mode: No persistent model, each job loads/unloads its own model
  - Pipeline jobs: transcription in-process (persistent) or subprocess (one-shot)
  - OpenAI + Wyoming compatible transcription endpoints on port 9000 (persistent only)
  - RQ worker processes pipeline jobs from Redis queue

Port 9000 serves (persistent mode only):
  POST /v1/audio/transcriptions  (OpenAI Whisper API compatible)
  Wyoming protocol (TODO: separate port for HA integration)
"""

import os
import sys
import json
import threading
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from redis import Redis
from rq import SimpleWorker, Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
API_PORT = int(os.getenv("WHISPER_API_PORT", "9000"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


def _fetch_persistent_setting() -> bool:
    """Fetch whisper_persistent from backend settings API with retries.

    Retries 3 times with 5-second delays (backend may not be ready at startup).
    Falls back to env var / default (True) on failure.
    """
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"{BACKEND_URL}/api/settings")
            resp = urllib.request.urlopen(req, timeout=5)
            settings = json.loads(resp.read())
            return settings.get("whisper_persistent", True)
        except Exception as e:
            print(f"[worker] Settings fetch attempt {attempt + 1}/3 failed: {e}", flush=True)
            if attempt < 2:
                time.sleep(5)

    # Fall back to env var or default
    fallback = os.getenv("WHISPER_PERSISTENT", "true").lower() in ("true", "1", "yes")
    print(f"[worker] Could not reach backend, using fallback persistent={fallback}", flush=True)
    return fallback


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
            elif self.path == "/v1/audio/process":
                self._handle_process()
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

        def _handle_process(self):
            """Ephemeral audio processing — transcribe + optional alignment.

            Returns results directly, no DB persistence. Designed for external
            apps that need transcription/word-timings without VS3 job overhead.

            Form params:
              file: audio file (required)
              alignment: "true" to include word-level timestamps (default: false)
              diarization: "true" to include speaker labels (default: false)
              language: language code override (default: auto-detect)
              prompt: initial prompt for Whisper
              response_format: "json" (default) or "verbose_json"
            """
            import time as _time
            t0 = _time.time()
            try:
                content_type = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in content_type:
                    self.send_error(400, "Expected multipart/form-data")
                    return

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

                do_align = form.getvalue("alignment", "false") in ("true", "1", "yes")
                do_diarize = form.getvalue("diarization", "false") in ("true", "1", "yes")
                language = form.getvalue("language", None)
                initial_prompt = form.getvalue("prompt", None)
                response_format = form.getvalue("response_format", "verbose_json")

                suffix = Path(filename).suffix or ".wav"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as f:
                    f.write(audio_data)
                    tmp_path = f.name

                try:
                    # Step 1: Transcribe with persistent WhisperX
                    from whisper_model import transcribe_audio
                    tx_result = transcribe_audio(
                        tmp_path,
                        language=language,
                        initial_prompt=initial_prompt,
                    )
                    t_tx = _time.time()
                    print(f"[process-api] Transcription: {t_tx - t0:.2f}s, "
                          f"{len(tx_result['segments'])} segments", flush=True)

                    # Step 2: Alignment / diarization (in-process, models freed after)
                    if do_align or do_diarize:
                        from pipeline.transcription import align_and_diarize
                        result = align_and_diarize(
                            tmp_path, tx_result, "ephemeral",
                            do_align=do_align,
                            do_diarize=do_diarize,
                        )
                        segments = result["segments"]
                        lang = result["language"]
                        t_post = _time.time()
                        print(f"[process-api] Post-processing: {t_post - t_tx:.2f}s "
                              f"(align={do_align}, diarize={do_diarize})", flush=True)
                    else:
                        segments = tx_result["segments"]
                        lang = tx_result["language"]

                    # Build response
                    text = " ".join(
                        seg.get("text", "").strip() for seg in segments
                    ).strip()

                    if response_format == "verbose_json":
                        seg_list = []
                        for i, seg in enumerate(segments):
                            s = {
                                "id": i,
                                "start": seg.get("start", 0),
                                "end": seg.get("end", 0),
                                "text": seg.get("text", "").strip(),
                            }
                            if do_align and "words" in seg:
                                s["words"] = [
                                    {"word": w.get("word", ""), "start": w.get("start", 0), "end": w.get("end", 0)}
                                    for w in seg["words"]
                                ]
                            if do_diarize and "speaker" in seg:
                                s["speaker"] = seg["speaker"]
                            seg_list.append(s)
                        response = {
                            "text": text,
                            "language": lang,
                            "segments": seg_list,
                        }
                    else:
                        response = {"text": text}

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(response).encode())
                    print(f"[process-api] Total: {_time.time() - t0:.2f}s", flush=True)

                finally:
                    os.unlink(tmp_path)

            except Exception as e:
                print(f"[process-api] Error: {e}", flush=True)
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, format, *args):
            print(f"[whisper-api] {args[0]}", flush=True)

    server = HTTPServer(("0.0.0.0", API_PORT), TranscriptionHandler)
    print(f"[whisper-api] OpenAI-compatible endpoint on :{API_PORT}", flush=True)
    print(f"[whisper-api]   POST /v1/audio/transcriptions  (OpenAI compat)", flush=True)
    print(f"[whisper-api]   POST /v1/audio/process        (ephemeral, align+diarize)", flush=True)
    print(f"[whisper-api]   POST /audio/transcriptions     (whisper.cpp compat)", flush=True)
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
    # Check persistent mode setting
    is_persistent = _fetch_persistent_setting()
    mode_label = "persistent" if is_persistent else "one-shot"

    print("=" * 60, flush=True)
    print("VoiceStack3 Worker", flush=True)
    print(f"  WhisperX mode: {mode_label}", flush=True)
    if is_persistent:
        print("  WhisperX: persistent (stays in VRAM)", flush=True)
        print("  Other models: per-job subprocess (unload after use)", flush=True)
    else:
        print("  WhisperX: one-shot (load/unload per job in subprocess)", flush=True)
        print("  All models: per-job subprocess (unload after use)", flush=True)
    print("=" * 60, flush=True)

    # Clean up any jobs left in PROCESSING from a previous crash
    cleanup_stale_jobs()

    if is_persistent:
        # Persistent mode: warmup model + start API server
        from whisper_model import warmup
        warmup()

        # Start transcription API server in background thread
        api_thread = threading.Thread(target=start_transcription_api, daemon=True)
        api_thread.start()
    else:
        print("[worker] One-shot mode: skipping model warmup and API server", flush=True)

    # Start RQ worker for pipeline jobs
    conn = Redis.from_url(REDIS_URL)
    queues = [Queue("voicestack", connection=conn)]
    worker = SimpleWorker(queues, connection=conn, name="vs3-gpu-worker")
    print("[rq] Listening on voicestack queue...", flush=True)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
