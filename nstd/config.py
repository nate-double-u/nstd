"""Configuration loading, validation, and credential management for nstd."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import keyring


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""


# Keys whose presence in config.toml indicates a leaked secret
_SECRET_KEY_PATTERN = re.compile(r"^(token|secret|password|api_key)$", re.IGNORECASE)


@dataclass
class UserConfig:
    github_username: str
    timezone: str


@dataclass
class GitHubConfig:
    repos: list[str]
    projects: list[str] = field(default_factory=list)
    exclude_labels: list[str] = field(default_factory=list)
    exclude_assignees: list[str] = field(default_factory=list)


@dataclass
class JiraConfig:
    server_url: str
    username: str
    projects: list[str]
    assigned_only: bool = True
    start_date_field: str = ""


@dataclass
class AsanaConfig:
    workspace_gid: str
    assigned_only: bool = True
    project_gids: list[str] = field(default_factory=list)


@dataclass
class GoogleCalendarConfig:
    calendar_name: str = "NSTD Planning"
    calendar_id: str = ""
    observe_calendars: list[str] = field(default_factory=list)
    calendar_poll_interval_minutes: int = 10
    default_duration_minutes: int = 60


@dataclass
class SyncConfig:
    interval_minutes: int = 15
    lookback_days: int = 7


@dataclass
class SchedulingConfig:
    max_hours_per_day: int = 8
    preferred_session_hours: float = 2.0
    min_block_hours: float = 0.25
    max_block_hours: float = 4.0
    work_start: str = "09:00"
    work_end: str = "17:00"
    skip_weekends: bool = False


@dataclass
class AIConfig:
    enabled: bool = False
    model: str = "deepseek-r1:latest"
    ollama_host: str = "http://localhost:11434"


@dataclass
class ConflictResolutionConfig:
    mode: str = "always_ask"


@dataclass
class TUIConfig:
    theme: str = "dark"


@dataclass
class NstdConfig:
    user: UserConfig
    github: GitHubConfig
    jira: JiraConfig
    asana: AsanaConfig
    google_calendar: GoogleCalendarConfig
    sync: SyncConfig
    scheduling: SchedulingConfig
    ai: AIConfig
    conflict_resolution: ConflictResolutionConfig
    tui: TUIConfig


_REQUIRED_SECTIONS = [
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


def _check_for_secrets(data: dict, path: str = "") -> None:
    """Recursively scan parsed TOML for keys that look like secrets."""
    for key, value in data.items():
        current_path = f"{path}.{key}" if path else key
        if _SECRET_KEY_PATTERN.match(key) and isinstance(value, str) and value:
            raise ConfigurationError(
                f"config.toml must not contain secret values. "
                f"Found secret key '{current_path}'. "
                f"Store credentials in macOS Keychain instead."
            )
        if isinstance(value, dict):
            _check_for_secrets(value, current_path)


def load_config(config_dir: Path | None = None) -> NstdConfig:
    """Load and validate nstd configuration from a TOML file.

    Args:
        config_dir: Directory containing config.toml.
                    Defaults to ~/.config/nstd/

    Returns:
        Validated NstdConfig instance.

    Raises:
        ConfigurationError: If config is missing, invalid, or contains secrets.
    """
    if config_dir is None:
        config_dir = Path.home() / ".config" / "nstd"

    config_path = config_dir / "config.toml"
    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    # Security: reject any secret values in config
    _check_for_secrets(raw)

    # Validate required sections
    for section in _REQUIRED_SECTIONS:
        if section not in raw:
            raise ConfigurationError(f"Missing required configuration section: [{section}]")

    try:
        return NstdConfig(
            user=UserConfig(**raw["user"]),
            github=GitHubConfig(**raw["github"]),
            jira=JiraConfig(**raw["jira"]),
            asana=AsanaConfig(**raw["asana"]),
            google_calendar=GoogleCalendarConfig(**raw["google_calendar"]),
            sync=SyncConfig(**raw["sync"]),
            scheduling=SchedulingConfig(**raw["scheduling"]),
            ai=AIConfig(**raw["ai"]),
            conflict_resolution=ConflictResolutionConfig(**raw["conflict_resolution"]),
            tui=TUIConfig(**raw["tui"]),
        )
    except TypeError as e:
        raise ConfigurationError(f"Invalid configuration: {e}") from e


def get_credential(service: str, account: str) -> str | None:
    """Retrieve a credential from macOS Keychain.

    Args:
        service: Keychain service name (e.g. 'nstd-github')
        account: Keychain account (e.g. 'nate-double-u')

    Returns:
        The stored password/token, or None if not found.
    """
    return keyring.get_password(service, account)


def set_credential(service: str, account: str, value: str) -> None:
    """Store a credential in macOS Keychain.

    Args:
        service: Keychain service name (e.g. 'nstd-github')
        account: Keychain account (e.g. 'nate-double-u')
        value: The password/token to store
    """
    keyring.set_password(service, account, value)
