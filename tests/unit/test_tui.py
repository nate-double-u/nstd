"""Tests for the nstd TUI application.

Spec references:
  §9.1 — Screen layout (header, tabs, list, detail)
  §9.2 — Keybindings
  §9.3 — Task list (source indicators, badges)
  §9.4 — Conflicts tab
  §9.5 — Calendar tab
  §9.6 — Sync log tab
"""

from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import TabbedContent

from nstd.db import create_schema, get_connection, upsert_task


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
        "title": f"Task {task_id}",
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


# --- Source indicator tests ---


class TestSourceIndicator:
    """§9.3: Source indicators for task list."""

    def test_github_indicator(self):
        from nstd.tui.app import source_indicator

        assert source_indicator("github") == "●"

    def test_jira_indicator(self):
        from nstd.tui.app import source_indicator

        assert source_indicator("jira") == "J"

    def test_asana_indicator(self):
        from nstd.tui.app import source_indicator

        assert source_indicator("asana") == "A"

    def test_unknown_indicator(self):
        from nstd.tui.app import source_indicator

        assert source_indicator("other") == "?"


# --- Short ID tests ---


class TestShortId:
    """§9.3: Task ID display format."""

    def test_github_short_id(self):
        from nstd.tui.app import short_id

        assert short_id("gh:cncf/staff:123") == "GH-123"

    def test_jira_short_id(self):
        from nstd.tui.app import short_id

        assert short_id("jira:CNCFSD-45") == "CNCFSD-45"

    def test_asana_short_id(self):
        from nstd.tui.app import short_id

        assert short_id("asana:12345") == "A-12345"

    def test_unknown_short_id(self):
        from nstd.tui.app import short_id

        assert short_id("foo:bar") == "foo:bar"


# --- Task row formatting tests ---


class TestFormatTaskRow:
    """§9.3: Each row displays source, id, title, due, priority, badges."""

    def test_basic_row(self):
        from nstd.tui.app import format_task_row

        task = _make_task("gh:cncf/staff:123", title="Fix the thing")
        row = format_task_row(task)
        assert "●" in row
        assert "GH-123" in row
        assert "Fix the thing" in row

    def test_row_with_due_date(self):
        from nstd.tui.app import format_task_row

        task = _make_task("gh:cncf/staff:123", due_date="2026-04-01")
        row = format_task_row(task)
        assert "2026-04-01" in row

    def test_row_with_priority(self):
        from nstd.tui.app import format_task_row

        task = _make_task("gh:cncf/staff:123", priority="high")
        row = format_task_row(task)
        assert "high" in row.lower() or "🔴" in row or "‼" in row

    def test_jira_row(self):
        from nstd.tui.app import format_task_row

        task = _make_task("jira:CNCFSD-45", source="jira", title="Review request")
        row = format_task_row(task)
        assert "J" in row
        assert "CNCFSD-45" in row


# --- Task loading from DB ---


class TestLoadTasks:
    """Tasks should be loaded from the DB for display."""

    def test_loads_open_tasks(self, conn):
        from nstd.tui.app import load_tasks

        upsert_task(conn, _make_task("gh:cncf/staff:1"))
        upsert_task(conn, _make_task("gh:cncf/staff:2"))

        tasks = load_tasks(conn)
        assert len(tasks) == 2

    def test_excludes_closed_tasks_by_default(self, conn):
        from nstd.tui.app import load_tasks

        upsert_task(conn, _make_task("gh:cncf/staff:1", state="open"))
        upsert_task(conn, _make_task("gh:cncf/staff:2", state="closed"))

        tasks = load_tasks(conn)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "gh:cncf/staff:1"

    def test_filter_by_source(self, conn):
        from nstd.tui.app import load_tasks

        upsert_task(conn, _make_task("gh:cncf/staff:1", source="github"))
        upsert_task(conn, _make_task("jira:CNCFSD-1", source="jira"))

        tasks = load_tasks(conn, source_filter="github")
        assert len(tasks) == 1
        assert tasks[0]["source"] == "github"

    def test_sort_by_due_date(self, conn):
        from nstd.tui.app import load_tasks

        upsert_task(conn, _make_task("gh:cncf/staff:1", due_date="2026-04-15"))
        upsert_task(conn, _make_task("gh:cncf/staff:2", due_date="2026-04-01"))
        upsert_task(conn, _make_task("gh:cncf/staff:3", due_date=None))

        tasks = load_tasks(conn, sort_by="due_date")
        # Tasks with due dates should come first, sorted ascending
        assert tasks[0]["id"] == "gh:cncf/staff:2"
        assert tasks[1]["id"] == "gh:cncf/staff:1"

    def test_invalid_sort_column_raises_error(self, conn):
        """SQL injection via sort_by should raise ValueError."""
        from nstd.tui.app import load_tasks

        with pytest.raises(ValueError, match="Invalid sort column"):
            load_tasks(conn, sort_by="id; DROP TABLE tasks")


# --- Sync log loading ---


class TestLoadSyncLog:
    """§9.6: Last 20 sync entries."""

    def test_loads_recent_entries(self, conn):
        from nstd.db import complete_sync_log, start_sync_log
        from nstd.tui.app import load_sync_log

        for i in range(5):
            log_id = start_sync_log(conn, source=None)
            complete_sync_log(conn, log_id, records_fetched=i * 10, records_updated=i * 5)

        entries = load_sync_log(conn)
        assert len(entries) == 5

    def test_limits_to_20(self, conn):
        from nstd.db import complete_sync_log, start_sync_log
        from nstd.tui.app import load_sync_log

        for i in range(25):
            log_id = start_sync_log(conn, source=None)
            complete_sync_log(conn, log_id, records_fetched=i, records_updated=i)

        entries = load_sync_log(conn)
        assert len(entries) == 20

    def test_ordered_most_recent_first(self, conn):
        from nstd.db import complete_sync_log, start_sync_log
        from nstd.tui.app import load_sync_log

        log1 = start_sync_log(conn, source=None)
        complete_sync_log(conn, log1, records_fetched=10, records_updated=5)
        log2 = start_sync_log(conn, source=None)
        complete_sync_log(conn, log2, records_fetched=20, records_updated=10)

        entries = load_sync_log(conn)
        # Most recent first
        assert entries[0]["records_fetched"] == 20


# --- Conflict loading ---


class TestLoadConflicts:
    """§9.4: List unresolved conflicts."""

    def test_loads_unresolved_conflicts(self, conn):
        from nstd.db import record_conflict
        from nstd.tui.app import load_conflicts

        upsert_task(conn, _make_task("gh:cncf/staff:1"))
        record_conflict(
            conn,
            task_id="gh:cncf/staff:1",
            field="priority",
            value_github="high",
            value_other="low",
            other_source="jira",
        )

        conflicts = load_conflicts(conn)
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "priority"

    def test_excludes_resolved_conflicts(self, conn):
        from nstd.db import record_conflict
        from nstd.tui.app import load_conflicts

        upsert_task(conn, _make_task("gh:cncf/staff:1"))
        record_conflict(
            conn,
            task_id="gh:cncf/staff:1",
            field="priority",
            value_github="high",
            value_other="low",
            other_source="jira",
        )
        # Resolve directly in DB (resolve_conflict may be on another branch)
        conn.execute(
            "UPDATE conflicts SET resolved_at = '2026-03-18T12:00:00Z', "
            "resolution = 'github_wins' WHERE task_id = ?",
            ("gh:cncf/staff:1",),
        )
        conn.commit()

        conflicts = load_conflicts(conn)
        assert len(conflicts) == 0


# --- Priority indicator tests ---


class TestPriorityIndicator:
    """Priority display in task rows."""

    def test_high(self):
        from nstd.tui.app import priority_indicator

        assert priority_indicator("high") != ""

    def test_medium(self):
        from nstd.tui.app import priority_indicator

        result = priority_indicator("medium")
        assert result != ""

    def test_low(self):
        from nstd.tui.app import priority_indicator

        result = priority_indicator("low")
        assert result != ""

    def test_none(self):
        from nstd.tui.app import priority_indicator

        result = priority_indicator(None)
        assert result == ""


# --- App class tests ---


class TestNstdApp:
    """Basic app structure tests."""

    def test_app_is_textual_app(self):
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        assert isinstance(app, App)

    def test_app_title(self):
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        assert app.title == "nstd"

    @pytest.mark.asyncio
    async def test_action_tab_tasks(self):
        """Tab action should switch to tasks tab."""
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        async with app.run_test() as pilot:
            await pilot.press("2")  # switch away from tasks
            await pilot.press("1")  # back to tasks
            tc = app.query_one(TabbedContent)
            assert tc.active == "tasks"

    @pytest.mark.asyncio
    async def test_action_tab_conflicts(self):
        """Tab action should switch to conflicts tab."""
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        async with app.run_test() as pilot:
            await pilot.press("2")
            tc = app.query_one(TabbedContent)
            assert tc.active == "conflicts"

    @pytest.mark.asyncio
    async def test_action_tab_calendar(self):
        """Tab action should switch to calendar tab."""
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        async with app.run_test() as pilot:
            await pilot.press("3")
            tc = app.query_one(TabbedContent)
            assert tc.active == "calendar"

    @pytest.mark.asyncio
    async def test_action_tab_log(self):
        """Tab action should switch to log tab."""
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        async with app.run_test() as pilot:
            await pilot.press("4")
            tc = app.query_one(TabbedContent)
            assert tc.active == "log"

    @pytest.mark.asyncio
    async def test_action_sync_does_not_crash(self):
        """Sync action should not raise (stub)."""
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        async with app.run_test() as pilot:
            await pilot.press("s")

    @pytest.mark.asyncio
    async def test_action_help_does_not_crash(self):
        """Help action should not raise (stub)."""
        from nstd.tui.app import NstdApp

        app = NstdApp(db_path=":memory:")
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
