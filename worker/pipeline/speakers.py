"""Speaker embedding extraction + cross-recording matching via pgvector.

This is THE critical feature: when a user renames "Speaker 1" to "Alice",
future recordings automatically identify Alice by matching voice embeddings.

Flow:
1. Extract ECAPA-TDNN 192-dim embedding per diarized speaker segment
2. Use ALL segments (≥2s) per speaker, average into centroid for robust matching
3. Query pgvector: average top-3 closest embeddings per candidate speaker
4. If avg distance < threshold → assign existing speaker (auto-fill name!)
5. If no match → create new speaker with generic name
6. Store all individual embeddings for future matching diversity
"""

import os
import gc
import uuid
import random
from sqlalchemy.orm import Session
from sqlalchemy import text

MATCH_THRESHOLD = float(os.getenv("SPEAKER_MATCH_THRESHOLD", "0.45"))
MAX_SEGMENTS_PER_SPEAKER = 0  # 0 = no cap, use ALL valid segments
MIN_SEGMENT_DURATION = 2.0    # Minimum seconds for usable embedding


def match_speakers(
    audio_path: str,
    segments: list,
    job_id: str,
    db: Session,
) -> tuple[dict[str, uuid.UUID], dict[str, str]]:
    """Extract speaker embeddings and match against existing speakers.

    Args:
        audio_path: Path to 16kHz mono WAV
        segments: WhisperX segments (with 'speaker' labels like SPEAKER_00)
        job_id: Current job UUID
        db: Database session

    Returns:
        (speaker_map, speaker_names):
            speaker_map: {"SPEAKER_00": uuid, "SPEAKER_01": uuid, ...}
            speaker_names: {"SPEAKER_00": "Nicole", "SPEAKER_01": "Speaker 2", ...}
    """
    import numpy as np
    import torch
    import librosa
    from pipeline.gpu_cleanup import cleanup_gpu, log_gpu_memory

    print(f"[speakers] Loading ECAPA-TDNN model...")
    log_gpu_memory("before_ecapa")

    # SpeechBrain >=1.0 moved to speechbrain.inference
    try:
        from speechbrain.inference.classifiers import EncoderClassifier
    except ImportError:
        from speechbrain.pretrained import EncoderClassifier

    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=os.getenv("SPEECHBRAIN_CACHE_DIR", "/app/model_cache/speechbrain"),
        run_opts={"device": device},
    )

    # Load audio
    audio, sr = librosa.load(audio_path, sr=16000)

    # Collect segments per speaker label
    speaker_segments: dict[str, list[dict]] = {}
    for seg in segments:
        label = seg.get("speaker")
        if not label:
            continue
        if label not in speaker_segments:
            speaker_segments[label] = []
        speaker_segments[label].append(seg)

    speaker_map: dict[str, uuid.UUID] = {}
    speaker_names: dict[str, str] = {}

    for label, segs in speaker_segments.items():
        # Filter to segments long enough for quality embeddings
        valid_segs = [s for s in segs if (s["end"] - s["start"]) >= MIN_SEGMENT_DURATION]

        if not valid_segs:
            duration = max((s["end"] - s["start"]) for s in segs)
            print(f"[speakers] {label}: no segments >= {MIN_SEGMENT_DURATION}s "
                  f"(longest: {duration:.1f}s), skipping embedding")
            speaker_id = _create_speaker(label, None, db)
            speaker_map[label] = speaker_id
            # Look up the generated name
            row = db.execute(text("SELECT name FROM speakers WHERE id = :id"),
                             {"id": str(speaker_id)}).fetchone()
            speaker_names[label] = row[0] if row else "Unknown"
            continue

        # Sort by duration descending; use all valid segments (or cap if set)
        valid_segs.sort(key=lambda s: s["end"] - s["start"], reverse=True)
        top_segs = valid_segs[:MAX_SEGMENTS_PER_SPEAKER] if MAX_SEGMENTS_PER_SPEAKER else valid_segs

        # Extract embeddings from each segment
        embeddings_np = []
        for seg in top_segs:
            start_sample = int(seg["start"] * sr)
            end_sample = int(seg["end"] * sr)
            segment_audio = audio[start_sample:end_sample]

            audio_tensor = torch.tensor(segment_audio).unsqueeze(0).to(device)
            embedding = classifier.encode_batch(audio_tensor)
            embedding_np = embedding.squeeze().cpu().detach().numpy()
            embeddings_np.append(embedding_np)

        durations = ', '.join(f"{s['end']-s['start']:.1f}s" for s in top_segs)
        print(f"[speakers] {label}: extracted {len(embeddings_np)} embeddings "
              f"from segments of {durations}")

        # Average embeddings into centroid for more robust matching
        centroid = np.mean(embeddings_np, axis=0)
        # Normalize centroid (cosine distance expects unit vectors for best results)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm

        # Query pgvector: average top-3 closest embeddings per candidate speaker
        # This is more robust than single-nearest-neighbor
        candidates = db.execute(
            text("""
                SELECT speaker_id, s.name as speaker_name,
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
                GROUP BY speaker_id, s.name
                ORDER BY AVG(distance)
                LIMIT 5
            """),
            {"query_vec": str(centroid.tolist())},
        ).fetchall()

        # Log all candidates for tuning visibility
        if candidates:
            print(f"[speakers] {label} matching candidates:")
            for c in candidates:
                print(f"[speakers]   {c.speaker_name}: avg={c.avg_distance:.4f} "
                      f"min={c.min_distance:.4f} (from {c.match_count} embeddings)")

        best = candidates[0] if candidates else None

        if best and best.avg_distance < MATCH_THRESHOLD:
            # Match found - reuse existing speaker
            print(f"[speakers] {label} → MATCHED '{best.speaker_name}' "
                  f"(avg_distance: {best.avg_distance:.4f})")
            speaker_map[label] = best.speaker_id
            speaker_names[label] = best.speaker_name
        else:
            # No match
            distance_info = f" (closest: {best.speaker_name} @ {best.avg_distance:.4f})" if best else ""
            print(f"[speakers] {label} → NEW speaker{distance_info}")
            speaker_id = _create_speaker(label, None, db)
            speaker_map[label] = speaker_id
            row = db.execute(text("SELECT name FROM speakers WHERE id = :id"),
                             {"id": str(speaker_id)}).fetchone()
            speaker_names[label] = row[0] if row else "Unknown"

        # Store ALL individual embeddings for future matching diversity
        target_speaker_id = speaker_map[label]
        for emb_np in embeddings_np:
            db.execute(
                text("""
                    INSERT INTO embeddings (id, speaker_id, job_id, embedding)
                    VALUES (:id, :speaker_id, :job_id, :embedding)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "speaker_id": str(target_speaker_id),
                    "job_id": job_id,
                    "embedding": str(emb_np.tolist()),
                },
            )

    db.commit()

    del classifier
    cleanup_gpu()
    log_gpu_memory("after_ecapa")

    print(f"[speakers] Mapped {len(speaker_map)} speakers: "
          + ", ".join(f"{k}→{speaker_names.get(k, k)}" for k in speaker_map))

    return speaker_map, speaker_names


# Custom speaker names — assigned in order, first-come-first-served.
# Add/reorder as desired. Once exhausted, falls back to adjective-noun combos.
_NAMES = [
    "Val", "Alcatraz", "Akane", "Vin", "Elegy", "Penrod", "Vivenna", "Lemex",
    "Adolin", "Yumi", "Yatti", "Exel", "Sazed", "Prof", "Kaladin", "Alanik",
    "Raoden", "Rashek", "Taravangian", "Phak", "Sarene", "Dockson", "Straff",
    "Charlie", "Renarin", "Camon", "Karata", "Jim", "Mizzy", "Ais", "Brade",
    "Godeke", "Duke", "Szeth", "Zu", "Tindwyl", "Shallan", "Frava", "Lightsong",
    "Navani", "Tia", "David", "Pattern", "Vasher", "Spook", "Tress", "Matisse",
    "Shai", "Aydee", "Jezrien", "Kelsier", "Kiin", "Kaz", "Cuna", "Kimmalyn",
    "Mayalaran", "Reen", "Eventeo", "Wit", "Nightblood", "Jasnah", "Siri",
    "Stephen", "Tobias", "Dalinar", "Breeze", "Ham", "Painter", "Lift", "Jorgen",
    "Spensa", "Hrathen", "Freyja", "Elend", "Zane", "Design", "Cobb",
]

_ADJECTIVES = [
    "Azure", "Coral", "Sage", "Amber", "Slate", "Ruby", "Jade", "Ivory",
    "Onyx", "Teal", "Crimson", "Violet", "Bronze", "Copper", "Silver",
    "Golden", "Scarlet", "Cobalt", "Indigo", "Olive", "Russet", "Garnet",
    "Opal", "Misty", "Dusty", "Smoky", "Frosty", "Sunny", "Cloudy", "Sandy",
]

_NOUNS = [
    "Fox", "Owl", "Elk", "Jay", "Wren", "Lynx", "Hare", "Dove",
    "Hawk", "Wolf", "Bear", "Crow", "Lark", "Swan", "Finch", "Crane",
    "Otter", "Robin", "Raven", "Falcon", "Badger", "Heron", "Sparrow",
    "Osprey", "Puma", "Gecko", "Parrot", "Condor", "Pelican", "Mantis",
]


def _generate_unique_name(db: Session) -> str:
    """Assign a name from the custom list, falling back to adjective-noun combos."""
    existing = {
        row[0] for row in db.execute(text("SELECT name FROM speakers")).fetchall()
    }
    # Try custom names first (in order)
    for name in _NAMES:
        if name not in existing:
            return name
    # Fallback: random adjective-noun combos (900 possible)
    for _ in range(50):
        name = f"{random.choice(_ADJECTIVES)} {random.choice(_NOUNS)}"
        if name not in existing:
            return name
    # Last resort with number suffix
    return f"{random.choice(_ADJECTIVES)} {random.choice(_NOUNS)} {random.randint(10, 99)}"


_AVATAR_COUNT = 100


def _assign_unique_avatar(db: Session) -> int:
    """Pick an avatar_id not already used by another speaker. Wraps around if all taken."""
    used = {
        row[0] for row in db.execute(text("SELECT avatar_id FROM speakers WHERE avatar_id IS NOT NULL")).fetchall()
    }
    # Find first unused
    available = [i for i in range(_AVATAR_COUNT) if i not in used]
    if available:
        return random.choice(available)
    # All taken — pick random (duplicates allowed once pool exhausted)
    return random.randint(0, _AVATAR_COUNT - 1)


def _create_speaker(label: str, confidence: float | None, db: Session) -> uuid.UUID:
    """Create a new speaker record with a unique generated name and avatar."""
    name = _generate_unique_name(db)
    avatar_id = _assign_unique_avatar(db)

    speaker_id = uuid.uuid4()
    db.execute(
        text("""
            INSERT INTO speakers (id, name, is_trusted, match_confidence, avatar_id)
            VALUES (:id, :name, FALSE, :confidence, :avatar_id)
        """),
        {"id": str(speaker_id), "name": name, "confidence": confidence, "avatar_id": avatar_id},
    )
    return speaker_id
