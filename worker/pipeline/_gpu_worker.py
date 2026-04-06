"""GPU-isolated pipeline subprocess.

This script runs in a fresh Python process with its own CUDA context.
When it exits (success or failure), ALL GPU memory is freed.
Called by run.py via subprocess.run().

Two modes:
  1. Full pipeline: python _gpu_worker.py <job_id> <input_path>
  2. Post-transcription: python _gpu_worker.py <job_id> <input_path> --tx-stdin
     Reads transcription results from stdin (JSON), skips whisperx load.
"""

import os
import sys
import json
import traceback

# Add worker directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# PyTorch 2.6+ changed torch.load default to weights_only=True
# pyannote/whisperx/speechbrain models use pickle-based checkpoints
import torch
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

import subprocess
import threading
import urllib.parse
import urllib.request
from sqlalchemy import text
from db_helper import get_db_session

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


def get_pipeline_settings() -> dict:
    """Fetch pipeline stage toggles from backend settings API."""
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/api/settings")
        resp = urllib.request.urlopen(req, timeout=5)
        settings = json.loads(resp.read())
        return {
            "alignment": settings.get("pipeline_alignment", True),
            "diarization": settings.get("pipeline_diarization", True),
            "emotion": settings.get("pipeline_emotion", True),
            "speaker_matching": settings.get("pipeline_speaker_matching", True),
            "auto_summary": settings.get("auto_summary", "off"),
            "whisper_model": settings.get("whisper_model", "large-v3"),
            "whisper_prompt": settings.get("whisper_prompt", ""),
            "whisper_persistent": settings.get("whisper_persistent", True),
        }
    except Exception as e:
        print(f"[pipeline] Could not fetch settings, using defaults: {e}", flush=True)
        return {
            "alignment": True, "diarization": True,
            "emotion": True, "speaker_matching": True,
            "auto_summary": "off",
            "whisper_model": os.getenv("WHISPER_MODEL", "large-v3"),
            "whisper_prompt": os.getenv(
                "WHISPER_INITIAL_PROMPT",
                "Natural conversational English with proper punctuation, "
                "including question marks, commas, and periods."
            ),
            "whisper_persistent": True,
        }


def update_job(db, job_id: str, **kwargs):
    """Update job fields (status, progress, pipeline_stage, error_message)."""
    sets = ", ".join(f"{k} = :{k}" for k in kwargs)
    params = {"job_id": job_id, **kwargs}
    db.execute(text(f"UPDATE jobs SET {sets} WHERE id = :job_id"), params)
    db.commit()


def _get_recording_time(input_path: str) -> str | None:
    """Extract recording timestamp from file metadata or mtime."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", input_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            creation_time = info.get("format", {}).get("tags", {}).get("creation_time")
            if creation_time:
                return creation_time
    except Exception:
        pass
    try:
        mtime = os.path.getmtime(input_path)
        from datetime import datetime, timezone
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except Exception:
        return None


def run_gpu_pipeline(job_id: str, input_path: str, tx_result: dict | None = None):
    """Execute the audio intelligence pipeline (post-transcription stages).

    If tx_result is provided, skips transcription and starts from
    alignment + diarization. Otherwise runs the full pipeline.

    This runs inside an isolated subprocess. All GPU models are loaded
    and unloaded within this process. When this function returns (or crashes),
    the process exits and ALL VRAM is freed.
    """
    db = get_db_session()

    try:
        # Fetch pipeline settings to determine which stages to run
        pipe_settings = get_pipeline_settings()
        print(f"[pipeline] Settings: alignment={pipe_settings['alignment']} "
              f"diarization={pipe_settings['diarization']} "
              f"emotion={pipe_settings['emotion']} "
              f"speakers={pipe_settings['speaker_matching']} "
              f"auto_summary={pipe_settings['auto_summary']} "
              f"whisper_model={pipe_settings['whisper_model']} "
              f"whisper_persistent={pipe_settings['whisper_persistent']}", flush=True)

        # ── Stage 1: Audio Processing (5%) ──────────────────────
        update_job(db, job_id, status="PROCESSING", progress=5,
                   pipeline_stage="audio_processing")
        print("[pipeline] Stage 1/9: Audio processing...", flush=True)

        from pipeline.audio import process_audio
        wav_path, opus_path = process_audio(input_path, job_id)
        print(f"[pipeline] Audio ready: {wav_path}", flush=True)

        # ── Stage 2-4: Transcription + Alignment + Diarization (15-40%) ──
        if tx_result is not None:
            # Transcription already done in main process (persistent WhisperX)
            update_job(db, job_id, progress=20, pipeline_stage="alignment")
            print("[pipeline] Stage 2/9: Transcription (pre-computed, skipped)", flush=True)

            if pipe_settings["alignment"] or pipe_settings["diarization"]:
                print("[pipeline] Stage 3-4/9: Alignment + diarization...", flush=True)
                from pipeline.transcription import align_and_diarize
                result = align_and_diarize(
                    wav_path, tx_result, job_id,
                    do_align=pipe_settings["alignment"],
                    do_diarize=pipe_settings["diarization"],
                )
                segments = result["segments"]
                language = result["language"]
            else:
                print("[pipeline] Stage 3-4/9: Alignment + diarization SKIPPED", flush=True)
                segments = tx_result["segments"]
                language = tx_result["language"]
        else:
            # Full pipeline mode (one-shot) - load whisperx in this subprocess
            # Use settings-based model name and prompt
            settings_model = pipe_settings.get("whisper_model", "").strip()
            settings_prompt = pipe_settings.get("whisper_prompt", "").strip()

            update_job(db, job_id, progress=15, pipeline_stage="transcription")
            print(f"[pipeline] Stage 2-4/9: Transcription + alignment + diarization "
                  f"(one-shot, model={settings_model or 'default'})...", flush=True)

            from pipeline.transcription import transcribe
            result = transcribe(
                wav_path, job_id,
                model_name=settings_model if settings_model else None,
                initial_prompt=settings_prompt if settings_prompt else None,
            )
            segments = result["segments"]
            language = result["language"]

        print(f"[pipeline] Transcription complete: {len(segments)} segments, lang={language}", flush=True)
        update_job(db, job_id, progress=40)

        # ── Stage 5: Emotion Detection (55%) ────────────────────
        if pipe_settings["emotion"]:
            update_job(db, job_id, progress=45, pipeline_stage="emotion_detection")
            print("[pipeline] Stage 5/9: Emotion detection...", flush=True)

            from pipeline.emotion import detect_emotions
            emotions = detect_emotions(wav_path, segments, job_id)
            print(f"[pipeline] Emotions detected for {len(emotions)} segments", flush=True)
        else:
            print("[pipeline] Stage 5/9: Emotion detection SKIPPED", flush=True)
            emotions = []

        update_job(db, job_id, progress=55)

        # ── Stage 6: Speaker Embeddings (70%) ───────────────────
        if pipe_settings["speaker_matching"]:
            update_job(db, job_id, progress=60, pipeline_stage="speaker_embeddings")
            print("[pipeline] Stage 6/9: Speaker embedding extraction + matching...", flush=True)

            from pipeline.speakers import match_speakers
            speaker_map, speaker_names = match_speakers(wav_path, segments, job_id, db)
            print(f"[pipeline] Speaker matching complete: {len(speaker_map)} speakers", flush=True)
        else:
            print("[pipeline] Stage 6/9: Speaker matching SKIPPED", flush=True)
            speaker_map = {}
            speaker_names = {}

        update_job(db, job_id, progress=70)

        # ── Stage 7: Persist to DB (85%) ────────────────────────
        update_job(db, job_id, progress=75, pipeline_stage="persisting")
        print("[pipeline] Stage 7/9: Persisting results...", flush=True)

        from pipeline.persist import persist_results
        events = []  # No event detection stage currently
        transcript_id = persist_results(
            job_id, language, segments, speaker_map,
            emotions, events, wav_path, opus_path, db,
        )
        print(f"[pipeline] Persisted transcript {transcript_id}", flush=True)

        update_job(db, job_id, progress=85)

        # ── Stage 8: Output Files (90%) ─────────────────────────
        update_job(db, job_id, progress=88, pipeline_stage="generating_artifacts")
        print("[pipeline] Stage 8/9: Generating output files...", flush=True)

        from pipeline.artifacts import generate_artifacts
        artifact_paths = generate_artifacts(
            job_id, segments, speaker_map, emotions, events, language,
            speaker_names=speaker_names,
        )
        print(f"[pipeline] Artifacts: {artifact_paths}", flush=True)

        update_job(db, job_id, progress=90)

        # ── Stage 9: LLM Metadata (95%, optional) ──────────────
        first_text = segments[0].get("text", "").strip()[:100] if segments else ""
        if first_text:
            db.execute(
                text("UPDATE transcripts SET title = :title WHERE id = :id"),
                {"title": first_text, "id": transcript_id},
            )
            db.commit()

        # ── Calendar match (auto-name from meeting) ──────────────
        recording_time = _get_recording_time(input_path)
        if recording_time:
            try:
                url = f"{BACKEND_URL}/api/calendar/match?ts={urllib.parse.quote(recording_time)}"
                req = urllib.request.Request(url)
                resp = urllib.request.urlopen(req, timeout=10)
                cal_data = json.loads(resp.read())
                if cal_data.get("matched"):
                    event_title = cal_data["event_title"]
                    date_str = recording_time[:10]
                    cal_title = f"Meeting: {event_title} {date_str}"
                    db.execute(
                        text("UPDATE transcripts SET title = :title WHERE id = :id"),
                        {"title": cal_title, "id": transcript_id},
                    )
                    db.execute(
                        text("UPDATE jobs SET params = params || :lock WHERE id = :jid"),
                        {"lock": json.dumps({"title_locked": True}), "jid": job_id},
                    )
                    db.commit()
                    print(f"[pipeline] Calendar match: {cal_title}", flush=True)
            except Exception as e:
                print(f"[pipeline] Calendar match failed (non-fatal): {e}", flush=True)

        # ── Done! ───────────────────────────────────────────────
        update_job(db, job_id, status="COMPLETED", progress=100,
                   pipeline_stage="completed")

        print(f"[pipeline] Job {job_id} COMPLETED in subprocess", flush=True)

        # Clean up large video source files now that job succeeded.
        # Audio inputs are kept (small). This is safe because the opus archive
        # and playback m4a have already been created.
        from pipeline.audio import has_video_stream
        from pathlib import Path
        try:
            if has_video_stream(input_path):
                input_size = Path(input_path).stat().st_size
                Path(input_path).unlink()
                print(f"[pipeline] Deleted video source ({input_size / 1048576:.1f} MB): {input_path}", flush=True)
        except OSError:
            pass

        # Fire-and-forget: index transcript for semantic search
        def _ingest():
            try:
                url = f"{BACKEND_URL}/api/semantic/ingest/{transcript_id}"
                req = urllib.request.Request(url, method="POST")
                urllib.request.urlopen(req, timeout=60)
                print(f"[pipeline] Indexed transcript {transcript_id} in Qdrant", flush=True)
            except Exception as e:
                print(f"[pipeline] Qdrant ingest failed (non-fatal): {e}", flush=True)

        threading.Thread(target=_ingest, daemon=True).start()

        # Auto-generate summary if enabled (synchronous — must finish before subprocess exits)
        auto_summary = pipe_settings.get("auto_summary", "off")
        if auto_summary != "off":
            try:
                should_summarize = True
                if auto_summary == "known_speakers_only":
                    # Check if all speakers in this transcript are recognized
                    rows = db.execute(
                        text("""
                            SELECT DISTINCT s.is_trusted, s.name
                            FROM segments seg
                            JOIN speakers s ON s.id = seg.speaker_id
                            WHERE seg.transcript_id = :tid
                        """),
                        {"tid": transcript_id},
                    ).fetchall()
                    if not rows:
                        should_summarize = False
                        print(f"[pipeline] Auto-summary: no speakers found, skipping", flush=True)
                    else:
                        unrecognized = [r.name for r in rows if not r.is_trusted]
                        if unrecognized:
                            should_summarize = False
                            print(f"[pipeline] Auto-summary: unrecognized speakers ({', '.join(unrecognized)}), skipping", flush=True)

                if should_summarize:
                    print(f"[pipeline] Auto-summary: generating overview...", flush=True)
                    url = f"{BACKEND_URL}/api/transcripts/{transcript_id}/generate-overview"
                    req = urllib.request.Request(url, method="POST")
                    urllib.request.urlopen(req, timeout=120)
                    print(f"[pipeline] Auto-summary: done", flush=True)
            except Exception as e:
                print(f"[pipeline] Auto-summary failed (non-fatal): {e}", flush=True)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"\n[pipeline] FAILED: {error_msg}", flush=True)
        traceback.print_exc()

        try:
            update_job(db, job_id, status="FAILED", error_message=error_msg[:1000])
        except Exception:
            print("[pipeline] Could not update job status to failed", flush=True)

        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <job_id> <input_path> [--tx-stdin]", flush=True)
        sys.exit(1)

    job_id = sys.argv[1]
    input_path = sys.argv[2]
    tx_result = None

    if "--tx-stdin" in sys.argv:
        # Read pre-computed transcription from stdin
        tx_json = sys.stdin.read()
        tx_result = json.loads(tx_json)
        print(f"[pipeline] Received pre-computed transcription: "
              f"{len(tx_result['segments'])} segments, lang={tx_result['language']}", flush=True)

    run_gpu_pipeline(job_id, input_path, tx_result=tx_result)
