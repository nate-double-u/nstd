"""Tests for nstd.config — written BEFORE implementation (TDD)."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfigLoading:
    """Test config.toml loading and validation."""

    def test_loads_valid_config(self, tmp_path):
        """A well-formed config.toml with all required fields loads successfully."""
        from nstd.config import load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"

            [github]
            repos = ["cncf/staff"]
            projects = ["cncf/27"]
            exclude_labels = []
            exclude_assignees = ["cncf-automation-bot"]

            [jira]
            server_url = "https://cncfservicedesk.atlassian.net"
            username = "nate@linuxfoundation.org"
            projects = ["CNCFSD"]
            assigned_only = true
            start_date_field = ""

            [asana]
            workspace_gid = "12345"
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = "abc123"
            observe_calendars = ["primary"]
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        cfg = load_config(config_dir=tmp_path)
        assert cfg.user.github_username == "nate-double-u"
        assert cfg.user.timezone == "America/Los_Angeles"
        assert cfg.github.repos == ["cncf/staff"]
        assert cfg.github.exclude_assignees == ["cncf-automation-bot"]
        assert cfg.jira.server_url == "https://cncfservicedesk.atlassian.net"
        assert cfg.asana.workspace_gid == "12345"
        assert cfg.google_calendar.calendar_name == "NSTD Planning"
        assert cfg.sync.interval_minutes == 15
        assert cfg.scheduling.preferred_session_hours == 2.0
        assert cfg.ai.enabled is False
        assert cfg.conflict_resolution.mode == "always_ask"

    def test_rejects_secrets_in_config(self, tmp_path):
        """Config containing a token/password/secret value raises ConfigurationError."""
        from nstd.config import ConfigurationError, load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"
            token = "ghp_secret123"

            [github]
            repos = ["cncf/staff"]
            projects = []
            exclude_labels = []
            exclude_assignees = []

            [jira]
            server_url = "https://example.atlassian.net"
            username = "user@example.com"
            projects = ["TEST"]
            assigned_only = true
            start_date_field = ""

            [asana]
            workspace_gid = ""
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = ""
            observe_calendars = []
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        with pytest.raises(ConfigurationError, match="secret"):
            load_config(config_dir=tmp_path)

    def test_rejects_password_key_in_config(self, tmp_path):
        """Config containing a 'password' key raises ConfigurationError."""
        from nstd.config import ConfigurationError, load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"

            [github]
            repos = ["cncf/staff"]
            projects = []
            exclude_labels = []
            exclude_assignees = []

            [jira]
            server_url = "https://example.atlassian.net"
            username = "user@example.com"
            password = "secret123"
            projects = ["TEST"]
            assigned_only = true
            start_date_field = ""

            [asana]
            workspace_gid = ""
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = ""
            observe_calendars = []
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        with pytest.raises(ConfigurationError, match="secret"):
            load_config(config_dir=tmp_path)

    def test_rejects_api_key_in_config(self, tmp_path):
        """Config containing an 'api_key' key raises ConfigurationError."""
        from nstd.config import ConfigurationError, load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"

            [github]
            repos = ["cncf/staff"]
            projects = []
            exclude_labels = []
            exclude_assignees = []
            api_key = "ghp_abc123"

            [jira]
            server_url = "https://example.atlassian.net"
            username = "user@example.com"
            projects = ["TEST"]
            assigned_only = true
            start_date_field = ""

            [asana]
            workspace_gid = ""
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = ""
            observe_calendars = []
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        with pytest.raises(ConfigurationError, match="secret"):
            load_config(config_dir=tmp_path)

    def test_missing_config_file_raises_error(self, tmp_path):
        """Missing config.toml raises ConfigurationError."""
        from nstd.config import ConfigurationError, load_config

        with pytest.raises(ConfigurationError, match="not found"):
            load_config(config_dir=tmp_path)

    def test_missing_required_section_raises_error(self, tmp_path):
        """Config missing a required section raises ConfigurationError."""
        from nstd.config import ConfigurationError, load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"
        """))

        with pytest.raises(ConfigurationError):
            load_config(config_dir=tmp_path)

    def test_defaults_applied_for_optional_fields(self, tmp_path):
        """Optional fields get sensible defaults when not specified."""
        from nstd.config import load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"

            [github]
            repos = ["cncf/staff"]
            projects = []
            exclude_labels = []
            exclude_assignees = []

            [jira]
            server_url = "https://example.atlassian.net"
            username = "user@example.com"
            projects = ["TEST"]
            assigned_only = true
            start_date_field = ""

            [asana]
            workspace_gid = ""
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = ""
            observe_calendars = []
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        cfg = load_config(config_dir=tmp_path)
        assert cfg.scheduling.min_block_hours == 0.25
        assert cfg.scheduling.max_block_hours == 4.0
        assert cfg.tui.theme == "dark"

    def test_default_config_dir_uses_home(self):
        """When config_dir is None, uses ~/.config/nstd/."""
        from nstd.config import ConfigurationError, load_config

        with pytest.raises(ConfigurationError):
            load_config(config_dir=None)

    def test_invalid_field_type_raises_error(self, tmp_path):
        """Config with unexpected keyword raises ConfigurationError."""
        from nstd.config import ConfigurationError, load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"

            [github]
            repos = ["cncf/staff"]
            projects = []
            exclude_labels = []
            exclude_assignees = []

            [jira]
            server_url = "https://example.atlassian.net"
            username = "user@example.com"
            projects = ["TEST"]
            assigned_only = true
            start_date_field = ""
            unexpected_kwarg = "boom"

            [asana]
            workspace_gid = ""
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = ""
            observe_calendars = []
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            load_config(config_dir=tmp_path)


class TestConfigWorkingHours:
    """Test working hours configuration."""

    def test_working_hours_defaults(self, tmp_path):
        """Default working hours are 09:00 - 17:00."""
        from nstd.config import load_config

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [user]
            github_username = "nate-double-u"
            timezone = "America/Los_Angeles"

            [github]
            repos = ["cncf/staff"]
            projects = []
            exclude_labels = []
            exclude_assignees = []

            [jira]
            server_url = "https://example.atlassian.net"
            username = "user@example.com"
            projects = ["TEST"]
            assigned_only = true
            start_date_field = ""

            [asana]
            workspace_gid = ""
            assigned_only = true
            project_gids = []

            [google_calendar]
            calendar_name = "NSTD Planning"
            calendar_id = ""
            observe_calendars = []
            calendar_poll_interval_minutes = 10
            default_duration_minutes = 60

            [sync]
            interval_minutes = 15
            lookback_days = 7

            [scheduling]
            max_hours_per_day = 8
            preferred_session_hours = 2.0
            min_block_hours = 0.25
            max_block_hours = 4.0

            [ai]
            enabled = false
            model = "deepseek-r1:latest"
            ollama_host = "http://localhost:11434"

            [conflict_resolution]
            mode = "always_ask"

            [tui]
            theme = "dark"
        """))

        cfg = load_config(config_dir=tmp_path)
        assert cfg.scheduling.work_start == "09:00"
        assert cfg.scheduling.work_end == "17:00"
        assert cfg.scheduling.skip_weekends is False


class TestKeychainIntegration:
    """Test credential retrieval via keyring (mocked)."""

    def test_get_github_token(self):
        """Retrieves GitHub PAT from keychain."""
        from nstd.config import get_credential

        with patch("keyring.get_password", return_value="ghp_test123"):
            token = get_credential("nstd-github", "nate-double-u")
            assert token == "ghp_test123"

    def test_missing_credential_returns_none(self):
        """Missing keychain entry returns None."""
        from nstd.config import get_credential

        with patch("keyring.get_password", return_value=None):
            token = get_credential("nstd-github", "nate-double-u")
            assert token is None

    def test_set_credential(self):
        """Stores credential in keychain."""
        from nstd.config import set_credential

        with patch("keyring.set_password") as mock_set:
            set_credential("nstd-github", "nate-double-u", "ghp_test123")
            mock_set.assert_called_once_with(
                "nstd-github", "nate-double-u", "ghp_test123"
            )
