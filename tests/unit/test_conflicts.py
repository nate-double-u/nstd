"""Tests for conflict detection module.

Spec references:
  §6.6 — Conflict resolution
  §19  — Conflict detection test cases

Test cases from spec:
  - Field changed in both GitHub and Jira → conflict recorded
  - Field changed only in GitHub → no conflict
  - `always_ask` mode → conflict not auto-resolved
  - Resolved conflict not re-raised
"""

from __future__ import annotations

import pytest

from nstd.conflicts import detect_conflicts, resolve_conflict
from nstd.db import (
    create_schema,
    get_connection,
    get_unresolved_conflicts,
    record_conflict,
    upsert_task,
)


@pytest.fixture()
def conn():
    """In-memory SQLite connection with schema."""
    c = get_connection(":memory:")
    create_schema(c)
    yield c
    c.close()


def _make_task(task_id, source, **overrides):
    """Helper to build a minimal task dict."""
    base = {
        "id": task_id,
        "source": source,
        "source_id": task_id,
        "source_url": f"https://example.com/{task_id}",
        "title": "Test task",
        "body": None,
        "state": "open",
        "assignee": "nate-double-u",
        "priority": None,
        "size": None,
        "estimate_hours": None,
        "start_date": None,
        "due_date": None,
        "created_at": "2026-03-18T00:00:00Z",
        "updated_at": "2026-03-18T00:00:00Z",
    }
    base.update(overrides)
    return base


# --- Core detection tests ---


class TestDetectConflicts:
    """Tests for detect_conflicts function."""

    def test_field_changed_in_both_github_and_other_records_conflict(self, conn):
        """§19: Field changed in both GitHub and Jira → conflict recorded."""
        # Stored state: priority is "P2"
        stored = _make_task("gh:cncf/staff:100", "github", priority="P2")
        upsert_task(conn, stored)

        # GitHub now says P1, Jira says P3 — both changed from stored P2
        github_values = {"priority": "P1"}
        other_values = {"priority": "P3"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:100",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "priority"
        assert conflicts[0]["value_github"] == "P1"
        assert conflicts[0]["value_other"] == "P3"

        # Verify it was persisted
        unresolved = get_unresolved_conflicts(conn)
        assert len(unresolved) == 1
        assert unresolved[0]["task_id"] == "gh:cncf/staff:100"

    def test_field_changed_only_in_github_no_conflict(self, conn):
        """§19: Field changed only in GitHub → no conflict."""
        stored = _make_task("gh:cncf/staff:101", "github", priority="P2")
        upsert_task(conn, stored)

        # GitHub changed to P1, but Jira still has P2 (same as stored)
        github_values = {"priority": "P1"}
        other_values = {"priority": "P2"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:101",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 0
        assert len(get_unresolved_conflicts(conn)) == 0

    def test_field_changed_only_in_other_no_conflict(self, conn):
        """Only the other source changed — no conflict."""
        stored = _make_task("gh:cncf/staff:102", "github", priority="P2")
        upsert_task(conn, stored)

        # GitHub still P2, Jira changed to P3
        github_values = {"priority": "P2"}
        other_values = {"priority": "P3"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:102",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 0

    def test_both_changed_to_same_value_no_conflict(self, conn):
        """Both sources changed, but to the same value — no conflict."""
        stored = _make_task("gh:cncf/staff:103", "github", priority="P2")
        upsert_task(conn, stored)

        # Both changed from P2 to P1 — convergent change
        github_values = {"priority": "P1"}
        other_values = {"priority": "P1"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:103",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 0

    def test_multiple_fields_conflict(self, conn):
        """Multiple fields changed in both sources → multiple conflicts."""
        stored = _make_task(
            "gh:cncf/staff:104",
            "github",
            priority="P2",
            due_date="2026-04-01",
            state="open",
        )
        upsert_task(conn, stored)

        github_values = {"priority": "P1", "due_date": "2026-04-15", "state": "open"}
        other_values = {"priority": "P3", "due_date": "2026-05-01", "state": "open"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:104",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 2
        fields = {c["field"] for c in conflicts}
        assert fields == {"priority", "due_date"}

    def test_no_stored_task_raises_error(self, conn):
        """detect_conflicts requires the task to exist in DB."""
        with pytest.raises(ValueError, match="not found"):
            detect_conflicts(
                conn,
                task_id="gh:nonexistent:999",
                github_values={"priority": "P1"},
                other_values={"priority": "P2"},
                other_source="jira",
            )

    def test_none_values_handled_correctly(self, conn):
        """Null/None field values should be compared properly."""
        stored = _make_task("gh:cncf/staff:105", "github", due_date=None)
        upsert_task(conn, stored)

        # GitHub set a due date, other also set one (both changed from None)
        github_values = {"due_date": "2026-04-01"}
        other_values = {"due_date": "2026-05-01"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:105",
            github_values=github_values,
            other_values=other_values,
            other_source="asana",
        )

        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "due_date"

    def test_none_to_value_only_one_side_no_conflict(self, conn):
        """One side sets a field from None, other stays None — no conflict."""
        stored = _make_task("gh:cncf/staff:106", "github", due_date=None)
        upsert_task(conn, stored)

        github_values = {"due_date": "2026-04-01"}
        other_values = {"due_date": None}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:106",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 0

    def test_empty_values_dicts_no_conflicts(self, conn):
        """No fields to compare → no conflicts."""
        stored = _make_task("gh:cncf/staff:107", "github")
        upsert_task(conn, stored)

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:107",
            github_values={},
            other_values={},
            other_source="jira",
        )

        assert len(conflicts) == 0

    def test_only_common_fields_compared(self, conn):
        """Only fields present in BOTH value dicts are compared."""
        stored = _make_task("gh:cncf/staff:108", "github", priority="P2", due_date="2026-04-01")
        upsert_task(conn, stored)

        # GitHub provides priority, other provides due_date — no overlap
        github_values = {"priority": "P1"}
        other_values = {"due_date": "2026-05-01"}

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:108",
            github_values=github_values,
            other_values=other_values,
            other_source="jira",
        )

        assert len(conflicts) == 0


# --- Resolved conflict re-raise tests ---


class TestResolvedConflictNotReRaised:
    """§19: Resolved conflict not re-raised."""

    def test_resolved_conflict_not_re_raised(self, conn):
        """A conflict that was resolved should not be detected again for the same values."""
        stored = _make_task("gh:cncf/staff:200", "github", priority="P2")
        upsert_task(conn, stored)

        # First detection
        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:200",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
        )
        assert len(conflicts) == 1

        # Resolve it
        resolve_conflict(conn, conflicts[0]["id"], resolution="github_wins")

        # Same conflict values again — should not re-raise
        conflicts2 = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:200",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
        )
        assert len(conflicts2) == 0

    def test_new_values_after_resolution_can_conflict(self, conn):
        """After resolving, if values change AGAIN to new different values, that's a new conflict."""
        stored = _make_task("gh:cncf/staff:201", "github", priority="P2")
        upsert_task(conn, stored)

        # First conflict: P1 vs P3
        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:201",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
        )
        resolve_conflict(conn, conflicts[0]["id"], resolution="github_wins")

        # New conflict: P4 vs P5 (different values entirely)
        conflicts2 = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:201",
            github_values={"priority": "P4"},
            other_values={"priority": "P5"},
            other_source="jira",
        )
        assert len(conflicts2) == 1
        assert conflicts2[0]["value_github"] == "P4"
        assert conflicts2[0]["value_other"] == "P5"

    def test_unresolved_conflict_same_values_not_duplicated(self, conn):
        """If a conflict already exists unresolved with same values, don't create a duplicate."""
        stored = _make_task("gh:cncf/staff:202", "github", priority="P2")
        upsert_task(conn, stored)

        # First detection
        detect_conflicts(
            conn,
            task_id="gh:cncf/staff:202",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
        )

        # Same values again — should not create another
        conflicts2 = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:202",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
        )
        assert len(conflicts2) == 0

        # Only 1 unresolved conflict total
        assert len(get_unresolved_conflicts(conn)) == 1


# --- Resolution tests ---


class TestResolveConflict:
    """Tests for resolve_conflict function."""

    def test_resolve_github_wins(self, conn):
        """Resolve a conflict with github_wins resolution."""
        stored = _make_task("gh:cncf/staff:300", "github")
        upsert_task(conn, stored)
        conflict_id = record_conflict(
            conn,
            task_id="gh:cncf/staff:300",
            field="priority",
            value_github="P1",
            value_other="P3",
            other_source="jira",
        )

        resolve_conflict(conn, conflict_id, resolution="github_wins")

        unresolved = get_unresolved_conflicts(conn)
        assert len(unresolved) == 0

        # Verify the resolved record
        row = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
        assert row["resolution"] == "github_wins"
        assert row["resolved_at"] is not None

    def test_resolve_other_wins(self, conn):
        """Resolve a conflict with other_wins resolution."""
        stored = _make_task("gh:cncf/staff:301", "github")
        upsert_task(conn, stored)
        conflict_id = record_conflict(
            conn,
            task_id="gh:cncf/staff:301",
            field="due_date",
            value_github="2026-04-01",
            value_other="2026-05-01",
            other_source="asana",
        )

        resolve_conflict(conn, conflict_id, resolution="other_wins")

        row = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
        assert row["resolution"] == "other_wins"

    def test_resolve_manual(self, conn):
        """Resolve a conflict with manual resolution."""
        stored = _make_task("gh:cncf/staff:302", "github")
        upsert_task(conn, stored)
        conflict_id = record_conflict(
            conn,
            task_id="gh:cncf/staff:302",
            field="priority",
            value_github="P1",
            value_other="P3",
            other_source="jira",
        )

        resolve_conflict(conn, conflict_id, resolution="manual")

        row = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
        assert row["resolution"] == "manual"

    def test_resolve_invalid_resolution_raises(self, conn):
        """Only valid resolution values are accepted."""
        stored = _make_task("gh:cncf/staff:303", "github")
        upsert_task(conn, stored)
        conflict_id = record_conflict(
            conn,
            task_id="gh:cncf/staff:303",
            field="priority",
            value_github="P1",
            value_other="P3",
            other_source="jira",
        )

        with pytest.raises(ValueError, match="Invalid resolution"):
            resolve_conflict(conn, conflict_id, resolution="yolo")

    def test_resolve_nonexistent_conflict_raises(self, conn):
        """Resolving a conflict that doesn't exist should raise."""
        with pytest.raises(ValueError, match="not found"):
            resolve_conflict(conn, conflict_id=99999, resolution="github_wins")

    def test_resolve_already_resolved_raises(self, conn):
        """Cannot resolve a conflict that's already resolved."""
        stored = _make_task("gh:cncf/staff:304", "github")
        upsert_task(conn, stored)
        conflict_id = record_conflict(
            conn,
            task_id="gh:cncf/staff:304",
            field="priority",
            value_github="P1",
            value_other="P3",
            other_source="jira",
        )
        resolve_conflict(conn, conflict_id, resolution="github_wins")

        with pytest.raises(ValueError, match="already resolved"):
            resolve_conflict(conn, conflict_id, resolution="other_wins")


# --- always_ask mode tests ---


class TestAlwaysAskMode:
    """§19: always_ask mode → conflict not auto-resolved."""

    def test_always_ask_conflicts_stay_unresolved(self, conn):
        """In always_ask mode (the default), conflicts are never auto-resolved."""
        stored = _make_task("gh:cncf/staff:400", "github", priority="P2")
        upsert_task(conn, stored)

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:400",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
            mode="always_ask",
        )

        assert len(conflicts) == 1
        # Verify it remains unresolved
        unresolved = get_unresolved_conflicts(conn)
        assert len(unresolved) == 1
        assert unresolved[0]["resolved_at"] is None
        assert unresolved[0]["resolution"] is None

    def test_mode_defaults_to_always_ask(self, conn):
        """The default mode should be always_ask."""
        stored = _make_task("gh:cncf/staff:401", "github", priority="P2")
        upsert_task(conn, stored)

        # No mode parameter — should default to always_ask behavior
        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:401",
            github_values={"priority": "P1"},
            other_values={"priority": "P3"},
            other_source="jira",
        )

        assert len(conflicts) == 1
        unresolved = get_unresolved_conflicts(conn)
        assert unresolved[0]["resolution"] is None


# --- Edge cases ---


class TestConflictEdgeCases:
    """Edge case tests for conflict detection."""

    def test_conflict_with_asana_source(self, conn):
        """Conflicts work with Asana as the other source."""
        stored = _make_task("gh:cncf/staff:500", "github", state="open")
        upsert_task(conn, stored)

        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:500",
            github_values={"state": "closed"},
            other_values={"state": "done"},
            other_source="asana",
        )

        assert len(conflicts) == 1
        assert conflicts[0]["other_source"] == "asana"

    def test_string_comparison_is_case_sensitive(self, conn):
        """Field values should be compared case-sensitively."""
        stored = _make_task("gh:cncf/staff:501", "github", priority="P2")
        upsert_task(conn, stored)

        # "p1" vs "P1" — both changed from "P2", and they differ
        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:501",
            github_values={"priority": "p1"},
            other_values={"priority": "P1"},
            other_source="jira",
        )

        assert len(conflicts) == 1

    def test_unsupported_mode_raises(self, conn):
        """Unsupported conflict resolution modes should raise ValueError."""
        stored = _make_task("gh:cncf/staff:502", "github", priority="P2")
        upsert_task(conn, stored)

        with pytest.raises(ValueError, match="Unsupported conflict resolution mode"):
            detect_conflicts(
                conn,
                task_id="gh:cncf/staff:502",
                github_values={"priority": "P1"},
                other_values={"priority": "P3"},
                other_source="jira",
                mode="github_wins",
            )

    def test_numeric_field_int_vs_float_no_false_conflict(self, conn):
        """Numeric fields should not create false conflicts from int vs float."""
        stored = _make_task("gh:cncf/staff:503", "github", estimate_hours=4.0)
        upsert_task(conn, stored)

        # GitHub sends int 4, other sends float 4.0 — same value, no conflict
        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:503",
            github_values={"estimate_hours": 4},
            other_values={"estimate_hours": 4.0},
            other_source="jira",
        )

        assert len(conflicts) == 0

    def test_numeric_field_genuine_conflict(self, conn):
        """Numeric fields with genuinely different values should conflict."""
        stored = _make_task("gh:cncf/staff:504", "github", estimate_hours=4.0)
        upsert_task(conn, stored)

        # Both changed from 4.0 to different values
        conflicts = detect_conflicts(
            conn,
            task_id="gh:cncf/staff:504",
            github_values={"estimate_hours": 6},
            other_values={"estimate_hours": 8.0},
            other_source="jira",
        )

        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "estimate_hours"
