"""Tests for nstd.sync.asana — written BEFORE implementation (TDD)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def db():
    """In-memory database with schema."""
    from nstd.db import create_schema, get_connection

    conn = get_connection(":memory:")
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def asana_config():
    """Minimal Asana config for testing."""
    from nstd.config import AsanaConfig

    return AsanaConfig(
        workspace_gid="12345",
        assigned_only=True,
        project_gids=["proj_001", "proj_002"],
    )


def _make_asana_task(gid="1200000000001", name="Asana task", completed=False,
                     due_on="2026-03-25", start_on="2026-03-18",
                     assignee_gid="me"):
    """Helper to create an Asana task dict."""
    return {
        "gid": gid,
        "name": name,
        "notes": f"Notes for {name}",
        "completed": completed,
        "due_on": due_on,
        "start_on": start_on,
        "permalink_url": f"https://app.asana.com/0/0/{gid}",
        "assignee": {"gid": assignee_gid} if assignee_gid else None,
        "memberships": [],
        "custom_fields": [],
    }


class TestAsanaTaskToTask:
    """Test conversion of Asana task to nstd task dict."""

    def test_converts_basic_task(self):
        """Basic Asana task converts correctly."""
        from nstd.sync.asana import asana_task_to_task

        asana_task = _make_asana_task()
        task = asana_task_to_task(asana_task)

        assert task["id"] == "asana:1200000000001"
        assert task["source"] == "asana"
        assert task["source_id"] == "1200000000001"
        assert task["title"] == "Asana task"
        assert task["state"] == "open"
        assert task["due_date"] == "2026-03-25"
        assert task["start_date"] == "2026-03-18"

    def test_completed_task_maps_to_done(self):
        """Completed Asana task maps to 'done' state."""
        from nstd.sync.asana import asana_task_to_task

        asana_task = _make_asana_task(completed=True)
        task = asana_task_to_task(asana_task)

        assert task["state"] == "done"


class TestAsanaSync:
    """Test full Asana sync flow."""

    @patch("nstd.sync.asana._fetch_assigned_tasks")
    @patch("nstd.sync.asana._fetch_project_tasks")
    def test_syncs_assigned_tasks(self, mock_project, mock_assigned, db, asana_config):
        """Assigned tasks are synced to DB."""
        from nstd.sync.asana import sync_asana

        mock_assigned.return_value = [
            _make_asana_task("1001", "Assigned task 1"),
            _make_asana_task("1002", "Assigned task 2"),
        ]
        mock_project.return_value = []

        stats = sync_asana(db, asana_config, token="fake-token")

        assert stats["fetched"] >= 2
        assert stats["updated"] == 2

    @patch("nstd.sync.asana._fetch_assigned_tasks")
    @patch("nstd.sync.asana._fetch_project_tasks")
    def test_syncs_project_tasks_regardless_of_assignee(
        self, mock_project, mock_assigned, db, asana_config
    ):
        """Tasks in configured projects sync even if not assigned to user."""
        from nstd.sync.asana import sync_asana

        mock_assigned.return_value = []
        mock_project.return_value = [
            _make_asana_task("2001", "Project task", assignee_gid="someone_else"),
        ]

        stats = sync_asana(db, asana_config, token="fake-token")

        assert stats["updated"] == 1
        row = db.execute("SELECT * FROM tasks WHERE id = 'asana:2001'").fetchone()
        assert row is not None

    @patch("nstd.sync.asana._fetch_assigned_tasks")
    @patch("nstd.sync.asana._fetch_project_tasks")
    def test_deduplicates_tasks_in_both_assigned_and_project(
        self, mock_project, mock_assigned, db, asana_config
    ):
        """Task appearing in both assigned and project lists is only inserted once."""
        from nstd.sync.asana import sync_asana

        shared_task = _make_asana_task("3001", "Shared task")
        mock_assigned.return_value = [shared_task]
        mock_project.return_value = [shared_task]

        stats = sync_asana(db, asana_config, token="fake-token")

        rows = db.execute("SELECT * FROM tasks WHERE id = 'asana:3001'").fetchall()
        assert len(rows) == 1

    @patch("nstd.sync.asana._fetch_assigned_tasks")
    @patch("nstd.sync.asana._fetch_project_tasks")
    def test_handles_api_error_gracefully(
        self, mock_project, mock_assigned, db, asana_config
    ):
        """API errors are caught and returned in stats."""
        from nstd.sync.asana import sync_asana

        mock_assigned.side_effect = Exception("Network error")
        mock_project.return_value = []

        stats = sync_asana(db, asana_config, token="fake-token")

        assert len(stats["errors"]) > 0
