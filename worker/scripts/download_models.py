"""Download all ML models at build time."""
import os
import sys

# PyTorch 2.6+ changed defaults for torch.load — pickle-based models (pyannote,
# speechbrain) need weights_only=False.  Patch before any model imports.
import torch
_orig_load = torch.load
def _patched_load(*a, **kw):
    kw["weights_only"] = False
    return _orig_load(*a, **kw)
torch.load = _patched_load


def main():
    hf_token = os.environ.get("HF_TOKEN", "").strip()

    # ── WhisperX / faster-whisper (~3 GB) ────────────────────────────────────
    whisper_model = os.environ.get("WHISPER_MODEL", "large-v3")
    print(f"==> Downloading WhisperX / faster-whisper {whisper_model}...")
    from faster_whisper import WhisperModel
    WhisperModel(
        whisper_model,
        device="cpu",
        compute_type="int8",
        download_root="/app/model_cache/whisper",
    )
    print("    done.")

    # ── wav2vec2 alignment model (en) ────────────────────────────────────────
    print("==> Downloading wav2vec2 alignment model (en)...")
    import whisperx
    whisperx.load_align_model(language_code="en", device="cpu")
    print("    done.")

    # ── pyannote speaker-diarization-3.1 (gated) ────────────────────────────
    if hf_token:
        print("==> Downloading pyannote/speaker-diarization-3.1...")
        from pyannote.audio import Pipeline
        # Don't pass cache_dir — let it use HF_HOME so runtime finds the
        # models in the same location (whisperx doesn't pass cache_dir).
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        # Force download of sub-models (segmentation + embedding) by sending
        # pipeline to CPU — from_pretrained alone only fetches the config.
        pipeline.to(torch.device("cpu"))
        print("    done.")
    else:
        print("WARNING: HF_TOKEN not set — skipping pyannote download.")
        print("         Speaker diarization will be disabled at runtime.")

    # ── SpeechBrain ECAPA-TDNN ───────────────────────────────────────────────
    print("==> Downloading SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb)...")
    try:
        from speechbrain.inference.classifiers import EncoderClassifier
    except ImportError:
        from speechbrain.pretrained import EncoderClassifier
    EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="/app/model_cache/speechbrain",
    )
    print("    done.")

    # ── emotion2vec+ large (ModelScope) ─────────────────────────────────────
    print("==> Downloading emotion2vec+ large (iic/emotion2vec_plus_large)...")
    from funasr import AutoModel
    AutoModel(model="iic/emotion2vec_plus_large", model_revision="v2.0.5", hub="ms")
    print("    done.")

    print("\nAll models downloaded successfully.")


if __name__ == "__main__":
    main()
