import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile, File
from pydantic import BaseModel
from redis import Redis as SyncRedis
from redis.asyncio import Redis as AsyncRedis
from rq import Queue
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from db.session import get_db
from sqlalchemy.orm import joinedload
from db.models import Speaker, Embedding, Segment, Transcript
from services.qdrant import reindex_transcript, mark_stale

AVATAR_DIR = Path("/data/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATA_DIR = Path("/data")
VERIFY_TIMEOUT = int(os.getenv("VERIFY_TIMEOUT", "120"))

router = APIRouter(prefix="/api/speakers", tags=["speakers"])


class SpeakerUpdate(BaseModel):
    name: str | None = None
    is_trusted: bool | None = None
    avatar_id: int | None = None


class SpeakerMerge(BaseModel):
    source_id: str
    target_id: str


class SegmentReassign(BaseModel):
    speaker_id: str


@router.get("/")
async def list_speakers(db: Session = Depends(get_db)):
    speakers = (
        db.query(
            Speaker,
            func.count(func.distinct(Embedding.id)).label("embedding_count"),
            func.count(func.distinct(Segment.id)).label("segment_count"),
        )
        .outerjoin(Embedding, Embedding.speaker_id == Speaker.id)
        .outerjoin(Segment, Segment.speaker_id == Speaker.id)
        .group_by(Speaker.id)
        .order_by(Speaker.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(speaker.id),
            "name": speaker.name,
            "is_trusted": speaker.is_trusted,
            "match_confidence": speaker.match_confidence,
            "avatar_id": speaker.avatar_id,
            "custom_avatar": f"/api/speakers/{speaker.id}/avatar-image" if speaker.custom_avatar else None,
            "embedding_count": embedding_count,
            "segment_count": segment_count,
            "created_at": speaker.created_at.isoformat() if speaker.created_at else None,
        }
        for speaker, embedding_count, segment_count in speakers
    ]


@router.put("/{speaker_id}")
async def update_speaker(
    speaker_id: str,
    update: SpeakerUpdate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    speaker = db.query(Speaker).filter(Speaker.id == uuid.UUID(speaker_id)).first()
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")

    if update.name is not None:
        speaker.name = update.name
        speaker.is_trusted = True  # naming = recognized
    if update.is_trusted is not None:
        speaker.is_trusted = update.is_trusted
    if update.avatar_id is not None:
        speaker.avatar_id = update.avatar_id

    db.commit()

    # Reindex all transcripts that have this speaker
    transcript_ids = (
        db.query(Segment.transcript_id)
        .filter(Segment.speaker_id == uuid.UUID(speaker_id))
        .distinct()
        .all()
    )
    for (tid,) in transcript_ids:
        mark_stale(str(tid))
        bg.add_task(reindex_transcript, str(tid))

    return {
        "id": str(speaker.id),
        "name": speaker.name,
        "is_trusted": speaker.is_trusted,
        "avatar_id": speaker.avatar_id,
        "custom_avatar": f"/api/speakers/{speaker.id}/avatar-image" if speaker.custom_avatar else None,
    }


@router.delete("/{speaker_id}")
async def delete_speaker(speaker_id: str, db: Session = Depends(get_db)):
    """Delete a speaker. Segments are unlinked (speaker set to NULL), embeddings cascade-deleted."""
    speaker = db.query(Speaker).filter(Speaker.id == uuid.UUID(speaker_id)).first()
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")

    # Unlink segments (set speaker_id to NULL) so transcripts aren't broken
    db.execute(
        text("UPDATE segments SET speaker_id = NULL WHERE speaker_id = :sid"),
        {"sid": str(speaker.id)},
    )

    db.delete(speaker)
    db.commit()
    return {"deleted": True, "speaker_id": speaker_id}


@router.get("/{speaker_id}/embeddings")
async def list_speaker_embeddings(speaker_id: str, db: Session = Depends(get_db)):
    """List all embeddings for a speaker with their source segment/recording context."""
    speaker = db.query(Speaker).filter(Speaker.id == uuid.UUID(speaker_id)).first()
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")

    embeddings = (
        db.query(Embedding)
        .filter(Embedding.speaker_id == speaker.id)
        .options(joinedload(Embedding.segment))
        .order_by(Embedding.created_at.desc())
        .all()
    )

    results = []
    for emb in embeddings:
        seg = emb.segment
        # Get transcript title for context
        transcript_title = None
        job_id = str(emb.job_id) if emb.job_id else None
        if seg:
            transcript = db.query(Transcript).filter(Transcript.id == seg.transcript_id).first()
            if transcript:
                transcript_title = transcript.title
                job_id = str(transcript.job_id)
        elif emb.job_id:
            # No segment linked — look up transcript via job_id for context
            transcript = db.query(Transcript).filter(Transcript.job_id == emb.job_id).first()
            if transcript:
                transcript_title = transcript.title

        results.append({
            "id": str(emb.id),
            "segment": {
                "id": str(seg.id),
                "text": seg.text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
            } if seg else None,
            "job_id": job_id,
            "transcript_title": transcript_title,
            "created_at": emb.created_at.isoformat() if emb.created_at else None,
        })

    return results


@router.delete("/{speaker_id}/embeddings/{embedding_id}")
async def delete_embedding(speaker_id: str, embedding_id: str, db: Session = Depends(get_db)):
    """Delete a single embedding from a speaker."""
    emb = (
        db.query(Embedding)
        .filter(
            Embedding.id == uuid.UUID(embedding_id),
            Embedding.speaker_id == uuid.UUID(speaker_id),
        )
        .first()
    )
    if not emb:
        raise HTTPException(status_code=404, detail="Embedding not found")

    db.delete(emb)
    db.commit()
    return {"deleted": True, "embedding_id": embedding_id}


@router.post("/{speaker_id}/avatar")
async def upload_avatar(
    speaker_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a custom avatar image for a speaker."""
    speaker = db.query(Speaker).filter(Speaker.id == uuid.UUID(speaker_id)).first()
    if not speaker:
        raise HTTPException(status_code=404, detail="Speaker not found")

    # Validate image type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    filename = f"{speaker_id}.{ext}"
    filepath = AVATAR_DIR / filename

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    speaker.custom_avatar = filename
    db.commit()

    return {
        "id": str(speaker.id),
        "custom_avatar": f"/api/speakers/{speaker_id}/avatar-image",
    }


@router.get("/{speaker_id}/avatar-image")
async def get_avatar_image(speaker_id: str, db: Session = Depends(get_db)):
    """Serve a speaker's custom avatar image."""
    from fastapi.responses import FileResponse

    speaker = db.query(Speaker).filter(Speaker.id == uuid.UUID(speaker_id)).first()
    if not speaker or not speaker.custom_avatar:
        raise HTTPException(status_code=404, detail="No custom avatar")

    filepath = AVATAR_DIR / speaker.custom_avatar
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Avatar file not found")

    return FileResponse(filepath, media_type="image/png")


@router.post("/merge")
async def merge_speakers(
    merge: SpeakerMerge,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Merge source speaker into target speaker.
    All segments and embeddings from source are reassigned to target.
    Source speaker is deleted."""
    source = db.query(Speaker).filter(Speaker.id == uuid.UUID(merge.source_id)).first()
    target = db.query(Speaker).filter(Speaker.id == uuid.UUID(merge.target_id)).first()

    if not source or not target:
        raise HTTPException(status_code=404, detail="Speaker not found")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot merge speaker with itself")

    # Find affected transcripts before merge
    affected_tids = (
        db.query(Segment.transcript_id)
        .filter(Segment.speaker_id.in_([source.id, target.id]))
        .distinct()
        .all()
    )

    # Reassign segments
    db.query(Segment).filter(Segment.speaker_id == source.id).update(
        {"speaker_id": target.id}
    )
    # Reassign embeddings
    db.query(Embedding).filter(Embedding.speaker_id == source.id).update(
        {"speaker_id": target.id}
    )
    # Delete source
    db.delete(source)
    db.commit()

    # Reindex all affected transcripts
    for (tid,) in affected_tids:
        mark_stale(str(tid))
        bg.add_task(reindex_transcript, str(tid))

    return {"merged": True, "target_id": str(target.id), "target_name": target.name}


@router.patch("/segments/{segment_id}")
async def reassign_segment_speaker(
    segment_id: str,
    body: SegmentReassign,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Reassign a single segment to a different speaker."""
    segment = db.query(Segment).filter(Segment.id == uuid.UUID(segment_id)).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    target = db.query(Speaker).filter(Speaker.id == uuid.UUID(body.speaker_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="Speaker not found")

    segment.speaker_id = target.id
    db.commit()

    mark_stale(str(segment.transcript_id))
    bg.add_task(reindex_transcript, str(segment.transcript_id))

    return {"segment_id": str(segment.id), "speaker_id": str(target.id), "speaker_name": target.name}


@router.post("/verify")
async def verify_speakers_endpoint(
    file: UploadFile = File(...),
    min_segment_duration: float = Form(2.0),
    confidence_threshold: float = Form(0.45),
):
    """Identify speakers in audio WITHOUT full pipeline processing.

    Returns speaker identification timeline with dialogue detection.
    Does NOT create a job, transcript, or store any data.
    Read-only query against existing speaker embeddings.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No audio file provided")

    # Save uploaded file to temp location
    job_key = f"verify:{uuid.uuid4()}"
    input_dir = DATA_DIR / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    temp_path = str(input_dir / f"verify_{uuid.uuid4()}_{file.filename}")

    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        # Enqueue verify job on worker via RQ
        conn = SyncRedis.from_url(REDIS_URL)
        q = Queue("voicestack", connection=conn)

        q.enqueue(
            "pipeline.verify_job.run_verify_job",
            job_key,
            temp_path,
            confidence_threshold,
            min_segment_duration,
            job_timeout=300,
        )

        # Poll Redis for result
        async_redis = AsyncRedis.from_url(REDIS_URL)
        start = time.time()

        try:
            while time.time() - start < VERIFY_TIMEOUT:
                result = await async_redis.get(job_key)
                if result:
                    data = json.loads(result)
                    if "error" in data:
                        raise HTTPException(status_code=500, detail=data["error"])
                    return data
                await asyncio.sleep(0.5)
        finally:
            await async_redis.aclose()

        raise HTTPException(status_code=504, detail="Verification timed out")

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
