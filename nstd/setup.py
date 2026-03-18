"""Interactive setup wizard for nstd.

Handles first-run configuration:
- Credential verification and Keychain storage
- config.toml generation
- launchd plist generation and installation

Spec references: §11, §13, §16
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import httpx

from nstd.config import set_credential

# --- Config generation ---


def generate_config_dict(answers: dict) -> dict:
    """Build a config dict from wizard answers.

    Args:
        answers: Dict of user-provided setup values.

    Returns:
        Dict matching the NstdConfig TOML structure.
    """
    return {
        "user": {
            "github_username": answers["github_username"],
            "timezone": answers["timezone"],
        },
        "github": {
            "repos": answers["github_repos"],
            "projects": answers.get("github_projects", []),
            "exclude_labels": [],
            "exclude_assignees": [],
        },
        "jira": {
            "server_url": answers["jira_server_url"],
            "username": answers["jira_username"],
            "projects": answers["jira_projects"],
            "assigned_only": True,
            "start_date_field": answers.get("jira_start_date_field", ""),
        },
        "asana": {
            "workspace_gid": answers["asana_workspace_gid"],
            "assigned_only": True,
            "project_gids": answers.get("asana_project_gids", []),
        },
        "google_calendar": {
            "calendar_name": "NSTD Planning",
            "calendar_id": answers.get("gcal_calendar_id", ""),
            "observe_calendars": answers.get("gcal_observe", []),
            "calendar_poll_interval_minutes": 10,
            "default_duration_minutes": 60,
        },
        "sync": {
            "interval_minutes": 15,
            "lookback_days": 7,
        },
        "scheduling": {
            "max_hours_per_day": answers.get("max_hours_per_day", 8),
            "preferred_session_hours": answers.get("preferred_session_hours", 2.0),
            "min_block_hours": 0.25,
            "max_block_hours": 4.0,
            "work_start": answers.get("work_start", "09:00"),
            "work_end": answers.get("work_end", "17:00"),
            "skip_weekends": False,
        },
        "ai": {
            "enabled": False,
            "model": "deepseek-r1:latest",
            "ollama_host": "http://localhost:11434",
        },
        "conflict_resolution": {
            "mode": "always_ask",
        },
        "tui": {
            "theme": "dark",
        },
    }


# --- TOML writing ---


def write_config_toml(
    config: dict,
    config_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Write config dict to config.toml.

    Args:
        config: Config dict (from generate_config_dict).
        config_dir: Directory to write to. Defaults to ~/.config/nstd/
        force: If True, overwrite existing config.

    Returns:
        Path to the written config file.

    Raises:
        FileExistsError: If config exists and force is False.
    """
    if config_dir is None:
        config_dir = Path.home() / ".config" / "nstd"  # pragma: no cover

    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    if config_path.exists() and not force:
        raise FileExistsError(
            f"Config file already exists: {config_path}. Use force=True to overwrite."
        )

    toml_str = _dict_to_toml(config)
    config_path.write_text(toml_str)
    return config_path


def _dict_to_toml(data: dict, prefix: str = "") -> str:
    """Convert a nested dict to TOML string.

    Simple serialiser — handles strings, ints, floats, bools, and lists of strings.
    Nested dicts become TOML sections.
    """
    lines: list[str] = []
    sections: list[tuple[str, dict]] = []

    for key, value in data.items():
        if isinstance(value, dict):
            sections.append((key, value))
        elif isinstance(value, list):
            items = ", ".join(f'"{v}"' for v in value)
            lines.append(f"{key} = [{items}]")
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, int | float):
            lines.append(f"{key} = {value}")

    result = "\n".join(lines)

    for section_name, section_data in sections:
        full_name = f"{prefix}.{section_name}" if prefix else section_name
        section_str = _dict_to_toml(section_data, prefix=full_name)
        result += f"\n\n[{full_name}]\n{section_str}"

    return result.strip() + "\n"


# --- Plist generation ---

_PLIST_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>dev.nstd.sync</string>
        <key>ProgramArguments</key>
        <array>
            <string>{venv_path}/bin/nstd</string>
            <string>sync</string>
            <string>--daemon</string>
        </array>
        <key>StartInterval</key>
        <integer>900</integer>
        <key>StandardOutPath</key>
        <string>/tmp/nstd.log</string>
        <key>StandardErrorPath</key>
        <string>/tmp/nstd.error.log</string>
        <key>EnvironmentVariables</key>
        <dict>
            <key>PATH</key>
            <string>/usr/local/bin:/usr/bin:/bin</string>
        </dict>
    </dict>
    </plist>
""")


def generate_plist(venv_path: str) -> str:
    """Generate a launchd plist for the nstd sync daemon.

    Args:
        venv_path: Path to the Python virtual environment.

    Returns:
        Plist XML string.
    """
    return _PLIST_TEMPLATE.format(venv_path=venv_path)


def write_plist(
    plist_content: str,
    launch_agents_dir: Path | None = None,
) -> Path:
    """Write the plist file to ~/Library/LaunchAgents/.

    Args:
        plist_content: Generated plist XML string.
        launch_agents_dir: Override for the LaunchAgents directory.

    Returns:
        Path to the written plist file.
    """
    if launch_agents_dir is None:
        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"  # pragma: no cover

    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents_dir / "dev.nstd.sync.plist"
    plist_path.write_text(plist_content)
    return plist_path


# --- Credential verification ---


def verify_github_token(token: str) -> str | None:
    """Verify a GitHub PAT by calling /user.

    Args:
        token: GitHub personal access token.

    Returns:
        GitHub username if valid, None otherwise.
    """
    try:
        response = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            return response.json()["login"]
    except Exception:
        pass
    return None


def verify_jira_credentials(
    server_url: str,
    username: str,
    api_token: str,
) -> str | None:
    """Verify Jira credentials by fetching user info.

    Args:
        server_url: Jira Cloud URL (e.g. https://test.atlassian.net).
        username: Jira username (email).
        api_token: Jira API token.

    Returns:
        Display name if valid, None otherwise.
    """
    try:
        response = httpx.get(
            f"{server_url}/rest/api/3/myself",
            auth=(username, api_token),
        )
        if response.status_code == 200:
            return response.json()["displayName"]
    except Exception:
        pass
    return None


def verify_asana_token(token: str) -> str | None:
    """Verify an Asana PAT by fetching user info.

    Args:
        token: Asana personal access token.

    Returns:
        User name if valid, None otherwise.
    """
    try:
        response = httpx.get(
            "https://app.asana.com/api/1.0/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            return response.json()["data"]["name"]
    except Exception:
        pass
    return None


# --- API discovery ---


def discover_jira_date_fields(
    server_url: str,
    username: str,
    api_token: str,
) -> list[dict]:
    """Discover date-type fields from Jira for start_date selection.

    Args:
        server_url: Jira Cloud URL.
        username: Jira username.
        api_token: Jira API token.

    Returns:
        List of dicts with 'id' and 'name' for date fields.
    """
    response = httpx.get(
        f"{server_url}/rest/api/3/field",
        auth=(username, api_token),
    )
    if response.status_code != 200:
        return []

    fields = response.json()
    return [
        {"id": f["id"], "name": f["name"]}
        for f in fields
        if f.get("schema", {}).get("type") == "date"
    ]


def list_jira_projects(
    server_url: str,
    username: str,
    api_token: str,
) -> list[dict]:
    """List accessible Jira projects.

    Args:
        server_url: Jira Cloud URL.
        username: Jira username.
        api_token: Jira API token.

    Returns:
        List of dicts with 'key' and 'name'.
    """
    response = httpx.get(
        f"{server_url}/rest/api/3/project",
        auth=(username, api_token),
    )
    if response.status_code != 200:
        return []

    return [{"key": p["key"], "name": p["name"]} for p in response.json()]


def list_asana_workspaces(token: str) -> list[dict]:
    """List Asana workspaces for the authenticated user.

    Args:
        token: Asana personal access token.

    Returns:
        List of dicts with 'gid' and 'name'.
    """
    response = httpx.get(
        "https://app.asana.com/api/1.0/workspaces",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:
        return []

    return [{"gid": w["gid"], "name": w["name"]} for w in response.json()["data"]]


def list_asana_projects(token: str, workspace_gid: str) -> list[dict]:
    """List Asana projects in a workspace.

    Args:
        token: Asana personal access token.
        workspace_gid: Workspace GID.

    Returns:
        List of dicts with 'gid' and 'name'.
    """
    response = httpx.get(
        "https://app.asana.com/api/1.0/projects",
        headers={"Authorization": f"Bearer {token}"},
        params={"workspace": workspace_gid},
    )
    if response.status_code != 200:
        return []

    return [{"gid": p["gid"], "name": p["name"]} for p in response.json()["data"]]


# --- Credential storage ---


def store_github_token(token: str, username: str) -> None:
    """Store GitHub PAT in macOS Keychain."""
    set_credential("nstd-github", username, token)


def store_jira_credentials(api_token: str, username: str) -> None:
    """Store Jira API token in macOS Keychain."""
    set_credential("nstd-jira", username, api_token)


def store_asana_token(token: str) -> None:
    """Store Asana PAT in macOS Keychain."""
    set_credential("nstd-asana", "default", token)
