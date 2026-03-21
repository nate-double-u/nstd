"""Tests for nstd.sync.jira — written BEFORE implementation (TDD)."""

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
def jira_config():
    """Minimal Jira config for testing."""
    from nstd.config import JiraConfig

    return JiraConfig(
        server_url="https://cncfservicedesk.atlassian.net",
        username="nate@linuxfoundation.org",
        projects=["CNCFSD"],
        assigned_only=True,
        start_date_field="customfield_10015",
    )


def _make_jira_issue(
    key="CNCFSD-100",
    summary="Test issue",
    status="In Progress",
    priority="Medium",
    due_date="2026-03-25",
    start_date=None,
):
    """Helper to create a mock Jira issue object."""
    issue = MagicMock()
    issue.key = key
    issue.permalink.return_value = f"https://cncfservicedesk.atlassian.net/browse/{key}"

    fields = MagicMock()
    fields.summary = summary
    fields.description = f"Description for {key}"
    fields.status.name = status
    fields.status.statusCategory.name = status
    fields.priority.name = priority
    fields.assignee.displayName = "Nate"
    fields.assignee.emailAddress = "nate@linuxfoundation.org"
    fields.created = "2026-03-01T00:00:00.000+0000"
    fields.updated = "2026-03-15T00:00:00.000+0000"
    fields.duedate = due_date

    # Start date custom field
    fields.customfield_10015 = start_date

    issue.fields = fields
    return issue


class TestJiraIssueToTask:
    """Test conversion of Jira issue to nstd task dict."""

    def test_converts_basic_issue(self, jira_config):
        """Basic Jira issue converts to task dict correctly."""
        from nstd.sync.jira import jira_issue_to_task

        issue = _make_jira_issue()
        task = jira_issue_to_task(issue, jira_config)

        assert task["id"] == "jira:CNCFSD-100"
        assert task["source"] == "jira"
        assert task["source_id"] == "CNCFSD-100"
        assert task["title"] == "Test issue"
        assert task["state"] == "open"
        assert task["priority"] == "Medium"
        assert task["due_date"] == "2026-03-25"

    def test_done_status_maps_to_closed(self, jira_config):
        """Jira issue with Done status category maps to 'closed'."""
        from nstd.sync.jira import jira_issue_to_task

        issue = _make_jira_issue(status="Done")
        issue.fields.status.statusCategory.name = "Done"
        task = jira_issue_to_task(issue, jira_config)

        assert task["state"] == "closed"

    def test_start_date_from_custom_field(self, jira_config):
        """Start date extracted from configured custom field."""
        from nstd.sync.jira import jira_issue_to_task

        issue = _make_jira_issue(start_date="2026-03-18")
        task = jira_issue_to_task(issue, jira_config)

        assert task["start_date"] == "2026-03-18"


class TestJiraSync:
    """Test full Jira sync flow."""

    @patch("nstd.sync.jira._get_jira_client")
    def test_syncs_assigned_issues(self, mock_client_factory, db, jira_config):
        """Assigned issues in configured projects are synced."""
        from nstd.sync.jira import sync_jira

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.search_issues.return_value = [
            _make_jira_issue("CNCFSD-101", "First task"),
            _make_jira_issue("CNCFSD-102", "Second task"),
        ]

        stats = sync_jira(db, jira_config, token="fake-token")

        assert stats["fetched"] == 2
        assert stats["updated"] == 2

        rows = db.execute("SELECT * FROM tasks WHERE source = 'jira'").fetchall()
        assert len(rows) == 2

    @patch("nstd.sync.jira._get_jira_client")
    def test_jql_filters_done_issues(self, mock_client_factory, db, jira_config):
        """Verify the JQL passed to search_issues excludes Done."""
        from nstd.sync.jira import sync_jira

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.search_issues.return_value = []

        sync_jira(db, jira_config, token="fake-token")

        call_args = mock_client.search_issues.call_args
        jql = call_args[0][0] if call_args[0] else call_args[1].get("jql_str", "")
        assert "statusCategory != Done" in jql

    @patch("nstd.sync.jira._get_jira_client")
    def test_handles_api_error_gracefully(self, mock_client_factory, db, jira_config):
        """API errors are caught and returned in stats, not raised."""
        from nstd.sync.jira import sync_jira

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.search_issues.side_effect = Exception("API timeout")

        stats = sync_jira(db, jira_config, token="fake-token")

        assert len(stats["errors"]) > 0
        assert "API timeout" in stats["errors"][0]


class TestSyncJiraDryRun:
    """§6.7: sync_jira dry-run mode suppresses all DB writes."""

    @patch("nstd.sync.jira._get_jira_client")
    def test_dry_run_skips_upsert(self, mock_client_factory, db, jira_config, capsys):
        """dry_run=True must not call upsert_task."""
        from nstd.sync.jira import sync_jira

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client

        issue = MagicMock()
        issue.key = "CNCFSD-500"
        fields = issue.fields
        fields.summary = "Dry run Jira issue"
        fields.description = None
        fields.status.name = "To Do"
        fields.priority.name = "Medium"
        fields.assignee.name = "nate"
        fields.created = "2026-03-01T00:00:00.000+0000"
        fields.updated = "2026-03-15T00:00:00.000+0000"
        fields.duedate = None
        mock_client.search_issues.return_value = [issue]

        stats = sync_jira(db, jira_config, token="fake-token", dry_run=True)

        rows = db.execute("SELECT * FROM tasks").fetchall()
        assert len(rows) == 0
        assert stats["fetched"] == 1
        assert stats["updated"] == 1

    @patch("nstd.sync.jira._get_jira_client")
    def test_dry_run_prints_dry_run_line(self, mock_client_factory, db, jira_config, capsys):
        """dry_run=True must print [DRY-RUN] lines to stdout."""
        from nstd.sync.jira import sync_jira

        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client

        issue = MagicMock()
        issue.key = "CNCFSD-501"
        fields = issue.fields
        fields.summary = "Preview Jira task"
        fields.description = None
        fields.status.name = "In Progress"
        fields.priority.name = "High"
        fields.assignee.name = "nate"
        fields.created = "2026-03-01T00:00:00.000+0000"
        fields.updated = "2026-03-15T00:00:00.000+0000"
        fields.duedate = None
        mock_client.search_issues.return_value = [issue]

        sync_jira(db, jira_config, token="fake-token", dry_run=True)

        out = capsys.readouterr().out
        assert "[DRY-RUN]" in out
        assert "Preview Jira task" in out
