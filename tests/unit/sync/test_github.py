"""Tests for nstd.sync.github — written BEFORE implementation (TDD)."""

import textwrap
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
def github_config():
    """Minimal GitHub-related config for testing."""
    from nstd.config import GitHubConfig, UserConfig

    return {
        "user": UserConfig(
            github_username="nate-double-u",
            timezone="America/Los_Angeles",
        ),
        "github": GitHubConfig(
            repos=["cncf/staff"],
            projects=["cncf/27"],
            exclude_labels=[],
            exclude_assignees=["cncf-automation-bot"],
        ),
    }


class TestJiraLinkExtraction:
    """Test Jira link parsing from GitHub Issue bodies."""

    def test_extracts_jira_link_from_issue_body(self):
        """Standard Jira link format in issue body is detected."""
        from nstd.sync.github import extract_jira_link

        body = textwrap.dedent("""\
            This issue tracks work on the service desk.

            **Jira:** https://cncfservicedesk.atlassian.net/browse/CNCFSD-456

            More details here.
        """)

        url, key = extract_jira_link(body)
        assert url == "https://cncfservicedesk.atlassian.net/browse/CNCFSD-456"
        assert key == "CNCFSD-456"

    def test_no_jira_link_returns_none(self):
        """Issue body without Jira link returns (None, None)."""
        from nstd.sync.github import extract_jira_link

        body = "Just a regular issue body with no links."
        url, key = extract_jira_link(body)
        assert url is None
        assert key is None

    def test_empty_body_returns_none(self):
        """Empty/None body returns (None, None)."""
        from nstd.sync.github import extract_jira_link

        assert extract_jira_link(None) == (None, None)
        assert extract_jira_link("") == (None, None)

    def test_extracts_different_project_keys(self):
        """Works with various Jira project key formats."""
        from nstd.sync.github import extract_jira_link

        body = "**Jira:** https://cncfservicedesk.atlassian.net/browse/PROJ-123"
        url, key = extract_jira_link(body)
        assert key == "PROJ-123"


class TestIssueToTask:
    """Test conversion of GitHub API issue data to nstd task dict."""

    def test_converts_basic_issue(self):
        """Basic GitHub issue converts to task dict correctly."""
        from nstd.sync.github import issue_to_task

        issue = {
            "number": 123,
            "title": "Fix the thing",
            "body": "Detailed description",
            "state": "open",
            "html_url": "https://github.com/cncf/staff/issues/123",
            "assignees": [{"login": "nate-double-u"}],
            "labels": [{"name": "bug"}],
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        }

        task = issue_to_task(issue, "cncf/staff")
        assert task["id"] == "gh:cncf/staff:123"
        assert task["source"] == "github"
        assert task["source_id"] == "123"
        assert task["title"] == "Fix the thing"
        assert task["state"] == "open"
        assert task["assignee"] == "nate-double-u"

    def test_closed_issue_state(self):
        """Closed GitHub issue maps to 'closed' state."""
        from nstd.sync.github import issue_to_task

        issue = {
            "number": 456,
            "title": "Done task",
            "body": "",
            "state": "closed",
            "html_url": "https://github.com/cncf/staff/issues/456",
            "assignees": [{"login": "nate-double-u"}],
            "labels": [],
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        }

        task = issue_to_task(issue, "cncf/staff")
        assert task["state"] == "closed"

    def test_no_assignee_sets_none(self):
        """Issue with no assignees sets assignee to None."""
        from nstd.sync.github import issue_to_task

        issue = {
            "number": 789,
            "title": "Unassigned task",
            "body": "",
            "state": "open",
            "html_url": "https://github.com/cncf/staff/issues/789",
            "assignees": [],
            "labels": [],
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-15T00:00:00Z",
        }

        task = issue_to_task(issue, "cncf/staff")
        assert task["assignee"] is None


class TestShouldSyncIssue:
    """Test filtering logic for which issues to sync."""

    def test_syncs_issue_assigned_to_configured_user(self, github_config):
        """Issue assigned to configured user should be synced."""
        from nstd.sync.github import should_sync_issue

        issue = {
            "assignees": [{"login": "nate-double-u"}],
            "labels": [],
        }

        assert should_sync_issue(issue, github_config["github"]) is True

    def test_skips_issue_assigned_to_bot(self, github_config):
        """Issue assigned only to excluded bot account is not synced."""
        from nstd.sync.github import should_sync_issue

        issue = {
            "assignees": [{"login": "cncf-automation-bot"}],
            "labels": [],
        }

        assert should_sync_issue(issue, github_config["github"]) is False

    def test_syncs_issue_with_mixed_assignees_including_user(self, github_config):
        """Issue with both bot and real user assignees is synced."""
        from nstd.sync.github import should_sync_issue

        issue = {
            "assignees": [
                {"login": "cncf-automation-bot"},
                {"login": "nate-double-u"},
            ],
            "labels": [],
        }

        assert should_sync_issue(issue, github_config["github"]) is True

    def test_skips_issue_with_excluded_label(self, github_config):
        """Issue with an excluded label is not synced."""
        from nstd.sync.github import should_sync_issue

        github_config["github"].exclude_labels = ["wontfix"]

        issue = {
            "assignees": [{"login": "nate-double-u"}],
            "labels": [{"name": "wontfix"}],
        }

        assert should_sync_issue(issue, github_config["github"]) is False


class TestProjectFieldMapping:
    """Test GitHub Projects v2 field value mapping."""

    def test_maps_priority_field(self):
        """Projects v2 Priority field maps to task priority."""
        from nstd.sync.github import extract_project_fields

        field_values = [
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "field": {"name": "Priority"},
                "name": "High",
            },
        ]

        fields = extract_project_fields(field_values)
        assert fields["priority"] == "High"

    def test_maps_size_field(self):
        """Projects v2 Size field maps to task size."""
        from nstd.sync.github import extract_project_fields

        field_values = [
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "field": {"name": "Size"},
                "name": "M",
            },
        ]

        fields = extract_project_fields(field_values)
        assert fields["size"] == "M"

    def test_maps_date_fields(self):
        """Projects v2 date fields map to start_date and due_date."""
        from nstd.sync.github import extract_project_fields

        field_values = [
            {
                "__typename": "ProjectV2ItemFieldDateValue",
                "field": {"name": "Start Date"},
                "date": "2026-03-18",
            },
            {
                "__typename": "ProjectV2ItemFieldDateValue",
                "field": {"name": "Due Date"},
                "date": "2026-03-25",
            },
        ]

        fields = extract_project_fields(field_values)
        assert fields["start_date"] == "2026-03-18"
        assert fields["due_date"] == "2026-03-25"

    def test_ignores_unknown_fields(self):
        """Unknown field names are ignored."""
        from nstd.sync.github import extract_project_fields

        field_values = [
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "field": {"name": "Custom Thing"},
                "name": "Whatever",
            },
        ]

        fields = extract_project_fields(field_values)
        assert "Custom Thing" not in fields

    def test_empty_field_values(self):
        """Empty field values list returns empty dict."""
        from nstd.sync.github import extract_project_fields

        assert extract_project_fields([]) == {}
        assert extract_project_fields(None) == {}


class TestGitHubSync:
    """Test the full GitHub sync flow (REST + DB upsert)."""

    @patch("nstd.sync.github._fetch_issues_rest")
    def test_syncs_assigned_issues(self, mock_fetch, db, github_config):
        """Issues assigned to user are synced to DB."""
        from nstd.sync.github import sync_github

        mock_fetch.return_value = [
            {
                "number": 100,
                "title": "Task from GitHub",
                "body": "Description",
                "state": "open",
                "html_url": "https://github.com/cncf/staff/issues/100",
                "assignees": [{"login": "nate-double-u"}],
                "labels": [],
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            },
        ]

        stats = sync_github(
            db,
            github_config["user"],
            github_config["github"],
            token="ghp_fake",
        )

        assert stats["fetched"] >= 1
        row = db.execute(
            "SELECT * FROM tasks WHERE id = 'gh:cncf/staff:100'"
        ).fetchone()
        assert row is not None
        assert row["title"] == "Task from GitHub"

    @patch("nstd.sync.github._fetch_issues_rest")
    def test_skips_bot_assigned_issues(self, mock_fetch, db, github_config):
        """Issues assigned only to bots are not inserted into DB."""
        from nstd.sync.github import sync_github

        mock_fetch.return_value = [
            {
                "number": 200,
                "title": "Bot task",
                "body": "",
                "state": "open",
                "html_url": "https://github.com/cncf/staff/issues/200",
                "assignees": [{"login": "cncf-automation-bot"}],
                "labels": [],
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            },
        ]

        sync_github(db, github_config["user"], github_config["github"], token="ghp_fake")

        row = db.execute(
            "SELECT * FROM tasks WHERE id = 'gh:cncf/staff:200'"
        ).fetchone()
        assert row is None

    @patch("nstd.sync.github._fetch_issues_rest")
    def test_detects_jira_link_and_creates_task_link(self, mock_fetch, db, github_config):
        """Issue with Jira link in body creates a task_links entry."""
        from nstd.sync.github import sync_github

        mock_fetch.return_value = [
            {
                "number": 300,
                "title": "Linked to Jira",
                "body": "**Jira:** https://cncfservicedesk.atlassian.net/browse/CNCFSD-789",
                "state": "open",
                "html_url": "https://github.com/cncf/staff/issues/300",
                "assignees": [{"login": "nate-double-u"}],
                "labels": [],
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            },
        ]

        sync_github(db, github_config["user"], github_config["github"], token="ghp_fake")

        links = db.execute("SELECT * FROM task_links").fetchall()
        assert len(links) == 1
        link = dict(links[0])
        assert link["task_id_a"] == "gh:cncf/staff:300"
        assert link["task_id_b"] == "jira:CNCFSD-789"
        assert link["link_type"] == "mirrors"

    @patch("nstd.sync.github._fetch_issues_rest")
    def test_no_jira_link_creates_no_task_link(self, mock_fetch, db, github_config):
        """Issue without Jira link creates no task_links entry."""
        from nstd.sync.github import sync_github

        mock_fetch.return_value = [
            {
                "number": 400,
                "title": "No Jira link",
                "body": "Just a plain issue",
                "state": "open",
                "html_url": "https://github.com/cncf/staff/issues/400",
                "assignees": [{"login": "nate-double-u"}],
                "labels": [],
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-15T00:00:00Z",
            },
        ]

        sync_github(db, github_config["user"], github_config["github"], token="ghp_fake")

        links = db.execute("SELECT * FROM task_links").fetchall()
        assert len(links) == 0
