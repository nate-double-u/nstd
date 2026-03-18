"""Conflict detection between GitHub and linked source systems.

Detects when the same field has been updated in both GitHub AND a linked
system between sync cycles with differing values (§6.6).

v1 supports only `always_ask` mode — conflicts are recorded but never
auto-resolved. The user resolves them via the TUI Conflicts tab (§9.4).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from nstd.db import get_task, record_conflict

# Fields that can be compared for conflicts between sources.
COMPARABLE_FIELDS = frozenset(
    {
        "state",
        "priority",
        "size",
        "due_date",
        "start_date",
        "title",
        "estimate_hours",
    }
)

VALID_RESOLUTIONS = frozenset({"github_wins", "other_wins", "manual"})


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def detect_conflicts(
    conn: sqlite3.Connection,
    task_id: str,
    github_values: dict,
    other_values: dict,
    other_source: str,
    mode: str = "always_ask",
) -> list[dict]:
    """Detect field conflicts between GitHub and another source.

    A conflict exists when:
    1. A field's value in GitHub differs from the stored value (GitHub changed it)
    2. The same field's value in the other source also differs from stored (other changed it)
    3. The two new values differ from each other (they diverged)

    Args:
        conn: Database connection.
        task_id: The task ID to check conflicts for.
        github_values: Dict of field→value from GitHub's current state.
        other_values: Dict of field→value from the other source's current state.
        other_source: Name of the other source ("jira" or "asana").
        mode: Conflict resolution mode. Only "always_ask" is supported in v1.

    Returns:
        List of newly created conflict dicts (empty if no conflicts).

    Raises:
        ValueError: If the task doesn't exist in the database.
    """
    stored = get_task(conn, task_id)
    if stored is None:
        raise ValueError(f"Task '{task_id}' not found in database")

    # Only compare fields present in both value dicts
    common_fields = set(github_values.keys()) & set(other_values.keys()) & COMPARABLE_FIELDS

    new_conflicts = []
    for field in sorted(common_fields):
        stored_value = stored.get(field)
        gh_value = github_values[field]
        other_value = other_values[field]

        # Normalize to strings for comparison (stored values come back as strings from SQLite)
        stored_str = str(stored_value) if stored_value is not None else None
        gh_str = str(gh_value) if gh_value is not None else None
        other_str = str(other_value) if other_value is not None else None

        github_changed = gh_str != stored_str
        other_changed = other_str != stored_str
        values_differ = gh_str != other_str

        if github_changed and other_changed and values_differ:
            # Check if this exact conflict already exists (unresolved or resolved)
            if _conflict_already_exists(conn, task_id, field, gh_str, other_str, other_source):
                continue

            conflict_id = record_conflict(
                conn,
                task_id=task_id,
                field=field,
                value_github=gh_str,
                value_other=other_str,
                other_source=other_source,
            )

            new_conflicts.append(
                {
                    "id": conflict_id,
                    "task_id": task_id,
                    "field": field,
                    "value_github": gh_str,
                    "value_other": other_str,
                    "other_source": other_source,
                }
            )

    return new_conflicts


def _conflict_already_exists(
    conn: sqlite3.Connection,
    task_id: str,
    field: str,
    value_github: str | None,
    value_other: str | None,
    other_source: str,
) -> bool:
    """Check if a conflict with the same values already exists (resolved or unresolved).

    This prevents:
    - Duplicate unresolved conflicts for the same field/values
    - Re-raising a conflict that was already resolved with the same values
    """
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM conflicts
        WHERE task_id = ? AND field = ? AND other_source = ?
          AND value_github IS ? AND value_other IS ?
        """,
        (task_id, field, other_source, value_github, value_other),
    ).fetchone()
    return row["cnt"] > 0


def resolve_conflict(
    conn: sqlite3.Connection,
    conflict_id: int,
    resolution: str,
) -> None:
    """Resolve a conflict.

    Args:
        conn: Database connection.
        conflict_id: The ID of the conflict to resolve.
        resolution: One of "github_wins", "other_wins", "manual".

    Raises:
        ValueError: If the resolution is invalid, conflict doesn't exist,
                    or conflict is already resolved.
    """
    if resolution not in VALID_RESOLUTIONS:
        raise ValueError(
            f"Invalid resolution '{resolution}'. Must be one of: {sorted(VALID_RESOLUTIONS)}"
        )

    row = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
    if row is None:
        raise ValueError(f"Conflict {conflict_id} not found")

    if row["resolved_at"] is not None:
        raise ValueError(f"Conflict {conflict_id} is already resolved")

    conn.execute(
        "UPDATE conflicts SET resolution = ?, resolved_at = ? WHERE id = ?",
        (resolution, _now_iso(), conflict_id),
    )
    conn.commit()
