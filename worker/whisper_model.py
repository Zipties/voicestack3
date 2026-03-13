"""WhisperX model manager with idle auto-unload.

Loads WhisperX on first request, unloads after idle timeout to free VRAM.
~4 GB VRAM when loaded, ~6 GB peak during transcription. On a 24 GB RTX 4090
that leaves 18+ GB for other workloads when idle.

The model lock ensures:
  - No unload while a transcription is in progress
  - No concurrent loads (double-checked locking)
  - Thread-safe for both API requests and pipeline jobs

Benchmarks (3 min audio, large-v2, float16, RTX 4090):
  Cold load: ~3.6s
  Warm transcription: ~1.3s (139x realtime)
"""

import os
import gc
import time
import threading
from dataclasses import replace as dc_replace

# PyTorch 2.6+ safe loading fix - must be applied before any model loads
import torch
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

import whisperx

_model = None
_model_lock = threading.Lock()
_last_used: float = 0.0
_reaper_started = False
_parked_on_cpu = False  # True when model is offloaded to CPU RAM

if torch.cuda.is_available():
    DEVICE = "cuda"
    COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    DEVICE = "cpu"  # CTranslate2 doesn't support MPS, force CPU
    COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
else:
    DEVICE = "cpu"
    COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")
BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "16"))
BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "8"))
LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en")
INITIAL_PROMPT = os.getenv(
    "WHISPER_INITIAL_PROMPT",
    "Natural conversational English with proper punctuation, "
    "including question marks, commas, and periods. "
    "Tech terms: Traefik, Proxmox, Docker, Authelia, Radarr, Sonarr, "
    "Readarr, Bazarr, Prowlarr, Piflix, Overseerr, Tautulli, Plex, "
    "Frigate, qBittorrent, SABnzbd, TrueNAS, ZFS, UniFi, pfSense, "
    "VLAN, nginx, systemd, Podman, Redis, PostgreSQL, WhisperX."
)
CACHE_DIR = os.getenv("WHISPER_CACHE_DIR", "/app/model_cache/whisper")
IDLE_TIMEOUT = int(os.getenv("WHISPER_IDLE_TIMEOUT", "1800"))  # 30 min default


def _start_reaper():
    """Start background thread that unloads model after idle timeout."""
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True

    def _reaper_loop():
        global _model, _last_used
        while True:
            time.sleep(60)  # Check every minute

            if IDLE_TIMEOUT <= 0:
                continue  # Disabled, never unload

            if _model is None:
                continue  # Nothing to unload

            idle_seconds = time.time() - _last_used
            if idle_seconds < IDLE_TIMEOUT:
                continue  # Still within timeout

            # Try to acquire lock - if someone is transcribing, skip this cycle
            if not _model_lock.acquire(blocking=False):
                continue

            try:
                # Double-check after acquiring lock
                if _model is None:
                    continue
                idle_seconds = time.time() - _last_used
                if idle_seconds < IDLE_TIMEOUT:
                    continue

                global _parked_on_cpu
                if _parked_on_cpu:
                    continue  # Already offloaded

                print(f"[whisper] Idle for {idle_seconds:.0f}s (timeout: {IDLE_TIMEOUT}s), "
                      f"offloading model to CPU RAM...", flush=True)
                t0 = time.time()
                _model.model.model.unload_model(to_cpu=True)
                _parked_on_cpu = True
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print(f"[whisper] Model offloaded to CPU in {time.time()-t0:.1f}s. VRAM freed.", flush=True)
            finally:
                _model_lock.release()

    t = threading.Thread(target=_reaper_loop, daemon=True, name="whisper-reaper")
    t.start()
    print(f"[whisper] Idle reaper started (timeout: {IDLE_TIMEOUT}s)", flush=True)


def _ensure_model():
    """Load model if not already loaded. Caller MUST hold _model_lock."""
    global _model, _last_used, _parked_on_cpu

    if _model is not None and _parked_on_cpu:
        t0 = time.time()
        print(f"[whisper] Resuming model from CPU RAM...", flush=True)
        _model.model.model.load_model()
        _parked_on_cpu = False
        _last_used = time.time()
        print(f"[whisper] Model resumed in {time.time()-t0:.1f}s.", flush=True)
        return _model

    if _model is not None:
        return _model

    t0 = time.time()
    print(f"[whisper] Loading {MODEL_NAME} ({COMPUTE_TYPE}) on {DEVICE}, "
          f"lang={LANGUAGE}, beam={BEAM_SIZE}...", flush=True)
    _model = whisperx.load_model(
        MODEL_NAME,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        language=LANGUAGE,
        asr_options={
            "beam_size": BEAM_SIZE,
            "initial_prompt": INITIAL_PROMPT if INITIAL_PROMPT else None,
        },
        download_root=CACHE_DIR,
    )
    _last_used = time.time()
    load_time = _last_used - t0
    print(f"[whisper] Model loaded in {load_time:.1f}s. beam_size={BEAM_SIZE}, "
          f"initial_prompt={'set' if INITIAL_PROMPT else 'none'}", flush=True)
    return _model


def transcribe_audio(
    audio_path: str,
    language: str | None = None,
    initial_prompt: str | None = None,
    beam_size: int | None = None,
    condition_on_previous_text: bool | None = None,
) -> dict:
    """Transcribe audio using the model (loads on demand if unloaded).

    Args:
        audio_path: Path to audio file (any format ffmpeg supports)
        language: Override language (default: server LANGUAGE env var)
        initial_prompt: Override initial prompt (default: server INITIAL_PROMPT env var)
        beam_size: Override beam size (default: server BEAM_SIZE env var)
        condition_on_previous_text: Use previous segment as context (default: False)

    Returns:
        {"segments": [...], "language": "en"}

    This is ONLY transcription - no alignment, no diarization.
    Those run in the per-job subprocess.

    The lock is held for the entire load+transcribe cycle, which:
    - Prevents the reaper from unloading mid-inference
    - Prevents concurrent transcriptions from fighting over GPU
    - Serializes API requests (fine - each takes ~1s)
    """
    global _last_used

    lang = language or LANGUAGE
    prompt = initial_prompt if initial_prompt is not None else INITIAL_PROMPT
    beams = beam_size if beam_size is not None else BEAM_SIZE
    cond_prev = condition_on_previous_text if condition_on_previous_text is not None else False

    t_start = time.time()
    was_cold = _model is None
    was_parked = _parked_on_cpu

    with _model_lock:
        t_lock = time.time()
        model = _ensure_model()
        t_model = time.time()

        # Per-request overrides: temporarily swap model options
        overrides = {}
        if prompt != INITIAL_PROMPT:
            overrides["initial_prompt"] = prompt if prompt else None
        if beams != BEAM_SIZE:
            overrides["beam_size"] = beams
        if cond_prev:
            overrides["condition_on_previous_text"] = True

        saved_options = None
        if overrides:
            saved_options = model.options
            model.options = dc_replace(model.options, **overrides)

        try:
            t_audio_start = time.time()
            audio = whisperx.load_audio(audio_path)
            t_audio_done = time.time()
            result = model.transcribe(audio, batch_size=BATCH_SIZE, language=lang)
        finally:
            if saved_options is not None:
                model.options = saved_options

        _last_used = time.time()

    t_done = time.time()
    lock_wait = t_lock - t_start
    model_load = t_model - t_lock
    audio_load = t_audio_done - t_audio_start
    inference = t_done - t_audio_done
    total = t_done - t_start
    cold_tag = " [COLD START]" if was_cold else " [CPU RESUME]" if was_parked else ""
    print(f"[whisper] Transcribe done: lock={lock_wait:.1f}s, model={model_load:.1f}s, "
          f"audio={audio_load:.1f}s, inference={inference:.1f}s, "
          f"total={total:.1f}s{cold_tag}", flush=True)

    language_out = result.get("language", lang or "en")
    # Free fragmented VRAM after each transcription
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {
        "segments": result["segments"],
        "language": language_out,
    }


def warmup():
    """Pre-load the model at startup and start the idle reaper."""
    with _model_lock:
        _ensure_model()
    _start_reaper()
