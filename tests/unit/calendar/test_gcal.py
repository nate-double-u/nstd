"""Tests for Google Calendar read module.

Spec references:
  §8.1 — Calendars (write vs observe)
  §8.2 — Calendar polling
  §8.4 — Block lifecycle (past blocks, orphaned blocks)
  §19  — Google Calendar test cases

Test cases from spec:
  - Calendar poll marks past blocks as is_past = 1
  - Orphaned block (task closed, block future) flagged
  - Block recorded in calendar_blocks table with correct task_id
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from nstd.calendar.gcal import (
    detect_orphaned_blocks,
    fetch_calendar_events,
    get_calendar_service,
    mark_past_blocks,
    poll_calendars,
)
from nstd.db import (
    create_schema,
    get_connection,
    insert_calendar_block,
    upsert_task,
)


@pytest.fixture()
def conn():
    """In-memory SQLite connection with schema."""
    c = get_connection(":memory:")
    create_schema(c)
    yield c
    c.close()


def _make_task(task_id, source="github", state="open", **overrides):
    """Helper to build a minimal task dict."""
    base = {
        "id": task_id,
        "source": source,
        "source_id": task_id,
        "source_url": f"https://example.com/{task_id}",
        "title": "Test task",
        "body": None,
        "state": state,
        "assignee": "nate-double-u",
        "priority": None,
        "size": None,
        "estimate_hours": None,
        "start_date": None,
        "due_date": None,
        "created_at": "2026-03-18T00:00:00Z",
        "updated_at": "2026-03-18T00:00:00Z",
    }
    base.update(overrides)
    return base


def _gcal_event(
    event_id="evt1",
    summary="Test event",
    start_dt="2026-03-20T09:00:00-07:00",
    end_dt="2026-03-20T11:00:00-07:00",
    description="",
    color_id=None,
):
    """Helper to build a Google Calendar event dict."""
    event = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
        "status": "confirmed",
    }
    if description:
        event["description"] = description
    if color_id:
        event["colorId"] = color_id
    return event


# --- OAuth / service tests ---


class TestGetCalendarService:
    """Tests for get_calendar_service (OAuth credential loading)."""

    @patch("nstd.calendar.gcal._build_service")
    def test_returns_service_object(self, mock_build):
        """get_calendar_service should return a Google Calendar service."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        service = get_calendar_service("/fake/creds/path")
        assert service == mock_service

    @patch("nstd.calendar.gcal._build_service")
    def test_uses_credentials_path(self, mock_build):
        """Should pass the credentials path to the builder."""
        get_calendar_service("/my/creds")
        mock_build.assert_called_once_with("/my/creds")


# --- Event fetching tests ---


class TestFetchCalendarEvents:
    """Tests for fetch_calendar_events."""

    def test_fetches_events_from_calendar(self):
        """Should call the GCal API and return event dicts."""
        mock_service = MagicMock()
        events_result = {
            "items": [
                _gcal_event(
                    "evt1", "Meeting", "2026-03-20T09:00:00-07:00", "2026-03-20T10:00:00-07:00"
                ),
                _gcal_event(
                    "evt2", "Standup", "2026-03-20T10:00:00-07:00", "2026-03-20T10:30:00-07:00"
                ),
            ]
        }
        mock_service.events().list().execute.return_value = events_result

        events = fetch_calendar_events(mock_service, calendar_id="primary", days_ahead=14)
        assert len(events) == 2
        assert events[0]["summary"] == "Meeting"
        assert events[1]["summary"] == "Standup"

    def test_handles_empty_calendar(self):
        """Should return empty list when calendar has no events."""
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {"items": []}

        events = fetch_calendar_events(mock_service, calendar_id="primary", days_ahead=14)
        assert events == []

    def test_handles_missing_items_key(self):
        """Should return empty list when response has no 'items' key."""
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {}

        events = fetch_calendar_events(mock_service, calendar_id="primary", days_ahead=14)
        assert events == []

    def test_filters_cancelled_events(self):
        """Cancelled events should be excluded."""
        mock_service = MagicMock()
        confirmed = _gcal_event("evt1", "Good event")
        cancelled = _gcal_event("evt2", "Cancelled event")
        cancelled["status"] = "cancelled"
        mock_service.events().list().execute.return_value = {"items": [confirmed, cancelled]}

        events = fetch_calendar_events(mock_service, calendar_id="primary", days_ahead=14)
        assert len(events) == 1
        assert events[0]["summary"] == "Good event"

    def test_handles_all_day_events(self):
        """All-day events (date instead of dateTime) should be included."""
        mock_service = MagicMock()
        all_day = {
            "id": "evt_allday",
            "summary": "Holiday",
            "start": {"date": "2026-03-20"},
            "end": {"date": "2026-03-21"},
            "status": "confirmed",
        }
        mock_service.events().list().execute.return_value = {"items": [all_day]}

        events = fetch_calendar_events(mock_service, calendar_id="primary", days_ahead=14)
        assert len(events) == 1
        assert events[0]["summary"] == "Holiday"

    def test_paginates_through_results(self):
        """Should follow nextPageToken to get all events."""
        mock_service = MagicMock()
        page1 = {
            "items": [_gcal_event("evt1", "Event 1")],
            "nextPageToken": "token123",
        }
        page2 = {
            "items": [_gcal_event("evt2", "Event 2")],
        }
        mock_service.events().list().execute.side_effect = [page1, page2]

        events = fetch_calendar_events(mock_service, calendar_id="primary", days_ahead=14)
        assert len(events) == 2


# --- Past block marking tests ---


class TestMarkPastBlocks:
    """§19: Calendar poll marks past blocks as is_past = 1."""

    def test_marks_past_blocks(self, conn):
        """Blocks with end_dt in the past should be marked is_past = 1."""
        task = _make_task("gh:cncf/staff:100")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        past_dt = (now - timedelta(hours=2)).isoformat()
        past_end = (now - timedelta(hours=1)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:100", "evt_past", past_dt, past_end, 1.0)

        mark_past_blocks(conn)

        row = conn.execute(
            "SELECT is_past FROM calendar_blocks WHERE gcal_event_id = 'evt_past'"
        ).fetchone()
        assert row["is_past"] == 1

    def test_does_not_mark_future_blocks(self, conn):
        """Blocks with end_dt in the future should remain is_past = 0."""
        task = _make_task("gh:cncf/staff:101")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:101", "evt_future", future_dt, future_end, 2.0)

        mark_past_blocks(conn)

        row = conn.execute(
            "SELECT is_past FROM calendar_blocks WHERE gcal_event_id = 'evt_future'"
        ).fetchone()
        assert row["is_past"] == 0

    def test_already_past_blocks_unchanged(self, conn):
        """Blocks already marked as past should remain unchanged."""
        task = _make_task("gh:cncf/staff:102")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        past_dt = (now - timedelta(hours=4)).isoformat()
        past_end = (now - timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:102", "evt_old", past_dt, past_end, 1.0)

        # Mark once
        mark_past_blocks(conn)
        # Mark again — should not error
        mark_past_blocks(conn)

        row = conn.execute(
            "SELECT is_past FROM calendar_blocks WHERE gcal_event_id = 'evt_old'"
        ).fetchone()
        assert row["is_past"] == 1


# --- Orphaned block detection tests ---


class TestDetectOrphanedBlocks:
    """§19: Orphaned block (task closed, block future) flagged."""

    def test_closed_task_future_block_is_orphaned(self, conn):
        """A future block for a closed task should be flagged as orphaned."""
        task = _make_task("gh:cncf/staff:200", state="closed")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:200", "evt_orphan", future_dt, future_end, 2.0)

        orphans = detect_orphaned_blocks(conn)
        assert len(orphans) == 1
        assert orphans[0]["gcal_event_id"] == "evt_orphan"
        assert orphans[0]["task_id"] == "gh:cncf/staff:200"

    def test_open_task_future_block_not_orphaned(self, conn):
        """A future block for an open task is not orphaned."""
        task = _make_task("gh:cncf/staff:201", state="open")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:201", "evt_ok", future_dt, future_end, 2.0)

        orphans = detect_orphaned_blocks(conn)
        assert len(orphans) == 0

    def test_closed_task_past_block_not_orphaned(self, conn):
        """A past block for a closed task is not orphaned (that's expected)."""
        task = _make_task("gh:cncf/staff:202", state="closed")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        past_dt = (now - timedelta(hours=4)).isoformat()
        past_end = (now - timedelta(hours=3)).isoformat()
        block_id = insert_calendar_block(
            conn, "gh:cncf/staff:202", "evt_past_closed", past_dt, past_end, 1.0
        )
        # Mark as past
        conn.execute("UPDATE calendar_blocks SET is_past = 1 WHERE id = ?", (block_id,))
        conn.commit()

        orphans = detect_orphaned_blocks(conn)
        assert len(orphans) == 0

    def test_done_task_future_block_is_orphaned(self, conn):
        """Tasks with state 'done' should also have future blocks flagged as orphaned."""
        task = _make_task("gh:cncf/staff:203", state="done")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:203", "evt_done", future_dt, future_end, 2.0)

        orphans = detect_orphaned_blocks(conn)
        assert len(orphans) == 1

    def test_multiple_orphaned_blocks(self, conn):
        """Multiple orphaned blocks across different tasks."""
        for i in range(3):
            task = _make_task(f"gh:cncf/staff:21{i}", state="closed")
            upsert_task(conn, task)
            now = datetime.now(UTC)
            future_dt = (now + timedelta(hours=1)).isoformat()
            future_end = (now + timedelta(hours=2)).isoformat()
            insert_calendar_block(
                conn, f"gh:cncf/staff:21{i}", f"evt_multi_{i}", future_dt, future_end, 1.0
            )

        orphans = detect_orphaned_blocks(conn)
        assert len(orphans) == 3


# --- Poll orchestration tests ---


class TestPollCalendars:
    """Tests for the poll_calendars orchestration function."""

    def test_poll_marks_past_blocks(self, conn):
        """poll_calendars should mark past blocks."""
        task = _make_task("gh:cncf/staff:300")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        past_dt = (now - timedelta(hours=2)).isoformat()
        past_end = (now - timedelta(hours=1)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:300", "evt_poll_past", past_dt, past_end, 1.0)

        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {"items": []}

        poll_calendars(
            conn,
            service=mock_service,
            nstd_calendar_id="cal_nstd",
            observe_calendar_ids=[],
        )

        row = conn.execute(
            "SELECT is_past FROM calendar_blocks WHERE gcal_event_id = 'evt_poll_past'"
        ).fetchone()
        assert row["is_past"] == 1

    def test_poll_returns_events_from_all_calendars(self, conn):
        """poll_calendars should return events from NSTD Planning + observed calendars."""
        mock_service = MagicMock()

        nstd_events = {"items": [_gcal_event("nstd1", "NSTD block")]}
        observed_events = {"items": [_gcal_event("obs1", "Team meeting")]}

        mock_service.events().list().execute.side_effect = [nstd_events, observed_events]

        result = poll_calendars(
            conn,
            service=mock_service,
            nstd_calendar_id="cal_nstd",
            observe_calendar_ids=["cal_team"],
        )

        assert "nstd_events" in result
        assert "observed_events" in result
        assert len(result["nstd_events"]) == 1
        assert len(result["observed_events"]) == 1

    def test_poll_returns_orphaned_blocks(self, conn):
        """poll_calendars should include orphaned blocks in result."""
        task = _make_task("gh:cncf/staff:301", state="closed")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(
            conn, "gh:cncf/staff:301", "evt_orphan_poll", future_dt, future_end, 2.0
        )

        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {"items": []}

        result = poll_calendars(
            conn,
            service=mock_service,
            nstd_calendar_id="cal_nstd",
            observe_calendar_ids=[],
        )

        assert len(result["orphaned_blocks"]) == 1

    def test_poll_with_multiple_observed_calendars(self, conn):
        """Should aggregate events from multiple observed calendars."""
        mock_service = MagicMock()

        nstd_events = {"items": []}
        team1_events = {"items": [_gcal_event("t1", "Team 1 meeting")]}
        team2_events = {"items": [_gcal_event("t2", "Team 2 standup")]}

        mock_service.events().list().execute.side_effect = [nstd_events, team1_events, team2_events]

        result = poll_calendars(
            conn,
            service=mock_service,
            nstd_calendar_id="cal_nstd",
            observe_calendar_ids=["cal_team1", "cal_team2"],
        )

        assert len(result["observed_events"]) == 2


# --- Event parsing helpers ---


class TestEventParsing:
    """Tests for event datetime parsing and duration calculation."""

    def test_parse_event_duration_hours(self):
        """Should correctly calculate event duration in hours."""
        from nstd.calendar.gcal import event_duration_hours

        event = _gcal_event(
            start_dt="2026-03-20T09:00:00-07:00",
            end_dt="2026-03-20T11:30:00-07:00",
        )
        assert event_duration_hours(event) == 2.5

    def test_parse_event_duration_half_hour(self):
        """30-minute event should return 0.5 hours."""
        from nstd.calendar.gcal import event_duration_hours

        event = _gcal_event(
            start_dt="2026-03-20T14:00:00-07:00",
            end_dt="2026-03-20T14:30:00-07:00",
        )
        assert event_duration_hours(event) == 0.5

    def test_parse_all_day_event_duration(self):
        """All-day event should return a full day (based on date difference)."""
        from nstd.calendar.gcal import event_duration_hours

        event = {
            "id": "allday",
            "summary": "Holiday",
            "start": {"date": "2026-03-20"},
            "end": {"date": "2026-03-21"},
            "status": "confirmed",
        }
        # 1 full day
        assert event_duration_hours(event) == 24.0

    def test_parse_event_date_extracts_date(self):
        """Should extract the date portion from a dateTime event."""
        from nstd.calendar.gcal import event_date

        event = _gcal_event(start_dt="2026-03-20T09:00:00-07:00")
        assert event_date(event) == "2026-03-20"

    def test_parse_all_day_event_date(self):
        """Should extract date from an all-day event."""
        from nstd.calendar.gcal import event_date

        event = {
            "id": "allday",
            "summary": "Holiday",
            "start": {"date": "2026-03-20"},
            "end": {"date": "2026-03-21"},
            "status": "confirmed",
        }
        assert event_date(event) == "2026-03-20"
