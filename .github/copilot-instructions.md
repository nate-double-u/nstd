# Copilot Instructions for nstd

## Project Overview

`nstd` ("Nate's Stuff To Do") is a personal task synchronisation daemon and minimal TUI that unifies GitHub Issues, Jira, Asana, and Google Calendar into a single local-first system. The canonical reference is `SPEC_Version4.md` in the repo root — read it before making significant changes.

**GitHub is the source of truth for tasks.** `nstd` is a sync engine and operator panel, not a daily UI. It never creates tasks or marks them done directly — it detects events in source systems and propagates them.

## User Context

The primary user and maintainer is the Head of Mentorship and Documentation at the Cloud Native Computing Foundation (CNCF). Communicate informally, skip preamble, be direct. Push back when you disagree. Don't be sycophantic.

## TDD Is Mandatory

Every feature uses Test-Driven Development. No exceptions.

1. **Red**: Write failing tests first
2. **Green**: Write the minimum code to pass
3. **Refactor**: Clean up while tests stay green

No code ships without test coverage. Unit tests must never make real API calls. Minimum 95% line coverage on the `nstd/` package, enforced in CI.

## Git Workflow

- **Always** create a new branch before making changes. Never commit directly to `main`.
- **Do not** commit or push until you've explained what changed and why, and received explicit approval.
- All commits must be signed and include DCO sign-off: `git commit -s -S`
- Include the Co-authored-by trailer: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## Architecture

- **Python 3.11+** — broad compatibility; `tomllib` is stdlib
- **Single daemon process** with two internal timer loops (task sync + calendar poll), not two launchd plists
- **SQLite** via stdlib `sqlite3` — local-first, no server
- **macOS Keychain** via `keyring` — credentials never touch disk unencrypted

### Package Structure

```
nstd/
├── cli.py              # click entry point
├── config.py           # TOML config + keyring credentials
├── db.py               # SQLite schema + data access
├── sync/               # Source system sync (github, jira, asana)
├── calendar/           # Google Calendar read/write + scheduling engine
├── writeback/          # Completion propagation (jira, asana)
├── tui/                # Textual TUI application
└── ai/                 # Ollama estimation (v3, behind flag)
```

## Testing Conventions

- Framework: `pytest` + `pytest-cov`
- All DB tests use `:memory:` SQLite
- Time-dependent tests use `freezegun`
- Test data uses `factory-boy` factories (defined in `tests/conftest.py`)

### Mocking Strategy (no real API calls in unit tests)

| System | Mock approach |
|---|---|
| GitHub REST | `responses` library or `unittest.mock.patch` on PyGithub |
| GitHub GraphQL | `respx` to mock `httpx` transport |
| Jira | `unittest.mock.patch` on `jira.JIRA` client methods |
| Asana | `unittest.mock.patch` on `asana` SDK methods |
| Google Calendar | `unittest.mock.patch` on `googleapiclient` service object |
| Ollama | `unittest.mock.patch` on `ollama.Client` |
| macOS Keychain | `unittest.mock.patch` on `keyring.get_password` / `keyring.set_password` |

Integration tests are opt-in (`pytest tests/integration/ -m integration`), never run in CI, and never modify production data.

## Security Invariants

These are enforced in code AND tested:

- `config.toml` must not contain secret values. The config loader raises `ConfigurationError` if a key matching `(token|secret|password|api_key)` appears.
- DB file permissions must be `600`; startup warns if not.
- API tokens must never appear in log output (sanitising logger filter).
- No data sent to external services beyond GitHub, Jira, Asana, Google Calendar APIs.
- AI estimation uses local Ollama only — no data egress.

## Build Order

Follow `SPEC_Version4.md` §20. Current status is tracked in session state, but the sequence is:

1. ~~Project scaffold~~ ✓
2. ~~Config module~~ ✓
3. DB module ← in progress
4. GitHub sync
5. Jira sync
6. Asana sync
7. Write-back
8. Conflict detection
9. Google Calendar — read
10. Scheduling engine
11. Google Calendar — write
12. Sync daemon
13. Setup wizard (`nstd setup`)
14. TUI
15. CLI
16. AI estimation (v3, deferred)

## What NOT To Do

- Don't skip tests or write code before tests
- Don't commit to `main` directly
- Don't add dependencies without justification
- Don't make real API calls in unit tests
- Don't put secrets in config files, logs, or source code
- Don't create tasks or mark them done — `nstd` syncs and propagates, it doesn't originate
