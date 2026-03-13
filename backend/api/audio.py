import os
import stat
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from db.session import get_db
from db.models import Job, Asset

router = APIRouter(prefix="/api/audio", tags=["audio"])

DATA_DIR = Path("/data")
CHUNK_SIZE = 64 * 1024  # 64KB chunks for streaming


def _resolve_audio_path(job_id: str, variant: str = "playback") -> Path:
    """Resolve the audio file path for a given job."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if variant == "playback":
        # Serve OGG by default (proven browser playback compatibility).
        # M4A available at /audio/{id}/m4a for clients that need accurate seeking.
        ogg = DATA_DIR / "artifacts" / job_id / "audio_playback.ogg"
        if ogg.exists():
            return ogg
        m4a = DATA_DIR / "artifacts" / job_id / "audio_playback.m4a"
        if m4a.exists():
            return m4a
        webm = DATA_DIR / "artifacts" / job_id / "audio_playback.webm"
        if webm.exists():
            return webm
        return DATA_DIR / "artifacts" / job_id / "audio_16k_mono.wav"
    elif variant == "wav":
        return DATA_DIR / "artifacts" / job_id / "audio_16k_mono.wav"
    elif variant == "opus":
        return DATA_DIR / "artifacts" / job_id / "audio_archival.opus"
    else:
        raise HTTPException(status_code=400, detail="Unknown audio variant")


def _range_response(path: Path, content_type: str, request: Request) -> Response:
    """Serve a file with HTTP Range request support."""
    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        # Parse Range: bytes=start-end
        try:
            range_spec = range_header.replace("bytes=", "").strip()
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
        except (ValueError, IndexError):
            raise HTTPException(status_code=416, detail="Invalid range")

        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(
                status_code=416,
                detail="Range not satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        content_length = end - start + 1

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
            },
        )

    # Full file response
    def iter_file():
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type=content_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


@router.get("/{job_id}")
async def stream_audio(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Stream the playback audio for a job with Range request support.

    Serves the 48kHz Opus playback file if available, falls back to WAV.
    """
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    path = _resolve_audio_path(job_id, "playback")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Set content type based on actual file
    ct_map = {".m4a": "audio/mp4", ".webm": "audio/webm", ".ogg": "audio/ogg", ".wav": "audio/wav"}
    content_type = ct_map.get(path.suffix, "application/octet-stream")
    return _range_response(path, content_type, request)


@router.get("/{job_id}/wav")
async def stream_audio_wav(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Stream the 16kHz mono WAV (ML pipeline version)."""
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    path = _resolve_audio_path(job_id, "wav")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return _range_response(path, "audio/wav", request)




@router.get("/{job_id}/m4a")
async def stream_audio_m4a(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Stream the M4A playback file (AAC in MP4, accurate seeking)."""
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    path = DATA_DIR / "artifacts" / job_id / "audio_playback.m4a"
    if not path.exists():
        raise HTTPException(status_code=404, detail="M4A file not found")

    return _range_response(path, "audio/mp4", request)

@router.get("/{job_id}/opus")
async def stream_audio_opus(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Stream the archival Opus file for a job with Range request support."""
    job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    path = _resolve_audio_path(job_id, "opus")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return _range_response(path, "audio/ogg", request)
