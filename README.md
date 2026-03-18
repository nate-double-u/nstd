# nstd — "Nate's Stuff To Do"

A personal task synchronisation daemon and minimal TUI that unifies
GitHub Issues, Jira, Asana, and Google Calendar into a single local-first
system.

**GitHub is the source of truth.** `nstd` syncs tasks from Jira and Asana
into a local SQLite database, detects cross-system links, propagates
completion events, and helps you schedule focused work sessions on
Google Calendar.

## Features

- **Sync**: GitHub Issues + Projects v2, Jira Cloud, Asana → local SQLite
- **Write-back**: Close a GitHub Issue → Jira/Asana marked done (and vice versa)
- **Calendar**: Schedule work sessions on a dedicated Google Calendar
- **Scheduling engine**: Suggests time blocks based on estimates, due dates, and availability
- **Conflict detection**: Surfaces field disagreements between systems
- **TUI**: Operator panel for reviewing tasks, conflicts, and calendar blocks
- **Local-first**: All state on your machine. No cloud service required beyond the APIs.
- **Security**: Credentials in macOS Keychain, never on disk

## Quick Start

```bash
# Clone and install
git clone https://github.com/nate-double-u/nstd.git
cd nstd
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# First-run setup (configures APIs, creates config)
nstd setup

# Open the TUI
nstd

# Or run a single sync
nstd sync
```

## Configuration

Configuration lives at `~/.config/nstd/config.toml`. Secrets are stored in
macOS Keychain — the config file contains no credentials and is safe to
version-control in your dotfiles.

See [SPEC.md](SPEC_Version4.md) for full configuration schema.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run unit tests
pytest

# Run with coverage
pytest --cov=nstd --cov-report=term-missing

# Run integration tests (requires real API tokens)
pytest tests/integration/ -m integration
```

## Architecture

```
Source Systems          nstd sync daemon           Outputs
─────────────          ────────────────           ───────
GitHub Issues ──┐                              ┌── Google Calendar
Jira Cloud ─────┼──→  SQLite (local DB)  ──→──┤   (NSTD Planning)
Asana ──────────┘                              ├── TUI (operator panel)
                                               └── Write-back (Jira/Asana)
```

Single daemon process with two internal loops:
- **Task sync** (default: every 15 min) — fetches from all sources
- **Calendar poll** (default: every 10 min) — reads availability, updates blocks

## License

Code: [Apache License 2.0](LICENSE)
Documentation: [Creative Commons Attribution 4.0 International](LICENSE-docs)
