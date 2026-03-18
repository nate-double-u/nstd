"""Tests for nstd.db — written BEFORE implementation (TDD)."""

import sqlite3
from datetime import datetime

import pytest


@pytest.fixture
def db():
    """Create an in-memory database with schema applied."""
    from nstd.db import create_schema, get_connection

    conn = get_connection(":memory:")
    create_schema(conn)
    yield conn
    conn.close()


class TestSchema:
    """Test schema creation."""

    def test_creates_all_tables(self, db):
        """Schema creates all required tables."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        expected = {
            "tasks", "calendar_blocks", "task_links",
            "sync_log", "conflicts", "estimates",
        }
        assert expected.issubset(tables)

    def test_schema_is_idempotent(self, db):
        """Calling create_schema twice doesn't raise."""
        from nstd.db import create_schema

        create_schema(db)  # second call
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        assert len(cursor.fetchall()) >= 6


class TestTaskUpsert:
    """Test task upsert operations."""

    def test_insert_new_task(self, db):
        """Inserting a new task creates a record."""
        from nstd.db import upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:123",
            "source": "github",
            "source_id": "123",
            "source_url": "https://github.com/cncf/staff/issues/123",
            "title": "Fix the thing",
            "body": "Detailed description",
            "state": "open",
            "assignee": "nate-double-u",
            "priority": "high",
            "size": "M",
            "estimate_hours": None,
            "start_date": "2026-03-18",
            "due_date": "2026-03-25",
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        row = db.execute("SELECT * FROM tasks WHERE id = ?", ("gh:cncf/staff:123",)).fetchone()
        assert row is not None
        assert row[0] == "gh:cncf/staff:123"  # id
        assert row[4] == "Fix the thing"      # title

    def test_update_existing_task(self, db):
        """Upserting an existing task updates it."""
        from nstd.db import upsert_task

        task_data = {
            "id": "gh:cncf/staff:123",
            "source": "github",
            "source_id": "123",
            "source_url": "https://github.com/cncf/staff/issues/123",
            "title": "Fix the thing",
            "body": "Description",
            "state": "open",
            "assignee": "nate-double-u",
            "priority": "high",
            "size": "M",
            "estimate_hours": None,
            "start_date": None,
            "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        }
        upsert_task(db, task_data)

        task_data["title"] = "Fix the thing (updated)"
        task_data["state"] = "closed"
        upsert_task(db, task_data)

        row = db.execute("SELECT title, state FROM tasks WHERE id = ?",
                         ("gh:cncf/staff:123",)).fetchone()
        assert row[0] == "Fix the thing (updated)"
        assert row[1] == "closed"

    def test_upsert_sets_synced_at(self, db):
        """Upsert sets synced_at timestamp."""
        from nstd.db import upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:999",
            "source": "github",
            "source_id": "999",
            "source_url": "https://github.com/cncf/staff/issues/999",
            "title": "Test task",
            "body": "",
            "state": "open",
            "assignee": "nate-double-u",
            "priority": None,
            "size": None,
            "estimate_hours": None,
            "start_date": None,
            "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        row = db.execute("SELECT synced_at FROM tasks WHERE id = ?",
                         ("gh:cncf/staff:999",)).fetchone()
        assert row[0] is not None


class TestTaskQueries:
    """Test task query helpers."""

    def test_get_task_by_id(self, db):
        """Retrieve a single task by ID."""
        from nstd.db import get_task, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:100",
            "source": "github",
            "source_id": "100",
            "source_url": "https://github.com/cncf/staff/issues/100",
            "title": "Task 100",
            "body": "",
            "state": "open",
            "assignee": "nate-double-u",
            "priority": None,
            "size": None,
            "estimate_hours": None,
            "start_date": None,
            "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        task = get_task(db, "gh:cncf/staff:100")
        assert task is not None
        assert task["title"] == "Task 100"

    def test_get_nonexistent_task_returns_none(self, db):
        """Querying a non-existent task returns None."""
        from nstd.db import get_task

        assert get_task(db, "gh:cncf/staff:9999") is None

    def test_get_open_tasks(self, db):
        """Retrieve all open tasks."""
        from nstd.db import get_open_tasks, upsert_task

        for i, state in [(1, "open"), (2, "open"), (3, "closed")]:
            upsert_task(db, {
                "id": f"gh:cncf/staff:{i}",
                "source": "github",
                "source_id": str(i),
                "source_url": f"https://github.com/cncf/staff/issues/{i}",
                "title": f"Task {i}",
                "body": "",
                "state": state,
                "assignee": "nate-double-u",
                "priority": None,
                "size": None,
                "estimate_hours": None,
                "start_date": None,
                "due_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            })

        open_tasks = get_open_tasks(db)
        assert len(open_tasks) == 2

    def test_get_tasks_by_source(self, db):
        """Retrieve tasks filtered by source system."""
        from nstd.db import get_tasks_by_source, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:1",
            "source": "github",
            "source_id": "1",
            "source_url": "https://github.com/cncf/staff/issues/1",
            "title": "GH Task",
            "body": "",
            "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })
        upsert_task(db, {
            "id": "jira:CNCFSD-100",
            "source": "jira",
            "source_id": "CNCFSD-100",
            "source_url": "https://cncfservicedesk.atlassian.net/browse/CNCFSD-100",
            "title": "Jira Task",
            "body": "",
            "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        gh_tasks = get_tasks_by_source(db, "github")
        assert len(gh_tasks) == 1
        assert gh_tasks[0]["title"] == "GH Task"


class TestTaskLinks:
    """Test task link operations."""

    def test_create_task_link(self, db):
        """Create a link between two tasks."""
        from nstd.db import create_task_link, upsert_task

        for task_id in ["gh:cncf/staff:1", "jira:CNCFSD-100"]:
            upsert_task(db, {
                "id": task_id,
                "source": "github" if "gh:" in task_id else "jira",
                "source_id": task_id.split(":")[-1],
                "source_url": f"https://example.com/{task_id}",
                "title": f"Task {task_id}",
                "body": "", "state": "open", "assignee": "nate-double-u",
                "priority": None, "size": None, "estimate_hours": None,
                "start_date": None, "due_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            })

        create_task_link(db, "gh:cncf/staff:1", "jira:CNCFSD-100", "mirrors")

        links = db.execute("SELECT * FROM task_links").fetchall()
        assert len(links) == 1

    def test_get_linked_tasks(self, db):
        """Retrieve tasks linked to a given task."""
        from nstd.db import create_task_link, get_linked_tasks, upsert_task

        for task_id in ["gh:cncf/staff:1", "jira:CNCFSD-100"]:
            upsert_task(db, {
                "id": task_id,
                "source": "github" if "gh:" in task_id else "jira",
                "source_id": task_id.split(":")[-1],
                "source_url": f"https://example.com/{task_id}",
                "title": f"Task {task_id}",
                "body": "", "state": "open", "assignee": "nate-double-u",
                "priority": None, "size": None, "estimate_hours": None,
                "start_date": None, "due_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            })

        create_task_link(db, "gh:cncf/staff:1", "jira:CNCFSD-100", "mirrors")

        linked = get_linked_tasks(db, "gh:cncf/staff:1")
        assert len(linked) == 1
        assert linked[0]["task_id"] == "jira:CNCFSD-100"

    def test_no_duplicate_links(self, db):
        """Creating the same link twice doesn't duplicate."""
        from nstd.db import create_task_link, upsert_task

        for task_id in ["gh:cncf/staff:1", "jira:CNCFSD-100"]:
            upsert_task(db, {
                "id": task_id,
                "source": "github" if "gh:" in task_id else "jira",
                "source_id": task_id.split(":")[-1],
                "source_url": f"https://example.com/{task_id}",
                "title": f"Task {task_id}",
                "body": "", "state": "open", "assignee": "nate-double-u",
                "priority": None, "size": None, "estimate_hours": None,
                "start_date": None, "due_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            })

        create_task_link(db, "gh:cncf/staff:1", "jira:CNCFSD-100", "mirrors")
        create_task_link(db, "gh:cncf/staff:1", "jira:CNCFSD-100", "mirrors")

        links = db.execute("SELECT * FROM task_links").fetchall()
        assert len(links) == 1


class TestSyncLog:
    """Test sync log operations."""

    def test_start_sync_log(self, db):
        """Start a sync log entry."""
        from nstd.db import start_sync_log

        log_id = start_sync_log(db, source="github")
        assert log_id is not None

        row = db.execute("SELECT status, source FROM sync_log WHERE id = ?",
                         (log_id,)).fetchone()
        assert row[0] == "running"
        assert row[1] == "github"

    def test_complete_sync_log(self, db):
        """Complete a sync log entry with stats."""
        from nstd.db import complete_sync_log, start_sync_log

        log_id = start_sync_log(db)
        complete_sync_log(db, log_id, records_fetched=10, records_updated=3)

        row = db.execute(
            "SELECT status, records_fetched, records_updated, finished_at FROM sync_log WHERE id = ?",
            (log_id,)
        ).fetchone()
        assert row[0] == "success"
        assert row[1] == 10
        assert row[2] == 3
        assert row[3] is not None

    def test_error_sync_log(self, db):
        """Record errors in sync log."""
        from nstd.db import error_sync_log, start_sync_log

        log_id = start_sync_log(db)
        error_sync_log(db, log_id, errors=["API timeout", "Rate limited"])

        row = db.execute("SELECT status, errors FROM sync_log WHERE id = ?",
                         (log_id,)).fetchone()
        assert row[0] == "error"
        assert "API timeout" in row[1]


class TestConflicts:
    """Test conflict operations."""

    def test_record_conflict(self, db):
        """Record a field conflict."""
        from nstd.db import record_conflict, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:1",
            "source": "github", "source_id": "1",
            "source_url": "https://github.com/cncf/staff/issues/1",
            "title": "Task 1", "body": "", "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        record_conflict(db,
            task_id="gh:cncf/staff:1",
            field="priority",
            value_github="high",
            value_other="medium",
            other_source="jira",
        )

        conflicts = db.execute("SELECT * FROM conflicts").fetchall()
        assert len(conflicts) == 1

    def test_get_unresolved_conflicts(self, db):
        """Retrieve only unresolved conflicts."""
        from nstd.db import get_unresolved_conflicts, record_conflict, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:1",
            "source": "github", "source_id": "1",
            "source_url": "https://github.com/cncf/staff/issues/1",
            "title": "Task 1", "body": "", "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        record_conflict(db, "gh:cncf/staff:1", "priority", "high", "low", "jira")
        record_conflict(db, "gh:cncf/staff:1", "due_date", "2026-03-25", "2026-03-30", "jira")

        # Resolve one
        db.execute(
            "UPDATE conflicts SET resolved_at = datetime('now'), resolution = 'github_wins' "
            "WHERE field = 'priority'"
        )
        db.commit()

        unresolved = get_unresolved_conflicts(db)
        assert len(unresolved) == 1
        assert unresolved[0]["field"] == "due_date"


class TestCalendarBlocks:
    """Test calendar block operations."""

    def test_insert_calendar_block(self, db):
        """Insert a calendar block for a task."""
        from nstd.db import insert_calendar_block, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:1",
            "source": "github", "source_id": "1",
            "source_url": "https://github.com/cncf/staff/issues/1",
            "title": "Task 1", "body": "", "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        block_id = insert_calendar_block(db,
            task_id="gh:cncf/staff:1",
            gcal_event_id="event_abc123",
            start_dt="2026-03-20T09:00:00-07:00",
            end_dt="2026-03-20T11:00:00-07:00",
            duration_hours=2.0,
        )

        assert block_id is not None
        row = db.execute("SELECT * FROM calendar_blocks WHERE id = ?",
                         (block_id,)).fetchone()
        assert row is not None

    def test_get_blocks_for_task(self, db):
        """Retrieve calendar blocks for a specific task."""
        from nstd.db import get_blocks_for_task, insert_calendar_block, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:1",
            "source": "github", "source_id": "1",
            "source_url": "https://github.com/cncf/staff/issues/1",
            "title": "Task 1", "body": "", "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        insert_calendar_block(db, "gh:cncf/staff:1", "evt1",
                              "2026-03-20T09:00:00", "2026-03-20T11:00:00", 2.0)
        insert_calendar_block(db, "gh:cncf/staff:1", "evt2",
                              "2026-03-21T09:00:00", "2026-03-21T11:00:00", 2.0)

        blocks = get_blocks_for_task(db, "gh:cncf/staff:1")
        assert len(blocks) == 2

    def test_get_future_blocks_for_task(self, db):
        """Retrieve only future (non-past) blocks for a task."""
        from nstd.db import get_future_blocks_for_task, insert_calendar_block, upsert_task

        upsert_task(db, {
            "id": "gh:cncf/staff:1",
            "source": "github", "source_id": "1",
            "source_url": "https://github.com/cncf/staff/issues/1",
            "title": "Task 1", "body": "", "state": "open",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        insert_calendar_block(db, "gh:cncf/staff:1", "evt1",
                              "2026-03-20T09:00:00", "2026-03-20T11:00:00", 2.0)
        # Mark one as past
        db.execute("UPDATE calendar_blocks SET is_past = 1 WHERE gcal_event_id = 'evt1'")

        insert_calendar_block(db, "gh:cncf/staff:1", "evt2",
                              "2026-03-21T09:00:00", "2026-03-21T11:00:00", 2.0)
        db.commit()

        future = get_future_blocks_for_task(db, "gh:cncf/staff:1")
        assert len(future) == 1
        assert future[0]["gcal_event_id"] == "evt2"
