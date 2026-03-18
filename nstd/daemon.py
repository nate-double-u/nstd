"""Sync daemon orchestration for nstd.

Manages the two sync loops:
  - Task sync: fetches from GitHub, Jira, Asana, upserts, write-back, conflicts
  - Calendar poll: reads calendar events, marks past blocks, detects orphans

Spec references: §6.1 (sync loop), §15 (error handling), §16 (log sanitization)
"""

from __future__ import annotations

import logging
import re
import sqlite3

from nstd.config import NstdConfig, get_credential
from nstd.db import (
    complete_sync_log,
    error_sync_log,
    start_sync_log,
)

logger = logging.getLogger("nstd")

# Patterns for sensitive values that must never appear in logs
_SENSITIVE_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),  # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9_]{36,}"),  # GitHub OAuth token
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),  # Fine-grained PAT
    re.compile(r"Bearer\s+\S+"),  # Bearer tokens
    re.compile(r"token=[^\s&]+"),  # Generic token= params
    re.compile(r"api_key=[^\s&]+"),  # Generic api_key= params
    re.compile(r"password=[^\s&]+"),  # Password params
    re.compile(r"secret=[^\s&]+"),  # Secret params
]


def _sanitize_str(text: str) -> str:
    """Apply all sensitive patterns to a string."""
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class LogSanitizer(logging.Filter):
    """Logging filter that redacts sensitive values from log output.

    §16: API tokens must never appear in log output.
    Sanitizes record.msg, record.args, and exception text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the log message, always returning True to keep it."""
        if isinstance(record.msg, str):
            record.msg = _sanitize_str(record.msg)

        # Sanitize args (logger.info("token=%s", token))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _sanitize_str(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _sanitize_str(str(a)) if isinstance(a, str) else a for a in record.args
                )

        # Sanitize exception text if present
        if record.exc_text:
            record.exc_text = _sanitize_str(record.exc_text)

        return True


def _sync_github(conn: sqlite3.Connection, config: NstdConfig) -> dict:
    """Sync tasks from GitHub using the real sync API.

    Args:
        conn: Database connection.
        config: Full NstdConfig.

    Returns:
        Stats dict with 'fetched' and 'updated' counts.
    """
    from nstd.sync.github import sync_github

    token = get_credential("nstd-github", config.user.github_username)
    if not token:
        raise RuntimeError("GitHub token not found in Keychain")
    return sync_github(conn, config.user, config.github, token)  # pragma: no cover


def _sync_jira(conn: sqlite3.Connection, config: NstdConfig) -> dict:
    """Sync tasks from Jira using the real sync API.

    Args:
        conn: Database connection.
        config: Full NstdConfig.

    Returns:
        Stats dict with 'fetched', 'updated', and 'errors' keys.
    """
    from nstd.sync.jira import sync_jira

    token = get_credential("nstd-jira", config.jira.username)
    if not token:
        raise RuntimeError("Jira token not found in Keychain")
    return sync_jira(conn, config.jira, token)  # pragma: no cover


def _sync_asana(conn: sqlite3.Connection, config: NstdConfig) -> dict:
    """Sync tasks from Asana using the real sync API.

    Args:
        conn: Database connection.
        config: Full NstdConfig.

    Returns:
        Stats dict with 'fetched', 'updated', and 'errors' keys.
    """
    from nstd.sync.asana import sync_asana

    token = get_credential("nstd-asana", "default")
    if not token:
        raise RuntimeError("Asana token not found in Keychain")
    return sync_asana(conn, config.asana, token)  # pragma: no cover


def run_task_sync(conn: sqlite3.Connection, config: NstdConfig) -> dict:
    """Run a full task sync cycle.

    Calls all source sync functions in order. Each sync function handles
    its own upserts and returns a stats dict. If any source fails,
    the error is logged and the remaining sources still run.

    Per spec §6.1 steps 1-10:
    1-6. Fetch from all sources + upsert (handled by each sync_fn)
    7-8. Write-back and conflict detection (handled by callers after sync)
    9. Scheduling nudge evaluation (handled by callers)
    10. Write sync log entry

    Args:
        conn: Database connection.
        config: NstdConfig object.

    Returns:
        Dict with keys: total_fetched (int), total_updated (int),
                        errors (list[str]), log_id (int)
    """
    log_id = start_sync_log(conn, source=None)
    total_fetched = 0
    total_updated = 0
    errors = []

    # Sync each source with error isolation
    sync_sources = [
        ("GitHub", _sync_github),
        ("Jira", _sync_jira),
        ("Asana", _sync_asana),
    ]

    for source_name, sync_fn in sync_sources:
        try:
            stats = sync_fn(conn, config)
            total_fetched += stats.get("fetched", 0)
            total_updated += stats.get("updated", 0)
            # Aggregate per-source errors from stats dict
            for err in stats.get("errors", []):
                errors.append(f"{source_name}: {err}")
            logger.info(
                "Synced %d/%d tasks from %s",
                stats.get("updated", 0),
                stats.get("fetched", 0),
                source_name,
            )
        except Exception as exc:
            error_msg = f"{source_name} sync failed: {exc}"
            errors.append(error_msg)
            logger.exception(error_msg)

    # Complete sync log
    if errors:
        error_sync_log(conn, log_id, errors)
    else:
        complete_sync_log(
            conn, log_id, records_fetched=total_fetched, records_updated=total_updated
        )

    return {
        "total_fetched": total_fetched,
        "total_updated": total_updated,
        "errors": errors,
        "log_id": log_id,
    }


def run_calendar_poll(conn: sqlite3.Connection, config, service, poll_fn=None) -> dict:
    """Run a calendar poll cycle.

    Per spec §6.1 Loop 2:
    1. Read events from NSTD Planning and observed calendars
    2. Mark past blocks
    3. Detect orphaned blocks
    4. Re-evaluate scheduling nudges for affected days

    Args:
        conn: Database connection.
        config: NstdConfig object.
        service: Google Calendar API service object.
        poll_fn: Optional callable override for poll_calendars (for testing).

    Returns:
        Dict with poll results and any errors.
    """
    errors = []

    try:
        if poll_fn is None:  # pragma: no cover
            from nstd.calendar.gcal import poll_calendars

            poll_fn = poll_calendars

        result = poll_fn(
            conn,
            service=service,
            nstd_calendar_id=config.google_calendar.calendar_id,
            observe_calendar_ids=config.google_calendar.observe_calendars,
        )
        return {**result, "errors": errors}
    except Exception:
        error_msg = "Calendar poll failed"
        errors.append(error_msg)
        logger.exception(error_msg)
        return {
            "nstd_events": [],
            "observed_events": [],
            "orphaned_blocks": [],
            "past_blocks_marked": 0,
            "errors": errors,
        }
