"""GitHub sync — REST issues + GraphQL Projects v2 field metadata."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Optional

import httpx

from nstd.config import GitHubConfig, UserConfig
from nstd.db import create_task_link, upsert_task

logger = logging.getLogger(__name__)

# Pattern to extract Jira link from GitHub Issue body (per §2.4)
JIRA_LINK_PATTERN = re.compile(
    r"\*\*Jira:\*\*\s*(https://[^\s]+atlassian\.net/browse/([A-Z]+-\d+))"
)

# Projects v2 field name → task dict key
_FIELD_MAP = {
    "Priority": "priority",
    "Size": "size",
    "Start Date": "start_date",
    "Due Date": "due_date",
}


def extract_jira_link(body: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Extract a Jira link from a GitHub Issue body.

    Args:
        body: The issue body text.

    Returns:
        (url, issue_key) if found, else (None, None).
    """
    if not body:
        return None, None

    match = JIRA_LINK_PATTERN.search(body)
    if match:
        return match.group(1), match.group(2)
    return None, None


def issue_to_task(issue: dict, repo: str) -> dict:
    """Convert a GitHub REST API issue dict to an nstd task dict.

    Args:
        issue: Raw issue dict from GitHub API.
        repo: Repository in "owner/repo" format.

    Returns:
        Task dict ready for upsert_task().
    """
    assignees = issue.get("assignees", [])
    first_assignee = assignees[0]["login"] if assignees else None

    return {
        "id": f"gh:{repo}:{issue['number']}",
        "source": "github",
        "source_id": str(issue["number"]),
        "source_url": issue["html_url"],
        "title": issue["title"],
        "body": issue.get("body") or "",
        "state": issue["state"],
        "assignee": first_assignee,
        "priority": None,
        "size": None,
        "estimate_hours": None,
        "start_date": None,
        "due_date": None,
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
    }


def should_sync_issue(issue: dict, config: GitHubConfig) -> bool:
    """Determine whether an issue should be synced.

    Excludes issues assigned only to bot accounts and issues
    with excluded labels.

    Args:
        issue: Raw issue dict from GitHub API.
        config: GitHub configuration.

    Returns:
        True if the issue should be synced.
    """
    # Check for excluded labels
    labels = {label["name"] for label in issue.get("labels", [])}
    if labels & set(config.exclude_labels):
        return False

    # Check assignees: skip if ALL assignees are in the exclude list
    assignees = [a["login"] for a in issue.get("assignees", [])]
    if not assignees:
        return True

    non_excluded = [a for a in assignees if a not in config.exclude_assignees]
    return len(non_excluded) > 0


def extract_project_fields(field_values: Optional[list[dict]]) -> dict:
    """Extract mapped fields from Projects v2 field values.

    Args:
        field_values: List of GraphQL ProjectV2ItemFieldValue nodes.

    Returns:
        Dict with keys from _FIELD_MAP (priority, size, start_date, due_date).
    """
    if not field_values:
        return {}

    result = {}
    for fv in field_values:
        typename = fv.get("__typename", "")
        field_name = fv.get("field", {}).get("name", "")

        if field_name not in _FIELD_MAP:
            continue

        mapped_key = _FIELD_MAP[field_name]

        if "Date" in typename:
            result[mapped_key] = fv.get("date")
        elif "SingleSelect" in typename:
            result[mapped_key] = fv.get("name")
        elif "Number" in typename:
            result[mapped_key] = fv.get("number")

    return result


def _fetch_issues_rest(
    repo: str,
    username: str,
    token: str,
) -> list[dict]:
    """Fetch issues assigned to the user from a GitHub repo via REST API.

    Args:
        repo: Repository in "owner/repo" format.
        username: GitHub username to filter by assignee.
        token: GitHub PAT.

    Returns:
        List of issue dicts from the GitHub API.
    """
    issues: list[dict] = []
    page = 1

    with httpx.Client() as client:
        while True:
            resp = client.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={
                    "assignee": username,
                    "state": "open",
                    "per_page": 100,
                    "page": page,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            resp.raise_for_status()
            batch = resp.json()

            if not batch:
                break

            issues.extend(batch)
            page += 1

            # GitHub returns at most 100 per page
            if len(batch) < 100:
                break

    return issues


def sync_github(
    conn: sqlite3.Connection,
    user_config: UserConfig,
    github_config: GitHubConfig,
    token: str,
) -> dict:
    """Run GitHub sync: fetch issues, filter, upsert, detect Jira links.

    Args:
        conn: Database connection.
        user_config: User configuration.
        github_config: GitHub configuration.
        token: GitHub PAT.

    Returns:
        Stats dict with 'fetched' and 'updated' counts.
    """
    fetched = 0
    updated = 0

    for repo in github_config.repos:
        issues = _fetch_issues_rest(repo, user_config.github_username, token)
        fetched += len(issues)

        for issue in issues:
            if not should_sync_issue(issue, github_config):
                continue

            task = issue_to_task(issue, repo)
            upsert_task(conn, task)
            updated += 1

            # Detect Jira links
            jira_url, jira_key = extract_jira_link(issue.get("body"))
            if jira_key:
                jira_task_id = f"jira:{jira_key}"
                # Ensure a placeholder task exists for the Jira side of the link
                jira_placeholder = {
                    "id": jira_task_id,
                    "source": "jira",
                    "source_id": jira_key,
                    "source_url": jira_url,
                    "title": f"[Jira] {jira_key}",
                    "body": None,
                    "state": "open",
                    "assignee": None,
                    "priority": None,
                    "size": None,
                    "estimate_hours": None,
                    "start_date": None,
                    "due_date": None,
                    "created_at": None,
                    "updated_at": None,
                }
                upsert_task(conn, jira_placeholder)
                create_task_link(conn, task["id"], jira_task_id, "mirrors")

    return {"fetched": fetched, "updated": updated}
