"""Jira Cloud sync — fetch assigned issues and map to nstd tasks."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from jira import JIRA

from nstd.config import JiraConfig
from nstd.db import upsert_task

logger = logging.getLogger(__name__)


def _get_jira_client(server_url: str, username: str, token: str) -> JIRA:  # pragma: no cover
    """Create a Jira client instance."""
    return JIRA(server=server_url, basic_auth=(username, token))


def jira_issue_to_task(issue: Any, config: JiraConfig) -> dict:
    """Convert a Jira issue object to an nstd task dict.

    Args:
        issue: Jira issue object from the jira library.
        config: Jira configuration (for custom field mapping).

    Returns:
        Task dict ready for upsert_task().
    """
    fields = issue.fields
    status_category = fields.status.statusCategory.name

    # Map Jira status categories to nstd states
    if status_category == "Done":
        state = "closed"
    else:
        state = "open"

    # Extract start date from custom field if configured
    start_date = None
    if config.start_date_field:
        start_date = getattr(fields, config.start_date_field, None)

    # Extract priority name safely
    priority = None
    if fields.priority:
        priority = fields.priority.name

    return {
        "id": f"jira:{issue.key}",
        "source": "jira",
        "source_id": issue.key,
        "source_url": issue.permalink(),
        "title": fields.summary,
        "body": fields.description or "",
        "state": state,
        "assignee": getattr(fields.assignee, "displayName", None) if fields.assignee else None,
        "priority": priority,
        "size": None,
        "estimate_hours": None,
        "start_date": start_date,
        "due_date": fields.duedate,
        "created_at": fields.created,
        "updated_at": fields.updated,
    }


def sync_jira(
    conn: sqlite3.Connection,
    config: JiraConfig,
    token: str,
) -> dict:
    """Run Jira sync: fetch assigned issues via JQL, upsert to DB.

    Args:
        conn: Database connection.
        config: Jira configuration.
        token: Jira API token.

    Returns:
        Stats dict with 'fetched', 'updated', and 'errors' keys.
    """
    stats: dict = {"fetched": 0, "updated": 0, "errors": []}

    try:
        client = _get_jira_client(config.server_url, config.username, token)

        projects_list = ", ".join(config.projects)
        jql = (
            f"assignee = currentUser() "
            f"AND project in ({projects_list}) "
            f"AND statusCategory != Done "
            f"ORDER BY updated DESC"
        )

        fields = [
            "summary",
            "description",
            "status",
            "priority",
            "assignee",
            "created",
            "updated",
            "duedate",
        ]
        if config.start_date_field:
            fields.append(config.start_date_field)

        issues = client.search_issues(
            jql,
            maxResults=200,
            fields=fields,
        )

        stats["fetched"] = len(issues)

        for issue in issues:
            task = jira_issue_to_task(issue, config)
            upsert_task(conn, task)
            stats["updated"] += 1

    except Exception as e:
        logger.error("Jira sync error: %s", e)
        stats["errors"].append(str(e))

    return stats
