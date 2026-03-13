"""Qdrant integration for semantic search over transcripts.

Uses the same BGE-large-en-v1.5 embedding model and Qdrant instance
as the brain CLI, storing transcript chunks in vs3-transcripts-bge.

Chunking strategy:
- One point per segment (speaker turn) with full metadata
- Also stores a transcript-level summary point for overview searches
"""

import os
import uuid
from datetime import datetime, timezone

import httpx

from services.settings import get_settings

EMBED_MODEL = "BAAI/bge-large-en-v1.5"
DEFAULT_COLLECTION = "vs3-transcripts-bge"

_http = httpx.AsyncClient(timeout=30.0)

# In-memory index status tracker.
# Values: "indexed" | "indexing" | "stale" | "failed" | "disabled"
_index_status: dict[str, dict] = {}


def mark_stale(transcript_id: str):
    """Mark a transcript as needing reindex."""
    _index_status[transcript_id] = {"status": "stale", "ts": datetime.now(timezone.utc).isoformat()}


def get_index_status(transcript_id: str) -> dict:
    """Get the current index status for a transcript."""
    if not _is_qdrant_enabled():
        return {"status": "disabled"}
    return _index_status.get(transcript_id, {"status": "unknown"})


def _get_qdrant_config() -> dict:
    """Return qdrant config dict from settings with env fallback."""
    settings = get_settings()
    return {
        "qdrant_url": settings.get("qdrant_url") or os.getenv("QDRANT_URL", ""),
        "qdrant_api_key": settings.get("qdrant_api_key") or "",
        "embed_url": settings.get("embed_url") or os.getenv("EMBED_URL", ""),
        "embed_api_key": settings.get("embed_api_key") or os.getenv("EMBED_API_KEY", ""),
        "app_base_url": os.getenv("APP_BASE_URL", ""),
        "collection": settings.get("qdrant_collection") or DEFAULT_COLLECTION,
    }


def _qdrant_headers(config: dict) -> dict:
    """Build headers for Qdrant API requests (includes API key if set)."""
    headers = {}
    if config.get("qdrant_api_key"):
        headers["api-key"] = config["qdrant_api_key"]
    return headers


def _is_qdrant_enabled() -> bool:
    """Check if Qdrant is enabled in settings."""
    return get_settings().get("qdrant_enabled", False)


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get BGE-1024 embeddings for a batch of texts."""
    cfg = _get_qdrant_config()
    if not cfg["embed_url"]:
        raise RuntimeError("Embedding API URL not configured")

    headers = {}
    if cfg["embed_api_key"]:
        headers["Authorization"] = f"Bearer {cfg['embed_api_key']}"

    resp = await _http.post(
        cfg["embed_url"],
        json={"input": texts, "model": EMBED_MODEL},
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    # Sort by index to ensure order matches input
    data.sort(key=lambda x: x["index"])
    return [d["embedding"] for d in data]


async def ingest_transcript(transcript, segments, tags: list[str] | None = None) -> dict:
    """Ingest a transcript and its segments into Qdrant.

    Embedded text is enriched with emotion, speaker, timing, and tag metadata
    to maximize LLM search relevance. The primary use case is finding recordings
    by semantic query ("when was Cory upset?", "conversation about X").

    Args:
        transcript: dict with id, job_id, title, raw_text, summary, language, created_at
        segments: list of dicts with id, text, speaker_name, start_time, end_time,
                  emotion, emotion_confidence
        tags: optional list of tag strings for the transcript

    Returns:
        dict with point counts and status
    """
    transcript_id = str(transcript["id"])
    job_id = str(transcript["job_id"])
    tags = tags or []

    cfg = _get_qdrant_config()
    qdrant_url, collection, qheaders = cfg["qdrant_url"], cfg["collection"], _qdrant_headers(cfg)
    if not qdrant_url:
        return {"status": "skipped", "points_stored": 0}

    # First, delete any existing points for this transcript
    await _http.post(
        f"{qdrant_url}/collections/{collection}/points/delete",
        headers=qheaders,
        json={
            "filter": {
                "must": [
                    {"key": "metadata.transcript_id", "match": {"value": transcript_id}}
                ]
            }
        },
    )

    points = []
    texts_to_embed = []

    # Build segment points with rich embedded text for LLM search
    for seg in segments:
        if not seg["text"].strip():
            continue

        speaker = seg.get("speaker_name", "Unknown")
        emotion = seg.get("emotion", "unknown")
        confidence = seg.get("emotion_confidence", 0.0)

        # Build enriched text: speaker + emotion context + speech
        parts = [f"{speaker}"]
        if emotion and emotion not in ("unknown", "neutral", "<unk>") and confidence > 0.5:
            parts.append(f"(feeling {emotion})")
        parts.append(f": {seg['text']}")
        text = " ".join(parts)

        texts_to_embed.append(text)

        points.append({
            "id": str(uuid.uuid4()),
            "payload": {
                "document": text,
                "metadata": {
                    "type": "segment",
                    "transcript_id": transcript_id,
                    "job_id": job_id,
                    "segment_id": str(seg["id"]),
                    "speaker": speaker,
                    "start_time": seg.get("start_time", 0),
                    "end_time": seg.get("end_time", 0),
                    "emotion": emotion,
                    "emotion_confidence": confidence,
                    "title": transcript.get("title", ""),
                    "timestamp": transcript.get("created_at", datetime.now(timezone.utc).isoformat()),
                },
            },
        })

    # Build transcript-level summary point with maximum context
    title = transcript.get("title") or "Untitled"
    speakers = sorted({s.get("speaker_name", "Unknown") for s in segments if s.get("speaker_name")})
    ts = transcript.get("created_at", "")

    # Compute duration from segments
    if segments:
        duration_s = max(s.get("end_time", 0) for s in segments)
        duration_str = f"{int(duration_s // 60)}m {int(duration_s % 60)}s" if duration_s >= 60 else f"{int(duration_s)}s"
    else:
        duration_str = "unknown"

    # Build emotion summary across all segments
    emotion_counts: dict[str, int] = {}
    for seg in segments:
        emo = seg.get("emotion", "unknown")
        conf = seg.get("emotion_confidence", 0.0)
        if emo and emo not in ("unknown", "<unk>") and conf > 0.5:
            emotion_counts[emo] = emotion_counts.get(emo, 0) + 1
    emotion_summary = ", ".join(f"{e} ({c}x)" for e, c in sorted(emotion_counts.items(), key=lambda x: -x[1]))

    # Assemble rich summary text
    summary_parts = [f"Recording: {title}."]
    summary_parts.append(f"Speakers: {', '.join(speakers)}.")
    summary_parts.append(f"Duration: {duration_str}.")
    if emotion_summary:
        summary_parts.append(f"Emotional tone: {emotion_summary}.")
    if tags:
        summary_parts.append(f"Topics: {', '.join(tags)}.")
    # Parse structured summary (JSON with text, action_items, outline)
    raw_summary = transcript.get("summary")
    summary_data: dict = {}
    if raw_summary:
        import json as _json
        try:
            summary_data = _json.loads(raw_summary) if isinstance(raw_summary, str) else raw_summary
            if isinstance(summary_data, dict):
                if summary_data.get("text"):
                    summary_parts.append(f"Summary: {summary_data['text']}")
                items = summary_data.get("action_items", [])
                if items:
                    item_texts = []
                    for item in items:
                        t = item["text"] if isinstance(item, dict) else item
                        item_texts.append(f"- {t}")
                    summary_parts.append(f"Action Items: {'; '.join(item_texts)}")
                outline = summary_data.get("outline", [])
                if outline:
                    outline_texts = []
                    for section in outline:
                        heading = section.get("heading", "") if isinstance(section, dict) else str(section)
                        content = section.get("content", "") if isinstance(section, dict) else ""
                        outline_texts.append(f"{heading}: {content}" if content else heading)
                    summary_parts.append(f"Outline: {'; '.join(outline_texts)}")
            else:
                # Plain string summary
                summary_parts.append(f"Summary: {raw_summary}")
        except (ValueError, TypeError):
            summary_parts.append(f"Summary: {raw_summary}")
    if transcript.get("raw_text"):
        summary_parts.append(f"Content: {transcript['raw_text'][:500]}")

    summary_text = " ".join(summary_parts)

    texts_to_embed.append(summary_text)
    points.append({
        "id": str(uuid.uuid4()),
        "payload": {
            "document": summary_text,
            "metadata": {
                "type": "transcript_summary",
                "transcript_id": transcript_id,
                "job_id": job_id,
                "title": title,
                "speakers": speakers,
                "emotions": emotion_counts,
                "tags": tags,
                "duration_seconds": max(s.get("end_time", 0) for s in segments) if segments else 0,
                "segment_count": len(segments),
                "language": transcript.get("language", "en"),
                "timestamp": ts or datetime.now(timezone.utc).isoformat(),
                "action_items": summary_data.get("action_items", []) if isinstance(summary_data, dict) else [],
                "outline": summary_data.get("outline", []) if isinstance(summary_data, dict) else [],
            },
        },
    })

    if not texts_to_embed:
        return {"status": "empty", "points_stored": 0}

    # Batch embed - embedding server handles batches
    # Process in chunks of 32 to avoid overloading
    all_embeddings = []
    batch_size = 32
    for i in range(0, len(texts_to_embed), batch_size):
        batch = texts_to_embed[i:i + batch_size]
        embeddings = await get_embeddings(batch)
        all_embeddings.extend(embeddings)

    # Attach vectors to points
    for point, embedding in zip(points, all_embeddings):
        point["vector"] = embedding

    # Batch upsert to Qdrant (chunks of 100)
    upsert_batch_size = 100
    for i in range(0, len(points), upsert_batch_size):
        batch = points[i:i + upsert_batch_size]
        resp = await _http.put(
            f"{qdrant_url}/collections/{collection}/points",
            json={"points": batch},
            headers=qheaders,
        )
        resp.raise_for_status()

    return {
        "status": "ok",
        "points_stored": len(points),
        "segments_indexed": len(points) - 1,  # minus the summary point
        "transcript_id": transcript_id,
    }


async def semantic_search(query: str, limit: int = 10, speaker: str | None = None,
                          transcript_id: str | None = None) -> list[dict]:
    """Semantic search across all transcripts.

    Args:
        query: Natural language search query
        limit: Max results
        speaker: Optional speaker name filter
        transcript_id: Optional transcript ID filter

    Returns:
        list of search results with score, text, and metadata
    """
    embedding = (await get_embeddings([query]))[0]

    # Build filter
    must_conditions = []
    if speaker:
        must_conditions.append({
            "key": "metadata.speaker",
            "match": {"value": speaker},
        })
    if transcript_id:
        must_conditions.append({
            "key": "metadata.transcript_id",
            "match": {"value": transcript_id},
        })

    body: dict = {
        "vector": embedding,
        "limit": limit,
        "with_payload": True,
    }
    if must_conditions:
        body["filter"] = {"must": must_conditions}

    cfg = _get_qdrant_config()
    qdrant_url, collection, qheaders = cfg["qdrant_url"], cfg["collection"], _qdrant_headers(cfg)
    app_base_url = cfg["app_base_url"]
    if not qdrant_url:
        return []

    resp = await _http.post(
        f"{qdrant_url}/collections/{collection}/points/query",
        json={"query": embedding, "limit": limit, "with_payload": True,
              "filter": {"must": must_conditions} if must_conditions else None},
        headers=qheaders,
    )
    resp.raise_for_status()
    results = resp.json().get("result", {}).get("points", [])

    out = []
    for r in results:
        meta = r["payload"].get("metadata", {})
        job_id = meta.get("job_id", "")
        entry = {
            "id": r["id"],
            "score": r["score"],
            "text": r["payload"].get("document", ""),
            "metadata": meta,
        }
        if job_id and app_base_url:
            entry["url"] = f"{app_base_url}/jobs/{job_id}"
        out.append(entry)
    return out


async def delete_transcript_points(transcript_id: str) -> dict:
    """Remove all points for a transcript from Qdrant."""
    if not _is_qdrant_enabled():
        return {"status": "skipped", "transcript_id": transcript_id}
    cfg = _get_qdrant_config()
    qdrant_url, collection, qheaders = cfg["qdrant_url"], cfg["collection"], _qdrant_headers(cfg)
    if not qdrant_url:
        return {"status": "skipped", "transcript_id": transcript_id}
    resp = await _http.post(
        f"{qdrant_url}/collections/{collection}/points/delete",
        headers=qheaders,
        json={
            "filter": {
                "must": [
                    {"key": "metadata.transcript_id", "match": {"value": transcript_id}}
                ]
            }
        },
    )
    resp.raise_for_status()
    return {"status": "ok", "transcript_id": transcript_id}


async def reindex_transcript(transcript_id: str):
    """Re-ingest a transcript from DB into Qdrant.

    Designed to be called as a BackgroundTask after mutations
    (title edit, tag add/remove, speaker rename, overview generation).
    No-ops silently if Qdrant is disabled in settings.
    """
    if not _is_qdrant_enabled():
        _index_status[transcript_id] = {"status": "disabled"}
        return

    _index_status[transcript_id] = {"status": "indexing", "ts": datetime.now(timezone.utc).isoformat()}

    from db.session import SessionLocal
    from db.models import Transcript, Segment, Tag

    db = SessionLocal()
    try:
        from sqlalchemy.orm import joinedload
        transcript = (
            db.query(Transcript)
            .filter(Transcript.id == uuid.UUID(transcript_id))
            .options(
                joinedload(Transcript.segments).joinedload(Segment.speaker),
                joinedload(Transcript.tags),
            )
            .first()
        )
        if not transcript:
            print(f"[qdrant] reindex skipped: transcript {transcript_id} not found")
            _index_status[transcript_id] = {"status": "unknown"}
            return

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

        result = await ingest_transcript(t_dict, seg_dicts, tags=tag_list)
        _index_status[transcript_id] = {
            "status": "indexed",
            "points": result["points_stored"],
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[qdrant] reindexed {transcript_id}: {result['points_stored']} points")
    except Exception as e:
        _index_status[transcript_id] = {
            "status": "failed",
            "error": str(e),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[qdrant] reindex failed for {transcript_id}: {e}")
    finally:
        db.close()


async def collection_stats() -> dict:
    """Get collection stats."""
    cfg = _get_qdrant_config()
    collection = cfg["collection"]
    if not _is_qdrant_enabled():
        return {"collection": collection, "status": "disabled", "points_count": 0, "vectors_count": 0}
    qdrant_url, qheaders = cfg["qdrant_url"], _qdrant_headers(cfg)
    if not qdrant_url:
        return {"collection": collection, "status": "not_configured", "points_count": 0, "vectors_count": 0}
    resp = await _http.get(f"{qdrant_url}/collections/{collection}", headers=qheaders)
    resp.raise_for_status()
    result = resp.json().get("result", {})
    return {
        "collection": collection,
        "points_count": result.get("points_count", 0),
        "vectors_count": result.get("vectors_count", 0),
        "status": result.get("status", "unknown"),
    }
