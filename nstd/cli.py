"""CLI entry point for nstd.

All commands per §10:
  nstd              - Open TUI (default)
  nstd setup        - Interactive first-run setup wizard
  nstd sync         - Run one full sync cycle and exit
  nstd sync --source github - Sync only one source
  nstd sync --daemon - Run continuously (used by launchd)
  nstd status       - Print last sync status to stdout
  nstd block <task-id> - Open scheduling dialog for a task
  nstd config       - Open config.toml in $EDITOR
  nstd logs         - Tail the sync log
"""

from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import click

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "nstd"
_DEFAULT_DB_PATH = _DEFAULT_CONFIG_DIR / "nstd.db"


def _get_db_path() -> str:
    """Get the database file path."""
    return str(_DEFAULT_DB_PATH)


def _get_version() -> str:
    """Get the package version from installed metadata."""
    try:
        return version("nstd")
    except PackageNotFoundError:
        return "0.1.0-dev"


def _safe_get_readonly_connection(db_path: str) -> sqlite3.Connection | None:
    """Open a read-only DB connection without WAL mode or schema creation.

    Used by status/logs commands to avoid side effects on the database.
    Returns None if the DB file doesn't exist.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@click.group(invoke_without_command=True)
@click.version_option(version=_get_version(), prog_name="nstd")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """nstd - Nate's Stuff To Do. Personal task synchronisation daemon and TUI."""
    if ctx.invoked_subcommand is None:
        # Default: launch TUI
        click.echo("Launching TUI... (not yet fully wired)")


@cli.command()
def setup() -> None:
    """Interactive first-run setup wizard."""
    click.echo("Starting setup wizard...")


@cli.command()
@click.option(
    "--source", type=click.Choice(["github", "jira", "asana"]), help="Sync only one source."
)
@click.option("--daemon", is_flag=True, help="Run continuously (used by launchd).")
@click.option("--dry-run", is_flag=True, help="Preview sync: read all sources, skip all writes.")
def sync(source: str | None, daemon: bool, dry_run: bool) -> None:
    """Run a sync cycle (one-shot or continuous)."""
    if daemon and dry_run:
        raise click.UsageError("--dry-run cannot be used with --daemon.")
    if daemon:
        click.echo("Starting daemon mode...")
        return

    # One-shot sync: load config, open DB, run task sync
    from nstd.config import ConfigurationError, load_config
    from nstd.daemon import run_task_sync
    from nstd.db import create_schema, get_connection

    try:
        config = load_config()
    except ConfigurationError as e:
        raise click.ClickException(f"Configuration error: {e}") from None

    db_path = _get_db_path()

    if dry_run:
        # Dry-run is strictly read-only (§6.7): no schema creation, no DB writes.
        conn = _safe_get_readonly_connection(db_path)
        if conn is None:
            raise click.ClickException(
                "Database not initialized. Run 'nstd sync' once without --dry-run first."
            )
    else:
        _DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        conn = get_connection(db_path)
        create_schema(conn)

    try:
        if dry_run:
            if source:
                click.echo(f"Dry run: syncing {source} (no writes)...")
            else:
                click.echo("Dry run: running full sync (no writes)...")
        elif source:
            click.echo(f"Syncing {source}...")
        else:
            click.echo("Running full sync...")

        result = run_task_sync(conn, config, dry_run=dry_run, source=source)

        if dry_run:
            _print_dry_run_summary(result)
        else:
            click.echo(
                f"Sync complete: fetched={result['total_fetched']} "
                f"updated={result['total_updated']}"
            )

        if result["errors"]:
            for err in result["errors"]:
                click.echo(f"  Error: {err}", err=True)
    finally:
        conn.close()


def _print_dry_run_summary(result: dict) -> None:
    """Print the dry-run summary block per spec §6.7."""
    click.echo("")
    click.echo("--- Dry-run summary ---")
    click.echo(f"Tasks fetched:           {result.get('total_fetched', 0)}")
    click.echo(f"Upserts skipped:         {result.get('total_updated', 0)}")
    click.echo(f"Links skipped:           {result.get('links_skipped', 0)}")
    click.echo(f"Write-backs skipped:     {result.get('writebacks_skipped', 0)}")
    click.echo(f"Calendar writes skipped: {result.get('calendar_writes_skipped', 0)}")
    errors = result.get("errors")
    if errors:
        click.echo(f"Errors:                  {len(errors)}")


@cli.command()
def status() -> None:
    """Print last sync status to stdout."""
    db_path = _get_db_path()
    conn = _safe_get_readonly_connection(db_path)

    if conn is None:
        click.echo("No sync has been run yet (never synced). Run 'nstd setup' first.")
        return

    try:
        row = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        click.echo("No sync has been run yet (never synced).")
        return
    finally:
        conn.close()

    if row is None:
        click.echo("No sync has been run yet (never synced).")
        return

    click.echo(
        f"Last sync: {row['started_at']} | Status: {row['status']} | "
        f"Fetched: {row['records_fetched']} | Updated: {row['records_updated']}"
    )


@cli.command()
@click.argument("task_id")
def block(task_id: str) -> None:
    """Open scheduling dialog for a task."""
    click.echo(f"Opening scheduling dialog for {task_id}...")


@cli.command("config")
def config_cmd() -> None:
    """Open config.toml in $EDITOR."""
    config_path = _DEFAULT_CONFIG_DIR / "config.toml"
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR", "vi")

    if not config_path.exists():
        click.echo(f"Config file not found: {config_path}")
        click.echo("Run 'nstd setup' first.")
        return

    cmd = [*shlex.split(editor), str(config_path)]
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError:
        raise click.ClickException(f"Editor not found: {editor}") from None
    if result.returncode != 0:
        raise click.ClickException(f"Editor exited with code {result.returncode}")


@cli.command()
def logs() -> None:
    """Show recent sync log entries."""
    db_path = _get_db_path()
    conn = _safe_get_readonly_connection(db_path)

    if conn is None:
        click.echo("No sync log entries found. Run 'nstd setup' first.")
        return

    try:
        rows = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 20").fetchall()
    except sqlite3.Error:
        click.echo("No sync log entries found.")
        return
    finally:
        conn.close()

    if not rows:
        click.echo("No sync log entries found.")
        return

    for row in rows:
        source = row["source"] or "all"
        click.echo(
            f"{row['started_at']}  {source:>8}  "
            f"{row['status']:>7}  fetched={row['records_fetched']}  "
            f"updated={row['records_updated']}"
        )


def main() -> None:
    """Entry point for the nstd CLI."""
    cli()
