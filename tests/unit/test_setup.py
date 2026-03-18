"""Tests for the setup wizard module.

Spec references:
  §11 — Setup wizard steps
  §13 — launchd plist generation
  §16 — Security (credential storage in Keychain)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

# --- Config generation tests ---


class TestGenerateConfigDict:
    """§11: Generates a config dict from wizard answers."""

    def test_minimal_config_has_all_sections(self):
        """Config dict must have all 10 required sections."""
        from nstd.setup import generate_config_dict

        answers = _make_answers()
        config = generate_config_dict(answers)

        required = [
            "user",
            "github",
            "jira",
            "asana",
            "google_calendar",
            "sync",
            "scheduling",
            "ai",
            "conflict_resolution",
            "tui",
        ]
        for section in required:
            assert section in config, f"Missing section: {section}"

    def test_user_section_populated(self):
        """User section should contain github_username and timezone."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(github_username="nate-double-u", timezone="US/Pacific")
        config = generate_config_dict(answers)

        assert config["user"]["github_username"] == "nate-double-u"
        assert config["user"]["timezone"] == "US/Pacific"

    def test_github_repos_stored_as_list(self):
        """GitHub repos should be a list of strings."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(github_repos=["cncf/staff", "cncf/mentoring"])
        config = generate_config_dict(answers)

        assert config["github"]["repos"] == ["cncf/staff", "cncf/mentoring"]

    def test_jira_config_includes_start_date_field(self):
        """Jira config should include the discovered start date field."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(jira_start_date_field="customfield_10015")
        config = generate_config_dict(answers)

        assert config["jira"]["start_date_field"] == "customfield_10015"

    def test_jira_comment_visibility_role(self):
        """Jira config should include the comment visibility role."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(jira_comment_visibility_role="Internal Team")
        config = generate_config_dict(answers)

        assert config["jira"]["comment_visibility_role"] == "Internal Team"

    def test_jira_comment_visibility_role_default(self):
        """Jira comment visibility role should default to 'Service Desk Team'."""
        from nstd.setup import generate_config_dict

        answers = _make_answers()
        # Remove the role from answers to test default
        answers.pop("jira_comment_visibility_role", None)
        config = generate_config_dict(answers)

        assert config["jira"]["comment_visibility_role"] == "Service Desk Team"

    def test_asana_project_gids(self):
        """Asana config should include selected project GIDs."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(asana_project_gids=["111", "222"])
        config = generate_config_dict(answers)

        assert config["asana"]["project_gids"] == ["111", "222"]

    def test_calendar_config(self):
        """Calendar config should include calendar_id and observe list."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(
            gcal_calendar_id="abc123@group.calendar.google.com",
            gcal_observe=["primary", "team@group.calendar.google.com"],
        )
        config = generate_config_dict(answers)

        assert config["google_calendar"]["calendar_id"] == "abc123@group.calendar.google.com"
        assert config["google_calendar"]["observe_calendars"] == [
            "primary",
            "team@group.calendar.google.com",
        ]

    def test_scheduling_defaults(self):
        """Scheduling should use spec defaults when not overridden."""
        from nstd.setup import generate_config_dict

        answers = _make_answers()
        config = generate_config_dict(answers)

        assert config["scheduling"]["max_hours_per_day"] == 8
        assert config["scheduling"]["preferred_session_hours"] == 2.0
        assert config["scheduling"]["work_start"] == "09:00"
        assert config["scheduling"]["work_end"] == "17:00"

    def test_scheduling_custom_values(self):
        """Custom scheduling values should override defaults."""
        from nstd.setup import generate_config_dict

        answers = _make_answers(
            max_hours_per_day=6,
            preferred_session_hours=1.5,
            work_start="08:00",
            work_end="16:00",
        )
        config = generate_config_dict(answers)

        assert config["scheduling"]["max_hours_per_day"] == 6
        assert config["scheduling"]["preferred_session_hours"] == 1.5
        assert config["scheduling"]["work_start"] == "08:00"
        assert config["scheduling"]["work_end"] == "16:00"


# --- TOML writing tests ---


class TestWriteConfigToml:
    """§11: Config is persisted to ~/.config/nstd/config.toml."""

    def test_writes_valid_toml(self, tmp_path):
        """Written file should be valid TOML that can be re-read."""
        import tomllib

        from nstd.setup import generate_config_dict, write_config_toml

        answers = _make_answers()
        config = generate_config_dict(answers)
        write_config_toml(config, config_dir=tmp_path)

        config_path = tmp_path / "config.toml"
        assert config_path.exists()

        with open(config_path, "rb") as f:
            parsed = tomllib.load(f)

        assert parsed["user"]["github_username"] == "testuser"

    def test_creates_config_dir_if_missing(self, tmp_path):
        """Should create the config directory if it doesn't exist."""
        from nstd.setup import generate_config_dict, write_config_toml

        config_dir = tmp_path / "nstd"
        answers = _make_answers()
        config = generate_config_dict(answers)
        write_config_toml(config, config_dir=config_dir)

        assert (config_dir / "config.toml").exists()

    def test_does_not_overwrite_without_flag(self, tmp_path):
        """Should not overwrite an existing config without explicit flag."""
        from nstd.setup import generate_config_dict, write_config_toml

        answers = _make_answers()
        config = generate_config_dict(answers)
        write_config_toml(config, config_dir=tmp_path)

        with pytest.raises(FileExistsError):
            write_config_toml(config, config_dir=tmp_path)

    def test_overwrites_with_force_flag(self, tmp_path):
        """Should overwrite existing config when force=True."""
        from nstd.setup import generate_config_dict, write_config_toml

        answers = _make_answers()
        config = generate_config_dict(answers)
        write_config_toml(config, config_dir=tmp_path)

        answers2 = _make_answers(github_username="updated-user")
        config2 = generate_config_dict(answers2)
        write_config_toml(config2, config_dir=tmp_path, force=True)

        import tomllib

        with open(tmp_path / "config.toml", "rb") as f:
            parsed = tomllib.load(f)
        assert parsed["user"]["github_username"] == "updated-user"

    def test_unsupported_type_raises_error(self, tmp_path):
        """Unsupported value types should raise TypeError."""
        from nstd.setup import write_config_toml

        config = {"bad_key": None}  # None is not a supported TOML type
        with pytest.raises(TypeError, match="Unsupported TOML value type"):
            write_config_toml(config, config_dir=tmp_path)


# --- Plist generation tests ---


class TestGeneratePlist:
    """§13: launchd plist generation."""

    def test_plist_contains_label(self):
        """Plist should have label dev.nstd.sync."""
        from nstd.setup import generate_plist

        plist = generate_plist(venv_path="/opt/nstd/.venv")
        assert "<string>dev.nstd.sync</string>" in plist

    def test_plist_contains_venv_path(self):
        """Plist should substitute the venv path."""
        from nstd.setup import generate_plist

        plist = generate_plist(venv_path="/opt/nstd/.venv")
        assert "<string>/opt/nstd/.venv/bin/nstd</string>" in plist

    def test_plist_has_sync_daemon_args(self):
        """Plist program arguments should be 'nstd sync --daemon'."""
        from nstd.setup import generate_plist

        plist = generate_plist(venv_path="/opt/nstd/.venv")
        assert "<string>sync</string>" in plist
        assert "<string>--daemon</string>" in plist

    def test_plist_has_start_interval(self):
        """Plist should have 900s start interval."""
        from nstd.setup import generate_plist

        plist = generate_plist(venv_path="/opt/nstd/.venv")
        assert "<integer>900</integer>" in plist

    def test_plist_has_log_paths(self):
        """Plist should have stdout and stderr log paths."""
        from nstd.setup import generate_plist

        plist = generate_plist(venv_path="/opt/nstd/.venv")
        assert "/tmp/nstd.log" in plist
        assert "/tmp/nstd.error.log" in plist

    def test_write_plist_creates_file(self, tmp_path):
        """write_plist should create the plist file in LaunchAgents dir."""
        from nstd.setup import generate_plist, write_plist

        plist_content = generate_plist(venv_path="/opt/nstd/.venv")
        write_plist(plist_content, launch_agents_dir=tmp_path)

        plist_path = tmp_path / "dev.nstd.sync.plist"
        assert plist_path.exists()
        assert "dev.nstd.sync" in plist_path.read_text()

    def test_plist_is_valid_xml(self):
        """Generated plist should be valid XML."""
        import xml.etree.ElementTree as ET

        from nstd.setup import generate_plist

        plist = generate_plist(venv_path="/opt/nstd/.venv")
        # Should not raise
        ET.fromstring(plist)


# --- Credential verification tests ---


class TestVerifyGitHub:
    """§11.1: Verify GitHub PAT by calling /user."""

    def test_valid_token_returns_username(self):
        """Valid PAT should return the authenticated username."""
        from nstd.setup import verify_github_token

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "nate-double-u"}

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            result = verify_github_token("ghp_fake_token")

        assert result == "nate-double-u"

    def test_invalid_token_returns_none(self):
        """Invalid PAT should return None."""
        from nstd.setup import verify_github_token

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            result = verify_github_token("ghp_bad_token")

        assert result is None

    def test_network_error_returns_none(self):
        """Network failure should return None, not raise."""
        from nstd.setup import verify_github_token

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("connection refused")):
            result = verify_github_token("ghp_fake_token")

        assert result is None


class TestVerifyJira:
    """§11.2: Verify Jira credentials."""

    def test_valid_credentials_return_display_name(self):
        """Valid Jira creds should return the user display name."""
        from nstd.setup import verify_jira_credentials

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"displayName": "Nate W"}

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            result = verify_jira_credentials(
                "https://test.atlassian.net", "user@test.com", "api_token_123"
            )

        assert result == "Nate W"

    def test_invalid_credentials_return_none(self):
        """Invalid Jira creds should return None."""
        from nstd.setup import verify_jira_credentials

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            result = verify_jira_credentials(
                "https://test.atlassian.net", "user@test.com", "bad_token"
            )

        assert result is None

    def test_network_error_returns_none(self):
        """Network failure should return None, not raise."""
        from nstd.setup import verify_jira_credentials

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("timeout")):
            result = verify_jira_credentials("https://test.atlassian.net", "user@test.com", "token")

        assert result is None


class TestVerifyAsana:
    """§11.3: Verify Asana PAT."""

    def test_valid_token_returns_name(self):
        """Valid Asana PAT should return the user name."""
        from nstd.setup import verify_asana_token

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"name": "Nate W"}}

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            result = verify_asana_token("fake_asana_token")

        assert result == "Nate W"

    def test_invalid_token_returns_none(self):
        """Invalid Asana PAT should return None."""
        from nstd.setup import verify_asana_token

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            result = verify_asana_token("bad_asana_token")

        assert result is None

    def test_network_error_returns_none(self):
        """Network failure should return None, not raise."""
        from nstd.setup import verify_asana_token

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("dns failure")):
            result = verify_asana_token("fake_token")

        assert result is None


# --- API discovery tests ---


class TestDiscoverJiraFields:
    """§11.2: Discover Jira date fields for start_date selection."""

    def test_returns_date_fields(self):
        """Should return only date-type fields."""
        from nstd.setup import discover_jira_date_fields

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "customfield_10015", "name": "Start Date", "schema": {"type": "date"}},
            {"id": "summary", "name": "Summary", "schema": {"type": "string"}},
            {"id": "customfield_10020", "name": "Target End", "schema": {"type": "date"}},
            {"id": "duedate", "name": "Due Date", "schema": {"type": "date"}},
        ]

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            fields = discover_jira_date_fields(
                "https://test.atlassian.net", "user@test.com", "token"
            )

        assert len(fields) == 3
        field_ids = [f["id"] for f in fields]
        assert "customfield_10015" in field_ids
        assert "summary" not in field_ids

    def test_error_returns_empty_list(self):
        """API failure should return empty list."""
        from nstd.setup import discover_jira_date_fields

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            fields = discover_jira_date_fields(
                "https://test.atlassian.net", "user@test.com", "token"
            )

        assert fields == []

    def test_network_error_returns_empty_list(self):
        """Network failure should return empty list."""
        from nstd.setup import discover_jira_date_fields

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("dns failure")):
            fields = discover_jira_date_fields(
                "https://test.atlassian.net", "user@test.com", "token"
            )

        assert fields == []


class TestListJiraProjects:
    """§11.2: List accessible Jira projects."""

    def test_returns_project_keys(self):
        """Should return project key and name pairs."""
        from nstd.setup import list_jira_projects

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"key": "CNCFSD", "name": "CNCF Service Desk"},
            {"key": "TOC", "name": "TOC Operations"},
        ]

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            projects = list_jira_projects("https://test.atlassian.net", "user@test.com", "token")

        assert len(projects) == 2
        assert projects[0]["key"] == "CNCFSD"

    def test_error_returns_empty_list(self):
        """API failure should return empty list."""
        from nstd.setup import list_jira_projects

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            projects = list_jira_projects("https://test.atlassian.net", "user@test.com", "token")

        assert projects == []

    def test_network_error_returns_empty_list(self):
        """Network failure should return empty list."""
        from nstd.setup import list_jira_projects

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("timeout")):
            projects = list_jira_projects("https://test.atlassian.net", "user@test.com", "token")

        assert projects == []


class TestListAsanaWorkspaces:
    """§11.3: List Asana workspaces."""

    def test_returns_workspaces(self):
        """Should return workspace GID and name."""
        from nstd.setup import list_asana_workspaces

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"gid": "12345", "name": "CNCF"},
                {"gid": "67890", "name": "Personal"},
            ]
        }

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            workspaces = list_asana_workspaces("fake_token")

        assert len(workspaces) == 2
        assert workspaces[0]["gid"] == "12345"

    def test_error_returns_empty_list(self):
        """API failure should return empty list."""
        from nstd.setup import list_asana_workspaces

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            workspaces = list_asana_workspaces("fake_token")

        assert workspaces == []

    def test_network_error_returns_empty_list(self):
        """Network failure should return empty list."""
        from nstd.setup import list_asana_workspaces

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("dns")):
            workspaces = list_asana_workspaces("fake_token")

        assert workspaces == []


class TestListAsanaProjects:
    """§11.3: List Asana projects in a workspace."""

    def test_returns_projects(self):
        """Should return project GID and name."""
        from nstd.setup import list_asana_projects

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"gid": "111", "name": "Mentoring Program"},
                {"gid": "222", "name": "Docs Refresh"},
            ]
        }

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            projects = list_asana_projects("fake_token", "12345")

        assert len(projects) == 2
        assert projects[1]["name"] == "Docs Refresh"

    def test_error_returns_empty_list(self):
        """API failure should return empty list."""
        from nstd.setup import list_asana_projects

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("nstd.setup.httpx.get", return_value=mock_response):
            projects = list_asana_projects("fake_token", "12345")

        assert projects == []

    def test_network_error_returns_empty_list(self):
        """Network failure should return empty list."""
        from nstd.setup import list_asana_projects

        with patch("nstd.setup.httpx.get", side_effect=httpx.ConnectError("timeout")):
            projects = list_asana_projects("fake_token", "12345")

        assert projects == []


# --- Credential storage tests ---


class TestStoreCredentials:
    """§16: Credentials stored in Keychain via keyring."""

    def test_stores_github_token(self):
        """Should call keyring.set_password for GitHub PAT."""
        from nstd.setup import store_github_token

        with patch("nstd.setup.set_credential") as mock_set:
            store_github_token("ghp_test_token", "nate-double-u")
            mock_set.assert_called_once_with("nstd-github", "nate-double-u", "ghp_test_token")

    def test_stores_jira_credentials(self):
        """Should store Jira API token in Keychain."""
        from nstd.setup import store_jira_credentials

        with patch("nstd.setup.set_credential") as mock_set:
            store_jira_credentials("api_token_123", "user@test.com")
            mock_set.assert_called_once_with("nstd-jira", "user@test.com", "api_token_123")

    def test_stores_asana_token(self):
        """Should store Asana PAT in Keychain."""
        from nstd.setup import store_asana_token

        with patch("nstd.setup.set_credential") as mock_set:
            store_asana_token("asana_pat_123")
            mock_set.assert_called_once_with("nstd-asana", "default", "asana_pat_123")


# --- Helper ---


def _make_answers(**overrides):
    """Create a default answers dict for setup wizard, with overrides."""
    defaults = {
        "github_username": "testuser",
        "timezone": "US/Pacific",
        "github_repos": ["cncf/staff"],
        "github_projects": ["27"],
        "jira_server_url": "https://test.atlassian.net",
        "jira_username": "user@test.com",
        "jira_projects": ["CNCFSD"],
        "jira_start_date_field": "customfield_10015",
        "jira_comment_visibility_role": "Service Desk Team",
        "asana_workspace_gid": "12345",
        "asana_project_gids": [],
        "gcal_calendar_id": "nstd_planning@group.calendar.google.com",
        "gcal_observe": ["primary"],
        "max_hours_per_day": 8,
        "preferred_session_hours": 2.0,
        "work_start": "09:00",
        "work_end": "17:00",
    }
    defaults.update(overrides)
    return defaults
