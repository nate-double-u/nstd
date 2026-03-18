# nstd — "Nate's Stuff To Do"
## Technical Specification v1.2

**Author**: nate-double-u  
**Date**: 2026-03-18  
**Status**: Final Draft — for implementation by LLM coding agent  
**Target repo**: `nate-double-u/nstd` (private, personal)

---

## 1. Purpose and Philosophy

`nstd` is a personal task synchronisation daemon and minimal TUI for a single user: `@nate-double-u`, a technical writer on the CNCF Projects Team at the Linux Foundation.

### Core principles

1. **GitHub is the source of truth for tasks.** Nothing is authoritative unless it lives in GitHub Issues.
2. **`nstd` is a sync engine and operator panel, not a daily UI.** The user's daily interfaces are GitHub Issues/Projects and Google Calendar. `nstd` runs in the background and surfaces only when something needs human attention.
3. **Completion happens in the source systems.** `nstd` never marks tasks done directly. It detects completion events in source systems and propagates them.
4. **Reduce meta-work.** Every manual step that can be automated should be. The user should not maintain the same information in multiple places.
5. **Open source preferred throughout.** Proprietary dependencies are acceptable only where no viable OSS alternative exists.
6. **Local-first.** All state is stored on the user's machine. No cloud service is required to run `nstd` beyond the APIs it syncs with.
7. **Test-driven development is mandatory.** Every feature must have tests written before or alongside implementation. No feature ships without test coverage. See §19.
8. **Security by default.** Credentials never touch disk unencrypted. All API interactions use least-privilege tokens. See §16.

---

## 2. System Context

### 2.1 The user's environment

- **OS**: macOS (primary workstation)
- **GitHub account**: `nate-double-u`
- **Primary GitHub org**: `cncf`
- **Primary GitHub repo for personal task tracking**: `cncf/staff` (private)
- **GitHub Projects v2**: The CNCF team uses GitHub Projects v2 with custom fields including Start Date, Due Date, Priority, and Size. These fields are authoritative for scheduling.
- **Jira**: Enterprise Jira Cloud (Linux Foundation instance: `cncfservicedesk.atlassian.net`)
- **Asana**: Used org-wide at Linux Foundation; the user's CNCF team is migrating away from it, but it remains active for cross-LF work. Both individual task assignment AND project membership are sync scope.
- **Google Calendar**: Primary scheduling tool, synced to macOS Calendar app. A dedicated calendar named **`NSTD Planning`** is used for all nstd-created time blocks. Additional calendars are observed (read-only) to understand daily availability.
- **Ollama**: Running locally with `deepseek-r1:latest` (7b) and `deepseek-r1:14b`
- **GitHub Copilot**: Available via `gh copilot` CLI extension (LF enterprise licence)

### 2.2 Data flow overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  SOURCE SYSTEMS (read + status write-back)                          │
│                                                                     │
│   Jira Cloud ──────────────────────────────────────────────────┐   │
│   Asana (assigned tasks + project tasks) ──────────────────────┤   │
│   GitHub Issues + Projects v2 (cncf/staff + others) ──────────┤   │
│                                                                 ▼   │
│                         nstd sync daemon                            │
│                         (launchd, macOS)                            │
│                              │                                      │
│                              ▼                                      │
│                     SQLite (local state DB)                         │
│                              │                                      │
│         ┌────────────────────┼────────────────────┐               │
│         ▼                    ▼                     ▼               │
│  Google Calendar         nstd TUI             Write-back           │
│  "NSTD Planning"      (operator panel)     (Jira → Done,           │
│  (write: blocks)                            Asana → Done)          │
│  + observed calendars                                               │
│  (read: availability)                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 What nstd does NOT do

- Create new tasks (tasks are created natively in GitHub/Jira/Asana)
- Mark tasks as done (completion happens natively in GitHub/Jira/Asana)
- Replace the user's daily GitHub or Google Calendar UI
- Operate as a server or expose any network port

### 2.4 Observed conventions in cncf/staff

Inspection of the live `cncf/staff` repository reveals:

- GitHub Issues that originate from Jira already contain a link in the body in the format:
  `**Jira:** https://cncfservicedesk.atlassian.net/browse/PROJ-NNN`
- `nstd` MUST detect and parse this pattern when building cross-system links, rather than treating these issues as unlinked.
- The automation bot (`cncf-automation-bot`) creates issues programmatically — `nstd` should not sync issues where `assignee` is `cncf-automation-bot` or similar bot accounts. This is configurable via `github.exclude_assignees` in `config.toml`.

---

## 3. Architecture

### 3.1 Repository layout

```
nstd/
├── nstd/                        # Main Python package
│   ├── __init__.py
│   ├── cli.py                   # Entry point (`nstd` command)
│   ├── config.py                # Config loading (~/.config/nstd/)
│   ├── db.py                    # SQLite schema and access layer
│   ├── sync/
│   │   ├── __init__.py
│   │   ├── github.py            # GitHub REST + GraphQL sync
│   │   ├── jira.py              # Jira Cloud sync
│   │   └── asana.py             # Asana sync (assigned + projects)
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── gcal.py              # Google Calendar read/write
│   │   └── scheduler.py        # Scheduling engine (session suggestion)
│   ├── writeback/
│   │   ├── __init__.py
│   │   ├── jira.py              # Jira status transition
│   │   └── asana.py             # Asana task completion
│   ├── tui/
│   │   ├── __init__.py
│   │   └── app.py               # Textual TUI application
│   └── ai/
│       ├── __init__.py
│       └── estimate.py          # Ollama estimation (optional, v3)
├── tests/
│   ├── conftest.py              # Shared fixtures, mock API clients
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_db.py
│   │   ├── sync/
│   │   │   ├── test_github.py
│   │   │   ├── test_jira.py
│   │   │   └── test_asana.py
│   │   ├── calendar/
│   │   │   ├── test_gcal.py
│   │   │   └── test_scheduler.py
│   │   └── writeback/
│   │       ├── test_jira_writeback.py
│   │       └── test_asana_writeback.py
│   └── integration/
│       ├── README.md
│       ├── test_github_integration.py
│       ├── test_jira_integration.py
│       ├── test_asana_integration.py
│       └── test_gcal_integration.py
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── README.md
└── SPEC.md                      # This document
```

### 3.2 Technology choices

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Strong API client ecosystem, good macOS integration |
| TUI framework | [Textual](https://github.com/Textualize/textual) | OSS, actively maintained, excellent Python TUI |
| Local DB | SQLite via `sqlite3` stdlib | No server, local-first, zero dependencies |
| GitHub API (REST) | `PyGithub` | Mature, well-documented |
| GitHub API (GraphQL) | `gql` + `httpx` | Required for Projects v2 field metadata |
| Jira API | `jira` (Python lib) | Jira Cloud compatible |
| Asana API | `asana` (official SDK) | Official SDK |
| Google Calendar | `google-api-python-client` + `google-auth-oauthlib` | Official Google client |
| AI estimation | `ollama` Python client | Local inference, no data egress |
| Scheduler | `launchd` plist | macOS-native, more reliable than cron on Mac |
| Config | TOML via `tomllib` (stdlib 3.11+) | Standard, human-readable |
| Testing | `pytest` + `pytest-cov` + `responses` + `unittest.mock` | Standard Python TDD stack |
| Secrets | `keyring` | macOS Keychain integration |

---

## 4. Configuration

### 4.1 Config file location

```
~/.config/nstd/
├── config.toml                  # All non-secret configuration (safe to version control)
├── credentials/
│   ├── google_token.json        # OAuth token (auto-managed by Google client)
│   └── google_client_secret.json  # Downloaded from Google Cloud Console
└── nstd.db                      # SQLite database (treat as sensitive, chmod 600)
```

### 4.2 config.toml schema

```toml
[user]
github_username = "nate-double-u"
timezone = "America/Los_Angeles"

[github]
repos = [
  "cncf/staff",
]
projects = [
  "cncf/27",
]
exclude_labels = []
exclude_assignees = ["cncf-automation-bot"]

[jira]
server_url = "https://cncfservicedesk.atlassian.net"
username = "your.email@linuxfoundation.org"
# token stored in macOS Keychain under service "nstd-jira"
projects = ["CNCFSD"]
assigned_only = true
start_date_field = ""    # e.g. "customfield_10015", discovered during setup

[asana]
# token stored in macOS Keychain under service "nstd-asana"
workspace_gid = ""
assigned_only = true
project_gids = []        # Additional projects to sync regardless of assignee

[google_calendar]
# OAuth credentials: ~/.config/nstd/credentials/
# The calendar nstd writes time blocks to
calendar_name = "NSTD Planning"
calendar_id = ""         # Populated by `nstd setup`
# Additional calendars to read for availability (read-only, never written to)
# Populated during `nstd setup` — user selects from their calendar list
observe_calendars = []   # e.g. ["primary", "abc123@group.calendar.google.com"]
# How often to re-read all calendars for availability (minutes)
# Separate from the task sync interval because office hours bookings can appear at any time
calendar_poll_interval_minutes = 10
default_duration_minutes = 60

[sync]
interval_minutes = 15
lookback_days = 7

[scheduling]
# Maximum hours of nstd blocks per calendar day
max_hours_per_day = 8
# Preferred session length in hours (nstd will try to suggest blocks this long)
preferred_session_hours = 2.0
# Hard minimum and maximum block duration (hours)
min_block_hours = 0.25   # 15 minutes
max_block_hours = 4.0

[ai]
enabled = false
model = "deepseek-r1:latest"
ollama_host = "http://localhost:11434"

[conflict_resolution]
# "always_ask" = present every conflict to user for confirmation (default, v1)
# "ai_recommend" = present AI recommendation with one-click accept (v2+)
# "github_wins" = auto-resolve silently (not recommended until trust is established)
mode = "always_ask"

[tui]
theme = "dark"
```

### 4.3 Secrets management (macOS Keychain)

Secrets are stored in and retrieved from macOS Keychain using the `keyring` Python library.

| Secret | Keychain service name | Keychain account |
|---|---|---|
| GitHub PAT | `nstd-github` | `nate-double-u` |
| Jira API token | `nstd-jira` | value of `jira.username` |
| Asana PAT | `nstd-asana` | `nate-double-u` |

Google Calendar credentials use OAuth managed by `google-auth-oauthlib`, stored as JSON files under `~/.config/nstd/credentials/`.

**Security invariants** (enforced in code and tested):
- `config.toml` MUST NOT contain any secret values. The config loader must raise `ConfigurationError` if a known-secret key (token, password, secret, api_key) appears in the file.
- Database file permissions must be verified as `600` on startup; warn if not.
- API tokens must never appear in log output (logger must have a sanitising filter).

---

## 5. Database Schema

```sql
-- Unified task record
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,   -- "gh:cncf/staff:123", "jira:CNCFSD-456", "asana:789"
    source          TEXT NOT NULL,      -- "github" | "jira" | "asana"
    source_id       TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    state           TEXT NOT NULL,      -- "open" | "closed" | "done"
    assignee        TEXT,
    priority        TEXT,               -- "high" | "medium" | "low" | null
    size            TEXT,               -- "XS" | "S" | "M" | "L" | "XL" | null
    estimate_hours  REAL,               -- Total work estimated (set in TUI or AI-suggested)
    start_date      TEXT,               -- ISO 8601 date — when work is intended to begin
    due_date        TEXT,               -- ISO 8601 date — when work must be complete
    created_at      TEXT,
    updated_at      TEXT,
    synced_at       TEXT
);

-- Calendar blocks placed for a task (one task may have many blocks)
CREATE TABLE calendar_blocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    gcal_event_id   TEXT NOT NULL,      -- Google Calendar event ID
    start_dt        TEXT NOT NULL,      -- ISO 8601 datetime
    end_dt          TEXT NOT NULL,      -- ISO 8601 datetime
    duration_hours  REAL NOT NULL,      -- Derived: (end_dt - start_dt) in hours
    is_past         INTEGER DEFAULT 0,  -- 1 if end_dt is in the past (updated each poll)
    created_at      TEXT NOT NULL
);

-- Cross-system link table (bidirectional)
CREATE TABLE task_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id_a       TEXT NOT NULL REFERENCES tasks(id),
    task_id_b       TEXT NOT NULL REFERENCES tasks(id),
    link_type       TEXT NOT NULL,      -- "mirrors" | "blocks" | "relates_to"
    created_at      TEXT NOT NULL
);

-- Sync log
CREATE TABLE sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    source          TEXT,               -- null = full sync
    records_fetched INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    errors          TEXT,               -- JSON array of error strings
    status          TEXT NOT NULL       -- "running" | "success" | "error"
);

-- Conflicts awaiting user resolution
CREATE TABLE conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    field           TEXT NOT NULL,
    value_github    TEXT,
    value_other     TEXT,
    other_source    TEXT,
    ai_recommendation TEXT,
    detected_at     TEXT NOT NULL,
    resolved_at     TEXT,
    resolution      TEXT                -- "github_wins" | "other_wins" | "manual"
);

-- Estimation history
CREATE TABLE estimates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    estimated_hours REAL,
    actual_hours    REAL,               -- Sum of past block durations at time of issue close
    ai_suggested    REAL,
    recorded_at     TEXT NOT NULL
);
```

> **Note**: `tasks.gcal_event_id` from v1.1 is replaced by the `calendar_blocks` table. A task may have zero, one, or many blocks. This enables tracking of partial scheduling, session history, and rescheduling nudges.

---

## 6. Sync Engine

### 6.1 Sync loop (daemon mode)

Two concurrent loops run via launchd:

**Loop 1 — Task sync** (interval: `sync.interval_minutes`, default 15min):
1. Fetch assigned GitHub Issues from configured repos (REST API)
2. Fetch GitHub Projects v2 field metadata (GraphQL API)
3. Detect and parse Jira links in GitHub Issue bodies
4. Fetch assigned Jira issues from configured projects
5. Fetch assigned Asana tasks AND all tasks in configured `asana.project_gids`
6. Upsert all records into SQLite
7. Detect completion events → trigger write-back
8. Detect conflicts → write to `conflicts` table
9. Evaluate scheduling status for all open tasks (see §8.5) → update nudge state
10. Write sync log entry

**Loop 2 — Calendar poll** (interval: `google_calendar.calendar_poll_interval_minutes`, default 10min):
1. Read all events from `NSTD Planning` and all `observe_calendars` for the next 14 days
2. Update `calendar_blocks` table (mark past blocks, detect orphaned blocks)
3. Update the availability model used by the scheduling engine (see §8.5)
4. If any office-hours bookings have appeared since last poll, re-evaluate scheduling nudges for affected days

These two loops are implemented as separate launchd plists or as a single daemon process managing two internal timers — implementation detail for the coding agent to decide.

### 6.2 GitHub sync (REST + GraphQL)

**REST** — issues assigned to the configured user, excluding bot assignees:

```
GET /repos/{owner}/{repo}/issues
  ?assignee={github_username}
  &state=open
  &per_page=100
```

Fields captured: `number`, `title`, `body`, `state`, `labels`, `assignees`, `created_at`, `updated_at`, `html_url`

**Jira link extraction from issue body:**
```python
import re
JIRA_LINK_PATTERN = re.compile(
    r'\*\*Jira:\*\*\s*(https://[^\s]+atlassian\.net/browse/([A-Z]+-\d+))'
)
```

**GraphQL** — Projects v2 field metadata (paginated):

```graphql
query($login: String!, $projectNumber: Int!, $cursor: String) {
  organization(login: $login) {
    projectV2(number: $projectNumber) {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldDateValue {
                field { ... on ProjectV2FieldCommon { name } }
                date
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2FieldCommon { name } }
                name
              }
              ... on ProjectV2ItemFieldNumberValue {
                field { ... on ProjectV2FieldCommon { name } }
                number
              }
            }
          }
          content {
            ... on Issue {
              number
              repository { nameWithOwner }
            }
          }
        }
      }
    }
  }
}
```

Field name mapping (defaults):

| Projects v2 field name | SQLite column |
|---|---|
| `Start Date` | `start_date` |
| `Due Date` | `due_date` |
| `Priority` | `priority` |
| `Size` | `size` |

### 6.3 Jira sync

```python
jira.search_issues(
    jql=f"assignee = currentUser() AND project in ({projects}) AND statusCategory != Done ORDER BY updated DESC",
    maxResults=200,
    fields=["summary", "description", "status", "priority", "assignee",
            "created", "updated", "duedate", config.jira.start_date_field]
)
```

### 6.4 Asana sync

**Path 1 — assigned tasks:**
```python
tasks_api.get_tasks({
    'assignee': 'me',
    'workspace': workspace_gid,
    'completed_since': 'now',
    'opt_fields': 'name,notes,due_on,start_on,completed,permalink_url,memberships,custom_fields'
})
```

**Path 2 — project tasks:**
```python
tasks_api.get_tasks_for_project(project_gid, {
    'completed_since': 'now',
    'opt_fields': 'name,notes,due_on,start_on,completed,permalink_url,assignee,custom_fields'
})
```

Both result sets are merged (deduplicated by GID) before upsert.

### 6.5 Bidirectional linking

**Auto-detection:**
- GitHub Issue body contains `**Jira:** https://...atlassian.net/browse/PROJ-NNN` → automatically linked
- GitHub Issue body contains an Asana task URL → automatically linked

**Manual linking via TUI**: User selects an unlinked item, presses `l`.

**Write-back of links (quiet/internal):**
- **Jira**: Internal comment — `Tracked in GitHub: https://github.com/cncf/staff/issues/NNN`
  Uses `POST /rest/api/3/issue/{issueId}/comment` with `visibility: { type: "role", value: "Service Desk Team" }` (role confirmed during setup)
- **Asana**: Task comment — `Tracked in GitHub: https://github.com/cncf/staff/issues/NNN`
- **GitHub → Jira/Asana**: Link recorded in `task_links` only; issue body is not modified

### 6.6 Conflict resolution

A conflict is detected when the same field has been updated in both GitHub AND a linked system between sync cycles with differing values.

**v1 default** (`conflict_resolution.mode = "always_ask"`):
- Every conflict written to `conflicts` table
- TUI badge shows conflict count
- No automatic resolution
- User resolves in TUI Conflicts tab

**Future modes** (not implemented in v1):
- `"ai_recommend"`: Ollama suggests resolution; user accepts with one keypress
- `"github_wins"`: Auto-resolves silently; logged

Mode is promoted only by explicit user edit of `config.toml`.

---

## 7. Write-back

### 7.1 GitHub → Jira

When a linked GitHub Issue is closed:
1. Look up linked Jira ticket from `task_links`
2. Fetch transitions: `GET /rest/api/3/issue/{issueId}/transitions`
3. Find transition matching `["Done", "Closed", "Resolved", "Complete"]` (case-insensitive, first match)
4. Apply: `POST /rest/api/3/issue/{issueId}/transitions`
5. Log in `sync_log`

### 7.2 GitHub → Asana

1. Look up linked Asana GID from `task_links`
2. Mark complete: `PUT /tasks/{task_gid}` with `{ "completed": true }`
3. Log in `sync_log`

### 7.3 Jira/Asana → GitHub

1. Look up linked GitHub Issue from `task_links`
2. Close: `PATCH /repos/{owner}/{repo}/issues/{issue_number}` with `{ "state": "closed", "state_reason": "completed" }`
3. Log in `sync_log`

---

## 8. Google Calendar Integration

### 8.1 Calendars

`nstd` interacts with two categories of calendar:

| Category | Calendar | Access |
|---|---|---|
| **Write** | `NSTD Planning` | Read + write. All time blocks are created here. |
| **Observe** | Any calendars listed in `observe_calendars` | Read-only. Used to understand availability. Never written to. |

Both categories are configured during `nstd setup`. The user selects observed calendars from their full Google Calendar list. Examples: `primary` (main work calendar), team shared calendars, office hours calendars.

### 8.2 Calendar polling

Because observed calendars can change at any time (e.g. someone books an office hours slot), `nstd` polls all calendars every `calendar_poll_interval_minutes` (default 10min), independently of the task sync interval. This keeps the availability model current.

On each poll:
1. Read events from `NSTD Planning` and all `observe_calendars` for the next 14 days
2. Update `calendar_blocks` table (mark past blocks as `is_past = 1`)
3. Detect orphaned blocks (event exists in `NSTD Planning` but task is closed or not found) → flag in TUI
4. Rebuild the in-memory availability model for the scheduling engine (§8.5)

### 8.3 Time block format

When a block is created in `NSTD Planning`:

```
Title:       Fix the thing
Description: https://github.com/cncf/staff/issues/123

             Priority: high  |  Size: M  |  Due: 2026-03-25

             [First 200 characters of issue body, if present]
Color:       Tomato = high priority
             Banana = medium priority
             Blueberry = low priority
             Graphite = no priority / completed
```

- **Title**: Exactly the GitHub Issue title. No prefix, no ID.
- **Description**: GitHub Issue URL is the first line — canonical link back to source. Metadata follows.
- **Source**: Only GitHub Issues get calendar blocks. Jira/Asana items feed into GitHub; calendar blocks are created from the GitHub Issue, not the Jira/Asana item.

### 8.4 Block lifecycle

- **Created**: User initiates via `b` in TUI or `nstd block <task-id>`. The scheduling engine suggests sessions (§8.5); user confirms, adjusts, or overrides.
- **Updated**: If `due_date` or `start_date` changes during sync, the event description is updated. The time slot is not moved automatically.
- **Task closed**: All future blocks for the task have their title prefixed with `✓ ` and colour set to Graphite. Blocks are not deleted (kept for review). Past blocks contribute to `estimates.actual_hours`.
- **Orphaned**: Block exists in `NSTD Planning` but task is not found or is closed. Flagged in Calendar tab.

### 8.5 Scheduling Engine

The scheduling engine (`nstd/calendar/scheduler.py`) is responsible for:

1. **Availability modelling**: Building a per-day picture of available hours, given the daily cap and existing calendar events.
2. **Session suggestion**: Given a task, suggesting a set of time blocks that fit within the task's window and the user's available time.
3. **Scheduling nudges**: Identifying tasks that need to be scheduled or rescheduled.

#### 8.5.1 Availability model

For each day in the planning horizon (today + 14 days):

```
available_hours(day) = min(max_hours_per_day, workday_hours)
                     - sum(duration of all events on observe_calendars that day)
                     - sum(duration of existing NSTD Planning blocks that day)
```

Rules:
- Events on observed calendars occupy **specific time slots**. `nstd` will not suggest blocks that overlap any existing event on any observed calendar or on `NSTD Planning`.
- `max_hours_per_day` (default 8h) is the hard ceiling for `NSTD Planning` blocks in a single day, regardless of how free the rest of the calendar looks.
- Weekends are treated as available days by default (configurable: `scheduling.skip_weekends = false`).
- Days where `available_hours <= 0` are skipped when distributing sessions.

#### 8.5.2 Session suggestion algorithm

Inputs:
- `task.estimate_hours` — total work estimated
- `task.start_date` — earliest day to begin (may be null; default: today)
- `task.due_date` — latest day to finish (may be null; no deadline)
- `hours_already_scheduled` — sum of `duration_hours` for future blocks in `calendar_blocks` for this task
- `remaining_hours = estimate_hours - hours_already_scheduled` (floored at 0)
- `preferred_session_hours` (default 2.0h, from config)
- `min_block_hours` (default 0.25h / 15min)
- `max_block_hours` (default 4.0h)
- Current availability model

Algorithm:

```
1. If remaining_hours <= 0: no sessions to suggest. 
   (Task may still be open — remind user it may need rescheduling if past blocks have elapsed.)

2. Clamp preferred_session_hours to [min_block_hours, max_block_hours].

3. Build list of candidate days:
   - Start from max(today, task.start_date)
   - Stop at task.due_date (inclusive), or +14 days if no due_date
   - Filter to days with available_hours > 0

4. Distribute sessions across candidate days:
   - For each candidate day (in order):
     - session_length = min(preferred_session_hours, remaining_hours, available_hours(day), max_block_hours)
     - If session_length < min_block_hours: skip day
     - Suggest a block of session_length on this day
     - Subtract session_length from remaining_hours and available_hours(day)
     - Stop when remaining_hours <= 0

5. If remaining_hours > 0 after exhausting candidate days (window is too tight):
   - Still return the partial suggestion
   - Flag: "Not enough time in window — consider extending the due date or reducing estimate"

6. Return the list of suggested blocks with suggested start times.
   - Suggested start time: first available slot on each day (after existing events), 
     respecting a configurable working hours window (default 09:00–17:00, 
     config key: scheduling.work_start = "09:00", scheduling.work_end = "17:00")
```

#### 8.5.3 User interaction flow for scheduling

When the user presses `b` on a task (or runs `nstd block <task-id>`):

1. `nstd` runs the session suggestion algorithm.
2. The TUI shows a **scheduling dialog**:
   ```
   Schedule: Fix the thing
   ─────────────────────────────────────────────
   Estimate:    10h total  |  Already scheduled: 4h  |  Remaining: 6h
   Window:      2026-03-18 → 2026-03-25
   
   Suggested sessions:
     ① Mon 2026-03-18  09:00–11:00  (2h)  ← 1h free after 11am meeting
     ② Tue 2026-03-19  09:00–11:00  (2h)
     ③ Wed 2026-03-20  09:00–11:00  (2h)
   
   [Accept all]  [Edit]  [Accept one at a time]  [Cancel]
   ```
3. The user can:
   - **Accept all**: All suggested blocks are created in `NSTD Planning`
   - **Edit**: Modify start times, durations, or remove sessions before accepting
   - **Accept one at a time**: Step through sessions, accepting or skipping each
   - **Cancel**: No blocks created
4. If the user schedules **past the due date**, `nstd` shows a warning but does not block the action:
   > ⚠ This block is after the due date (2026-03-25). You can still schedule it.

#### 8.5.4 Scheduling nudges

After each task sync and calendar poll, `nstd` evaluates the scheduling status of every open GitHub Issue:

| Status | Condition | Nudge |
|---|---|---|
| **Unscheduled** | `estimate_hours` is set, no future blocks exist, task is open | "Not scheduled" |
| **Needs estimate** | Task is open, `estimate_hours` is null, `due_date` is set | "No estimate — can't schedule" |
| **Time elapsed** | All blocks are in the past, task is still open | "Scheduled time elapsed — reschedule?" |
| **Overdue** | `due_date` is in the past, task is still open | "Past due date" |
| **Tight window** | Scheduling algorithm flagged insufficient time in window | "Not enough time before due date" |
| **On track** | Future blocks exist covering remaining estimated hours | (no nudge) |

Nudges are surfaced:
- As a **badge count** in the TUI header: `[⚑ 4 need scheduling]`
- As **inline indicators** on each task row in the Tasks tab
- In a dedicated **"Needs Attention" section** at the top of the Tasks tab, listing all tasks with any nudge status

The nudge count in the header covers both unscheduled tasks and time-elapsed tasks. These are treated as equal priority — both mean work is not getting done.

---

## 9. TUI Specification

Built with [Textual](https://github.com/Textualize/textual), invoked with `nstd`.

### 9.1 Screen layout

```
┌──────────────────��──────────────────────────────────────────────────┐
│  nstd  [● synced 2m ago]  [⚠ 3 conflicts]  [⚑ 4 need scheduling]  │
│                                             [q]uit  [?]help         │
├──────────────────────┬──────────────────────────────────────────────┤
│  [1]Tasks [2]Conflicts│                                             │
│  [3]Calendar [4]Log   │   Task / Conflict / Calendar detail panel   │
├──────────────────────┤                                              │
│  ⚑ NEEDS ATTENTION   │                                              │
│  ⚑ GH-99  Fix thing  │  (unscheduled)                              │
│  ⚑ GH-87  Write docs │  (time elapsed)                             │
│  ─────────────────── │                                              │
│  ALL TASKS           │                                              │
│  ● GH-123  Fix thing │                                              │
│  J CNCFSD-45 Review  │                                              │
│  A Write docs        │                                              │
│  Filter: [________]  │                                              │
│  Source: [All ▼]     │                                              │
│  Sort:   [Due ▼]     │                                              │
└──────────────────────┴──────────────────────────────────────────────┘
```

### 9.2 Keybindings

| Key | Action |
|---|---|
| `1`–`4` | Switch tabs |
| `↑` / `↓` | Navigate list |
| `Enter` | View detail |
| `b` | Open scheduling dialog for selected task |
| `e` | Edit manual time estimate |
| `l` | Link selected task to another system's item |
| `s` | Trigger manual sync (all sources) |
| `S` | Trigger sync for selected task's source only |
| `r` | Resolve selected conflict |
| `?` | Help overlay |
| `q` | Quit |

### 9.3 Task list

Each row displays:
- Source indicator (`●`=GitHub, `J`=Jira, `A`=Asana)
- ID (e.g. `GH-123`, `CNCFSD-45`)
- Title (truncated)
- Due date (if set)
- Priority indicator
- `[linked]` badge if cross-system link exists
- `[conflict]` badge if unresolved conflict
- `[⚑]` badge if any scheduling nudge is active

The **Needs Attention** section at the top of the Tasks tab lists all tasks with an active nudge, grouped by nudge type, regardless of the current sort/filter settings.

### 9.4 Conflicts tab

Lists unresolved conflicts. For each: task ID/title, field name, GitHub value vs. other value, AI recommendation (if available), actions: `[Accept GitHub]` `[Accept Other]` `[Edit]`.

### 9.5 Calendar tab

Shows two panels:

**Left: Next 7 days** — events from `NSTD Planning` only, showing:
- Linked task title + source indicator
- Duration
- Orphaned block indicator (task closed or not found)

**Right: Tasks needing blocks** — tasks with active scheduling nudges, with a one-press `b` shortcut to open the scheduling dialog directly from this tab.

### 9.6 Sync log tab

Last 20 sync entries: timestamp, source, records fetched/updated, error count (expandable).

---

## 10. CLI Commands

```
nstd                      # Open TUI (default)
nstd setup                # Interactive first-run setup wizard
nstd sync                 # Run one full sync cycle and exit
nstd sync --source github # Sync only one source
nstd sync --daemon        # Run continuously (used by launchd)
nstd status               # Print last sync status to stdout
nstd block <task-id>      # Open scheduling dialog for a task (non-TUI)
nstd config               # Open config.toml in $EDITOR
nstd logs                 # Tail the sync log
```

---

## 11. Setup Wizard (`nstd setup`)

Interactive first-run wizard. Steps:

1. **GitHub**
   - Prompt for PAT (required scopes: `repo`, `read:org`, `read:project`)
   - Store in Keychain via `keyring`
   - Verify by calling `/user`
   - Prompt for repos to watch (suggest `cncf/staff`)
   - Prompt for project numbers (suggest `27` for CNCF TOC board)

2. **Jira**
   - Prompt for Jira Cloud URL (suggest `https://cncfservicedesk.atlassian.net`)
   - Prompt for username and API token → store in Keychain
   - Verify by fetching user info
   - List accessible projects, prompt user to select
   - Query `GET /rest/api/3/field`, filter for date fields, present list, prompt user to identify "Start Date" field ID
   - Query available comment visibility roles, prompt user to confirm internal role (default: `"Service Desk Team"`)
   - Store both in `config.toml`

3. **Asana**
   - Prompt for Asana PAT → store in Keychain
   - Verify and list workspaces, prompt user to select
   - List projects in workspace, prompt user to select projects to sync (in addition to assigned tasks)
   - Store selected `project_gids` in `config.toml`

4. **Google Calendar**
   - Instruct user to create a calendar named `NSTD Planning` in Google Calendar
   - Trigger OAuth flow (opens browser)
   - List all user calendars; prompt user to:
     a. Confirm the `NSTD Planning` calendar (stores `calendar_id`)
     b. Select additional calendars to observe for availability (stores `observe_calendars`)
   - Store both in `config.toml`

5. **Scheduling preferences**
   - Prompt for max hours per day (default 8)
   - Prompt for preferred session length (default 2h, explain min 15min / max 4h)
   - Prompt for working hours window (default 09:00–17:00)
   - Store in `config.toml` under `[scheduling]`

6. **Sync test**
   - Run one full sync cycle
   - Report: X tasks from GitHub, Y from Jira, Z from Asana
   - Report: N tasks need scheduling

7. **launchd install**
   - Offer to install the launchd plist(s)
   - Write `~/Library/LaunchAgents/dev.nstd.sync.plist`
   - Run `launchctl load`

---

## 12. AI Estimation (Optional, v3)

Enabled via `ai.enabled = true`. All inference is local via Ollama.

### Model recommendation

`deepseek-r1:latest` (7b) for speed; `deepseek-r1:14b` for quality. Both already available on the user's machine.

In v3, the AI may also refine session length suggestions based on task type and historical patterns (e.g. "writing tasks tend to need longer focus blocks for this user").

### 12.1 Estimation prompt

```
System: You are a task estimation assistant. Respond with JSON only.

User:   Task title: {title}
        Description: {body_excerpt}
        Labels: {labels}
        Priority: {priority}
        Size: {size}
        
        Historical similar tasks (title | estimated_hours | actual_hours):
        {top_5_similar}
        
        Suggest an estimate in hours.
        Response: {"suggested_hours": 2.0, "confidence": "high|medium|low", "reasoning": "..."}
```

### 12.2 Conflict resolution prompt

```
System: You are a task management assistant. Respond with JSON only.

User:   Field "{field}" conflicts between GitHub and {other_source}.
        GitHub value: {value_github}
        {other_source} value: {value_other}
        GitHub is the source of truth.
        
        Response: {"recommendation": "github|other", "reasoning": "..."}
```

---

## 13. launchd Plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.nstd.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>{VENV_PATH}/bin/nstd</string>
        <string>sync</string>
        <string>--daemon</string>
    </array>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>StandardOutPath</key>
    <string>/tmp/nstd.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/nstd.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

`{VENV_PATH}` is substituted with the actual venv path at setup time.

---

## 14. Python Dependencies

```
# requirements.txt
PyGithub>=2.1.1
gql[httpx]>=3.5.0
httpx>=0.27.0
jira>=3.8.0
asana>=5.0.0
google-api-python-client>=2.130.0
google-auth-oauthlib>=1.2.0
textual>=0.61.0
keyring>=25.0.0
ollama>=0.2.0
click>=8.1.7
rich>=13.7.0

# requirements-dev.txt
pytest>=8.0.0
pytest-cov>=5.0.0
pytest-asyncio>=0.23.0
responses>=0.25.0
respx>=0.21.0
freezegun>=1.4.0
factory-boy>=3.3.0
```

---

## 15. Error Handling and Resilience

- All API calls use retry logic with exponential backoff (max 3 retries, base delay 1s)
- Rate limit headers respected: 429 → sleep until `X-RateLimit-Reset`
- Failed sync of one source does not abort others — errors logged, cycle continues
- Calendar poll failure does not abort task sync — logged separately
- SQLite lock contention: daemon waits up to 30s before logging lock error
- Network unavailability: daemon logs "offline, skipping cycle" and retries at next interval

---

## 16. Privacy and Security

- No data sent to external services beyond GitHub, Jira, Asana, Google Calendar APIs
- AI estimation uses local Ollama only — no data egress
- API tokens stored in macOS Keychain, never on disk
- `config.toml` contains no secrets — safe for personal dotfiles version control
- SQLite database at `~/.config/nstd/nstd.db` with permissions `600`; startup checks and warns if incorrect
- Log output sanitised: logging filter strips values matching known API token patterns
- Config loader raises `ConfigurationError` if any value matches `(token|secret|password|api_key)\s*=\s*\S+`

---

## 17. Out of Scope for v1

- Weekly review view (v3)
- Estimation improvement loop / actual vs. planned report (v3)
- AI estimation and AI-refined session sizing (v3)
- Menu bar app / system tray
- Multi-user support
- Any network-facing API or server
- Mobile client
- Notification/alert system
- Automatic block placement without user confirmation

---

## 18. Open Questions (Resolve During Implementation)

1. **Jira start date field ID**: Discovered per-instance during `nstd setup`. Default guess: `customfield_10015`.
2. **Asana project GIDs**: User selects from list during `nstd setup`.
3. **GitHub PAT vs. GitHub App**: Fine-grained PAT assumed. GitHub App auth may be needed as fallback if `cncf` org requires it.
4. **Jira internal comment visibility role**: Confirmed during setup. Default: `"Service Desk Team"`.
5. **Google Calendar OAuth app**: User must create a Google Cloud project and download `client_secret.json`. Setup wizard provides exact instructions.
6. **Two launchd plists vs. one daemon process**: The task sync loop (15min) and calendar poll loop (10min) can be implemented as two separate launchd plists or as a single long-running daemon with internal timers. Implementation agent's choice — document the decision in `README.md`.
7. **Working hours and weekends**: Default working hours are 09:00–17:00; weekends are included by default (`scheduling.skip_weekends = false`). These should be prompted during `nstd setup`.

---

## 19. Testing Strategy (Mandatory TDD)

**Test-driven development is a hard requirement.** Tests are written before or alongside each feature. No feature ships without coverage.

These are all production systems actively in use. Unit tests must never make real API calls.

### 19.1 Principles

- **Unit tests**: All business logic, sync parsers, write-back, scheduling engine, config loading, DB operations. No real network calls. All external APIs mocked.
- **Integration tests**: Opt-in only. Read-only where possible. Never modify production data.
- **Coverage**: Minimum 80% line coverage on `nstd/` package, enforced in CI.

### 19.2 Mocking strategy

| External system | Mock approach |
|---|---|
| GitHub REST API | `responses` library; or `unittest.mock.patch` on `PyGithub` |
| GitHub GraphQL API | `respx` to mock `httpx` transport |
| Jira API | `unittest.mock.patch` on `jira.JIRA` client methods |
| Asana API | `unittest.mock.patch` on `asana` SDK methods |
| Google Calendar API | `unittest.mock.patch` on `googleapiclient` service object |
| Ollama | `unittest.mock.patch` on `ollama.Client` |
| macOS Keychain | `unittest.mock.patch` on `keyring.get_password` / `keyring.set_password` |
| SQLite | In-memory SQLite (`:memory:`) for all unit tests |
| System time | `freezegun` for all time-dependent logic |

### 19.3 Test data factories

```python
# tests/conftest.py (example)
import factory

class GitHubIssueFactory(factory.Factory):
    class Meta:
        model = dict
    number = factory.Sequence(lambda n: n + 100)
    title = factory.Faker('sentence', nb_words=5)
    body = factory.Faker('paragraph')
    state = "open"
    html_url = factory.LazyAttribute(
        lambda o: f"https://github.com/cncf/staff/issues/{o.number}"
    )
    assignees = factory.LazyFunction(lambda: [{"login": "nate-double-u"}])

class CalendarEventFactory(factory.Factory):
    class Meta:
        model = dict
    id = factory.Faker('uuid4')
    summary = factory.Faker('sentence', nb_words=4)
    start = factory.LazyFunction(lambda: {"dateTime": "2026-03-20T09:00:00-07:00"})
    end = factory.LazyFunction(lambda: {"dateTime": "2026-03-20T11:00:00-07:00"})
```

### 19.4 Key test scenarios (required coverage)

**Config**
- [ ] `config.toml` with no secrets loads successfully
- [ ] `config.toml` containing a token value raises `ConfigurationError`
- [ ] Missing required fields raise appropriate errors

**GitHub sync**
- [ ] Issue assigned to configured user is synced
- [ ] Issue assigned to bot account is not synced
- [ ] Issue body with Jira link is parsed and link recorded
- [ ] Issue body with no Jira link records no link
- [ ] GraphQL response maps `Due Date`, `Start Date`, `Priority`, `Size` correctly
- [ ] Pagination followed when `hasNextPage = true`

**Jira sync**
- [ ] Assigned issues in configured projects are synced
- [ ] Issues in non-configured projects are not synced
- [ ] Closed issues filtered by JQL

**Asana sync**
- [ ] Assigned tasks are synced
- [ ] Tasks in configured `project_gids` are synced regardless of assignee
- [ ] Duplicate tasks (assigned AND in project) deduplicated

**Write-back**
- [ ] Closing linked GitHub Issue triggers Jira transition
- [ ] Closing linked GitHub Issue marks Asana task complete
- [ ] Jira/Asana done triggers GitHub Issue close
- [ ] No linked item → no action, no error
- [ ] Failed Jira transition logged, does not crash sync

**Conflict detection**
- [ ] Field changed in both GitHub and Jira → conflict recorded
- [ ] Field changed only in GitHub → no conflict
- [ ] `always_ask` mode → conflict not auto-resolved
- [ ] Resolved conflict not re-raised

**Scheduling engine**
- [ ] `available_hours` correctly subtracts existing NSTD Planning blocks
- [ ] `available_hours` correctly subtracts observed calendar events
- [ ] Observed calendar event at 3–4pm → suggested block does not overlap 3–4pm
- [ ] Task with 6h estimate, 2h preferred session, 3 available days → 3 × 2h sessions suggested
- [ ] Task with 6h estimate, window too tight (1 available day at 2h cap) → partial suggestion + warning flag
- [ ] Session clamped to `max_block_hours` (4h)
- [ ] Session not created below `min_block_hours` (15min)
- [ ] Scheduling past `due_date` → warning flag set, block still suggested
- [ ] `remaining_hours = estimate_hours - future_block_hours` (past blocks excluded)
- [ ] Task with all past blocks and open issue → `time_elapsed` nudge status
- [ ] Task with no blocks and `estimate_hours` set → `unscheduled` nudge status
- [ ] Task with no `estimate_hours` and `due_date` set → `needs_estimate` nudge status
- [ ] Task with future blocks covering remaining hours → `on_track`, no nudge

**Google Calendar**
- [ ] Block created with correct title (issue title only, no prefix)
- [ ] Block description contains GitHub issue URL as first line
- [ ] Block description contains priority, size, due date where available
- [ ] Closed task → future blocks get `✓ ` prefix and Graphite colour
- [ ] Block recorded in `calendar_blocks` table with correct `task_id`
- [ ] Calendar poll marks past blocks as `is_past = 1`
- [ ] Orphaned block (task closed, block future) flagged in calendar tab

**Security**
- [ ] Log output does not contain API token values
- [ ] DB file path has `600` permissions check on startup

### 19.5 Integration test safety rules

`tests/integration/README.md` documents:
- Required environment variables (`NSTD_TEST_GITHUB_TOKEN`, etc.)
- Variables must be scoped to test resources only
- Dedicated test calendar: `NSTD Planning TEST`
- Run with: `pytest tests/integration/ -m integration` (never runs by default)
- Cleanup instructions

### 19.6 CI configuration

`.github/workflows/test.yml`:
- Runs on every push and PR
- Executes `pytest tests/unit/ --cov=nstd --cov-fail-under=80`
- Never runs integration tests
- Caches pip dependencies

---

## 20. Implementation Order (Suggested Build Sequence)

1. **Project scaffold**: `pyproject.toml`, package structure, `pytest` config, CI workflow
2. **Config module**: Load/validate `config.toml`; Keychain read/write; security checks
3. **DB module**: Schema creation, upsert helpers, query helpers (`:memory:` in tests)
4. **GitHub sync**: REST issue fetch, GraphQL project fields, Jira link detection
5. **Jira sync**: JQL fetch, field mapping
6. **Asana sync**: Assigned tasks + project tasks, deduplication
7. **Write-back**: Jira transition, Asana completion, GitHub close
8. **Conflict detection**: Detection logic, `conflicts` table population
9. **Google Calendar — read**: OAuth setup, event read, availability model
10. **Scheduling engine**: Availability modelling, session suggestion algorithm, nudge evaluation
11. **Google Calendar — write**: Block creation, update, lifecycle management
12. **Sync daemon**: Orchestration of task sync + calendar poll loops, error isolation, logging
13. **launchd setup** (`nstd setup` wizard): Interactive setup, plist generation
14. **TUI**: Textual app, all tabs, scheduling dialog, keybindings
15. **CLI**: `click` commands wiring everything together
16. **AI estimation** (`nstd/ai/estimate.py`): Ollama integration, behind `ai.enabled` flag (v3)