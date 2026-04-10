"""Calendar matching and discovery API endpoints."""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query

from services.ical import match_calendar_event
from services.gcal import list_calendars, match_calendar_event_google
from services.settings import get_settings

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/match")
async def calendar_match(ts: str = Query(..., description="ISO 8601 timestamp")):
    """Check if a timestamp matches a calendar event."""
    try:
        recording_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {ts}")

    settings = get_settings()
    provider = settings.get("calendar_provider", "ical")

    if provider == "google":
        event_title = match_calendar_event_google(recording_time)
    else:
        event_title = await match_calendar_event(recording_time)

    if event_title:
        return {"matched": True, "event_title": event_title}
    return {"matched": False}


@router.get("/sources")
async def calendar_sources():
    """Discover available calendars from Google Calendar API.

    Returns the list of calendars visible to the configured user,
    along with which ones are currently excluded.
    """
    settings = get_settings()
    sa_key = settings.get("calendar_google_sa_key", "")
    user = settings.get("calendar_google_user", "")

    if not sa_key or not user:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not configured. Set service account key path and user email.",
        )

    try:
        calendars = list_calendars(sa_key, user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list calendars: {e}")

    excluded = set(settings.get("calendar_excluded_calendars") or [])

    for cal in calendars:
        cal["enabled"] = cal["id"] not in excluded

    return {"calendars": calendars}
