"""Jira write-back — transition linked Jira tickets when GitHub issues close."""

from __future__ import annotations

import logging
import sqlite3

from jira import JIRA

from nstd.db import get_linked_tasks

logger = logging.getLogger(__name__)

# Transition names that indicate "done" (case-insensitive, first match wins)
_DONE_TRANSITIONS = ["done", "closed", "resolved", "complete"]


def _get_jira_client(server_url: str, username: str, token: str) -> JIRA:  # pragma: no cover
    """Create a Jira client instance."""
    return JIRA(server=server_url, basic_auth=(username, token))


def writeback_jira_done(
    conn: sqlite3.Connection,
    github_task_id: str,
    token: str,
    server_url: str,
    username: str,
) -> dict:
    """Transition linked Jira ticket to Done when a GitHub issue closes.

    Args:
        conn: Database connection.
        github_task_id: The nstd task ID of the closed GitHub issue.
        token: Jira API token.
        server_url: Jira server URL.
        username: Jira username.

    Returns:
        Result dict with 'success', optionally 'skipped' or 'error'.
    """
    # Find linked Jira tasks
    linked = get_linked_tasks(conn, github_task_id)
    jira_links = [l for l in linked if l["task_id"].startswith("jira:")]

    if not jira_links:
        return {"success": True, "skipped": True}

    for link in jira_links:
        jira_key = link["task_id"].replace("jira:", "")

        try:
            client = _get_jira_client(server_url, username, token)
            transitions = client.transitions(jira_key)

            # Find a "done" transition
            done_transition_id = None
            for t in transitions:
                if t["name"].lower() in _DONE_TRANSITIONS:
                    done_transition_id = t["id"]
                    break

            if done_transition_id is None:
                logger.warning(
                    "No done transition found for %s. Available: %s",
                    jira_key,
                    [t["name"] for t in transitions],
                )
                return {"success": False, "error": f"No done transition for {jira_key}"}

            client.transition_issue(jira_key, done_transition_id)
            logger.info("Transitioned %s to Done", jira_key)

        except Exception as e:
            logger.error("Jira write-back failed for %s: %s", jira_key, e)
            return {"success": False, "error": str(e)}

    return {"success": True}
