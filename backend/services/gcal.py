"""Google Calendar API service.

Uses a service account with domain-wide delegation to list calendars
and fetch events for a specific user. Used as an alternative to iCal
feeds for calendar-based auto-naming.
"""

import os
from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

from services.settings import get_settings

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service(sa_key_path: str, user_email: str):
    """Build an authenticated Calendar API service."""
    creds = service_account.Credentials.from_service_account_file(
        os.path.expanduser(sa_key_path),
        scopes=CALENDAR_SCOPES,
        subject=user_email,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_calendars(sa_key_path: str, user_email: str) -> list[dict]:
    """List all calendars visible to the user.

    Returns list of {id, summary, primary, accessRole}.
    """
    service = _get_service(sa_key_path, user_email)
    result = []
    page_token = None

    while True:
        resp = service.calendarList().list(pageToken=page_token).execute()
        for cal in resp.get("items", []):
            result.append({
                "id": cal["id"],
                "summary": cal.get("summary", cal["id"]),
                "primary": cal.get("primary", False),
                "accessRole": cal.get("accessRole", ""),
                "backgroundColor": cal.get("backgroundColor", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return result


def match_calendar_event_google(
    recording_time: datetime,
    tolerance_minutes: int = 15,
) -> str | None:
    """Find a calendar event matching the recording time via Google Calendar API.

    Queries all non-excluded calendars for events near the recording time.
    Returns the event summary or None.
    """
    settings = get_settings()
    sa_key = settings.get("calendar_google_sa_key", "")
    user = settings.get("calendar_google_user", "")
    excluded = set(settings.get("calendar_excluded_calendars") or [])

    if not sa_key or not user:
        return None

    try:
        service = _get_service(sa_key, user)
    except Exception as e:
        print(f"[gcal] Failed to authenticate: {e}", flush=True)
        return None

    # Get list of calendars, filter out excluded
    try:
        calendars = list_calendars(sa_key, user)
    except Exception as e:
        print(f"[gcal] Failed to list calendars: {e}", flush=True)
        return None

    active_cals = [c for c in calendars if c["id"] not in excluded]
    if not active_cals:
        return None

    # Ensure recording_time is timezone-aware
    if recording_time.tzinfo is None:
        recording_time = recording_time.replace(tzinfo=timezone.utc)

    tolerance = timedelta(minutes=tolerance_minutes)
    time_min = (recording_time - tolerance).isoformat()
    time_max = (recording_time + tolerance + timedelta(hours=2)).isoformat()

    best_match: str | None = None
    best_distance: float | None = None

    for cal in active_cals:
        try:
            events = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    maxResults=10,
                )
                .execute()
            )
        except Exception as e:
            print(f"[gcal] Error fetching events from {cal['id']}: {e}", flush=True)
            continue

        for event in events.get("items", []):
            summary = event.get("summary", "")
            if not summary:
                continue

            start_raw = event["start"].get("dateTime")
            if not start_raw:
                continue  # skip all-day events

            start = datetime.fromisoformat(start_raw)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)

            end_raw = event["end"].get("dateTime")
            if end_raw:
                end = datetime.fromisoformat(end_raw)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
            else:
                end = start + timedelta(hours=1)

            window_start = start - tolerance
            window_end = end + tolerance

            if window_start <= recording_time <= window_end:
                distance = abs((recording_time - start).total_seconds())
                if best_distance is None or distance < best_distance:
                    best_match = summary
                    best_distance = distance

    return best_match
