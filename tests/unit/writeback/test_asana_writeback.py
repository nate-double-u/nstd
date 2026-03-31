"""Tests for nstd.writeback.asana — written BEFORE implementation (TDD)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def db():
    """In-memory database with schema and linked tasks."""
    from nstd.db import create_schema, create_task_link, get_connection, upsert_task

    conn = get_connection(":memory:")
    create_schema(conn)

    # Create a GitHub task linked to an Asana task
    upsert_task(
        conn,
        {
            "id": "gh:cncf/staff:100",
            "source": "github",
            "source_id": "100",
            "source_url": "https://github.com/cncf/staff/issues/100",
            "title": "Fix the thing",
            "body": "",
            "state": "closed",
            "assignee": "nate-double-u",
            "priority": None,
            "size": None,
            "estimate_hours": None,
            "start_date": None,
            "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        },
    )
    upsert_task(
        conn,
        {
            "id": "asana:1200000000001",
            "source": "asana",
            "source_id": "1200000000001",
            "source_url": "https://app.asana.com/0/0/1200000000001",
            "title": "Asana mirror",
            "body": "",
            "state": "open",
            "assignee": "me",
            "priority": None,
            "size": None,
            "estimate_hours": None,
            "start_date": None,
            "due_date": None,
            "created_at": None,
            "updated_at": None,
        },
    )
    create_task_link(conn, "gh:cncf/staff:100", "asana:1200000000001", "mirrors")

    yield conn
    conn.close()


class TestAsanaWriteback:
    """Test Asana completion write-back when GitHub issues close."""

    @patch("nstd.writeback.asana._get_asana_client")
    def test_closing_github_issue_completes_asana_task(self, mock_client_factory, db):
        """Closing a linked GitHub Issue marks the Asana task complete."""
        from nstd.writeback.asana import writeback_asana_done

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client

        result = writeback_asana_done(
            db,
            github_task_id="gh:cncf/staff:100",
            token="fake-token",
        )

        assert result["success"] is True
        mock_client.tasks.update_task.assert_called_once_with("1200000000001", {"completed": True})

    def test_no_linked_asana_task_is_noop(self, db):
        """GitHub task with no Asana link results in no action, no error."""
        from nstd.db import upsert_task
        from nstd.writeback.asana import writeback_asana_done

        upsert_task(
            db,
            {
                "id": "gh:cncf/staff:999",
                "source": "github",
                "source_id": "999",
                "source_url": "https://github.com/cncf/staff/issues/999",
                "title": "Unlinked",
                "body": "",
                "state": "closed",
                "assignee": "nate-double-u",
                "priority": None,
                "size": None,
                "estimate_hours": None,
                "start_date": None,
                "due_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            },
        )

        result = writeback_asana_done(db, "gh:cncf/staff:999", "fake-token")

        assert result["success"] is True
        assert result["skipped"] is True

    @patch("nstd.writeback.asana._get_asana_client")
    def test_api_error_does_not_crash(self, mock_client_factory, db):
        """Failed Asana update is logged, not raised."""
        from nstd.writeback.asana import writeback_asana_done

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.tasks.update_task.side_effect = Exception("Asana API down")

        result = writeback_asana_done(db, "gh:cncf/staff:100", "fake-token")

        assert result["success"] is False
        assert "error" in result


class TestAsanaWritebackDryRun:
    """Dry-run mode for Asana write-back (§6.7)."""

    @patch("nstd.writeback.asana._get_asana_client")
    def test_dry_run_skips_api_call(self, mock_client_factory, db, capsys):
        """dry_run=True must not call the Asana API."""
        from nstd.writeback.asana import writeback_asana_done

        result = writeback_asana_done(
            db,
            github_task_id="gh:cncf/staff:100",
            token="fake-token",
            dry_run=True,
        )

        mock_client_factory.assert_not_called()
        assert result["success"] is True

    @patch("nstd.writeback.asana._get_asana_client")
    def test_dry_run_prints_dry_run_line(self, mock_client_factory, db, capsys):
        """dry_run=True must print a [DRY-RUN] line to stdout."""
        from nstd.writeback.asana import writeback_asana_done

        writeback_asana_done(
            db,
            github_task_id="gh:cncf/staff:100",
            token="fake-token",
            dry_run=True,
        )

        out = capsys.readouterr().out
        assert "[DRY-RUN]" in out
        assert "1200000000001" in out

    def test_dry_run_with_no_linked_task_is_noop(self, db, capsys):
        """dry_run=True with no linked task should be a noop (skipped)."""
        from nstd.db import upsert_task
        from nstd.writeback.asana import writeback_asana_done

        upsert_task(
            db,
            {
                "id": "gh:cncf/staff:888",
                "source": "github",
                "source_id": "888",
                "source_url": "https://github.com/cncf/staff/issues/888",
                "title": "Unlinked",
                "body": "",
                "state": "closed",
                "assignee": "nate-double-u",
                "priority": None,
                "size": None,
                "estimate_hours": None,
                "start_date": None,
                "due_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            },
        )

        result = writeback_asana_done(db, "gh:cncf/staff:888", "fake-token", dry_run=True)

        out = capsys.readouterr().out
        assert result["skipped"] is True
        assert "[DRY-RUN]" not in out
