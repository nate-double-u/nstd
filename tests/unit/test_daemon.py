"""Tests for the sync daemon orchestration module.

Spec references:
  §6.1  — Sync loop (daemon mode)
  §15   — Error handling and resilience
  §16   — Privacy and security (log sanitization)
  §19   — Testing strategy

Test focus areas:
  - Task sync orchestration calls all sources in order
  - Error in one source does not abort others
  - Calendar poll orchestration
  - Log sanitization strips API tokens
  - Sync log entries created and completed
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from nstd.daemon import (
    LogSanitizer,
    run_calendar_poll,
    run_task_sync,
)
from nstd.db import (
    create_schema,
    get_connection,
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


# --- Task sync orchestration tests ---


class TestRunTaskSync:
    """Tests for run_task_sync orchestration."""

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_calls_all_sources(self, mock_gh, mock_jira, mock_asana, conn):
        """Task sync should call all three source sync functions."""
        mock_gh.return_value = []
        mock_jira.return_value = []
        mock_asana.return_value = []

        config = MagicMock()
        run_task_sync(conn, config)

        mock_gh.assert_called_once()
        mock_jira.assert_called_once()
        mock_asana.assert_called_once()

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_github_error_does_not_abort_jira_asana(self, mock_gh, mock_jira, mock_asana, conn):
        """§15: Failed sync of one source does not abort others."""
        mock_gh.side_effect = Exception("GitHub API rate limited")
        mock_jira.return_value = []
        mock_asana.return_value = []

        config = MagicMock()
        result = run_task_sync(conn, config)

        # Jira and Asana should still have been called
        mock_jira.assert_called_once()
        mock_asana.assert_called_once()

        # Result should contain the error
        assert len(result["errors"]) >= 1
        assert "GitHub" in result["errors"][0] or "github" in result["errors"][0].lower()

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_jira_error_does_not_abort_asana(self, mock_gh, mock_jira, mock_asana, conn):
        """Jira failure shouldn't prevent Asana sync."""
        mock_gh.return_value = []
        mock_jira.side_effect = Exception("Jira connection timeout")
        mock_asana.return_value = []

        config = MagicMock()
        result = run_task_sync(conn, config)

        mock_asana.assert_called_once()
        assert len(result["errors"]) >= 1

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_all_sources_fail_logs_all_errors(self, mock_gh, mock_jira, mock_asana, conn):
        """If all sources fail, all errors should be recorded."""
        mock_gh.side_effect = Exception("GitHub down")
        mock_jira.side_effect = Exception("Jira down")
        mock_asana.side_effect = Exception("Asana down")

        config = MagicMock()
        result = run_task_sync(conn, config)

        assert len(result["errors"]) == 3

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_creates_sync_log_entry(self, mock_gh, mock_jira, mock_asana, conn):
        """Should create a sync_log entry for each run."""
        mock_gh.return_value = [_make_task("gh:cncf/staff:1")]
        mock_jira.return_value = []
        mock_asana.return_value = []

        config = MagicMock()
        run_task_sync(conn, config)

        # Check sync_log was written
        log = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log is not None
        assert log["status"] in ("success", "error")

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_upserts_fetched_tasks(self, mock_gh, mock_jira, mock_asana, conn):
        """Tasks returned by sync functions should be upserted into DB."""
        task = _make_task("gh:cncf/staff:42")
        mock_gh.return_value = [task]
        mock_jira.return_value = []
        mock_asana.return_value = []

        config = MagicMock()
        run_task_sync(conn, config)

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", ("gh:cncf/staff:42",)).fetchone()
        assert row is not None
        assert row["title"] == "Test task"

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_sync_log_records_error_on_failure(self, mock_gh, mock_jira, mock_asana, conn):
        """Sync log should record errors when a source fails."""
        mock_gh.side_effect = Exception("Network error")
        mock_jira.return_value = []
        mock_asana.return_value = []

        config = MagicMock()
        run_task_sync(conn, config)

        log = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log["status"] == "error"


# --- Calendar poll orchestration tests ---


class TestRunCalendarPoll:
    """Tests for run_calendar_poll orchestration."""

    def test_calls_poll_calendars(self, conn):
        """Should invoke the poll_calendars function."""
        mock_service = MagicMock()
        config = MagicMock()
        config.google_calendar.calendar_id = "cal_nstd"
        config.google_calendar.observe_calendars = ["primary"]

        mock_poll = MagicMock(
            return_value={
                "nstd_events": [],
                "observed_events": [],
                "orphaned_blocks": [],
                "past_blocks_marked": 0,
            }
        )
        run_calendar_poll(conn, config, mock_service, poll_fn=mock_poll)

        mock_poll.assert_called_once()

    def test_calendar_poll_error_logged(self, conn):
        """§15: Calendar poll failure is logged, does not crash."""
        mock_service = MagicMock()
        config = MagicMock()
        config.google_calendar.calendar_id = "cal_nstd"
        config.google_calendar.observe_calendars = []

        mock_poll = MagicMock(side_effect=Exception("Calendar API error"))
        result = run_calendar_poll(conn, config, mock_service, poll_fn=mock_poll)

        assert len(result["errors"]) >= 1

    def test_returns_poll_result(self, conn):
        """Should return the poll result dict."""
        mock_service = MagicMock()
        config = MagicMock()
        config.google_calendar.calendar_id = "cal_nstd"
        config.google_calendar.observe_calendars = []

        expected = {
            "nstd_events": [{"id": "e1"}],
            "observed_events": [],
            "orphaned_blocks": [],
            "past_blocks_marked": 2,
        }

        mock_poll = MagicMock(return_value=expected)
        result = run_calendar_poll(conn, config, mock_service, poll_fn=mock_poll)

        assert result["past_blocks_marked"] == 2
        assert len(result["nstd_events"]) == 1


# --- Log sanitization tests ---


class TestLogSanitizer:
    """§16: API tokens must never appear in log output."""

    def test_strips_github_token(self):
        """GitHub PAT should be redacted from log messages."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Using token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn for API call",
            args=(),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert "ghp_ABCDEF" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_strips_bearer_token(self):
        """Bearer token values should be redacted."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.xxx",
            args=(),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert "eyJhbGci" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_strips_generic_token_pattern(self):
        """Generic token= patterns should be redacted."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="token=mysecrettoken123 connecting to server",
            args=(),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert "mysecrettoken123" not in record.msg

    def test_strips_api_key_pattern(self):
        """api_key= patterns should be redacted."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="api_key=AKIAIOSFODNN7EXAMPLE sending request",
            args=(),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert "AKIAIOSFODNN7EXAMPLE" not in record.msg

    def test_preserves_non_sensitive_messages(self):
        """Non-sensitive log messages should pass through unchanged."""
        sanitizer = LogSanitizer()
        msg = "Synced 42 tasks from GitHub in 1.3s"
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert record.msg == msg

    def test_filter_always_returns_true(self):
        """Filter should always return True (message is kept, just sanitized)."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="ghp_secrettoken",
            args=(),
            exc_info=None,
        )
        result = sanitizer.filter(record)
        assert result is True
