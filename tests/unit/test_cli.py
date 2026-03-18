"""Tests for the nstd CLI module.

Spec references:
  §10 — CLI Commands
  §11 — Setup wizard (nstd setup)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from nstd.cli import cli


@pytest.fixture()
def runner():
    """Click CLI test runner."""
    return CliRunner()


# --- Root command tests ---


class TestRootCommand:
    """The root `nstd` command should launch the TUI by default."""

    def test_help_flag(self, runner):
        """--help should show usage info and exit 0."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "nstd" in result.output.lower()

    def test_version_flag(self, runner):
        """--version should show version and exit 0."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "nstd" in result.output.lower() or "0." in result.output


# --- Setup command tests ---


class TestSetupCommand:
    """nstd setup — interactive first-run wizard."""

    def test_setup_appears_in_help(self, runner):
        """Setup command should be listed in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "setup" in result.output

    def test_setup_help(self, runner):
        """nstd setup --help should work."""
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "setup" in result.output.lower()


# --- Sync command tests ---


class TestSyncCommand:
    """nstd sync — run sync cycle."""

    def test_sync_appears_in_help(self, runner):
        """Sync command should be listed in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "sync" in result.output

    def test_sync_help(self, runner):
        """nstd sync --help should work."""
        result = runner.invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0

    def test_sync_has_source_option(self, runner):
        """nstd sync should accept --source option."""
        result = runner.invoke(cli, ["sync", "--help"])
        assert "--source" in result.output

    def test_sync_has_daemon_flag(self, runner):
        """nstd sync should accept --daemon flag."""
        result = runner.invoke(cli, ["sync", "--help"])
        assert "--daemon" in result.output


# --- Status command tests ---


class TestStatusCommand:
    """nstd status — print last sync status."""

    def test_status_appears_in_help(self, runner):
        """Status command should be listed in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "status" in result.output

    def test_status_help(self, runner):
        """nstd status --help should work."""
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0

    @patch("nstd.cli._get_db_path")
    def test_status_no_sync_log(self, mock_db_path, runner, tmp_path):
        """Status with empty DB should report 'never synced'."""
        db_file = tmp_path / "nstd.db"
        mock_db_path.return_value = str(db_file)

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "never" in result.output.lower() or "no sync" in result.output.lower()

    @patch("nstd.cli._get_db_path")
    def test_status_with_sync_entry(self, mock_db_path, runner, tmp_path):
        """Status with existing sync log should print last sync info."""
        from nstd.db import complete_sync_log, create_schema, get_connection, start_sync_log

        db_file = tmp_path / "nstd.db"
        mock_db_path.return_value = str(db_file)

        conn = get_connection(str(db_file))
        create_schema(conn)
        log_id = start_sync_log(conn, source="all")
        complete_sync_log(conn, log_id, records_fetched=10, records_updated=5)
        conn.close()

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Last sync" in result.output
        assert "Fetched: 10" in result.output
        assert "Updated: 5" in result.output

    @patch("nstd.cli._get_db_path")
    def test_status_missing_dir(self, mock_db_path, runner, tmp_path):
        """Status with missing config dir should report 'never synced'."""
        mock_db_path.return_value = str(tmp_path / "nonexistent" / "nstd.db")

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "never" in result.output.lower() or "setup" in result.output.lower()


# --- Config command tests ---


class TestConfigCommand:
    """nstd config — open config in editor."""

    def test_config_appears_in_help(self, runner):
        """Config command should be listed in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "config" in result.output

    def test_config_help(self, runner):
        """nstd config --help should work."""
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0


# --- Logs command tests ---


class TestLogsCommand:
    """nstd logs — tail the sync log."""

    def test_logs_appears_in_help(self, runner):
        """Logs command should be listed in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "logs" in result.output

    def test_logs_help(self, runner):
        """nstd logs --help should work."""
        result = runner.invoke(cli, ["logs", "--help"])
        assert result.exit_code == 0

    @patch("nstd.cli._get_db_path")
    def test_logs_empty_db(self, mock_db_path, runner, tmp_path):
        """Logs with empty DB should report 'no entries'."""
        db_file = tmp_path / "nstd.db"
        mock_db_path.return_value = str(db_file)

        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    @patch("nstd.cli._get_db_path")
    def test_logs_with_entries(self, mock_db_path, runner, tmp_path):
        """Logs with sync entries should print them."""
        from nstd.db import complete_sync_log, create_schema, get_connection, start_sync_log

        db_file = tmp_path / "nstd.db"
        mock_db_path.return_value = str(db_file)

        conn = get_connection(str(db_file))
        create_schema(conn)
        log_id = start_sync_log(conn, source="all")
        complete_sync_log(conn, log_id, records_fetched=15, records_updated=10)
        conn.close()

        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert "fetched=15" in result.output
        assert "updated=10" in result.output

    @patch("nstd.cli._get_db_path")
    def test_logs_null_source(self, mock_db_path, runner, tmp_path):
        """Logs with NULL source should not crash."""
        from nstd.db import create_schema, get_connection

        db_file = tmp_path / "nstd.db"
        mock_db_path.return_value = str(db_file)

        conn = get_connection(str(db_file))
        create_schema(conn)
        # Insert with NULL source manually
        conn.execute(
            "INSERT INTO sync_log (source, started_at, status, records_fetched, records_updated) "
            "VALUES (NULL, '2026-03-18T12:00:00Z', 'success', 5, 3)"
        )
        conn.commit()
        conn.close()

        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert "all" in result.output  # NULL source should display as "all"

    @patch("nstd.cli._get_db_path")
    def test_logs_missing_dir(self, mock_db_path, runner, tmp_path):
        """Logs with missing config dir should report 'no entries'."""
        mock_db_path.return_value = str(tmp_path / "nonexistent" / "nstd.db")

        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()


# --- Block command tests ---


class TestBlockCommand:
    """nstd block <task-id> — scheduling dialog."""

    def test_block_appears_in_help(self, runner):
        """Block command should be listed in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "block" in result.output

    def test_block_help(self, runner):
        """nstd block --help should work."""
        result = runner.invoke(cli, ["block", "--help"])
        assert result.exit_code == 0

    def test_block_requires_task_id(self, runner):
        """nstd block without task-id should fail."""
        result = runner.invoke(cli, ["block"])
        assert result.exit_code != 0
