"""Google Calendar write operations for nstd.

Handles creating, updating, and completing calendar blocks in the
NSTD Planning calendar.

Spec references: §8.3 (time block format), §8.4 (block lifecycle)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from dateutil import parser as dtparser

from nstd.db import get_future_blocks_for_task, insert_calendar_block

# Google Calendar color IDs per spec §8.3
# See: https://developers.google.com/calendar/api/v3/reference/colors
PRIORITY_COLORS = {
    "high": "11",  # Tomato
    "medium": "5",  # Banana
    "low": "9",  # Blueberry
    None: "8",  # Graphite (no priority)
    "completed": "8",  # Graphite (completed)
}


def _is_truly_future(block: dict) -> bool:
    """Check if a block's end_dt is actually in the future.

    Provides a runtime safety check beyond the is_past DB flag,
    in case is_past hasn't been updated yet.
    """
    try:
        end = dtparser.isoparse(block["end_dt"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return end > datetime.now(UTC)
    except (ValueError, TypeError, KeyError):
        return False


def _build_description(task: dict) -> str:
    """Build the event description per spec §8.3.

    Format:
      - Line 1: GitHub Issue URL (canonical link)
      - Blank line
      - Metadata line: Priority, Size, Due date (where available)
      - Blank line
      - First 200 chars of issue body (if present)
    """
    lines = [task["source_url"]]

    # Metadata line
    meta_parts = []
    if task.get("priority"):
        meta_parts.append(f"Priority: {task['priority']}")
    if task.get("size"):
        meta_parts.append(f"Size: {task['size']}")
    if task.get("due_date"):
        meta_parts.append(f"Due: {task['due_date']}")

    if meta_parts:
        lines.append("")
        lines.append("  |  ".join(meta_parts))

    # Body excerpt
    body = task.get("body")
    if body:
        excerpt = body[:200]
        lines.append("")
        lines.append(excerpt)

    return "\n".join(lines)


def build_event_body(
    task: dict,
    start_dt: str,
    end_dt: str,
) -> dict:
    """Build a Google Calendar event body from a task.

    Args:
        task: Task dict from the database.
        start_dt: ISO 8601 start datetime string.
        end_dt: ISO 8601 end datetime string.

    Returns:
        Dict suitable for GCal API events().insert().
    """
    priority = task.get("priority")
    color_id = PRIORITY_COLORS.get(priority, PRIORITY_COLORS[None])

    return {
        "summary": task["title"],
        "description": _build_description(task),
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
        "colorId": color_id,
    }


def create_calendar_block(
    conn: sqlite3.Connection,
    service,
    calendar_id: str,
    task: dict,
    start_dt: str,
    end_dt: str,
    duration_hours: float,
    dry_run: bool = False,
) -> dict:
    """Create a calendar block in GCal and record it in the database.

    Args:
        conn: Database connection.
        service: Google Calendar API service object.
        calendar_id: Calendar ID for the NSTD Planning calendar.
        task: Task dict from the database.
        start_dt: ISO 8601 start datetime string.
        end_dt: ISO 8601 end datetime string.
        duration_hours: Duration of the block in hours.
        dry_run: If True, suppress all API and DB writes and print [DRY-RUN] lines.

    Returns:
        Dict with block info including gcal_event_id and task_id.

    Raises:
        ValueError: If the task is not from GitHub (§8.3: only GitHub Issues
                   get calendar blocks).
    """
    # §8.3: Only GitHub Issues get calendar blocks
    if task.get("source") != "github":
        raise ValueError(
            f"Only GitHub tasks can have calendar blocks. "
            f"Task '{task.get('id')}' has source '{task.get('source')}'."
        )

    if dry_run:
        # Parse start/end for human-readable display
        try:
            start_parsed = dtparser.isoparse(start_dt)
            end_parsed = dtparser.isoparse(end_dt)
            date_str = start_parsed.strftime("%Y-%m-%d")
            time_range = f"{start_parsed.strftime('%H:%M')}\u2013{end_parsed.strftime('%H:%M')}"
        except (ValueError, TypeError):
            date_str = start_dt
            time_range = end_dt
        print(f'[DRY-RUN] Would create calendar block: "{task["title"]}" {date_str} {time_range}')
        return {
            "id": None,
            "task_id": task["id"],
            "gcal_event_id": None,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "duration_hours": duration_hours,
        }

    event_body = build_event_body(task, start_dt, end_dt)

    created_event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    gcal_event_id = created_event["id"]

    block_id = insert_calendar_block(
        conn,
        task_id=task["id"],
        gcal_event_id=gcal_event_id,
        start_dt=start_dt,
        end_dt=end_dt,
        duration_hours=duration_hours,
    )

    return {
        "id": block_id,
        "task_id": task["id"],
        "gcal_event_id": gcal_event_id,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "duration_hours": duration_hours,
    }


def mark_task_blocks_completed(
    conn: sqlite3.Connection,
    service,
    calendar_id: str,
    task_id: str,
    dry_run: bool = False,
) -> int:
    """Mark all future blocks for a task as completed in GCal.

    Per spec §8.4: title gets "✓ " prefix, colour set to Graphite.
    Blocks are not deleted (kept for review).

    Args:
        conn: Database connection.
        service: Google Calendar API service object.
        calendar_id: Calendar ID for the NSTD Planning calendar.
        task_id: Task ID whose blocks should be marked.
        dry_run: If True, suppress all API writes and print [DRY-RUN] lines.

    Returns:
        Number of blocks updated.
    """
    future_blocks = get_future_blocks_for_task(conn, task_id)
    updated = 0

    for block in future_blocks:
        # Runtime safety: skip blocks that are actually past even if is_past=0
        if not _is_truly_future(block):
            continue

        if dry_run:
            print(f"[DRY-RUN] Would mark calendar block as past: block_id={block['id']}")
            updated += 1
            continue

        gcal_event_id = block["gcal_event_id"]

        # Fetch current event from GCal
        event = service.events().get(calendarId=calendar_id, eventId=gcal_event_id).execute()

        # Add ✓ prefix if not already present
        summary = event.get("summary", "")
        if not summary.startswith("✓ "):
            summary = f"✓ {summary}"

        event["summary"] = summary
        event["colorId"] = PRIORITY_COLORS["completed"]

        service.events().update(
            calendarId=calendar_id,
            eventId=gcal_event_id,
            body=event,
        ).execute()

        updated += 1

    return updated


def update_block_description(
    conn: sqlite3.Connection,
    service,
    calendar_id: str,
    task: dict,
    dry_run: bool = False,
) -> int:
    """Update the description of all future blocks for a task.

    Called when task metadata (due_date, start_date, priority) changes
    during sync. The time slot is not moved — only the description
    is refreshed.

    Args:
        conn: Database connection.
        service: Google Calendar API service object.
        calendar_id: Calendar ID for the NSTD Planning calendar.
        task: Updated task dict.
        dry_run: If True, suppress all API writes and print [DRY-RUN] lines.

    Returns:
        Number of blocks updated.
    """
    future_blocks = get_future_blocks_for_task(conn, task["id"])
    updated = 0

    for block in future_blocks:
        # Runtime safety: skip blocks that are actually past even if is_past=0
        if not _is_truly_future(block):
            continue

        if dry_run:
            print(
                f"[DRY-RUN] Would update calendar block description: "
                f'block_id={block["id"]} task="{task["title"]}"'
            )
            updated += 1
            continue

        gcal_event_id = block["gcal_event_id"]

        event = service.events().get(calendarId=calendar_id, eventId=gcal_event_id).execute()

        event["description"] = _build_description(task)

        # Also update color based on current priority
        priority = task.get("priority")
        event["colorId"] = PRIORITY_COLORS.get(priority, PRIORITY_COLORS[None])

        service.events().update(
            calendarId=calendar_id,
            eventId=gcal_event_id,
            body=event,
        ).execute()

        updated += 1

    return updated
