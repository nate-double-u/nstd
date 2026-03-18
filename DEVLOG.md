# nstd Development Log

Persistent record of build progress, decisions, and outstanding work.
Canonical spec: `SPEC_Version4.md` (read-only, never modified).

## Phase Completion

| # | Phase | Status | PR | Notes |
|---|-------|--------|-----|-------|
| 1 | Project scaffold | ✅ Done | — | pyproject.toml, CI, ruff, pytest |
| 2 | Config module | ✅ Done | — | TOML config, dataclasses |
| 3 | Database module | ✅ Done | — | SQLite schema, CRUD helpers |
| 4 | GitHub sync | ✅ Done | — | REST + GraphQL, label mapping |
| 5 | Jira sync | ✅ Done | — | JQL queries, field mapping |
| 6 | Asana sync | ✅ Done | — | PAT auth, workspace/project fetch |
| 7 | Write-back | ✅ Done | — | Jira + Asana state writeback |
| 8 | Scheduler | ✅ Done | — | Time-block allocation engine |
| 9 | Conflict detection | ✅ Done | #5 | Field-level diff, resolution strategies |
| 10 | GCal read | ✅ Done | #6 | OAuth, event parsing, orphan detection |
| 11 | GCal write | ✅ Done | #7 | Block create/update/delete via API |
| 12 | Sync daemon | ✅ Done | #8 | Orchestration, launchd, polling |
| 13 | Setup wizard | ✅ Done | #9 | Interactive first-run, credential store |
| 14 | TUI | ✅ Done | #10 | Textual app, 4 tabs, key bindings |
| 15 | CLI | 🔄 In PR | #11 | Click commands, status/logs/config/block |
| 16 | AI estimation | ⏳ Deferred | — | Deferred to v3 per spec |

## Test Coverage

All modules target ≥95% coverage (`fail_under = 95` in pyproject.toml).

| Module | Tests | Notes |
|--------|-------|-------|
| config | 30 | TOML round-trip, validation |
| db | 38 | Schema, CRUD, query helpers |
| github sync | 14 | Label mapping, pagination |
| jira sync | 12 | JQL, field mapping |
| asana sync | 16 | Workspace + project fetch |
| writeback (jira) | 8 | State transitions |
| writeback (asana) | 7 | Completion writeback |
| conflicts | 27 | Detection, resolution |
| gcal read | 28 | Events, orphans, duration |
| gcal write | 23 | Create, update, delete blocks |
| scheduler | 29 | Allocation, constraints |
| daemon | 24 | Orchestration, error handling |
| setup wizard | 48 | TOML gen, credentials, plist |
| tui | 28 | Formatting, data loading, app |
| cli | 41 | All commands, config, error paths |

## Outstanding Work

### PR #11 (CLI) — awaiting merge
- All review threads resolved
- 41 tests, zero `pragma: no cover`

### Post-merge cleanup (new PR needed)
- [ ] Remove remaining `pragma: no cover` from merged modules
  - `setup.py`: 2 pragmas (Path.home() defaults — testable with mocking)
  - `daemon.py`: 4 pragmas (sync function calls, poll_fn guard)
  - `sync/asana.py`: 2 pragmas (API fetch functions — legitimate external API)
  - `sync/github.py`: 1 pragma (REST fetch — legitimate external API)
  - `sync/jira.py`: 1 pragma (client constructor — legitimate external API)
  - `writeback/asana.py`: 1 pragma (client constructor — legitimate external API)
  - `writeback/jira.py`: 1 pragma (client constructor — legitimate external API)
  - `calendar/gcal.py`: 1 pragma (OAuth service builder — legitimate external API)
- [ ] Update `.github/copilot-instructions.md` with phase completion checkmarks
- [ ] Add `comment_visibility_role` to JiraConfig dataclass (cross-branch issue from PR #9)

### Design Decisions (documented disagreements with online Copilot)
- **OAuth scope (GCal):** Using read/write scope from the start because PR #7 needs
  write access. Re-auth for scope upgrade is poor UX.
- **`_build_service` coverage:** Thin wrapper around Google OAuth SDK. Testing it means
  testing Google's library, not our code. Legitimate `no cover`.
- **`python-dateutil` vs stdlib:** `datetime.fromisoformat()` handles ISO 8601 fine
  on Python 3.11+, but `dateutil` is already a dep and more flexible. Low priority.
- **SQL in modules vs db helpers:** Refactored TUI queries into `nstd.db` per review
  feedback. Other modules may benefit from similar refactoring in future.

### v3 Features (from spec)
- Phase 16: AI-powered time estimation (OpenAI/Anthropic)
- Integration tests with live services
- End-to-end TUI wiring
