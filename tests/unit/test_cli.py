"""Tests for the nstd CLI module.

Spec references:
  §10 — CLI Commands
  §11 — Setup wizard (nstd setup)
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from unittest.mock import MagicMock, patch

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

    def test_no_subcommand_launches_tui(self, runner):
        """Running nstd with no subcommand should indicate TUI launch."""
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        assert "TUI" in result.output


class TestGetVersion:
    """_get_version should return version from package metadata."""

    def test_returns_version_string(self):
        """Should return a version string."""
        from nstd.cli import _get_version

        ver = _get_version()
        assert isinstance(ver, str)
        assert len(ver) > 0

    @patch("nstd.cli.version", side_effect=PackageNotFoundError)
    def test_fallback_on_missing_package(self, _mock_version):
        """Should return dev version when package is not installed."""
        from nstd.cli import _get_version

        assert _get_version() == "0.1.0-dev"


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

    def test_setup_runs(self, runner):
        """nstd setup should output setup wizard message."""
        result = runner.invoke(cli, ["setup"])
        assert result.exit_code == 0
        assert "setup wizard" in result.output.lower()


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

    def test_sync_full(self, runner):
        """nstd sync with no options should run full sync."""
        with (
            patch("nstd.config.load_config") as mock_config,
            patch("nstd.daemon.run_task_sync") as mock_sync,
            patch("nstd.db.get_connection") as mock_conn,
            patch("nstd.db.create_schema"),
        ):
            mock_sync.return_value = {
                "total_fetched": 10,
                "total_updated": 5,
                "errors": [],
                "log_id": 1,
            }
            mock_conn.return_value = mock_config  # just needs .close()
            result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        assert "full sync" in result.output.lower()
        assert "sync complete" in result.output.lower()

    def test_sync_with_source(self, runner):
        """nstd sync --source github should sync only that source."""
        with (
            patch("nstd.config.load_config"),
            patch("nstd.daemon.run_task_sync") as mock_sync,
            patch("nstd.db.get_connection") as mock_conn,
            patch("nstd.db.create_schema"),
        ):
            mock_sync.return_value = {
                "total_fetched": 3,
                "total_updated": 3,
                "errors": [],
                "log_id": 1,
            }
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            result = runner.invoke(cli, ["sync", "--source", "github"])
        assert result.exit_code == 0
        assert "github" in result.output.lower()
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        assert call_kwargs[1]["source"] == "github"

    def test_sync_daemon_mode(self, runner):
        """nstd sync --daemon should start daemon mode."""
        result = runner.invoke(cli, ["sync", "--daemon"])
        assert result.exit_code == 0
        assert "daemon" in result.output.lower()

    def test_sync_has_dry_run_flag(self, runner):
        """nstd sync should accept --dry-run flag."""
        result = runner.invoke(cli, ["sync", "--help"])
        assert "--dry-run" in result.output

    def test_sync_dry_run_full(self, runner):
        """nstd sync --dry-run should run sync with dry_run=True and print summary."""
        mock_conn = MagicMock()
        with (
            patch("nstd.config.load_config"),
            patch("nstd.daemon.run_task_sync") as mock_sync,
            patch("nstd.cli._safe_get_readonly_connection", return_value=mock_conn),
        ):
            mock_sync.return_value = {
                "total_fetched": 14,
                "total_updated": 14,
                "links_skipped": 3,
                "writebacks_skipped": 1,
                "calendar_writes_skipped": 2,
                "errors": [],
                "log_id": None,
            }
            result = runner.invoke(cli, ["sync", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()
        assert "no writes" in result.output.lower()
        assert "Dry-run summary" in result.output
        assert "Tasks fetched:" in result.output
        assert "Links skipped:" in result.output
        assert "Write-backs skipped:" in result.output
        assert "Calendar writes skipped:" in result.output
        mock_sync.assert_called_once()
        assert mock_sync.call_args[1]["dry_run"] is True

    def test_sync_dry_run_with_source(self, runner):
        """nstd sync --dry-run --source github should pass both flags through."""
        mock_conn = MagicMock()
        with (
            patch("nstd.config.load_config"),
            patch("nstd.daemon.run_task_sync") as mock_sync,
            patch("nstd.cli._safe_get_readonly_connection", return_value=mock_conn),
        ):
            mock_sync.return_value = {
                "total_fetched": 5,
                "total_updated": 5,
                "errors": [],
                "log_id": None,
            }
            result = runner.invoke(cli, ["sync", "--dry-run", "--source", "github"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()
        assert "github" in result.output.lower()
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["dry_run"] is True
        assert call_kwargs["source"] == "github"

    def test_sync_daemon_dry_run_rejected(self, runner):
        """nstd sync --daemon --dry-run must be rejected with an error."""
        result = runner.invoke(cli, ["sync", "--daemon", "--dry-run"])
        assert result.exit_code != 0
        assert "dry-run" in result.output.lower()
        assert "daemon" in result.output.lower()

    def test_sync_config_not_found(self, runner):
        """nstd sync should fail gracefully when config is missing."""
        from nstd.config import ConfigurationError

        with patch("nstd.config.load_config", side_effect=ConfigurationError("not found")):
            result = runner.invoke(cli, ["sync"])
        assert result.exit_code != 0
        assert "configuration error" in result.output.lower()

    def test_sync_dry_run_no_db(self, runner):
        """nstd sync --dry-run should fail gracefully when DB doesn't exist."""
        with (
            patch("nstd.config.load_config"),
            patch("nstd.cli._safe_get_readonly_connection", return_value=None),
        ):
            result = runner.invoke(cli, ["sync", "--dry-run"])
        assert result.exit_code != 0
        assert "not initialized" in result.output.lower()

    def test_sync_reports_errors(self, runner):
        """nstd sync should print errors from sync sources."""
        with (
            patch("nstd.config.load_config"),
            patch("nstd.daemon.run_task_sync") as mock_sync,
            patch("nstd.db.get_connection") as mock_conn,
            patch("nstd.db.create_schema"),
        ):
            mock_sync.return_value = {
                "total_fetched": 5,
                "total_updated": 3,
                "errors": ["GitHub: rate limited"],
                "log_id": 1,
            }
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            result = runner.invoke(cli, ["sync"])
        assert result.exit_code == 0
        assert "rate limited" in result.output


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
        log_id = start_sync_log(conn, source=None)
        complete_sync_log(conn, log_id, records_fetched=10, records_updated=5)
        conn.close()

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Last sync" in result.output
        assert "Fetched: 10" in result.output
        assert "Updated: 5" in result.output

    @patch("nstd.cli._get_db_path")
    def test_status_db_exists_no_schema(self, mock_db_path, runner, tmp_path):
        """Status with DB file but no schema should report 'never synced'."""
        import sqlite3

        db_file = tmp_path / "nstd.db"
        # Create an empty DB file (no tables)
        sqlite3.connect(str(db_file)).close()
        mock_db_path.return_value = str(db_file)

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "never" in result.output.lower() or "no sync" in result.output.lower()

    @patch("nstd.cli._get_db_path")
    def test_status_missing_dir(self, mock_db_path, runner, tmp_path):
        """Status with missing config dir should report 'never synced'."""
        mock_db_path.return_value = str(tmp_path / "nonexistent" / "nstd.db")

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "never" in result.output.lower() or "setup" in result.output.lower()

    @patch("nstd.cli._get_db_path")
    def test_status_corrupted_db(self, mock_db_path, runner, tmp_path):
        """Status with corrupted DB file should handle gracefully."""
        db_file = tmp_path / "nstd.db"
        db_file.write_text("this is not a sqlite database")
        mock_db_path.return_value = str(db_file)

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "never" in result.output.lower() or "no sync" in result.output.lower()


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

    def test_config_missing_file(self, runner, tmp_path):
        """Config command reports missing config file."""
        fake_dir = tmp_path / "nstd"
        fake_dir.mkdir()
        with patch("nstd.cli._DEFAULT_CONFIG_DIR", fake_dir):
            result = runner.invoke(cli, ["config"])
        assert "Config file not found" in result.output
        assert "nstd setup" in result.output

    def test_config_opens_editor(self, runner, tmp_path):
        """Config command opens editor on existing config file."""
        fake_dir = tmp_path / "nstd"
        fake_dir.mkdir()
        config_file = fake_dir / "config.toml"
        config_file.write_text("[general]\n")
        with (
            patch("nstd.cli._DEFAULT_CONFIG_DIR", fake_dir),
            patch("subprocess.run", return_value=type("R", (), {"returncode": 0})()) as mock_run,
            patch.dict("os.environ", {"EDITOR": "nano"}),
        ):
            result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        assert str(config_file) in mock_run.call_args[0][0]

    def test_config_editor_not_found(self, runner, tmp_path):
        """Config command handles missing editor binary."""
        fake_dir = tmp_path / "nstd"
        fake_dir.mkdir()
        config_file = fake_dir / "config.toml"
        config_file.write_text("[general]\n")
        with (
            patch("nstd.cli._DEFAULT_CONFIG_DIR", fake_dir),
            patch("subprocess.run", side_effect=FileNotFoundError),
            patch.dict("os.environ", {"EDITOR": "nonexistent-editor"}),
        ):
            result = runner.invoke(cli, ["config"])
        assert result.exit_code != 0
        assert "Editor not found" in result.output

    def test_config_editor_nonzero_exit(self, runner, tmp_path):
        """Config command reports editor failure."""
        fake_dir = tmp_path / "nstd"
        fake_dir.mkdir()
        config_file = fake_dir / "config.toml"
        config_file.write_text("[general]\n")
        with (
            patch("nstd.cli._DEFAULT_CONFIG_DIR", fake_dir),
            patch("subprocess.run", return_value=type("R", (), {"returncode": 1})()),
            patch.dict("os.environ", {"EDITOR": "vim"}),
        ):
            result = runner.invoke(cli, ["config"])
        assert result.exit_code != 0
        assert "Editor exited with code 1" in result.output

    def test_config_honors_visual_over_editor(self, runner, tmp_path):
        """Config command prefers $VISUAL over $EDITOR."""
        fake_dir = tmp_path / "nstd"
        fake_dir.mkdir()
        config_file = fake_dir / "config.toml"
        config_file.write_text("[general]\n")
        with (
            patch("nstd.cli._DEFAULT_CONFIG_DIR", fake_dir),
            patch("subprocess.run", return_value=type("R", (), {"returncode": 0})()) as mock_run,
            patch.dict("os.environ", {"VISUAL": "code -w", "EDITOR": "vim"}),
        ):
            result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        cmd_args = mock_run.call_args[0][0]
        assert cmd_args[0] == "code"
        assert "-w" in cmd_args


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
        log_id = start_sync_log(conn, source=None)
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

    @patch("nstd.cli._get_db_path")
    def test_logs_db_exists_no_schema(self, mock_db_path, runner, tmp_path):
        """Logs with DB file but no schema should report 'no entries'."""
        import sqlite3

        db_file = tmp_path / "nstd.db"
        sqlite3.connect(str(db_file)).close()
        mock_db_path.return_value = str(db_file)

        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    @patch("nstd.cli._get_db_path")
    def test_logs_corrupted_db(self, mock_db_path, runner, tmp_path):
        """Logs with corrupted DB file should handle gracefully."""
        db_file = tmp_path / "nstd.db"
        db_file.write_text("this is not a sqlite database")
        mock_db_path.return_value = str(db_file)

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

    def test_block_with_task_id(self, runner):
        """nstd block with task-id should show scheduling dialog message."""
        result = runner.invoke(cli, ["block", "gh:cncf/staff:42"])
        assert result.exit_code == 0
        assert "gh:cncf/staff:42" in result.output
