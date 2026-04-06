"""Calendar matching API endpoint."""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query

from services.ical import match_calendar_event

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/match")
async def calendar_match(ts: str = Query(..., description="ISO 8601 timestamp")):
    """Check if a timestamp matches a calendar event."""
    try:
        recording_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {ts}")

    event_title = await match_calendar_event(recording_time)

    if event_title:
        return {"matched": True, "event_title": event_title}
    return {"matched": False}
