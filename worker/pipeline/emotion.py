"""Emotion detection via emotion2vec+ large (9-class per segment)."""

import os
import gc

# emotion2vec+ 9 classes
EMOTIONS = [
    "angry", "disgusted", "fearful", "happy",
    "neutral", "other", "sad", "surprised", "unknown"
]


def detect_emotions(audio_path: str, segments: list, job_id: str) -> list[dict]:
    """Run emotion2vec+ on each segment.

    Args:
        audio_path: Path to 16kHz mono WAV
        segments: WhisperX segments with start/end times
        job_id: For logging

    Returns list of dicts:
        [{"segment_idx": 0, "emotion": "happy", "confidence": 0.87}, ...]
    """
    import numpy as np
    import torch
    import librosa
    from pipeline.gpu_cleanup import cleanup_gpu, log_gpu_memory

    print(f"[emotion2vec] Loading model for {len(segments)} segments...")
    log_gpu_memory("before_emotion")

    # Use HuggingFace hub (faster than ModelScope) with persistent cache
    os.environ.setdefault("HF_HOME", "/app/model_cache/huggingface")

    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    from funasr import AutoModel
    # Use local path directly to avoid ModelScope re-download at runtime
    # (the model is baked into the image at build time)
    local_model = "/app/model_cache/modelscope/models/iic/emotion2vec_plus_large"
    model = AutoModel(
        model=local_model,
        device=device,
    )

    # Load full audio once
    audio, sr = librosa.load(audio_path, sr=16000)

    results = []
    for idx, seg in enumerate(segments):
        start_sample = int(seg["start"] * sr)
        end_sample = int(seg["end"] * sr)
        segment_audio = audio[start_sample:end_sample]

        # Skip very short segments (< 0.5s)
        if len(segment_audio) < sr * 0.5:
            results.append({
                "segment_idx": idx,
                "emotion": "unknown",
                "confidence": 0.0,
            })
            continue

        try:
            output = model.generate(segment_audio, granularity="utterance")

            # Parse emotion2vec output
            # Output format varies by version - handle both list and dict
            if isinstance(output, list) and len(output) > 0:
                scores = output[0]
                if isinstance(scores, dict):
                    # Dict format: {"labels": [...], "scores": [...]}
                    labels = scores.get("labels", EMOTIONS)
                    score_values = scores.get("scores", [])
                    if score_values:
                        best_idx = np.argmax(score_values)
                        emotion = labels[best_idx] if best_idx < len(labels) else "unknown"
                        confidence = float(score_values[best_idx])
                    else:
                        emotion, confidence = "unknown", 0.0
                else:
                    # Array format: [score1, score2, ...]
                    scores_arr = np.array(scores)
                    best_idx = np.argmax(scores_arr)
                    emotion = EMOTIONS[best_idx] if best_idx < len(EMOTIONS) else "unknown"
                    confidence = float(scores_arr[best_idx])
            else:
                emotion, confidence = "unknown", 0.0

            # emotion2vec outputs bilingual labels like "难过/sad" - extract English
            if "/" in emotion:
                emotion = emotion.split("/")[-1]

            results.append({
                "segment_idx": idx,
                "emotion": emotion,
                "confidence": round(confidence, 4),
            })
        except Exception as e:
            print(f"[emotion2vec] Warning: segment {idx} failed: {e}")
            results.append({
                "segment_idx": idx,
                "emotion": "unknown",
                "confidence": 0.0,
            })

    print(f"[emotion2vec] Processed {len(results)} segments")
    del model
    cleanup_gpu()
    log_gpu_memory("after_emotion")

    return results
