"""Persist pipeline results to PostgreSQL."""

import json
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import text


def persist_results(
    job_id: str,
    language: str,
    segments: list,
    speaker_map: dict[str, uuid.UUID],
    emotions: list[dict],
    events: list[dict],
    wav_path: str,
    opus_path: str,
    db: Session,
) -> str:
    """Write transcript, segments (with emotion + events), and link speakers to DB.

    Returns transcript_id.
    """
    # Create transcript
    transcript_id = str(uuid.uuid4())
    raw_text = " ".join(seg.get("text", "").strip() for seg in segments if seg.get("text"))

    db.execute(
        text("""
            INSERT INTO transcripts (id, job_id, raw_text, language)
            VALUES (:id, :job_id, :raw_text, :language)
        """),
        {
            "id": transcript_id,
            "job_id": job_id,
            "raw_text": raw_text,
            "language": language,
        },
    )

    # Build event lookup
    event_lookup = {e["segment_idx"]: e.get("events", []) for e in events}

    # Create segments with emotion + event data
    for idx, seg in enumerate(segments):
        # Find emotion for this segment
        emotion_data = next(
            (e for e in emotions if e["segment_idx"] == idx),
            {"emotion": "unknown", "confidence": 0.0},
        )

        # Find events for this segment
        seg_events = event_lookup.get(idx, [])

        # Resolve speaker
        speaker_label = seg.get("speaker")
        speaker_id = speaker_map.get(speaker_label) if speaker_label else None

        # Extract word timings
        words = seg.get("words", [])
        word_timings = [
            {
                "word": w.get("word", ""),
                "start": w.get("start", 0),
                "end": w.get("end", 0),
                "score": w.get("score", 0),
            }
            for w in words
        ] if words else None

        db.execute(
            text("""
                INSERT INTO segments (
                    id, transcript_id, segment_index,
                    start_time, end_time, text,
                    speaker_id, word_timings,
                    emotion, emotion_confidence,
                    speech_events
                ) VALUES (
                    :id, :transcript_id, :segment_index,
                    :start_time, :end_time, :text,
                    :speaker_id, CAST(:word_timings AS jsonb),
                    :emotion, :emotion_confidence,
                    CAST(:speech_events AS jsonb)
                )
            """),
            {
                "id": str(uuid.uuid4()),
                "transcript_id": transcript_id,
                "segment_index": idx,
                "start_time": seg.get("start", 0),
                "end_time": seg.get("end", 0),
                "text": seg.get("text", "").strip(),
                "speaker_id": str(speaker_id) if speaker_id else None,
                "word_timings": json.dumps(word_timings) if word_timings else None,
                "emotion": emotion_data["emotion"],
                "emotion_confidence": emotion_data["confidence"],
                "speech_events": json.dumps(seg_events) if seg_events else None,
            },
        )

    # Update asset with archival path
    db.execute(
        text("""
            UPDATE assets SET archival_path = :opus_path
            WHERE job_id = :job_id
        """),
        {"opus_path": opus_path, "job_id": job_id},
    )

    db.commit()

    # Link embeddings to segments for this job.
    # Embeddings were inserted earlier (speakers.py) without segment_id.
    # For each speaker, match embeddings to segments by duration descending
    # (same order used during extraction).
    if speaker_map:
        for label, spk_id in speaker_map.items():
            # Get segments for this speaker in this transcript, ordered by duration desc
            # (mirrors the extraction order in speakers.py)
            seg_rows = db.execute(
                text("""
                    SELECT id FROM segments
                    WHERE transcript_id = :tid AND speaker_id = :sid
                      AND (end_time - start_time) >= 2.0
                    ORDER BY (end_time - start_time) DESC
                """),
                {"tid": transcript_id, "sid": str(spk_id)},
            ).fetchall()

            # Get unlinked embeddings for this speaker+job, oldest first
            emb_rows = db.execute(
                text("""
                    SELECT id FROM embeddings
                    WHERE speaker_id = :sid AND job_id = :jid AND segment_id IS NULL
                    ORDER BY created_at ASC
                """),
                {"sid": str(spk_id), "jid": job_id},
            ).fetchall()

            # Pair them up (same count if extraction worked correctly)
            for emb_row, seg_row in zip(emb_rows, seg_rows):
                db.execute(
                    text("UPDATE embeddings SET segment_id = :seg_id WHERE id = :emb_id"),
                    {"seg_id": str(seg_row.id), "emb_id": str(emb_row.id)},
                )

        db.commit()

    print(f"[persist] Saved transcript {transcript_id}: "
          f"{len(segments)} segments, {len(speaker_map)} speakers")

    return transcript_id
