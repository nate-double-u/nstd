"""Tests for the sync daemon orchestration module.

Spec references:
  §6.1  — Sync loop (daemon mode)
  §15   — Error handling and resilience
  §16   — Privacy and security (log sanitization)
  §19   — Testing strategy

Test focus areas:
  - Task sync orchestration calls all sources in order
  - Error in one source does not abort others
  - Sync functions receive correct signatures (conn, config)
  - Stats dicts are accumulated correctly
  - Calendar poll orchestration
  - Log sanitization strips API tokens from msg, args, and exc_text
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


# --- Task sync orchestration tests ---


class TestRunTaskSync:
    """Tests for run_task_sync orchestration."""

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_calls_all_sources(self, mock_gh, mock_jira, mock_asana, conn):
        """Task sync should call all three source sync functions."""
        mock_gh.return_value = {"fetched": 0, "updated": 0}
        mock_jira.return_value = {"fetched": 0, "updated": 0, "errors": []}
        mock_asana.return_value = {"fetched": 0, "updated": 0, "errors": []}

        config = MagicMock()
        run_task_sync(conn, config)

        mock_gh.assert_called_once_with(conn, config)
        mock_jira.assert_called_once_with(conn, config)
        mock_asana.assert_called_once_with(conn, config)

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_github_error_does_not_abort_jira_asana(self, mock_gh, mock_jira, mock_asana, conn):
        """§15: Failed sync of one source does not abort others."""
        mock_gh.side_effect = Exception("GitHub API rate limited")
        mock_jira.return_value = {"fetched": 5, "updated": 3, "errors": []}
        mock_asana.return_value = {"fetched": 2, "updated": 1, "errors": []}

        config = MagicMock()
        result = run_task_sync(conn, config)

        mock_jira.assert_called_once()
        mock_asana.assert_called_once()

        assert len(result["errors"]) >= 1
        assert "GitHub" in result["errors"][0]
        assert "GitHub API rate limited" in result["errors"][0]

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_jira_error_does_not_abort_asana(self, mock_gh, mock_jira, mock_asana, conn):
        """Jira failure shouldn't prevent Asana sync."""
        mock_gh.return_value = {"fetched": 10, "updated": 8}
        mock_jira.side_effect = Exception("Jira connection timeout")
        mock_asana.return_value = {"fetched": 2, "updated": 1, "errors": []}

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
        mock_gh.return_value = {"fetched": 5, "updated": 3}
        mock_jira.return_value = {"fetched": 2, "updated": 2, "errors": []}
        mock_asana.return_value = {"fetched": 1, "updated": 1, "errors": []}

        config = MagicMock()
        run_task_sync(conn, config)

        log = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log is not None
        assert log["status"] == "success"

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_sync_log_source_is_null_for_full_sync(self, mock_gh, mock_jira, mock_asana, conn):
        """Full sync should log source=NULL per spec (NULL = full sync)."""
        mock_gh.return_value = {"fetched": 1, "updated": 1}
        mock_jira.return_value = {"fetched": 0, "updated": 0, "errors": []}
        mock_asana.return_value = {"fetched": 0, "updated": 0, "errors": []}

        config = MagicMock()
        run_task_sync(conn, config)

        log = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log["source"] is None

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_aggregates_per_source_errors(self, mock_gh, mock_jira, mock_asana, conn):
        """Per-source errors from stats dicts should be aggregated."""
        mock_gh.return_value = {"fetched": 5, "updated": 3, "errors": ["rate limited on repo X"]}
        mock_jira.return_value = {"fetched": 2, "updated": 2, "errors": []}
        mock_asana.return_value = {"fetched": 1, "updated": 0, "errors": ["project not found"]}

        config = MagicMock()
        result = run_task_sync(conn, config)

        assert len(result["errors"]) == 2
        assert "GitHub: rate limited on repo X" in result["errors"][0]
        assert "Asana: project not found" in result["errors"][1]

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_accumulates_stats_correctly(self, mock_gh, mock_jira, mock_asana, conn):
        """Stats from all sources should be accumulated."""
        mock_gh.return_value = {"fetched": 10, "updated": 8}
        mock_jira.return_value = {"fetched": 5, "updated": 3, "errors": []}
        mock_asana.return_value = {"fetched": 2, "updated": 1, "errors": []}

        config = MagicMock()
        result = run_task_sync(conn, config)

        assert result["total_fetched"] == 17
        assert result["total_updated"] == 12
        assert result["errors"] == []

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_sync_log_records_counts(self, mock_gh, mock_jira, mock_asana, conn):
        """Sync log should record accurate fetched/updated counts."""
        mock_gh.return_value = {"fetched": 10, "updated": 8}
        mock_jira.return_value = {"fetched": 5, "updated": 3, "errors": []}
        mock_asana.return_value = {"fetched": 2, "updated": 1, "errors": []}

        config = MagicMock()
        run_task_sync(conn, config)

        log = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log["records_fetched"] == 17
        assert log["records_updated"] == 12

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_sync_log_records_error_on_failure(self, mock_gh, mock_jira, mock_asana, conn):
        """Sync log should record errors when a source fails."""
        mock_gh.side_effect = Exception("Network error")
        mock_jira.return_value = {"fetched": 0, "updated": 0, "errors": []}
        mock_asana.return_value = {"fetched": 0, "updated": 0, "errors": []}

        config = MagicMock()
        run_task_sync(conn, config)

        log = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log["status"] == "error"

    @patch("nstd.daemon._sync_asana")
    @patch("nstd.daemon._sync_jira")
    @patch("nstd.daemon._sync_github")
    def test_partial_success_records_error(self, mock_gh, mock_jira, mock_asana, conn):
        """If some sources succeed and some fail, log should record error."""
        mock_gh.return_value = {"fetched": 10, "updated": 8}
        mock_jira.side_effect = Exception("Jira timeout")
        mock_asana.return_value = {"fetched": 2, "updated": 1, "errors": []}

        config = MagicMock()
        result = run_task_sync(conn, config)

        # Partial results should still be counted
        assert result["total_fetched"] == 12
        assert result["total_updated"] == 9
        assert len(result["errors"]) == 1

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

    def test_sanitizes_string_args(self):
        """Secrets in record.args (e.g. logger.info('token=%s', token)) should be redacted."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="token=%s",
            args=("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn",),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert "ghp_ABCDEF" not in str(record.args)
        assert "[REDACTED]" in record.args[0]

    def test_sanitizes_dict_args(self):
        """Secrets in dict-style args should be redacted."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="token=%(tok)s",
            args=None,
            exc_info=None,
        )
        # Set dict args after init to avoid LogRecord's tuple-based validation
        record.args = {"tok": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"}
        sanitizer.filter(record)
        assert "ghp_ABCDEF" not in record.args["tok"]
        assert "[REDACTED]" in record.args["tok"]

    def test_sanitizes_exc_text(self):
        """Exception text should be sanitized."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )
        record.exc_text = "Exception: token=mysecrettoken123 failed"
        sanitizer.filter(record)
        assert "mysecrettoken123" not in record.exc_text
        assert "[REDACTED]" in record.exc_text

    def test_non_string_args_preserved(self):
        """Non-string args should not be modified."""
        sanitizer = LogSanitizer()
        record = logging.LogRecord(
            name="nstd",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Synced %d tasks in %0.1fs",
            args=(42, 1.3),
            exc_info=None,
        )
        sanitizer.filter(record)
        assert record.args == (42, 1.3)


class TestSyncFunctionWiring:
    """Tests that _sync_github, _sync_jira, _sync_asana correctly wire up to sync modules."""

    @patch("nstd.daemon.get_credential", return_value="fake-token")
    @patch("nstd.sync.github.sync_github", return_value={"fetched": 5, "updated": 3})
    def test_sync_github_calls_sync_function(self, mock_sync, mock_cred, conn):
        """_sync_github should call sync_github with correct args."""
        from nstd.daemon import _sync_github

        config = MagicMock()
        result = _sync_github(conn, config)
        mock_sync.assert_called_once_with(conn, config.user, config.github, "fake-token")
        assert result["fetched"] == 5

    @patch("nstd.daemon.get_credential", return_value="fake-token")
    @patch("nstd.sync.jira.sync_jira", return_value={"fetched": 3, "updated": 1, "errors": []})
    def test_sync_jira_calls_sync_function(self, mock_sync, mock_cred, conn):
        """_sync_jira should call sync_jira with correct args."""
        from nstd.daemon import _sync_jira

        config = MagicMock()
        result = _sync_jira(conn, config)
        mock_sync.assert_called_once_with(conn, config.jira, "fake-token")
        assert result["fetched"] == 3

    @patch("nstd.daemon.get_credential", return_value="fake-token")
    @patch("nstd.sync.asana.sync_asana", return_value={"fetched": 2, "updated": 1, "errors": []})
    def test_sync_asana_calls_sync_function(self, mock_sync, mock_cred, conn):
        """_sync_asana should call sync_asana with correct args."""
        from nstd.daemon import _sync_asana

        config = MagicMock()
        result = _sync_asana(conn, config)
        mock_cred.assert_called_once_with("nstd-asana", config.user.github_username)
        mock_sync.assert_called_once_with(conn, config.asana, "fake-token")
        assert result["fetched"] == 2

    @patch("nstd.calendar.gcal.poll_calendars")
    def test_calendar_poll_default_poll_fn(self, mock_poll, conn):
        """run_calendar_poll with no poll_fn should use poll_calendars."""
        mock_poll.return_value = {"events": 5}
        config = MagicMock()
        service = MagicMock()

        run_calendar_poll(conn, config, service)
        mock_poll.assert_called_once_with(
            conn,
            service=service,
            nstd_calendar_id=config.google_calendar.calendar_id,
            observe_calendar_ids=config.google_calendar.observe_calendars,
        )
