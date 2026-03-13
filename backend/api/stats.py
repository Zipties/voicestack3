from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from db.session import get_db
from db.models import Job, Speaker, Asset

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/")
async def get_stats(db: Session = Depends(get_db)):
    """System-wide stats for the dashboard."""
    total_jobs = db.query(func.count(Job.id)).scalar() or 0
    completed_jobs = db.query(func.count(Job.id)).filter(Job.status.in_(["completed", "COMPLETED"])).scalar() or 0
    total_speakers = db.query(func.count(Speaker.id)).scalar() or 0
    total_duration = db.query(func.coalesce(func.sum(Asset.duration_seconds), 0.0)).scalar() or 0.0

    return {
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "total_speakers": total_speakers,
        "total_duration_seconds": round(float(total_duration), 2),
    }
