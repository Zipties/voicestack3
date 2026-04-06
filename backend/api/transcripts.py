import asyncio
import json
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from db.session import get_db
from db.models import Transcript, Segment, Speaker, Tag, Job
from services.llm import generate_overview
from services.chat import chat_with_agent, list_agents
from services.qdrant import reindex_transcript, mark_stale, get_index_status

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])


class TranscriptUpdate(BaseModel):
    title: str


class TagCreate(BaseModel):
    tag: str
    source: str = "manual"


class TagsSet(BaseModel):
    """Replace all tags on a transcript (idempotent)."""
    tags: list[str]
    source: str = "api"


@router.get("/agents/available")
async def get_available_agents():
    """List agents available for chat."""
    return await list_agents()


@router.get("/search")
async def search_transcripts(q: str, limit: int = 20, db: Session = Depends(get_db)):
    """Search across transcript titles and raw_text using ILIKE."""
    pattern = f"%{q}%"
    transcripts = (
        db.query(Transcript)
        .filter(
            or_(
                Transcript.title.ilike(pattern),
                Transcript.raw_text.ilike(pattern),
            )
        )
        .order_by(Transcript.created_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for t in transcripts:
        # Build a snippet: find the match position in raw_text
        snippet = None
        if t.raw_text:
            lower_text = t.raw_text.lower()
            idx = lower_text.find(q.lower())
            if idx >= 0:
                start = max(0, idx - 50)
                end = min(len(t.raw_text), idx + len(q) + 50)
                snippet = ("..." if start > 0 else "") + t.raw_text[start:end] + ("..." if end < len(t.raw_text) else "")
            else:
                snippet = t.raw_text[:100] + ("..." if len(t.raw_text) > 100 else "")
        results.append({
            "id": str(t.id),
            "title": t.title,
            "snippet": snippet,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return results


@router.get("/by-job/{job_id}")
async def get_transcript_by_job(job_id: str, db: Session = Depends(get_db)):
    transcript = (
        db.query(Transcript)
        .filter(Transcript.job_id == uuid.UUID(job_id))
        .options(
            joinedload(Transcript.segments).joinedload(Segment.speaker),
            joinedload(Transcript.tags),
        )
        .first()
    )
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    return _serialize_transcript(transcript)


@router.get("/{transcript_id}")
async def get_transcript(transcript_id: str, db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=404, detail="Transcript not found")

    return _serialize_transcript(transcript)


@router.get("/{transcript_id}/index-status")
async def transcript_index_status(transcript_id: str):
    """Get the Qdrant index status for a transcript."""
    return get_index_status(transcript_id)


@router.patch("/{transcript_id}")
async def update_transcript(
    transcript_id: str,
    update: TranscriptUpdate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Update transcript title."""
    transcript = db.query(Transcript).filter(Transcript.id == uuid.UUID(transcript_id)).first()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    transcript.title = update.title

    # Lock title so LLM re-summarization won't overwrite manual edits
    job = db.query(Job).filter(Job.id == transcript.job_id).first()
    if job:
        params = dict(job.params or {})
        params["title_locked"] = True
        job.params = params

    db.commit()

    mark_stale(transcript_id)
    bg.add_task(reindex_transcript, transcript_id)

    return {
        "id": str(transcript.id),
        "title": transcript.title,
    }


@router.post("/{transcript_id}/tags")
async def add_tag(
    transcript_id: str,
    tag_req: TagCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Add a tag to a transcript."""
    transcript = db.query(Transcript).filter(Transcript.id == uuid.UUID(transcript_id)).first()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    tag = Tag(
        transcript_id=transcript.id,
        tag=tag_req.tag,
        source=tag_req.source,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)

    mark_stale(transcript_id)
    bg.add_task(reindex_transcript, transcript_id)

    return {
        "id": str(tag.id),
        "transcript_id": str(tag.transcript_id),
        "tag": tag.tag,
        "source": tag.source,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


@router.put("/{transcript_id}/tags")
async def set_tags(
    transcript_id: str,
    req: TagsSet,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Replace all tags on a transcript (idempotent). For API/agent use."""
    transcript = (
        db.query(Transcript)
        .filter(Transcript.id == uuid.UUID(transcript_id))
        .options(joinedload(Transcript.tags))
        .first()
    )
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Delete all existing tags
    for tag in list(transcript.tags):
        db.delete(tag)
    db.flush()

    # Add new tags
    new_tags = []
    for tag_text in req.tags:
        tag_text = tag_text.strip().lower()
        if tag_text:
            tag = Tag(transcript_id=transcript.id, tag=tag_text, source=req.source)
            db.add(tag)
            new_tags.append(tag)

    db.commit()

    mark_stale(transcript_id)
    bg.add_task(reindex_transcript, transcript_id)

    return {
        "transcript_id": transcript_id,
        "tags": [{"id": str(t.id), "tag": t.tag, "source": t.source} for t in new_tags],
    }


@router.delete("/{transcript_id}/tags/{tag_id}")
async def remove_tag(
    transcript_id: str,
    tag_id: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Remove a tag from a transcript."""
    tag = (
        db.query(Tag)
        .filter(
            Tag.id == uuid.UUID(tag_id),
            Tag.transcript_id == uuid.UUID(transcript_id),
        )
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    db.delete(tag)
    db.commit()
    mark_stale(transcript_id)
    bg.add_task(reindex_transcript, transcript_id)
    return Response(status_code=204)


@router.post("/{transcript_id}/generate-overview")
async def generate_transcript_overview(transcript_id: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Generate title, summary, tags, action items, and outline via LLM.

    This is the "Analyze" button. It:
    1. Generates a structured title (e.g., "Journal Entry: Morning Reflections")
    2. Writes a summary with emotional context
    3. Auto-tags with searchable keywords
    4. Extracts action items
    5. Builds an outline
    6. Re-indexes in Qdrant with all new metadata
    """
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
        raise HTTPException(status_code=404, detail="Transcript not found")

    if not transcript.segments:
        raise HTTPException(status_code=400, detail="Transcript has no segments")

    attributed_text = _build_attributed_text(transcript)

    # Pass recording date so title includes it
    recorded_at = None
    if transcript.created_at:
        recorded_at = transcript.created_at.strftime("%Y-%m-%d")

    try:
        overview = await generate_overview(attributed_text, recorded_at=recorded_at)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Store with checked state on each action item (action_items already normalized to objects by llm.py)
    action_items = [
        {"text": item.get("text", item) if isinstance(item, dict) else item,
         "assignee": item.get("assignee") if isinstance(item, dict) else None,
         "checked": False}
        for item in overview["action_items"]
    ]
    # Only update title if not locked by calendar match or manual edit
    job = db.query(Job).filter(Job.id == transcript.job_id).first()
    title_locked = (job.params or {}).get("title_locked", False) if job else False
    if not title_locked:
        transcript.title = overview["title"]
    transcript.summary = json.dumps({
        "text": overview["summary"],
        "action_items": action_items,
        "outline": overview["outline"],
    })

    # Replace LLM-generated tags (preserve manual tags)
    existing_manual = [t for t in transcript.tags if t.source == "manual"]
    # Delete old LLM tags
    for tag in list(transcript.tags):
        if tag.source != "manual":
            db.delete(tag)
    db.flush()
    # Add new LLM tags (deduplicated against manual)
    manual_set = {t.tag.lower() for t in existing_manual}
    for tag_text in overview.get("tags", []):
        if tag_text.lower() not in manual_set:
            db.add(Tag(transcript_id=transcript.id, tag=tag_text, source="llm"))

    db.commit()

    mark_stale(transcript_id)
    bg.add_task(reindex_transcript, transcript_id)

    overview["action_items"] = action_items
    return overview


@router.post("/{transcript_id}/resummarize")
async def resummarize_transcript(transcript_id: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Delete vectors, clear summary, and regenerate overview.

    For testing prompt changes without reprocessing audio.
    """
    from services.qdrant import delete_transcript_points

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
        raise HTTPException(status_code=404, detail="Transcript not found")

    if not transcript.segments:
        raise HTTPException(status_code=400, detail="Transcript has no segments")

    # 1. Delete existing vectors
    await delete_transcript_points(transcript_id)

    # 2. Clear existing summary
    transcript.summary = None
    # Delete LLM-generated tags (preserve manual)
    for tag in list(transcript.tags):
        if tag.source != "manual":
            db.delete(tag)
    db.flush()

    # 3. Regenerate overview
    attributed_text = _build_attributed_text(transcript)
    recorded_at = None
    if transcript.created_at:
        recorded_at = transcript.created_at.strftime("%Y-%m-%d")

    try:
        overview = await generate_overview(attributed_text, recorded_at=recorded_at)
    except RuntimeError as e:
        db.commit()
        raise HTTPException(status_code=503, detail=str(e))

    # 4. Store new results
    action_items = [
        {"text": item.get("text", item) if isinstance(item, dict) else item,
         "assignee": item.get("assignee") if isinstance(item, dict) else None,
         "checked": False}
        for item in overview["action_items"]
    ]
    # Only update title if not locked by calendar match or manual edit
    job = db.query(Job).filter(Job.id == transcript.job_id).first()
    title_locked = (job.params or {}).get("title_locked", False) if job else False
    if not title_locked:
        transcript.title = overview["title"]
    transcript.summary = json.dumps({
        "text": overview["summary"],
        "action_items": action_items,
        "outline": overview["outline"],
    })

    # Add new LLM tags
    manual_set = {t.tag.lower() for t in transcript.tags if t.source == "manual"}
    for tag_text in overview.get("tags", []):
        if tag_text.lower() not in manual_set:
            db.add(Tag(transcript_id=transcript.id, tag=tag_text, source="llm"))

    db.commit()

    # 5. Reindex with fresh vectors
    bg.add_task(reindex_transcript, transcript_id)

    overview["action_items"] = action_items
    return overview


@router.patch("/{transcript_id}/action-items/{item_index}")
async def toggle_action_item(
    transcript_id: str,
    item_index: int,
    db: Session = Depends(get_db),
):
    """Toggle the checked state of an action item."""
    transcript = db.query(Transcript).filter(Transcript.id == uuid.UUID(transcript_id)).first()
    if not transcript or not transcript.summary:
        raise HTTPException(status_code=404, detail="Transcript or summary not found")

    summary_data = json.loads(transcript.summary)
    items = summary_data.get("action_items", [])

    if item_index < 0 or item_index >= len(items):
        raise HTTPException(status_code=400, detail="Invalid item index")

    # Handle both old format (string) and new format (object with checked)
    item = items[item_index]
    if isinstance(item, str):
        items[item_index] = {"text": item, "checked": True, "assignee": None}
    else:
        items[item_index]["checked"] = not item.get("checked", False)

    summary_data["action_items"] = items
    transcript.summary = json.dumps(summary_data)
    db.commit()

    return {"index": item_index, "item": items[item_index]}


class ActionItemUpdate(BaseModel):
    text: str
    checked: bool = False
    assignee: str | None = None


class OutlineItemUpdate(BaseModel):
    heading: str
    content: str = ""


class OverviewUpdate(BaseModel):
    summary: str | None = None
    action_items: list[ActionItemUpdate] | None = None
    outline: list[OutlineItemUpdate] | None = None


@router.put("/{transcript_id}/overview")
async def update_overview(
    transcript_id: str,
    update: OverviewUpdate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Update overview fields (summary, action items, outline). Triggers Qdrant reindex."""
    transcript = db.query(Transcript).filter(Transcript.id == uuid.UUID(transcript_id)).first()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    summary_data = {}
    if transcript.summary:
        try:
            summary_data = json.loads(transcript.summary)
        except (json.JSONDecodeError, TypeError):
            summary_data = {"text": transcript.summary}

    if update.summary is not None:
        summary_data["text"] = update.summary
    if update.action_items is not None:
        summary_data["action_items"] = [item.model_dump() for item in update.action_items]
    if update.outline is not None:
        summary_data["outline"] = [item.model_dump() for item in update.outline]

    transcript.summary = json.dumps(summary_data)
    db.commit()

    mark_stale(transcript_id)
    bg.add_task(reindex_transcript, transcript_id)

    return {
        "title": transcript.title,
        "summary": summary_data.get("text", ""),
        "action_items": summary_data.get("action_items", []),
        "outline": summary_data.get("outline", []),
    }


class ChatRequest(BaseModel):
    message: str
    agent: str = "main"
    session_id: str | None = None


@router.post("/{transcript_id}/chat")
async def chat_about_transcript(
    transcript_id: str,
    req: ChatRequest,
    db: Session = Depends(get_db),
):
    """Chat with the configured LLM about this transcript."""
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

    attributed_text = _build_attributed_text(transcript)

    # Build overview context if available
    overview_text = ""
    if transcript.summary:
        try:
            summary_data = json.loads(transcript.summary) if isinstance(transcript.summary, str) else transcript.summary
            parts = []
            if transcript.title:
                parts.append(f"Title: {transcript.title}")
            if summary_data.get("text"):
                parts.append(f"Summary: {summary_data['text']}")
            items = summary_data.get("action_items", [])
            if items:
                item_lines = []
                for item in items:
                    text_val = item["text"] if isinstance(item, dict) else item
                    checked = item.get("checked", False) if isinstance(item, dict) else False
                    assignee = item.get("assignee") if isinstance(item, dict) else None
                    assignee_tag = f" @{assignee}" if assignee else ""
                    item_lines.append(f"  [{'x' if checked else ' '}] {text_val}{assignee_tag}")
                parts.append("Action Items:\n" + "\n".join(item_lines))
            outline = summary_data.get("outline", [])
            if outline:
                outline_lines = []
                for section in outline:
                    outline_lines.append(f"  ## {section['heading']}")
                    if section.get("content"):
                        outline_lines.append(f"  {section['content']}")
                parts.append("Outline:\n" + "\n".join(outline_lines))
            if parts:
                overview_text = "\n".join(parts) + "\n\n"
        except (json.JSONDecodeError, TypeError):
            pass

    # Build the message with transcript context
    context_message = f"<transcript-overview>\n{overview_text}</transcript-overview>\n\n<transcript>\n{attributed_text}\n</transcript>\n\nUser question: {req.message}"

    try:
        result = await chat_with_agent(
            agent_id=req.agent,
            message=context_message,
            session_id=req.session_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return result


def _build_attributed_text(transcript: Transcript) -> str:
    """Build speaker-attributed transcript text with emotion annotations."""
    lines = []
    for seg in sorted(transcript.segments, key=lambda s: s.start_time):
        name = seg.speaker.name if seg.speaker else "Unknown"
        minutes = int(seg.start_time // 60)
        seconds = int(seg.start_time % 60)

        # Add emotion annotation when meaningful
        emotion_tag = ""
        if seg.emotion and seg.emotion not in ("unknown", "neutral") and seg.emotion_confidence and seg.emotion_confidence > 0.5:
            emotion_tag = f" ({seg.emotion})"

        # Add speech events like laughter, applause
        events_tag = ""
        if seg.speech_events:
            events = seg.speech_events if isinstance(seg.speech_events, list) else []
            if events:
                events_tag = f" [{', '.join(events)}]"

        lines.append(f"[{minutes:02d}:{seconds:02d}] {name}{emotion_tag}: {seg.text}{events_tag}")
    return "\n".join(lines)


def _serialize_transcript(transcript: Transcript) -> dict:
    import os
    job_id = str(transcript.job_id)
    app_base_url = os.getenv("APP_BASE_URL", "")
    return {
        "id": str(transcript.id),
        "job_id": job_id,
        "url": f"{app_base_url}/jobs/{job_id}",
        "raw_text": transcript.raw_text,
        "title": transcript.title,
        "summary": transcript.summary,
        "language": transcript.language,
        "segments": [
            {
                "id": str(seg.id),
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "text": seg.text,
                "word_timings": seg.word_timings,
                "speaker": {
                    "id": str(seg.speaker.id),
                    "name": seg.speaker.name,
                    "avatar_id": seg.speaker.avatar_id,
                    "custom_avatar": f"/api/speakers/{seg.speaker.id}/avatar-image" if seg.speaker.custom_avatar else None,
                } if seg.speaker else None,
                "original_speaker_label": seg.original_speaker_label,
                "emotion": seg.emotion,
                "emotion_confidence": seg.emotion_confidence,
                "speech_events": seg.speech_events or [],
            }
            for seg in sorted(transcript.segments, key=lambda s: s.start_time)
        ],
        "tags": [
            {"id": str(tag.id), "tag": tag.tag, "source": tag.source}
            for tag in transcript.tags
        ],
        "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
    }
