"""Speaker verification pipeline — lightweight, no transcription.

Runs diarization + ECAPA-TDNN embedding extraction + pgvector matching.
Returns speaker identification timeline with dialogue analysis.
Does NOT create jobs, transcripts, speakers, or store any embeddings.
"""

import os
import subprocess
import tempfile
import time
import numpy as np
import torch
import librosa
from sqlalchemy import text
from db_helper import get_db_session
from pipeline.gpu_cleanup import cleanup_gpu, log_gpu_memory

MATCH_THRESHOLD = float(os.getenv("SPEAKER_MATCH_THRESHOLD", "0.45"))


def verify_speakers(audio_path: str, min_duration: float = 2.0,
                    threshold: float = None) -> dict:
    """Run diarization + speaker matching only. No transcription.

    Returns dict with speakers, segments, dialogue analysis.
    """
    if threshold is None:
        threshold = MATCH_THRESHOLD

    t_start = time.time()
    db = get_db_session()

    wav_path = None
    try:
        # Convert to 16kHz mono WAV via ffmpeg (handles any input format)
        wav_path = tempfile.mktemp(suffix=".wav", prefix="verify_")
        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-ar", "16000", "-ac", "1",
            wav_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[-300:]}")

        # Load audio
        audio, sr = librosa.load(wav_path, sr=16000)
        duration = len(audio) / sr
        print(f"[verify] Audio loaded: {duration:.1f}s", flush=True)

        # ── Device detection ──
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        print(f"[verify] Using device: {device}", flush=True)

        # ── Step 1: Pyannote Diarization ──
        hf_token = os.getenv("HF_TOKEN", "")
        if not hf_token:
            raise RuntimeError("HF_TOKEN required for speaker diarization (pyannote)")

        print("[verify] Loading pyannote diarization pipeline...", flush=True)
        log_gpu_memory("before_diarize")

        from pyannote.audio import Pipeline as PyannotePipeline

        diarization_pipeline = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
            cache_dir=os.getenv("PYANNOTE_CACHE_DIR", "/app/model_cache/pyannote"),
        )
        # pyannote supports CUDA and MPS
        diarize_device = device
        diarization_pipeline.to(torch.device(diarize_device))

        diarization = diarization_pipeline(wav_path)

        raw_segments = []
        for turn, _, speaker_label in diarization.itertracks(yield_label=True):
            raw_segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker_label,
            })

        print(f"[verify] Diarization complete: {len(raw_segments)} segments", flush=True)

        del diarization_pipeline
        cleanup_gpu()
        log_gpu_memory("after_diarize")

        # ── Step 2: ECAPA-TDNN Speaker Embedding Extraction ──
        try:
            from speechbrain.inference.classifiers import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier

        print("[verify] Loading ECAPA-TDNN model...", flush=True)
        log_gpu_memory("before_ecapa")

        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=os.getenv("SPEECHBRAIN_CACHE_DIR", "/app/model_cache/speechbrain"),
            run_opts={"device": device},
        )

        # Group segments by speaker label
        speaker_segments: dict[str, list[dict]] = {}
        for seg in raw_segments:
            label = seg["speaker"]
            if label not in speaker_segments:
                speaker_segments[label] = []
            speaker_segments[label].append(seg)

        # For each speaker: extract embeddings, match against DB
        speakers_result = []
        for label, segs in speaker_segments.items():
            valid_segs = [s for s in segs if (s["end"] - s["start"]) >= min_duration]

            if not valid_segs:
                speakers_result.append({
                    "label": label,
                    "speaker_id": None,
                    "speaker_name": None,
                    "is_trusted": False,
                    "avg_distance": None,
                    "is_known": False,
                })
                continue

            # Sort by duration, use top segments for embedding
            valid_segs.sort(key=lambda s: s["end"] - s["start"], reverse=True)
            top_segs = valid_segs[:10]

            # Extract embeddings
            embeddings_np = []
            for seg in top_segs:
                start_sample = int(seg["start"] * sr)
                end_sample = int(seg["end"] * sr)
                segment_audio = audio[start_sample:end_sample]
                audio_tensor = torch.tensor(segment_audio).unsqueeze(0).to(device)
                embedding = classifier.encode_batch(audio_tensor)
                embeddings_np.append(embedding.squeeze().cpu().detach().numpy())

            # Average into centroid, normalize
            centroid = np.mean(embeddings_np, axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm

            # Query pgvector — same logic as speakers.py match_speakers()
            candidates = db.execute(
                text("""
                    SELECT speaker_id, s.name as speaker_name, s.is_trusted,
                           AVG(distance) as avg_distance,
                           MIN(distance) as min_distance,
                           COUNT(*) as match_count
                    FROM (
                        SELECT e.speaker_id, e.embedding <=> :query_vec AS distance,
                               ROW_NUMBER() OVER (
                                   PARTITION BY e.speaker_id
                                   ORDER BY e.embedding <=> :query_vec
                               ) as rn
                        FROM embeddings e
                    ) ranked
                    JOIN speakers s ON s.id = ranked.speaker_id
                    WHERE rn <= 3
                    GROUP BY speaker_id, s.name, s.is_trusted
                    ORDER BY AVG(distance)
                    LIMIT 5
                """),
                {"query_vec": str(centroid.tolist())},
            ).fetchall()

            best = candidates[0] if candidates else None
            is_known = best is not None and best.avg_distance < threshold

            if best:
                print(f"[verify] {label}: closest='{best.speaker_name}' "
                      f"avg_dist={best.avg_distance:.4f} "
                      f"{'MATCH' if is_known else 'NO MATCH'}", flush=True)
            else:
                print(f"[verify] {label}: no candidates in DB", flush=True)

            speakers_result.append({
                "label": label,
                "speaker_id": str(best.speaker_id) if is_known else None,
                "speaker_name": best.speaker_name if is_known else None,
                "is_trusted": best.is_trusted if is_known else False,
                "avg_distance": round(best.avg_distance, 4) if best else None,
                "is_known": is_known,
            })

        del classifier
        cleanup_gpu()
        log_gpu_memory("after_ecapa")

        # ── Step 3: Dialogue Analysis ──
        known_speakers = [s for s in speakers_result if s["is_known"]]
        known_labels = {s["label"] for s in known_speakers}

        known_speech = sum(
            seg["end"] - seg["start"]
            for seg in raw_segments
            if seg["speaker"] in known_labels
        )
        unknown_speech = sum(
            seg["end"] - seg["start"]
            for seg in raw_segments
            if seg["speaker"] not in known_labels
        )

        # Count turn-taking between known speakers
        known_turns = [seg for seg in raw_segments if seg["speaker"] in known_labels]
        turn_count = 0
        prev_speaker = None
        for seg in known_turns:
            if seg["speaker"] != prev_speaker and prev_speaker is not None:
                turn_count += 1
            prev_speaker = seg["speaker"]

        # Dialogue = 2+ known speakers with turn-taking
        dialogue_detected = len(known_speakers) >= 2 and turn_count >= 2

        t_end = time.time()
        print(f"[verify] Complete in {t_end - t_start:.1f}s: "
              f"{len(speakers_result)} speakers, "
              f"{len(known_speakers)} known, "
              f"dialogue={'yes' if dialogue_detected else 'no'}", flush=True)

        return {
            "duration_seconds": round(duration, 1),
            "speakers": speakers_result,
            "segments": [
                {
                    "start": round(s["start"], 2),
                    "end": round(s["end"], 2),
                    "label": s["speaker"],
                }
                for s in raw_segments
            ],
            "dialogue_detected": dialogue_detected,
            "dialogue_summary": {
                "known_speaker_count": len(known_speakers),
                "known_speakers": [s["speaker_name"] for s in known_speakers],
                "turn_count": turn_count,
                "total_known_speech_seconds": round(known_speech, 1),
                "total_unknown_speech_seconds": round(unknown_speech, 1),
            },
            "processing_time_seconds": round(t_end - t_start, 1),
        }

    finally:
        db.close()
        if wav_path and os.path.exists(wav_path):
            os.unlink(wav_path)
