"""iCal calendar matching service.

Fetches an iCal feed and matches recording timestamps to calendar events.
Used for auto-naming recordings based on scheduled meetings.
"""

import time
from datetime import datetime, timezone

import httpx
from icalendar import Calendar

from services.settings import get_settings

_ical_cache: bytes | None = None
_ical_cache_time: float = 0
_ICAL_CACHE_TTL = 300  # 5 minutes


async def _fetch_ical(url: str) -> bytes:
    """Fetch iCal feed with 5-min cache."""
    global _ical_cache, _ical_cache_time

    now = time.time()
    if _ical_cache is not None and (now - _ical_cache_time) < _ICAL_CACHE_TTL:
        return _ical_cache

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    _ical_cache = resp.content
    _ical_cache_time = time.time()
    return _ical_cache


async def match_calendar_event(recording_time: datetime, tolerance_minutes: int = 15) -> str | None:
    """Find a calendar event that overlaps with the given recording time.

    Returns the event SUMMARY string or None if no match.
    Tolerance extends the match window before event start and after event end.
    """
    settings = get_settings()
    ical_url = settings.get("calendar_ical_url", "")
    if not ical_url:
        return None

    try:
        raw = await _fetch_ical(ical_url)
    except Exception as e:
        print(f"[ical] Failed to fetch calendar: {e}", flush=True)
        return None

    cal = Calendar.from_ical(raw)

    # Ensure recording_time is timezone-aware (assume UTC if naive)
    if recording_time.tzinfo is None:
        recording_time = recording_time.replace(tzinfo=timezone.utc)

    from datetime import timedelta
    tolerance = timedelta(minutes=tolerance_minutes)

    best_match: str | None = None
    best_distance = None

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        summary = str(component.get("SUMMARY", ""))
        if not summary:
            continue

        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        if not dtstart:
            continue

        start = dtstart.dt
        # Handle date-only (all-day) events — skip them
        if not isinstance(start, datetime):
            continue

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        if dtend:
            end = dtend.dt
            if not isinstance(end, datetime):
                continue
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
        else:
            # Default 1-hour event if no end time
            end = start + timedelta(hours=1)

        # Check if recording falls within event window (with tolerance)
        window_start = start - tolerance
        window_end = end + tolerance

        if window_start <= recording_time <= window_end:
            distance = abs((recording_time - start).total_seconds())
            if best_distance is None or distance < best_distance:
                best_match = summary
                best_distance = distance

    return best_match
