"""Asana sync — fetch assigned tasks and project tasks, deduplicate."""

from __future__ import annotations

import logging
import sqlite3

from nstd.config import AsanaConfig
from nstd.db import upsert_task

logger = logging.getLogger(__name__)

_OPT_FIELDS = (
    "name,notes,due_on,start_on,completed,permalink_url,assignee,memberships,custom_fields"
)


def asana_task_to_task(asana_task: dict) -> dict:
    """Convert an Asana task dict to an nstd task dict.

    Args:
        asana_task: Task dict from the Asana API.

    Returns:
        Task dict ready for upsert_task().
    """
    gid = asana_task["gid"]
    state = "done" if asana_task.get("completed") else "open"

    assignee = asana_task.get("assignee")
    assignee_name = assignee.get("gid") if assignee else None

    return {
        "id": f"asana:{gid}",
        "source": "asana",
        "source_id": gid,
        "source_url": asana_task.get("permalink_url", ""),
        "title": asana_task["name"],
        "body": asana_task.get("notes") or "",
        "state": state,
        "assignee": assignee_name,
        "priority": None,
        "size": None,
        "estimate_hours": None,
        "start_date": asana_task.get("start_on"),
        "due_date": asana_task.get("due_on"),
        "created_at": None,
        "updated_at": None,
    }


def _fetch_assigned_tasks(token: str, workspace_gid: str) -> list[dict]:  # pragma: no cover
    """Fetch tasks assigned to the current user.

    Args:
        token: Asana PAT.
        workspace_gid: Asana workspace GID.

    Returns:
        List of Asana task dicts.
    """
    import asana

    client = asana.Client.access_token(token)
    client.headers = {"asana-enable": "new_memberships"}

    tasks = list(
        client.tasks.get_tasks(
            {
                "assignee": "me",
                "workspace": workspace_gid,
                "completed_since": "now",
                "opt_fields": _OPT_FIELDS,
            }
        )
    )
    return tasks


def _fetch_project_tasks(token: str, project_gid: str) -> list[dict]:  # pragma: no cover
    """Fetch tasks from a specific project.

    Args:
        token: Asana PAT.
        project_gid: Asana project GID.

    Returns:
        List of Asana task dicts.
    """
    import asana

    client = asana.Client.access_token(token)
    client.headers = {"asana-enable": "new_memberships"}

    tasks = list(
        client.tasks.get_tasks_for_project(
            project_gid,
            {
                "completed_since": "now",
                "opt_fields": _OPT_FIELDS,
            },
        )
    )
    return tasks


def sync_asana(
    conn: sqlite3.Connection,
    config: AsanaConfig,
    token: str,
    dry_run: bool = False,
) -> dict:
    """Run Asana sync: fetch assigned + project tasks, deduplicate, upsert.

    Args:
        conn: Database connection.
        config: Asana configuration.
        token: Asana PAT.
        dry_run: If True, suppress all DB writes and print [DRY-RUN] lines.

    Returns:
        Stats dict with 'fetched', 'updated', and 'errors' keys.
    """
    stats: dict = {"fetched": 0, "updated": 0, "errors": []}
    seen_gids: set[str] = set()
    all_tasks: list[dict] = []

    # Path 1: assigned tasks
    try:
        assigned = _fetch_assigned_tasks(token, config.workspace_gid)
        for t in assigned:
            if t["gid"] not in seen_gids:
                seen_gids.add(t["gid"])
                all_tasks.append(t)
    except Exception as e:
        logger.error("Asana assigned tasks fetch error: %s", e)
        stats["errors"].append(str(e))

    # Path 2: project tasks
    for project_gid in config.project_gids:
        try:
            project_tasks = _fetch_project_tasks(token, project_gid)
            for t in project_tasks:
                if t["gid"] not in seen_gids:
                    seen_gids.add(t["gid"])
                    all_tasks.append(t)
        except Exception as e:
            logger.error("Asana project %s fetch error: %s", project_gid, e)
            stats["errors"].append(str(e))

    stats["fetched"] = len(all_tasks)

    for asana_task in all_tasks:
        task = asana_task_to_task(asana_task)
        if dry_run:
            print(
                f"[DRY-RUN] Would upsert task: {task['id']} "
                f'"{task["title"]}" (status: {task["state"]})'
            )
        else:
            upsert_task(conn, task)
        stats["updated"] += 1

    return stats
