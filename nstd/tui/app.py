"""nstd TUI application.

Textual-based terminal UI with 4 tabs: Tasks, Conflicts, Calendar, Log.

Spec references: §9.1-§9.6
"""

from __future__ import annotations

import sqlite3
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from nstd.db import get_unresolved_conflicts

# --- Helpers (pure functions, easily testable) ---

_SOURCE_INDICATORS = {
    "github": "●",
    "jira": "J",
    "asana": "A",
}

_PRIORITY_INDICATORS = {
    "high": "‼",
    "medium": "!",
    "low": "·",
}


def source_indicator(source: str) -> str:
    """Return the display indicator for a task source.

    §9.3: ●=GitHub, J=Jira, A=Asana
    """
    return _SOURCE_INDICATORS.get(source, "?")


def short_id(task_id: str) -> str:
    """Convert a full task ID to a display-friendly short form.

    Examples:
        gh:cncf/staff:123 → GH-123
        jira:CNCFSD-45 → CNCFSD-45
        asana:12345 → A-12345
    """
    if task_id.startswith("gh:"):
        parts = task_id.split(":")
        return f"GH-{parts[-1]}" if len(parts) >= 3 else task_id
    if task_id.startswith("jira:"):
        return task_id.removeprefix("jira:")
    if task_id.startswith("asana:"):
        return f"A-{task_id.removeprefix('asana:')}"
    return task_id


def priority_indicator(priority: str | None) -> str:
    """Return a display indicator for task priority."""
    if priority is None:
        return ""
    return _PRIORITY_INDICATORS.get(priority, "")


def format_task_row(task: dict) -> str:
    """Format a task dict as a single display row.

    §9.3: source indicator, ID, title, due date, priority.
    """
    src = source_indicator(task.get("source", ""))
    sid = short_id(task.get("id", ""))
    title = task.get("title", "")
    due = task.get("due_date") or ""
    pri = priority_indicator(task.get("priority"))

    parts = [src, sid, title]
    if due:
        parts.append(due)
    if pri:
        parts.append(pri)

    return "  ".join(parts)


# --- Data loading functions ---


def load_tasks(
    conn: sqlite3.Connection,
    source_filter: str | None = None,
    sort_by: str | None = None,
) -> list[dict]:
    """Load tasks from DB for display.

    Args:
        conn: Database connection.
        source_filter: If set, only return tasks from this source.
        sort_by: Column to sort by. Must be one of the allowed sort columns.

    Returns:
        List of task dicts.

    Raises:
        ValueError: If sort_by is not an allowed column.
    """
    allowed_sort_columns = {"due_date", "priority", "updated_at", "created_at", "title", "source"}

    query = "SELECT * FROM tasks WHERE state = 'open'"
    params: list = []

    if source_filter:
        query += " AND source = ?"
        params.append(source_filter)

    if sort_by == "due_date":
        # Tasks with due dates first (ascending), then nulls
        query += " ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC"
    elif sort_by:
        if sort_by not in allowed_sort_columns:
            msg = f"Invalid sort column: {sort_by}"
            raise ValueError(msg)
        query += f" ORDER BY {sort_by}"
    else:
        query += " ORDER BY updated_at DESC"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def load_sync_log(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Load recent sync log entries.

    §9.6: Last 20 sync entries, most recent first.
    """
    rows = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def load_conflicts(conn: sqlite3.Connection) -> list[dict]:
    """Load unresolved conflicts.

    §9.4: Lists unresolved conflicts for display.
    """
    return get_unresolved_conflicts(conn)


# --- App class ---


class NstdApp(App):
    """nstd TUI application.

    §9.1: Screen layout with header, tabs, list, detail panel.
    """

    TITLE = "nstd"
    CSS = """
    TabbedContent {
        height: 1fr;
    }
    """

    BINDINGS: ClassVar[list] = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
        ("s", "sync", "Sync"),
        ("1", "tab_tasks", "Tasks"),
        ("2", "tab_conflicts", "Conflicts"),
        ("3", "tab_calendar", "Calendar"),
        ("4", "tab_log", "Log"),
    ]

    def __init__(self, db_path: str = ":memory:", **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.title = "nstd"

    def compose(self) -> ComposeResult:
        """Build the UI layout."""
        yield Header()
        with TabbedContent():
            with TabPane("Tasks", id="tasks"):
                yield Static("Tasks will appear here")
            with TabPane("Conflicts", id="conflicts"):
                yield Static("Conflicts will appear here")
            with TabPane("Calendar", id="calendar"):
                yield Static("Calendar will appear here")
            with TabPane("Log", id="log"):
                yield Static("Sync log will appear here")
        yield Footer()

    def action_tab_tasks(self) -> None:
        """Switch to Tasks tab."""
        self.query_one(TabbedContent).active = "tasks"  # pragma: no cover

    def action_tab_conflicts(self) -> None:
        """Switch to Conflicts tab."""
        self.query_one(TabbedContent).active = "conflicts"  # pragma: no cover

    def action_tab_calendar(self) -> None:
        """Switch to Calendar tab."""
        self.query_one(TabbedContent).active = "calendar"  # pragma: no cover

    def action_tab_log(self) -> None:
        """Switch to Log tab."""
        self.query_one(TabbedContent).active = "log"  # pragma: no cover

    def action_sync(self) -> None:
        """Trigger a manual sync."""
        pass  # pragma: no cover

    def action_help(self) -> None:
        """Show help overlay."""
        pass  # pragma: no cover
