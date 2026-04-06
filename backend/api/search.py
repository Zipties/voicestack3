"""Unified search endpoint — combines Qdrant semantic + PostgreSQL verbatim."""

import asyncio
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.session import get_db
from services.qdrant import semantic_search, _is_qdrant_enabled

router = APIRouter(prefix="/api/search", tags=["search"])


async def verbatim_segment_search(
    q: str, limit: int, speaker: str | None, db: Session
) -> list[dict]:
    """ILIKE search on segments.text joined with speakers and transcripts."""
    params = {"pattern": f"%{q}%", "limit": limit}

    speaker_filter = ""
    if speaker:
        speaker_filter = "AND sp.name ILIKE :speaker"
        params["speaker"] = f"%{speaker}%"

    sql = text(f"""
        SELECT
            seg.id AS segment_id,
            t.id AS transcript_id,
            t.job_id,
            t.title,
            sp.name AS speaker,
            seg.text,
            seg.start_time,
            seg.end_time,
            seg.emotion,
            t.created_at
        FROM segments seg
        JOIN transcripts t ON t.id = seg.transcript_id
        LEFT JOIN speakers sp ON sp.id = seg.speaker_id
        WHERE seg.text ILIKE :pattern
        {speaker_filter}
        ORDER BY t.created_at DESC, seg.start_time ASC
        LIMIT :limit
    """)

    rows = db.execute(sql, params).fetchall()
    return [
        {
            "segment_id": str(r.segment_id),
            "transcript_id": str(r.transcript_id),
            "job_id": str(r.job_id),
            "title": r.title,
            "speaker": r.speaker or "Unknown",
            "text": r.text,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "emotion": r.emotion,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("")
async def unified_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    speaker: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Unified search: Qdrant semantic + PostgreSQL verbatim, merged and deduplicated."""
    t0 = time.monotonic()

    semantic_available = _is_qdrant_enabled()

    # Run both searches in parallel
    async def _semantic():
        if not semantic_available:
            return []
        try:
            return await semantic_search(q, limit=limit, speaker=speaker)
        except Exception:
            return []

    async def _verbatim():
        return await verbatim_segment_search(q, limit, speaker, db)

    semantic_results, verbatim_results = await asyncio.gather(
        _semantic(), _verbatim()
    )

    # Check if semantic actually returned (could fail silently)
    semantic_ok = semantic_available and isinstance(semantic_results, list)

    # Build results keyed by segment_id for dedup
    merged: dict[str, dict] = {}

    # Verbatim results get a synthetic high score for exact phrase matches
    for v in verbatim_results:
        sid = v["segment_id"]
        merged[sid] = {
            "type": "segment",
            "source": "verbatim",
            "score": 0.95,
            "segment_id": sid,
            "transcript_id": v["transcript_id"],
            "job_id": v["job_id"],
            "title": v["title"],
            "speaker": v["speaker"],
            "text": v["text"],
            "start_time": v["start_time"],
            "end_time": v["end_time"],
            "emotion": v["emotion"],
            "created_at": v["created_at"],
        }

    # Semantic results
    for s in semantic_results:
        meta = s.get("metadata", {})
        sid = meta.get("segment_id", "")
        if not sid:
            continue  # skip transcript_summary points

        if sid in merged:
            # Already found verbatim — upgrade source to "both", keep higher score
            merged[sid]["source"] = "both"
            merged[sid]["score"] = max(merged[sid]["score"], s.get("score", 0))
        else:
            merged[sid] = {
                "type": meta.get("type", "segment"),
                "source": "semantic",
                "score": s.get("score", 0),
                "segment_id": sid,
                "transcript_id": meta.get("transcript_id", ""),
                "job_id": meta.get("job_id", ""),
                "title": meta.get("title", ""),
                "speaker": meta.get("speaker", "Unknown"),
                "text": s.get("text", ""),
                "start_time": meta.get("start_time"),
                "end_time": meta.get("end_time"),
                "emotion": meta.get("emotion"),
                "created_at": meta.get("timestamp"),
            }

    # Sort by score descending, limit
    results = sorted(merged.values(), key=lambda r: r["score"], reverse=True)[:limit]

    duration_ms = round((time.monotonic() - t0) * 1000, 1)

    return {
        "query": q,
        "results": results,
        "meta": {
            "semantic_available": semantic_ok,
            "semantic_count": len(semantic_results),
            "verbatim_count": len(verbatim_results),
            "total": len(results),
            "duration_ms": duration_ms,
        },
    }
