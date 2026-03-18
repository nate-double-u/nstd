"""SQLite database schema and data access layer for nstd."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def get_connection(db_path: str = ":memory:") -> sqlite3.Connection:
    """Open a SQLite connection with row factory enabled.

    Args:
        db_path: Path to SQLite file, or ":memory:" for in-memory DB.

    Returns:
        sqlite3.Connection with Row factory.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    state           TEXT NOT NULL,
    assignee        TEXT,
    priority        TEXT,
    size            TEXT,
    estimate_hours  REAL,
    start_date      TEXT,
    due_date        TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    synced_at       TEXT
);

CREATE TABLE IF NOT EXISTS calendar_blocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    gcal_event_id   TEXT NOT NULL,
    start_dt        TEXT NOT NULL,
    end_dt          TEXT NOT NULL,
    duration_hours  REAL NOT NULL,
    is_past         INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id_a       TEXT NOT NULL REFERENCES tasks(id),
    task_id_b       TEXT NOT NULL REFERENCES tasks(id),
    link_type       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(task_id_a, task_id_b, link_type)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    source          TEXT,
    records_fetched INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    errors          TEXT,
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    field           TEXT NOT NULL,
    value_github    TEXT,
    value_other     TEXT,
    other_source    TEXT,
    ai_recommendation TEXT,
    detected_at     TEXT NOT NULL,
    resolved_at     TEXT,
    resolution      TEXT
);

CREATE TABLE IF NOT EXISTS estimates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    estimated_hours REAL,
    actual_hours    REAL,
    ai_suggested    REAL,
    recorded_at     TEXT NOT NULL
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist. Idempotent."""
    conn.executescript(_SCHEMA)


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# --- Task operations ---

def upsert_task(conn: sqlite3.Connection, task: dict) -> None:
    """Insert or update a task record.

    Args:
        conn: Database connection.
        task: Dict with keys matching the tasks table columns.
              Must include at minimum: id, source, source_id, source_url,
              title, state.
    """
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO tasks (
            id, source, source_id, source_url, title, body, state,
            assignee, priority, size, estimate_hours,
            start_date, due_date, created_at, updated_at, synced_at
        ) VALUES (
            :id, :source, :source_id, :source_url, :title, :body, :state,
            :assignee, :priority, :size, :estimate_hours,
            :start_date, :due_date, :created_at, :updated_at, :synced_at
        )
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            body = excluded.body,
            state = excluded.state,
            assignee = excluded.assignee,
            priority = excluded.priority,
            size = excluded.size,
            estimate_hours = COALESCE(excluded.estimate_hours, tasks.estimate_hours),
            start_date = excluded.start_date,
            due_date = excluded.due_date,
            updated_at = excluded.updated_at,
            synced_at = excluded.synced_at
        """,
        {**task, "synced_at": now},
    )
    conn.commit()


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[dict]:
    """Retrieve a single task by ID.

    Returns:
        Task as dict, or None if not found.
    """
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def get_open_tasks(conn: sqlite3.Connection) -> list[dict]:
    """Retrieve all tasks with state 'open'."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE state = 'open' ORDER BY due_date, priority"
    ).fetchall()
    return [dict(r) for r in rows]


def get_tasks_by_source(conn: sqlite3.Connection, source: str) -> list[dict]:
    """Retrieve all tasks from a specific source system."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE source = ? ORDER BY updated_at DESC",
        (source,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- Task link operations ---

def create_task_link(
    conn: sqlite3.Connection,
    task_id_a: str,
    task_id_b: str,
    link_type: str,
) -> None:
    """Create a link between two tasks. Idempotent (ignores duplicates)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO task_links (task_id_a, task_id_b, link_type, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (task_id_a, task_id_b, link_type, _now_iso()),
    )
    conn.commit()


def get_linked_tasks(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    """Get all tasks linked to the given task (bidirectional lookup).

    Returns:
        List of dicts with keys: task_id, link_type.
    """
    rows = conn.execute(
        """
        SELECT task_id_b AS task_id, link_type FROM task_links WHERE task_id_a = ?
        UNION
        SELECT task_id_a AS task_id, link_type FROM task_links WHERE task_id_b = ?
        """,
        (task_id, task_id),
    ).fetchall()
    return [dict(r) for r in rows]


# --- Sync log operations ---

def start_sync_log(
    conn: sqlite3.Connection, source: Optional[str] = None
) -> int:
    """Start a new sync log entry.

    Returns:
        The ID of the new log entry.
    """
    cursor = conn.execute(
        "INSERT INTO sync_log (started_at, source, status) VALUES (?, ?, 'running')",
        (_now_iso(), source),
    )
    conn.commit()
    return cursor.lastrowid


def complete_sync_log(
    conn: sqlite3.Connection,
    log_id: int,
    records_fetched: int = 0,
    records_updated: int = 0,
) -> None:
    """Mark a sync log entry as successfully completed."""
    conn.execute(
        """
        UPDATE sync_log
        SET status = 'success', finished_at = ?,
            records_fetched = ?, records_updated = ?
        WHERE id = ?
        """,
        (_now_iso(), records_fetched, records_updated, log_id),
    )
    conn.commit()


def error_sync_log(
    conn: sqlite3.Connection,
    log_id: int,
    errors: list[str],
) -> None:
    """Mark a sync log entry as failed with error details."""
    conn.execute(
        """
        UPDATE sync_log
        SET status = 'error', finished_at = ?, errors = ?
        WHERE id = ?
        """,
        (_now_iso(), json.dumps(errors), log_id),
    )
    conn.commit()


# --- Conflict operations ---

def record_conflict(
    conn: sqlite3.Connection,
    task_id: str,
    field: str,
    value_github: Optional[str],
    value_other: Optional[str],
    other_source: str,
    ai_recommendation: Optional[str] = None,
) -> int:
    """Record a field conflict between GitHub and another source.

    Returns:
        The ID of the new conflict record.
    """
    cursor = conn.execute(
        """
        INSERT INTO conflicts
            (task_id, field, value_github, value_other, other_source,
             ai_recommendation, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, field, value_github, value_other, other_source,
         ai_recommendation, _now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def get_unresolved_conflicts(conn: sqlite3.Connection) -> list[dict]:
    """Retrieve all conflicts that have not been resolved."""
    rows = conn.execute(
        "SELECT * FROM conflicts WHERE resolved_at IS NULL ORDER BY detected_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# --- Calendar block operations ---

def insert_calendar_block(
    conn: sqlite3.Connection,
    task_id: str,
    gcal_event_id: str,
    start_dt: str,
    end_dt: str,
    duration_hours: float,
) -> int:
    """Insert a calendar block for a task.

    Returns:
        The ID of the new block record.
    """
    cursor = conn.execute(
        """
        INSERT INTO calendar_blocks
            (task_id, gcal_event_id, start_dt, end_dt, duration_hours, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, gcal_event_id, start_dt, end_dt, duration_hours, _now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def get_blocks_for_task(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    """Retrieve all calendar blocks for a task."""
    rows = conn.execute(
        "SELECT * FROM calendar_blocks WHERE task_id = ? ORDER BY start_dt",
        (task_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_future_blocks_for_task(
    conn: sqlite3.Connection, task_id: str
) -> list[dict]:
    """Retrieve only future (non-past) calendar blocks for a task."""
    rows = conn.execute(
        """
        SELECT * FROM calendar_blocks
        WHERE task_id = ? AND is_past = 0
        ORDER BY start_dt
        """,
        (task_id,),
    ).fetchall()
    return [dict(r) for r in rows]
