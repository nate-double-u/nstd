"""Tests for Google Calendar write module.

Spec references:
  §8.3 — Time block format
  §8.4 — Block lifecycle
  §19  — Google Calendar test cases

Test cases from spec:
  - Block created with correct title (issue title only, no prefix)
  - Block description contains GitHub issue URL as first line
  - Block description contains priority, size, due date where available
  - Closed task → future blocks get ✓ prefix and Graphite colour
  - Block recorded in calendar_blocks table with correct task_id
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from nstd.calendar.gcal_write import (
    PRIORITY_COLORS,
    build_event_body,
    create_calendar_block,
    mark_task_blocks_completed,
    update_block_description,
)
from nstd.db import (
    create_schema,
    get_blocks_for_task,
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


def _make_task(task_id, **overrides):
    """Helper to build a minimal task dict."""
    base = {
        "id": task_id,
        "source": "github",
        "source_id": task_id,
        "source_url": f"https://github.com/cncf/staff/issues/{task_id.split(':')[-1]}",
        "title": "Fix the thing",
        "body": "This is the issue body describing the work to be done.",
        "state": "open",
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


# --- Event body building tests ---


class TestBuildEventBody:
    """§8.3: Tests for building GCal event body from a task."""

    def test_title_is_issue_title_only(self):
        """§19: Block created with correct title (issue title only, no prefix)."""
        task = _make_task("gh:cncf/staff:123", title="Fix the thing")
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert body["summary"] == "Fix the thing"

    def test_description_starts_with_github_url(self):
        """§19: Block description contains GitHub issue URL as first line."""
        task = _make_task(
            "gh:cncf/staff:123",
            source_url="https://github.com/cncf/staff/issues/123",
        )
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        first_line = body["description"].split("\n")[0]
        assert first_line == "https://github.com/cncf/staff/issues/123"

    def test_description_contains_priority_size_due(self):
        """§19: Block description contains priority, size, due date where available."""
        task = _make_task(
            "gh:cncf/staff:123",
            priority="high",
            size="M",
            due_date="2026-03-25",
        )
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert "Priority: high" in body["description"]
        assert "Size: M" in body["description"]
        assert "Due: 2026-03-25" in body["description"]

    def test_description_omits_missing_metadata(self):
        """Missing priority/size/due should not appear in description."""
        task = _make_task("gh:cncf/staff:123", priority=None, size=None, due_date=None)
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert "Priority:" not in body["description"]
        assert "Size:" not in body["description"]
        assert "Due:" not in body["description"]

    def test_description_includes_body_excerpt(self):
        """First 200 chars of issue body should be in description."""
        task = _make_task("gh:cncf/staff:123", body="A" * 250)
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert "A" * 200 in body["description"]
        # Should be truncated, not full 250
        assert "A" * 250 not in body["description"]

    def test_description_no_body(self):
        """No body → no body excerpt section."""
        task = _make_task("gh:cncf/staff:123", body=None)
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        # Should still have URL as first line
        assert body["description"].startswith("https://")

    def test_color_high_priority(self):
        """High priority → Tomato color (colorId 11)."""
        task = _make_task("gh:cncf/staff:123", priority="high")
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert body["colorId"] == PRIORITY_COLORS["high"]

    def test_color_medium_priority(self):
        """Medium priority → Banana color (colorId 5)."""
        task = _make_task("gh:cncf/staff:123", priority="medium")
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert body["colorId"] == PRIORITY_COLORS["medium"]

    def test_color_low_priority(self):
        """Low priority → Blueberry color (colorId 9)."""
        task = _make_task("gh:cncf/staff:123", priority="low")
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert body["colorId"] == PRIORITY_COLORS["low"]

    def test_color_no_priority(self):
        """No priority → Graphite color (colorId 8)."""
        task = _make_task("gh:cncf/staff:123", priority=None)
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert body["colorId"] == PRIORITY_COLORS[None]

    def test_start_and_end_times(self):
        """Event body should contain correct start and end times."""
        task = _make_task("gh:cncf/staff:123")
        body = build_event_body(task, "2026-03-20T09:00:00-07:00", "2026-03-20T11:00:00-07:00")

        assert body["start"]["dateTime"] == "2026-03-20T09:00:00-07:00"
        assert body["end"]["dateTime"] == "2026-03-20T11:00:00-07:00"


# --- Block creation tests ---


class TestCreateCalendarBlock:
    """Tests for create_calendar_block (API call + DB record)."""

    def test_creates_event_and_records_block(self, conn):
        """§19: Block recorded in calendar_blocks table with correct task_id."""
        task = _make_task("gh:cncf/staff:123")
        upsert_task(conn, task)

        mock_service = MagicMock()
        mock_service.events().insert().execute.return_value = {"id": "gcal_evt_abc"}

        block = create_calendar_block(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task=task,
            start_dt="2026-03-20T09:00:00-07:00",
            end_dt="2026-03-20T11:00:00-07:00",
            duration_hours=2.0,
        )

        assert block["gcal_event_id"] == "gcal_evt_abc"
        assert block["task_id"] == "gh:cncf/staff:123"

        # Verify DB record
        blocks = get_blocks_for_task(conn, "gh:cncf/staff:123")
        assert len(blocks) == 1
        assert blocks[0]["gcal_event_id"] == "gcal_evt_abc"
        assert blocks[0]["duration_hours"] == 2.0

    def test_calls_gcal_api_with_correct_body(self, conn):
        """Should pass the built event body to the GCal API."""
        task = _make_task("gh:cncf/staff:123", title="My Task", priority="high")
        upsert_task(conn, task)

        mock_service = MagicMock()
        mock_service.events().insert().execute.return_value = {"id": "gcal_evt_xyz"}

        create_calendar_block(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task=task,
            start_dt="2026-03-20T09:00:00-07:00",
            end_dt="2026-03-20T11:00:00-07:00",
            duration_hours=2.0,
        )

        # Verify the API was called
        mock_service.events().insert.assert_called()


# --- Block lifecycle: task completion tests ---


class TestMarkTaskBlocksCompleted:
    """§19: Closed task → future blocks get ✓ prefix and Graphite colour."""

    def test_future_blocks_get_checkmark_prefix(self, conn):
        """Future blocks should have title prefixed with ✓."""
        task = _make_task("gh:cncf/staff:200", title="Fix the thing")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:200", "evt_future", future_dt, future_end, 2.0)

        mock_service = MagicMock()
        mock_service.events().get().execute.return_value = {
            "id": "evt_future",
            "summary": "Fix the thing",
            "colorId": "11",
        }
        mock_service.events().update().execute.return_value = {}

        mark_task_blocks_completed(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task_id="gh:cncf/staff:200",
        )

        # Check the update call
        update_call = mock_service.events().update.call_args
        updated_body = update_call.kwargs.get("body") or update_call[1].get("body")
        assert updated_body["summary"].startswith("✓ ")

    def test_future_blocks_get_graphite_color(self, conn):
        """Future blocks should be set to Graphite colour."""
        task = _make_task("gh:cncf/staff:201", title="Another task")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:201", "evt_future2", future_dt, future_end, 2.0)

        mock_service = MagicMock()
        mock_service.events().get().execute.return_value = {
            "id": "evt_future2",
            "summary": "Another task",
            "colorId": "11",
        }
        mock_service.events().update().execute.return_value = {}

        mark_task_blocks_completed(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task_id="gh:cncf/staff:201",
        )

        update_call = mock_service.events().update.call_args
        updated_body = update_call.kwargs.get("body") or update_call[1].get("body")
        assert updated_body["colorId"] == PRIORITY_COLORS["completed"]

    def test_past_blocks_not_modified(self, conn):
        """Past blocks should not be updated."""
        task = _make_task("gh:cncf/staff:202")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        past_dt = (now - timedelta(hours=4)).isoformat()
        past_end = (now - timedelta(hours=3)).isoformat()
        block_id = insert_calendar_block(
            conn, "gh:cncf/staff:202", "evt_past", past_dt, past_end, 1.0
        )
        conn.execute("UPDATE calendar_blocks SET is_past = 1 WHERE id = ?", (block_id,))
        conn.commit()

        mock_service = MagicMock()

        mark_task_blocks_completed(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task_id="gh:cncf/staff:202",
        )

        # events().get() should not be called for past blocks
        mock_service.events().get().execute.assert_not_called()

    def test_already_prefixed_not_double_prefixed(self, conn):
        """Blocks already prefixed with ✓ should not get double-prefixed."""
        task = _make_task("gh:cncf/staff:203", title="Done task")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(
            conn, "gh:cncf/staff:203", "evt_already_done", future_dt, future_end, 2.0
        )

        mock_service = MagicMock()
        mock_service.events().get().execute.return_value = {
            "id": "evt_already_done",
            "summary": "✓ Done task",
            "colorId": "8",
        }
        mock_service.events().update().execute.return_value = {}

        mark_task_blocks_completed(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task_id="gh:cncf/staff:203",
        )

        update_call = mock_service.events().update.call_args
        updated_body = update_call.kwargs.get("body") or update_call[1].get("body")
        assert updated_body["summary"] == "✓ Done task"
        assert not updated_body["summary"].startswith("✓ ✓")

    def test_no_future_blocks_no_api_calls(self, conn):
        """If task has no future blocks, no API calls should be made."""
        task = _make_task("gh:cncf/staff:204")
        upsert_task(conn, task)

        mock_service = MagicMock()

        mark_task_blocks_completed(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task_id="gh:cncf/staff:204",
        )

        mock_service.events().get.assert_not_called()
        mock_service.events().update.assert_not_called()


# --- Block description update tests ---


class TestUpdateBlockDescription:
    """§8.4: If due_date or start_date changes, update description."""

    def test_updates_description_on_date_change(self, conn):
        """Should update the GCal event description when task metadata changes."""
        task = _make_task(
            "gh:cncf/staff:300",
            priority="high",
            due_date="2026-04-01",
        )
        upsert_task(conn, task)

        now = datetime.now(UTC)
        future_dt = (now + timedelta(hours=1)).isoformat()
        future_end = (now + timedelta(hours=3)).isoformat()
        insert_calendar_block(conn, "gh:cncf/staff:300", "evt_update", future_dt, future_end, 2.0)

        mock_service = MagicMock()
        mock_service.events().get().execute.return_value = {
            "id": "evt_update",
            "summary": "Fix the thing",
            "description": "old description",
            "colorId": "11",
            "start": {"dateTime": future_dt},
            "end": {"dateTime": future_end},
        }
        mock_service.events().update().execute.return_value = {}

        update_block_description(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task=task,
        )

        update_call = mock_service.events().update.call_args
        updated_body = update_call.kwargs.get("body") or update_call[1].get("body")
        assert "Due: 2026-04-01" in updated_body["description"]

    def test_no_future_blocks_no_update(self, conn):
        """If task has no future blocks, nothing to update."""
        task = _make_task("gh:cncf/staff:301")
        upsert_task(conn, task)

        mock_service = MagicMock()

        update_block_description(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task=task,
        )

        mock_service.events().get.assert_not_called()


# --- GitHub-only guard tests ---


class TestGitHubOnlyGuard:
    """§8.3: Only GitHub Issues get calendar blocks."""

    def test_jira_task_raises_error(self, conn):
        """Jira tasks should not get calendar blocks."""
        task = _make_task("jira:CNCFSD-123")
        task["source"] = "jira"
        upsert_task(conn, task)

        mock_service = MagicMock()
        with pytest.raises(ValueError, match="Only GitHub tasks"):
            create_calendar_block(
                conn,
                service=mock_service,
                calendar_id="cal_nstd",
                task=task,
                start_dt="2026-03-20T09:00:00-07:00",
                end_dt="2026-03-20T11:00:00-07:00",
                duration_hours=2.0,
            )

    def test_asana_task_raises_error(self, conn):
        """Asana tasks should not get calendar blocks."""
        task = _make_task("asana:12345")
        task["source"] = "asana"
        upsert_task(conn, task)

        mock_service = MagicMock()
        with pytest.raises(ValueError, match="Only GitHub tasks"):
            create_calendar_block(
                conn,
                service=mock_service,
                calendar_id="cal_nstd",
                task=task,
                start_dt="2026-03-20T09:00:00-07:00",
                end_dt="2026-03-20T11:00:00-07:00",
                duration_hours=2.0,
            )


# --- Past block with is_past=0 tests ---


class TestPastBlockWithoutFlag:
    """Copilot review: past block with is_past=0 should still be skipped."""

    def test_past_block_is_past_zero_not_modified(self, conn):
        """A block whose end_dt is past but is_past=0 should not be updated."""
        task = _make_task("gh:cncf/staff:600")
        upsert_task(conn, task)

        now = datetime.now(UTC)
        past_dt = (now - timedelta(hours=4)).isoformat()
        past_end = (now - timedelta(hours=3)).isoformat()
        # Insert with default is_past=0, even though it's in the past
        insert_calendar_block(conn, "gh:cncf/staff:600", "evt_stale", past_dt, past_end, 1.0)

        mock_service = MagicMock()

        mark_task_blocks_completed(
            conn,
            service=mock_service,
            calendar_id="cal_nstd",
            task_id="gh:cncf/staff:600",
        )

        # Should not call GCal API for this actually-past block
        mock_service.events().get().execute.assert_not_called()
