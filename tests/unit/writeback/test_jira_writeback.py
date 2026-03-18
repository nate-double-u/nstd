"""Tests for nstd.writeback.jira — written BEFORE implementation (TDD)."""

from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture
def db():
    """In-memory database with schema and linked tasks."""
    from nstd.db import create_schema, create_task_link, get_connection, upsert_task

    conn = get_connection(":memory:")
    create_schema(conn)

    # Create a GitHub task linked to a Jira task
    upsert_task(conn, {
        "id": "gh:cncf/staff:100",
        "source": "github", "source_id": "100",
        "source_url": "https://github.com/cncf/staff/issues/100",
        "title": "Fix the thing", "body": "", "state": "closed",
        "assignee": "nate-double-u",
        "priority": None, "size": None, "estimate_hours": None,
        "start_date": None, "due_date": None,
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-15T00:00:00Z",
    })
    upsert_task(conn, {
        "id": "jira:CNCFSD-200",
        "source": "jira", "source_id": "CNCFSD-200",
        "source_url": "https://cncfservicedesk.atlassian.net/browse/CNCFSD-200",
        "title": "Jira mirror", "body": "", "state": "open",
        "assignee": "nate",
        "priority": None, "size": None, "estimate_hours": None,
        "start_date": None, "due_date": None,
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-15T00:00:00Z",
    })
    create_task_link(conn, "gh:cncf/staff:100", "jira:CNCFSD-200", "mirrors")

    yield conn
    conn.close()


class TestJiraWriteback:
    """Test Jira transition write-back when GitHub issues close."""

    @patch("nstd.writeback.jira._get_jira_client")
    def test_closing_github_issue_triggers_jira_transition(self, mock_client_factory, db):
        """Closing a linked GitHub Issue transitions the Jira ticket to Done."""
        from nstd.writeback.jira import writeback_jira_done

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.transitions.return_value = [
            {"id": "31", "name": "Done"},
            {"id": "21", "name": "In Progress"},
        ]

        result = writeback_jira_done(
            db,
            github_task_id="gh:cncf/staff:100",
            token="fake-token",
            server_url="https://cncfservicedesk.atlassian.net",
            username="nate@linuxfoundation.org",
        )

        assert result["success"] is True
        mock_client.transition_issue.assert_called_once_with("CNCFSD-200", "31")

    @patch("nstd.writeback.jira._get_jira_client")
    def test_finds_closed_transition_variant(self, mock_client_factory, db):
        """Finds 'Closed' transition when 'Done' is not available."""
        from nstd.writeback.jira import writeback_jira_done

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.transitions.return_value = [
            {"id": "41", "name": "Closed"},
            {"id": "21", "name": "In Progress"},
        ]

        result = writeback_jira_done(
            db, "gh:cncf/staff:100", "fake-token",
            "https://cncfservicedesk.atlassian.net", "nate@linuxfoundation.org",
        )

        assert result["success"] is True
        mock_client.transition_issue.assert_called_once_with("CNCFSD-200", "41")

    @patch("nstd.writeback.jira._get_jira_client")
    def test_no_done_transition_available(self, mock_client_factory, db):
        """When no matching transition exists, report failure without crashing."""
        from nstd.writeback.jira import writeback_jira_done

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.transitions.return_value = [
            {"id": "21", "name": "In Progress"},
        ]

        result = writeback_jira_done(
            db, "gh:cncf/staff:100", "fake-token",
            "https://cncfservicedesk.atlassian.net", "nate@linuxfoundation.org",
        )

        assert result["success"] is False
        mock_client.transition_issue.assert_not_called()

    def test_no_linked_jira_task_is_noop(self, db):
        """GitHub task with no Jira link results in no action, no error."""
        from nstd.writeback.jira import writeback_jira_done
        from nstd.db import upsert_task

        # Create an unlinked task
        upsert_task(db, {
            "id": "gh:cncf/staff:999",
            "source": "github", "source_id": "999",
            "source_url": "https://github.com/cncf/staff/issues/999",
            "title": "Unlinked", "body": "", "state": "closed",
            "assignee": "nate-double-u",
            "priority": None, "size": None, "estimate_hours": None,
            "start_date": None, "due_date": None,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        })

        result = writeback_jira_done(
            db, "gh:cncf/staff:999", "fake-token",
            "https://cncfservicedesk.atlassian.net", "nate@linuxfoundation.org",
        )

        assert result["success"] is True
        assert result["skipped"] is True

    @patch("nstd.writeback.jira._get_jira_client")
    def test_api_error_does_not_crash(self, mock_client_factory, db):
        """Failed Jira transition is logged, not raised."""
        from nstd.writeback.jira import writeback_jira_done

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.transitions.side_effect = Exception("Jira API down")

        result = writeback_jira_done(
            db, "gh:cncf/staff:100", "fake-token",
            "https://cncfservicedesk.atlassian.net", "nate@linuxfoundation.org",
        )

        assert result["success"] is False
        assert "error" in result
