import asyncio
import json
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from rq import Queue
from db.session import get_db, SessionLocal
from db.models import Job, Asset, Transcript, Segment, Speaker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATA_DIR = Path("/data")


def get_queue() -> Queue:
    conn = Redis.from_url(REDIS_URL)
    return Queue("voicestack", connection=conn)


@router.post("/")
async def create_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Create job record
    job = Job(status="QUEUED", progress=0)
    db.add(job)
    db.flush()

    # Save uploaded file
    input_dir = DATA_DIR / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = f"{job.id}_{file.filename}"
    input_path = str(input_dir / safe_filename)

    content = await file.read()
    with open(input_path, "wb") as f:
        f.write(content)

    # Create asset record
    asset = Asset(
        job_id=job.id,
        filename=file.filename,
        mimetype=file.content_type,
        size_bytes=len(content),
        input_path=input_path,
    )
    db.add(asset)
    db.commit()

    # Enqueue pipeline job
    queue = get_queue()
    queue.enqueue(
        "pipeline.run.run_pipeline",
        str(job.id),
        input_path,
        job_timeout="1h",
    )

    return {"job_id": str(job.id), "status": "QUEUED"}


@router.get("/")
async def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    jobs = (
        db.query(Job)
        .options(joinedload(Job.assets), joinedload(Job.transcripts))
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    # Batch-fetch speakers per job via transcripts → segments → speakers
    from sqlalchemy import func, distinct
    job_ids = [j.id for j in jobs]
    speaker_rows = (
        db.query(
            Transcript.job_id,
            Speaker.id,
            Speaker.name,
            Speaker.avatar_id,
            Speaker.custom_avatar,
        )
        .join(Segment, Segment.transcript_id == Transcript.id)
        .join(Speaker, Speaker.id == Segment.speaker_id)
        .filter(Transcript.job_id.in_(job_ids))
        .distinct()
        .all()
    ) if job_ids else []

    # Group speakers by job_id
    job_speakers: dict[uuid.UUID, list[dict]] = {}
    for job_id, spk_id, spk_name, spk_avatar, spk_custom in speaker_rows:
        job_speakers.setdefault(job_id, []).append({
            "id": str(spk_id),
            "name": spk_name,
            "avatar_id": spk_avatar,
            "custom_avatar": f"/api/speakers/{spk_id}/avatar-image" if spk_custom else None,
        })

    results = []
    for j in jobs:
        asset = j.assets[0] if j.assets else None
        transcript = j.transcripts[0] if j.transcripts else None
        results.append({
            "id": str(j.id),
            "status": j.status,
            "progress": j.progress,
            "pipeline_stage": j.pipeline_stage,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            "title": transcript.title if transcript else None,
            "has_summary": bool(transcript.summary) if transcript else False,
            "speakers": job_speakers.get(j.id, []),
            "asset": {
                "filename": asset.filename,
                "mimetype": asset.mimetype,
                "size_bytes": asset.size_bytes,
                "duration_seconds": asset.duration_seconds,
            } if asset else None,
        })
    return results


@router.get("/{job_id}")
async def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    asset = db.query(Asset).filter(Asset.job_id == job.id).first()

    return {
        "id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "pipeline_stage": job.pipeline_stage,
        "params": job.params,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "asset": {
            "filename": asset.filename,
            "mimetype": asset.mimetype,
            "size_bytes": asset.size_bytes,
            "duration_seconds": asset.duration_seconds,
        } if asset else None,
    }


@router.delete("/{job_id}")
async def delete_job(job_id: str, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Delete a job and all associated data.

    Cascade deletes: assets, transcripts, segments, tags.
    Embeddings get job_id/segment_id SET NULL (preserved for speaker matching).
    Qdrant points for associated transcripts are cleaned up in background.
    """
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Collect transcript IDs for Qdrant cleanup before cascade deletes them
    transcript_ids = [
        str(t.id)
        for t in db.query(Transcript).filter(Transcript.job_id == job.id).all()
    ]

    # Delete input file from disk
    asset = db.query(Asset).filter(Asset.job_id == job.id).first()
    if asset and asset.input_path:
        try:
            Path(asset.input_path).unlink(missing_ok=True)
        except OSError:
            pass

    # Delete artifacts directory (wav, playback ogg, etc.)
    artifacts_dir = Path("/data/artifacts") / job_id
    if artifacts_dir.exists():
        import shutil
        shutil.rmtree(artifacts_dir, ignore_errors=True)

    # Delete archival opus file
    archive_file = Path("/data/archival") / f"{job_id}.opus"
    archive_file.unlink(missing_ok=True)

    # Delete job (cascades to assets, transcripts → segments → tags)
    db.delete(job)
    db.commit()

    # Clean up Qdrant points in background
    from services.qdrant import delete_transcript_points
    for tid in transcript_ids:
        bg.add_task(delete_transcript_points, tid)

    return {"deleted": True, "job_id": job_id, "transcripts_cleaned": len(transcript_ids)}


@router.post("/{job_id}/reprocess")
async def reprocess_job(job_id: str, db: Session = Depends(get_db)):
    """Re-run the full pipeline on an existing job.

    Deletes old transcript/segments/embeddings for this job,
    resets status to QUEUED, and re-enqueues the pipeline.
    The original audio file is preserved.
    """
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    asset = db.query(Asset).filter(Asset.job_id == job.id).first()
    if not asset or not asset.input_path:
        raise HTTPException(status_code=400, detail="No input audio file for this job")

    # Verify the input file still exists
    input_path = asset.input_path
    if not Path(input_path).exists():
        raise HTTPException(status_code=400, detail="Original audio file not found on disk")

    # Clean up old results: embeddings → segments → transcripts (cascade-safe order)
    from db.models import Transcript, Segment, Embedding
    from sqlalchemy import text as sql_text

    # Delete embeddings for this job
    db.execute(sql_text("DELETE FROM embeddings WHERE job_id = :job_id"), {"job_id": job_id})

    # Delete segments and transcripts for this job (segments cascade from transcript)
    transcripts = db.query(Transcript).filter(Transcript.job_id == job.id).all()
    for t in transcripts:
        db.execute(sql_text("DELETE FROM segments WHERE transcript_id = :tid"), {"tid": str(t.id)})
        db.delete(t)

    # Reset job status
    job.status = "QUEUED"
    job.progress = 0
    job.pipeline_stage = None
    job.error_message = None
    db.commit()

    # Re-enqueue pipeline
    queue = get_queue()
    queue.enqueue(
        "pipeline.run.run_pipeline",
        str(job.id),
        input_path,
        job_timeout="1h",
    )

    return {"job_id": str(job.id), "status": "QUEUED", "message": "Reprocessing started"}


@router.get("/{job_id}/progress")
async def stream_job_progress(job_id: str):
    """SSE endpoint that streams job progress updates every 2 seconds."""
    from main import shutdown_event

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    async def event_stream():
        terminal_states = {"COMPLETED", "FAILED"}
        max_duration = 3600  # 1 hour max SSE lifetime
        start = asyncio.get_event_loop().time()
        while not shutdown_event.is_set() and (asyncio.get_event_loop().time() - start) < max_duration:
            db = SessionLocal()
            try:
                job = db.query(Job).filter(Job.id == job_uuid).first()
                if not job:
                    yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                    return

                payload = {
                    "status": job.status,
                    "progress": job.progress,
                    "stage": job.pipeline_stage,
                }
                if job.error_message:
                    payload["error_message"] = job.error_message

                yield f"data: {json.dumps(payload)}\n\n"

                if job.status in terminal_states:
                    return
            finally:
                db.close()

            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{job_id}/logs")
async def stream_job_logs(job_id: str):
    """SSE endpoint that streams pipeline logs by polling Redis list.

    Uses a simple polling approach (like the progress endpoint) instead of
    async Redis pub/sub, which doesn't flush properly through StreamingResponse.
    """
    from main import shutdown_event

    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    def log_stream():
        conn = Redis.from_url(REDIS_URL)
        history_key = f"job:{job_id}:log_history"
        cursor = 0  # Track how many lines we've already sent

        try:
            max_idle = 300  # Stop after 5 min of no new lines
            idle = 0
            while idle < max_idle and not shutdown_event.is_set():
                entries = conn.lrange(history_key, cursor, -1)
                if entries:
                    idle = 0
                    for entry in entries:
                        line = entry.decode("utf-8", errors="replace") if isinstance(entry, bytes) else entry
                        yield f"data: {json.dumps({'line': line})}\n\n"
                    cursor += len(entries)
                else:
                    idle += 1
                    # Send keepalive every 15s (every 15 iterations at 1s each)
                    if idle % 15 == 0:
                        yield f": keepalive\n\n"

                import time
                time.sleep(1)
        finally:
            conn.close()

    return StreamingResponse(
        log_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
