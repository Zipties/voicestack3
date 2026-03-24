"""WhisperX model manager with idle auto-unload and runtime model switching.

Loads WhisperX on first request, unloads after idle timeout to free VRAM.
~4 GB VRAM when loaded, ~6 GB peak during transcription. On a 24 GB RTX 4090
that leaves 18+ GB for other workloads when idle.

Settings are fetched from the backend API every 30 seconds. If the configured
model has changed, the current model is unloaded and the new one is loaded.
If the backend is unreachable, cached/default values are used.

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
import json
import time
import threading
import urllib.request
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
_loaded_model_name: str | None = None  # Track which model is currently loaded

# Settings cache
_settings_cache: dict | None = None
_settings_cache_time: float = 0.0
_SETTINGS_CACHE_TTL = 30  # seconds

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

AVAILABLE_MODELS = [
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large-v2", "large-v3", "large-v3-turbo",
    "distil-large-v3",
]

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
    "including question marks, commas, and periods."
)
CACHE_DIR = os.getenv("WHISPER_CACHE_DIR", "/data/model_cache/whisper")
IDLE_TIMEOUT = int(os.getenv("WHISPER_IDLE_TIMEOUT", "1800"))  # 30 min default

def _get_dynamic_batch_size(max_batch: int | None = None) -> int:
    """Compute batch size based on available VRAM.

    Prevents OOM when other GPU workloads (CLAP, winded-stt, etc.)
    are consuming VRAM alongside WhisperX.

    Thresholds (free VRAM → batch size):
      18+ GB → max_batch (default 16)
      14+ GB → 12
      10+ GB → 8
       6+ GB → 4
      <6 GB  → 2
    """
    cap = max_batch or BATCH_SIZE
    if not torch.cuda.is_available():
        return cap
    try:
        free_bytes, _ = torch.cuda.mem_get_info()
        free_gb = free_bytes / (1024 ** 3)
        if free_gb >= 18:
            bs = cap
        elif free_gb >= 14:
            bs = min(cap, 12)
        elif free_gb >= 10:
            bs = min(cap, 8)
        elif free_gb >= 6:
            bs = min(cap, 4)
        else:
            bs = 2
        print(f"[whisper] Dynamic batch size: {bs} (free VRAM: {free_gb:.1f}GB)", flush=True)
        return bs
    except Exception:
        return cap




def _fetch_settings() -> dict | None:
    """Fetch settings from backend API with caching. Returns None on failure."""
    global _settings_cache, _settings_cache_time

    now = time.time()
    if _settings_cache is not None and (now - _settings_cache_time) < _SETTINGS_CACHE_TTL:
        return _settings_cache

    try:
        req = urllib.request.Request(f"{BACKEND_URL}/api/settings")
        resp = urllib.request.urlopen(req, timeout=5)
        settings = json.loads(resp.read())
        _settings_cache = settings
        _settings_cache_time = now
        return settings
    except Exception as e:
        print(f"[whisper] Could not fetch settings, using cached/defaults: {e}", flush=True)
        return _settings_cache  # Return stale cache, or None if never fetched


def _get_effective_model_name() -> str:
    """Get the model name to use, checking settings API first."""
    settings = _fetch_settings()
    if settings:
        model = settings.get("whisper_model", "").strip()
        if model and model in AVAILABLE_MODELS:
            return model
    return MODEL_NAME


def _get_effective_prompt() -> str:
    """Get the initial prompt to use, checking settings API first."""
    settings = _fetch_settings()
    if settings:
        prompt = settings.get("whisper_prompt", "").strip()
        if prompt:
            return prompt
    return INITIAL_PROMPT


def reload_model(model_name: str):
    """Unload current model and load a new one. Caller MUST hold _model_lock."""
    global _model, _last_used, _parked_on_cpu, _loaded_model_name

    old_name = _loaded_model_name
    print(f"[whisper] Reloading model: {old_name} -> {model_name}", flush=True)

    # Unload old model
    if _model is not None:
        del _model
        _model = None
        _parked_on_cpu = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[whisper] Old model ({old_name}) unloaded, VRAM freed.", flush=True)

    # Load new model
    t0 = time.time()
    prompt = _get_effective_prompt()
    print(f"[whisper] Loading {model_name} ({COMPUTE_TYPE}) on {DEVICE}, "
          f"lang={LANGUAGE}, beam={BEAM_SIZE}...", flush=True)
    _model = whisperx.load_model(
        model_name,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        language=LANGUAGE,
        asr_options={
            "beam_size": BEAM_SIZE,
            "initial_prompt": prompt if prompt else None,
        },
        download_root=CACHE_DIR,
    )
    _loaded_model_name = model_name
    _last_used = time.time()
    load_time = _last_used - t0
    print(f"[whisper] Model {model_name} loaded in {load_time:.1f}s. beam_size={BEAM_SIZE}, "
          f"initial_prompt={'set' if prompt else 'none'}", flush=True)


def _start_reaper():
    """Start background thread that unloads model after idle timeout."""
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True

    def _reaper_loop():
        global _model, _last_used, _parked_on_cpu, _loaded_model_name
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

                print(f"[whisper] Idle for {idle_seconds:.0f}s (timeout: {IDLE_TIMEOUT}s), "
                      f"fully unloading model to free VRAM...", flush=True)
                t0 = time.time()
                del _model
                _model = None
                _parked_on_cpu = False
                _loaded_model_name = None
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print(f"[whisper] Model fully unloaded in {time.time()-t0:.1f}s. VRAM freed.", flush=True)
            finally:
                _model_lock.release()

    t = threading.Thread(target=_reaper_loop, daemon=True, name="whisper-reaper")
    t.start()
    print(f"[whisper] Idle reaper started (timeout: {IDLE_TIMEOUT}s)", flush=True)


def _ensure_model():
    """Load model if not already loaded. Caller MUST hold _model_lock."""
    global _model, _last_used, _parked_on_cpu, _loaded_model_name

    # Check if model needs to be switched
    desired_model = _get_effective_model_name()
    if _model is not None and _loaded_model_name != desired_model:
        print(f"[whisper] Model switch detected: {_loaded_model_name} -> {desired_model}", flush=True)
        reload_model(desired_model)
        return _model

    if _model is not None:
        return _model

    model_name = desired_model
    prompt = _get_effective_prompt()

    t0 = time.time()
    print(f"[whisper] Loading {model_name} ({COMPUTE_TYPE}) on {DEVICE}, "
          f"lang={LANGUAGE}, beam={BEAM_SIZE}...", flush=True)
    _model = whisperx.load_model(
        model_name,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        language=LANGUAGE,
        asr_options={
            "beam_size": BEAM_SIZE,
            "initial_prompt": prompt if prompt else None,
        },
        download_root=CACHE_DIR,
    )
    _loaded_model_name = model_name
    _last_used = time.time()
    load_time = _last_used - t0
    print(f"[whisper] Model loaded in {load_time:.1f}s. beam_size={BEAM_SIZE}, "
          f"initial_prompt={'set' if prompt else 'none'}", flush=True)
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
        initial_prompt: Override initial prompt (default: settings or env var)
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
    # Use settings-based prompt if no explicit override
    effective_prompt = _get_effective_prompt()
    prompt = initial_prompt if initial_prompt is not None else effective_prompt
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
        if prompt != effective_prompt:
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
            effective_batch = _get_dynamic_batch_size()
            try:
                result = model.transcribe(audio, batch_size=effective_batch, language=lang)
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    # OOM recovery: free cache and retry with halved batch
                    retry_batch = max(1, effective_batch // 2)
                    print(f"[whisper] CUDA OOM with batch_size={effective_batch}, "
                          f"retrying with batch_size={retry_batch}...", flush=True)
                    torch.cuda.empty_cache()
                    gc.collect()
                    result = model.transcribe(audio, batch_size=retry_batch, language=lang)
                else:
                    raise
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
