"""Asana write-back — complete linked Asana tasks when GitHub issues close."""

from __future__ import annotations

import logging
import sqlite3

import asana as asana_sdk

from nstd.db import get_linked_tasks

logger = logging.getLogger(__name__)


def _get_asana_client(token: str) -> asana_sdk.Client:  # pragma: no cover
    """Create an Asana client instance."""
    client = asana_sdk.Client.access_token(token)
    client.headers = {"asana-enable": "new_memberships"}
    return client


def writeback_asana_done(
    conn: sqlite3.Connection,
    github_task_id: str,
    token: str,
) -> dict:
    """Mark linked Asana task as complete when a GitHub issue closes.

    Args:
        conn: Database connection.
        github_task_id: The nstd task ID of the closed GitHub issue.
        token: Asana PAT.

    Returns:
        Result dict with 'success', optionally 'skipped' or 'error'.
    """
    # Find linked Asana tasks
    linked = get_linked_tasks(conn, github_task_id)
    asana_links = [l for l in linked if l["task_id"].startswith("asana:")]

    if not asana_links:
        return {"success": True, "skipped": True}

    for link in asana_links:
        asana_gid = link["task_id"].replace("asana:", "")

        try:
            client = _get_asana_client(token)
            client.tasks.update_task(asana_gid, {"completed": True})
            logger.info("Marked Asana task %s as complete", asana_gid)

        except Exception as e:
            logger.error("Asana write-back failed for %s: %s", asana_gid, e)
            return {"success": False, "error": str(e)}

    return {"success": True}
