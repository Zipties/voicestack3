"""Semantic search API - Qdrant-backed vector search over transcripts."""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from db.session import get_db
from db.models import Transcript, Segment, Speaker
from services.qdrant import (
    semantic_search,
    ingest_transcript,
    delete_transcript_points,
    collection_stats,
)

router = APIRouter(prefix="/api/semantic", tags=["semantic"])


@router.get("/search")
async def search(
    q: str,
    limit: int = 10,
    speaker: str | None = None,
    transcript_id: str | None = None,
):
    """Semantic search across all indexed transcripts.

    Returns segments ranked by relevance to the query.
    """
    try:
        results = await semantic_search(
            query=q,
            limit=limit,
            speaker=speaker,
            transcript_id=transcript_id,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search error: {e}")

    return results


@router.post("/ingest/{transcript_id}")
async def ingest(transcript_id: str, db: Session = Depends(get_db)):
    """Index a transcript and all its segments into Qdrant for semantic search.

    Idempotent - re-ingesting replaces existing points.
    """
    transcript = (
        db.query(Transcript)
        .filter(Transcript.id == uuid.UUID(transcript_id))
        .options(
            joinedload(Transcript.segments).joinedload(Segment.speaker),
        )
        .first()
    )
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Build dicts for the qdrant service
    t_dict = {
        "id": transcript.id,
        "job_id": transcript.job_id,
        "title": transcript.title,
        "raw_text": transcript.raw_text,
        "summary": transcript.summary,
        "language": transcript.language,
        "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
    }

    seg_dicts = [
        {
            "id": seg.id,
            "text": seg.text,
            "speaker_name": seg.speaker.name if seg.speaker else "Unknown",
            "start_time": seg.start_time,
            "end_time": seg.end_time,
            "emotion": seg.emotion,
            "emotion_confidence": seg.emotion_confidence,
        }
        for seg in sorted(transcript.segments, key=lambda s: s.start_time)
    ]

    tag_list = [tag.tag for tag in transcript.tags] if transcript.tags else []

    try:
        result = await ingest_transcript(t_dict, seg_dicts, tags=tag_list)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ingest error: {e}")

    return result


@router.post("/ingest-all")
async def ingest_all(db: Session = Depends(get_db)):
    """Index ALL transcripts into Qdrant. Use for initial setup or re-index."""
    from db.models import Tag
    transcripts = (
        db.query(Transcript)
        .options(
            joinedload(Transcript.segments).joinedload(Segment.speaker),
            joinedload(Transcript.tags),
        )
        .all()
    )

    results = []
    for transcript in transcripts:
        t_dict = {
            "id": transcript.id,
            "job_id": transcript.job_id,
            "title": transcript.title,
            "raw_text": transcript.raw_text,
            "summary": transcript.summary,
            "language": transcript.language,
            "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
        }

        seg_dicts = [
            {
                "id": seg.id,
                "text": seg.text,
                "speaker_name": seg.speaker.name if seg.speaker else "Unknown",
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "emotion": seg.emotion,
                "emotion_confidence": seg.emotion_confidence,
            }
            for seg in sorted(transcript.segments, key=lambda s: s.start_time)
        ]

        tag_list = [tag.tag for tag in transcript.tags] if transcript.tags else []

        try:
            result = await ingest_transcript(t_dict, seg_dicts, tags=tag_list)
            results.append(result)
        except Exception as e:
            results.append({
                "status": "error",
                "transcript_id": str(transcript.id),
                "error": str(e),
            })

    return {
        "total": len(results),
        "indexed": sum(1 for r in results if r.get("status") == "ok"),
        "results": results,
    }


@router.delete("/index/{transcript_id}")
async def remove_from_index(transcript_id: str):
    """Remove a transcript from the semantic index."""
    try:
        result = await delete_transcript_points(transcript_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Delete error: {e}")
    return result


@router.get("/stats")
async def get_semantic_stats():
    """Get Qdrant collection stats for the transcript index."""
    try:
        return await collection_stats()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Stats error: {e}")
