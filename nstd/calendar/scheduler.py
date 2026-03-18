"""Scheduling engine — availability modelling, session suggestion, nudges (§8.5)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from nstd.config import SchedulingConfig


def build_availability(
    days: list[date],
    existing_nstd_blocks: list[dict],
    observed_events: list[dict],
    config: SchedulingConfig,
) -> dict[date, dict]:
    """Build a per-day availability model.

    Args:
        days: List of dates to model.
        existing_nstd_blocks: NSTD Planning blocks (dicts with 'start' and 'end' datetimes).
        observed_events: Events from observed calendars (dicts with 'start' and 'end' datetimes).
        config: Scheduling configuration.

    Returns:
        Dict mapping each date to {'available_hours': float, 'occupied_slots': list}.
    """
    work_start = _parse_time(config.work_start)
    work_end = _parse_time(config.work_end)
    workday_hours = (
        datetime.combine(date.min, work_end) - datetime.combine(date.min, work_start)
    ).total_seconds() / 3600.0

    result: dict[date, dict] = {}

    for day in days:
        occupied: list[dict] = []
        occupied_hours = 0.0

        # Collect all events on this day
        all_events = existing_nstd_blocks + observed_events
        for event in all_events:
            ev_start = event["start"]
            ev_end = event["end"]

            if ev_start.date() == day:
                duration = (ev_end - ev_start).total_seconds() / 3600.0
                occupied_hours += duration
                occupied.append({"start": ev_start, "end": ev_end})

        available = min(config.max_hours_per_day, workday_hours) - occupied_hours
        available = max(0.0, available)

        result[day] = {
            "available_hours": available,
            "occupied_slots": occupied,
        }

    return result


def suggest_sessions(
    estimate_hours: float,
    hours_already_scheduled: float,
    start_date: date | None,
    due_date: date | None,
    availability: dict[date, dict],
    config: SchedulingConfig,
    today: date | None = None,
) -> dict:
    """Suggest work sessions for a task based on the algorithm in §8.5.2.

    Args:
        estimate_hours: Total estimated work hours.
        hours_already_scheduled: Hours already scheduled in future blocks.
        start_date: Earliest day to begin (None → today).
        due_date: Latest day to finish (None → today + 14 days).
        availability: Pre-built availability model from build_availability().
        config: Scheduling configuration.
        today: Override for current date (for testing).

    Returns:
        Dict with 'sessions' list and optional 'warning' string.
    """
    if today is None:
        today = date.today()

    remaining = max(0.0, estimate_hours - hours_already_scheduled)

    if remaining <= 0:
        return {"sessions": [], "warning": None}

    # Clamp preferred session length
    preferred = min(
        max(config.preferred_session_hours, config.min_block_hours),
        config.max_block_hours,
    )

    # Build candidate days
    effective_start = max(today, start_date) if start_date else today
    effective_end = due_date if due_date else (today + timedelta(days=14))

    candidate_days = []
    current = effective_start
    while current <= effective_end:
        if current in availability and availability[current]["available_hours"] > 0:
            candidate_days.append(current)
        current += timedelta(days=1)

    # Distribute sessions
    sessions: list[dict] = []
    work_start = _parse_time(config.work_start)
    work_end = _parse_time(config.work_end)

    # Make a mutable copy of availability for this run
    avail_copy = {
        d: {
            "available_hours": v["available_hours"],
            "occupied_slots": list(v["occupied_slots"]),
        }
        for d, v in availability.items()
    }

    for day in candidate_days:
        if remaining <= 0:
            break

        day_avail = avail_copy.get(day, {}).get("available_hours", 0)
        session_length = min(preferred, remaining, day_avail, config.max_block_hours)

        if session_length < config.min_block_hours:
            continue

        # Find the first available time slot on this day
        suggested_start = _find_first_available_slot(
            day,
            avail_copy.get(day, {}).get("occupied_slots", []),
            session_length,
            work_start,
            work_end,
        )

        sessions.append(
            {
                "date": day,
                "start_time": suggested_start,
                "duration_hours": session_length,
            }
        )

        remaining -= session_length
        avail_copy[day]["available_hours"] -= session_length

    warning = None
    if remaining > 0:
        warning = (
            f"Not enough time in window — {remaining:.1f}h remaining. "
            f"Consider extending the due date or reducing the estimate."
        )

    return {"sessions": sessions, "warning": warning}


def evaluate_nudge(
    state: str,
    estimate_hours: float | None,
    due_date: str | None,
    future_block_hours: float,
    all_blocks_past: bool,
    has_any_blocks: bool,
    today: date | None = None,
) -> str | None:
    """Evaluate the scheduling nudge status for a task (§8.5.4).

    Args:
        state: Task state ('open', 'closed', 'done').
        estimate_hours: Estimated hours (may be None).
        due_date: Due date as ISO string (may be None).
        future_block_hours: Sum of duration_hours for future blocks.
        all_blocks_past: True if all existing blocks are in the past.
        has_any_blocks: True if any blocks exist at all.
        today: Override for current date (for testing).

    Returns:
        Nudge string or None if on track.
    """
    if state in ("closed", "done"):
        return None

    if today is None:
        today = date.today()

    # Check overdue first (highest priority)
    if due_date:
        due = date.fromisoformat(due_date)
        if due < today:
            return "overdue"

    # Needs estimate
    if estimate_hours is None and due_date:
        return "needs_estimate"

    # Time elapsed — had blocks, all past, still open
    if has_any_blocks and all_blocks_past and future_block_hours == 0:
        return "time_elapsed"

    # Unscheduled — has estimate but no future blocks
    if estimate_hours and estimate_hours > 0 and future_block_hours == 0 and not has_any_blocks:
        return "unscheduled"

    # On track — future blocks cover the remaining work
    if estimate_hours and future_block_hours >= estimate_hours:
        return None

    # Partially scheduled but not flagged
    return None


def _parse_time(t: str) -> time:
    """Parse 'HH:MM' string to time object."""
    parts = t.split(":")
    return time(int(parts[0]), int(parts[1]))


def _find_first_available_slot(
    day: date,
    occupied_slots: list[dict],
    duration_hours: float,
    work_start: time,
    work_end: time,
) -> time:
    """Find the first available slot on a day that doesn't overlap existing events.

    Returns the start time for the suggested block.
    """
    # Sort occupied slots by start time
    sorted_slots = sorted(occupied_slots, key=lambda s: s["start"])

    candidate_start = datetime.combine(day, work_start)
    day_end = datetime.combine(day, work_end)
    duration = timedelta(hours=duration_hours)

    for slot in sorted_slots:
        candidate_end = candidate_start + duration

        if candidate_end <= slot["start"]:
            # Fits before this slot
            return candidate_start.time()

        # Move candidate past this slot
        if slot["end"] > candidate_start:
            candidate_start = slot["end"]

    # Check if it fits after the last slot
    if candidate_start + duration <= day_end:
        return candidate_start.time()

    # Fallback: return work_start (may overflow, but the caller caps duration)
    return work_start
