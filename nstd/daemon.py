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

from nstd.db import (
    complete_sync_log,
    error_sync_log,
    start_sync_log,
    upsert_task,
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


class LogSanitizer(logging.Filter):
    """Logging filter that redacts sensitive values from log output.

    §16: API tokens must never appear in log output.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the log message, always returning True to keep it."""
        if isinstance(record.msg, str):
            for pattern in _SENSITIVE_PATTERNS:
                record.msg = pattern.sub("[REDACTED]", record.msg)
        return True


def _sync_github(conn: sqlite3.Connection, config) -> list[dict]:
    """Sync tasks from GitHub. Thin wrapper for error isolation.

    This calls the actual GitHub sync engine. The implementation
    imports and calls sync_github() from nstd.sync.github.
    """
    from nstd.sync.github import sync_github

    return sync_github(config)  # pragma: no cover


def _sync_jira(conn: sqlite3.Connection, config) -> list[dict]:
    """Sync tasks from Jira. Thin wrapper for error isolation."""
    from nstd.sync.jira import sync_jira

    return sync_jira(config)  # pragma: no cover


def _sync_asana(conn: sqlite3.Connection, config) -> list[dict]:
    """Sync tasks from Asana. Thin wrapper for error isolation."""
    from nstd.sync.asana import sync_asana

    return sync_asana(config)  # pragma: no cover


def run_task_sync(conn: sqlite3.Connection, config) -> dict:
    """Run a full task sync cycle.

    Calls all source sync functions in order. If any source fails,
    the error is logged and the remaining sources still run.

    Per spec §6.1 steps 1-10:
    1-5. Fetch from all sources
    6. Upsert all records
    7-8. Write-back and conflict detection (handled by callers after upsert)
    9. Scheduling nudge evaluation (handled by callers)
    10. Write sync log entry

    Args:
        conn: Database connection.
        config: NstdConfig object.

    Returns:
        Dict with keys: tasks_synced (int), errors (list[str]),
                        log_id (int)
    """
    log_id = start_sync_log(conn, source="all")
    all_tasks = []
    errors = []

    # Sync each source with error isolation
    sync_sources = [
        ("GitHub", _sync_github),
        ("Jira", _sync_jira),
        ("Asana", _sync_asana),
    ]

    for source_name, sync_fn in sync_sources:
        try:
            tasks = sync_fn(conn, config)
            all_tasks.extend(tasks)
            logger.info("Synced %d tasks from %s", len(tasks), source_name)
        except Exception:
            error_msg = f"{source_name} sync failed"
            errors.append(error_msg)
            logger.exception(error_msg)

    # Upsert all successfully fetched tasks
    for task in all_tasks:
        try:
            upsert_task(conn, task)
        except Exception:
            error_msg = f"Failed to upsert task {task.get('id', 'unknown')}"
            errors.append(error_msg)
            logger.exception(error_msg)

    # Complete sync log
    if errors:
        error_sync_log(conn, log_id, errors)
    else:
        complete_sync_log(
            conn, log_id, records_fetched=len(all_tasks), records_updated=len(all_tasks)
        )

    return {
        "tasks_synced": len(all_tasks),
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
