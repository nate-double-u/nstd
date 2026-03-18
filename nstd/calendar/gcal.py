"""Google Calendar read operations for nstd.

Handles OAuth credential loading, event fetching from NSTD Planning
and observed calendars, past block marking, and orphaned block detection.

Spec references: §8.1, §8.2, §8.4
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from dateutil import parser as dtparser


def _build_service(credentials_path: str):  # pragma: no cover
    """Build a Google Calendar API service from OAuth credentials.

    This is a thin wrapper around the Google API client library,
    tested via integration tests only.
    """
    from pathlib import Path

    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = Path(credentials_path) / "google_token.json"
    client_secret_path = Path(credentials_path) / "google_client_secret.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path))

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret_path),
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_calendar_service(credentials_path: str):
    """Get a Google Calendar API service.

    Args:
        credentials_path: Path to the credentials directory containing
                         google_token.json and google_client_secret.json.

    Returns:
        Google Calendar API service object.
    """
    return _build_service(credentials_path)


def fetch_calendar_events(
    service,
    calendar_id: str,
    days_ahead: int = 14,
) -> list[dict]:
    """Fetch events from a Google Calendar.

    Args:
        service: Google Calendar API service object.
        calendar_id: Calendar ID to fetch from.
        days_ahead: Number of days ahead to look (default 14).

    Returns:
        List of event dicts, excluding cancelled events.
    """
    now = datetime.now(UTC)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    all_events = []
    page_token = None

    while True:
        kwargs = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.events().list(**kwargs).execute()
        items = result.get("items", [])

        # Filter out cancelled events
        for event in items:
            if event.get("status") != "cancelled":
                all_events.append(event)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return all_events


def event_duration_hours(event: dict) -> float:
    """Calculate the duration of an event in hours.

    Handles both dateTime events and all-day (date) events.
    """
    start = event.get("start", {})
    end = event.get("end", {})

    if "dateTime" in start and "dateTime" in end:
        start_dt = dtparser.isoparse(start["dateTime"])
        end_dt = dtparser.isoparse(end["dateTime"])
    elif "date" in start and "date" in end:
        start_dt = dtparser.isoparse(start["date"])
        end_dt = dtparser.isoparse(end["date"])
    else:
        return 0.0

    delta = end_dt - start_dt
    return delta.total_seconds() / 3600.0


def event_date(event: dict) -> str:
    """Extract the date (YYYY-MM-DD) from an event's start time."""
    start = event.get("start", {})
    if "dateTime" in start:
        return dtparser.isoparse(start["dateTime"]).strftime("%Y-%m-%d")
    elif "date" in start:
        return start["date"]
    return ""


def mark_past_blocks(conn: sqlite3.Connection) -> int:
    """Mark calendar blocks with end_dt in the past as is_past = 1.

    Returns:
        Number of blocks marked as past.
    """
    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "UPDATE calendar_blocks SET is_past = 1 WHERE end_dt < ? AND is_past = 0",
        (now,),
    )
    conn.commit()
    return cursor.rowcount


def detect_orphaned_blocks(conn: sqlite3.Connection) -> list[dict]:
    """Detect orphaned blocks: future blocks for closed/done tasks.

    An orphaned block is a future (is_past = 0) calendar block whose
    associated task has state 'closed' or 'done'.

    Returns:
        List of orphaned block dicts.
    """
    rows = conn.execute(
        """
        SELECT cb.* FROM calendar_blocks cb
        JOIN tasks t ON cb.task_id = t.id
        WHERE cb.is_past = 0
          AND t.state IN ('closed', 'done')
        ORDER BY cb.start_dt
        """
    ).fetchall()
    return [dict(r) for r in rows]


def poll_calendars(
    conn: sqlite3.Connection,
    service,
    nstd_calendar_id: str,
    observe_calendar_ids: list[str],
    days_ahead: int = 14,
) -> dict:
    """Run a full calendar poll cycle.

    1. Mark past blocks in the database
    2. Fetch events from NSTD Planning calendar
    3. Fetch events from all observed calendars
    4. Detect orphaned blocks

    Args:
        conn: Database connection.
        service: Google Calendar API service object.
        nstd_calendar_id: Calendar ID for the NSTD Planning calendar.
        observe_calendar_ids: List of calendar IDs to observe.
        days_ahead: Number of days ahead to look.

    Returns:
        Dict with keys: nstd_events, observed_events, orphaned_blocks,
                        past_blocks_marked
    """
    # Step 1: Mark past blocks
    past_count = mark_past_blocks(conn)

    # Step 2: Fetch NSTD Planning events
    nstd_events = fetch_calendar_events(service, nstd_calendar_id, days_ahead)

    # Step 3: Fetch observed calendar events
    observed_events = []
    for cal_id in observe_calendar_ids:
        events = fetch_calendar_events(service, cal_id, days_ahead)
        observed_events.extend(events)

    # Step 4: Detect orphaned blocks
    orphaned = detect_orphaned_blocks(conn)

    return {
        "nstd_events": nstd_events,
        "observed_events": observed_events,
        "orphaned_blocks": orphaned,
        "past_blocks_marked": past_count,
    }
