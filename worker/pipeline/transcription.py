"""Transcription + word alignment + speaker diarization via WhisperX.

Architecture (VoiceStack3):
  - transcribe_only(): Uses persistent WhisperX model in main process
  - align_and_diarize(): Loads alignment + diarization models in subprocess
  - transcribe(): Legacy combined function (still works, loads own model)
"""

import os
import gc


def transcribe_only(audio_path: str) -> dict:
    """Run transcription using the persistent WhisperX model.

    This runs in the MAIN worker process - no model loading, no VRAM churn.
    Uses the singleton model from whisper_model.py.

    Returns:
        {"segments": [...], "language": "en"}
    """
    from whisper_model import transcribe_audio
    return transcribe_audio(audio_path)


def align_and_diarize(
    audio_path: str, tx_result: dict, job_id: str,
    do_align: bool = True, do_diarize: bool = True,
) -> dict:
    """Run alignment + diarization on pre-transcribed results.

    This runs in a SUBPROCESS - loads alignment and diarization models,
    processes, then the subprocess exits and frees all VRAM.

    Args:
        audio_path: Path to 16kHz mono WAV
        tx_result: Output from transcribe_only() with segments + language
        do_align: Whether to run word-level alignment
        do_diarize: Whether to run speaker diarization

    Returns:
        {"segments": [...], "language": "en"}
    """
    import torch
    import whisperx
    from pipeline.gpu_cleanup import cleanup_gpu, log_gpu_memory

    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    hf_token = os.getenv("HF_TOKEN")

    segments = tx_result["segments"]
    language = tx_result["language"]
    result = {"segments": segments}

    audio = whisperx.load_audio(audio_path)

    # Step 1: Word-level alignment
    if do_align:
        align_device = "cpu" if device == "mps" else device
        print(f"[WhisperX] Loading alignment model on {align_device}...", flush=True)
        log_gpu_memory("before_align")

        model_a, metadata = whisperx.load_align_model(
            language_code=language,
            device=align_device,
        )
        result = whisperx.align(
            segments,
            model_a,
            metadata,
            audio,
            align_device,
            return_char_alignments=False,
        )
        print(f"[WhisperX] Alignment complete. Segments: {len(result['segments'])}", flush=True)

        del model_a
        cleanup_gpu()
        log_gpu_memory("after_align")
    else:
        print("[WhisperX] Alignment SKIPPED", flush=True)

    # Step 2: Speaker diarization
    if do_diarize:
        if not hf_token:
            raise RuntimeError("HF_TOKEN required for speaker diarization (pyannote)")

        print("[WhisperX] Loading diarization pipeline...", flush=True)
        from whisperx.diarize import DiarizationPipeline
        diarize_model = DiarizationPipeline(
            use_auth_token=hf_token,
            device=device,
        )
        diarize_segments = diarize_model(audio)
        result = whisperx.assign_word_speakers(diarize_segments, result)
        print(f"[WhisperX] Diarization complete.", flush=True)

        del diarize_model
        cleanup_gpu()
        log_gpu_memory("after_diarize")
    else:
        print("[WhisperX] Diarization SKIPPED", flush=True)

    return {
        "segments": result["segments"],
        "language": language,
    }


def transcribe(audio_path: str, job_id: str) -> dict:
    """Legacy: full transcribe → align → diarize in one call.

    Loads its own WhisperX model. Used by _gpu_worker.py when running
    the entire pipeline in a subprocess.
    """
    import torch
    import whisperx
    from pipeline.gpu_cleanup import cleanup_gpu, log_gpu_memory

    if torch.cuda.is_available():
        device = "cuda"
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "cpu"  # CTranslate2 doesn't support MPS
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    else:
        device = "cpu"
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    model_name = os.getenv("WHISPER_MODEL", "large-v3")
    batch_size = int(os.getenv("WHISPER_BATCH_SIZE", "16"))
    beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "20"))
    language = os.getenv("WHISPER_LANGUAGE", "en")
    initial_prompt = os.getenv("WHISPER_INITIAL_PROMPT", "")
    hf_token = os.getenv("HF_TOKEN")

    if not hf_token:
        raise RuntimeError("HF_TOKEN required for speaker diarization (pyannote)")

    print(f"[WhisperX] Loading model: {model_name} ({compute_type}) on {device}")
    log_gpu_memory("before_whisperx")

    # Step 1: Transcribe
    model = whisperx.load_model(
        model_name,
        device=device,
        compute_type=compute_type,
        language=language,
        asr_options={
            "beam_size": beam_size,
            "initial_prompt": initial_prompt if initial_prompt else None,
        },
        download_root=os.getenv("WHISPER_CACHE_DIR", "/app/model_cache/whisper"),
    )
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    language = result.get("language", "en")
    print(f"[WhisperX] Transcription complete. Language: {language}, Segments: {len(result['segments'])}")

    # Free transcription model before loading alignment model
    del model
    cleanup_gpu()
    log_gpu_memory("after_transcribe")

    # Step 2: Word-level alignment (wav2vec2 may not work on MPS, fall back to CPU)
    align_device = "cpu" if device == "cpu" and hasattr(torch.backends, "mps") else device
    print(f"[WhisperX] Loading alignment model on {align_device}...")
    model_a, metadata = whisperx.load_align_model(
        language_code=language,
        device=align_device,
    )
    result = whisperx.align(
        result["segments"],
        model_a,
        metadata,
        audio,
        align_device,
        return_char_alignments=False,
    )
    print(f"[WhisperX] Alignment complete. Segments: {len(result['segments'])}")

    del model_a
    cleanup_gpu()
    log_gpu_memory("after_align")

    # Step 3: Speaker diarization (pyannote supports MPS)
    diarize_device = device
    if device == "cpu" and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        diarize_device = "mps"
    print(f"[WhisperX] Loading diarization pipeline on {diarize_device}...")
    from whisperx.diarize import DiarizationPipeline
    diarize_model = DiarizationPipeline(
        token=hf_token,
        device=diarize_device,
    )
    diarize_segments = diarize_model(audio)
    result = whisperx.assign_word_speakers(diarize_segments, result)
    print(f"[WhisperX] Diarization complete.")

    del diarize_model
    cleanup_gpu()
    log_gpu_memory("after_diarize")

    return {
        "segments": result["segments"],
        "language": language,
    }
