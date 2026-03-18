"""Tests for nstd.calendar.scheduler — written BEFORE implementation (TDD).

This is the most test-heavy module per the spec (§8.5, §19.4).
"""

from datetime import date, datetime, time, timedelta

import pytest
from freezegun import freeze_time


@pytest.fixture
def default_scheduling_config():
    """Default scheduling configuration."""
    from nstd.config import SchedulingConfig

    return SchedulingConfig(
        max_hours_per_day=8,
        preferred_session_hours=2.0,
        min_block_hours=0.25,
        max_block_hours=4.0,
        work_start="09:00",
        work_end="17:00",
        skip_weekends=False,
    )


class TestAvailabilityModel:
    """Test availability modelling (§8.5.1)."""

    def test_empty_calendar_gives_full_availability(self, default_scheduling_config):
        """Day with no events has max_hours_per_day available."""
        from nstd.calendar.scheduler import build_availability

        day = date(2026, 3, 18)  # Wednesday
        avail = build_availability(
            days=[day],
            existing_nstd_blocks=[],
            observed_events=[],
            config=default_scheduling_config,
        )

        assert avail[day]["available_hours"] == 8.0

    def test_nstd_blocks_reduce_availability(self, default_scheduling_config):
        """Existing NSTD Planning blocks reduce available hours."""
        from nstd.calendar.scheduler import build_availability

        day = date(2026, 3, 18)
        avail = build_availability(
            days=[day],
            existing_nstd_blocks=[
                {
                    "start": datetime(2026, 3, 18, 9, 0),
                    "end": datetime(2026, 3, 18, 11, 0),
                },  # 2h block
            ],
            observed_events=[],
            config=default_scheduling_config,
        )

        assert avail[day]["available_hours"] == 6.0

    def test_observed_events_reduce_availability(self, default_scheduling_config):
        """Events on observed calendars reduce available hours."""
        from nstd.calendar.scheduler import build_availability

        day = date(2026, 3, 18)
        avail = build_availability(
            days=[day],
            existing_nstd_blocks=[],
            observed_events=[
                {
                    "start": datetime(2026, 3, 18, 13, 0),
                    "end": datetime(2026, 3, 18, 14, 30),
                },  # 1.5h meeting
            ],
            config=default_scheduling_config,
        )

        assert avail[day]["available_hours"] == 6.5

    def test_observed_event_blocks_specific_time_slot(self, default_scheduling_config):
        """Observed events occupy specific slots; suggested blocks must not overlap."""
        from nstd.calendar.scheduler import build_availability

        day = date(2026, 3, 18)
        avail = build_availability(
            days=[day],
            existing_nstd_blocks=[],
            observed_events=[
                {
                    "start": datetime(2026, 3, 18, 15, 0),
                    "end": datetime(2026, 3, 18, 16, 0),
                },  # 3-4pm meeting
            ],
            config=default_scheduling_config,
        )

        # The 3-4pm slot should be marked as occupied
        slots = avail[day]["occupied_slots"]
        assert any(
            s["start"] == datetime(2026, 3, 18, 15, 0) and s["end"] == datetime(2026, 3, 18, 16, 0)
            for s in slots
        )

    def test_availability_capped_at_max_hours(self, default_scheduling_config):
        """Available hours never exceed max_hours_per_day."""
        from nstd.calendar.scheduler import build_availability

        default_scheduling_config.max_hours_per_day = 4
        day = date(2026, 3, 18)
        avail = build_availability(
            days=[day],
            existing_nstd_blocks=[],
            observed_events=[],
            config=default_scheduling_config,
        )

        assert avail[day]["available_hours"] == 4.0

    def test_zero_availability_day(self, default_scheduling_config):
        """Day fully booked has 0 availability."""
        from nstd.calendar.scheduler import build_availability

        day = date(2026, 3, 18)
        avail = build_availability(
            days=[day],
            existing_nstd_blocks=[],
            observed_events=[
                {
                    "start": datetime(2026, 3, 18, 9, 0),
                    "end": datetime(2026, 3, 18, 17, 0),
                },  # 8h all-day meeting
            ],
            config=default_scheduling_config,
        )

        assert avail[day]["available_hours"] == 0.0


class TestSessionSuggestion:
    """Test session suggestion algorithm (§8.5.2)."""

    def test_basic_suggestion_distributes_across_days(self, default_scheduling_config):
        """6h estimate, 2h sessions, 3 available days -> 3 x 2h sessions."""
        from nstd.calendar.scheduler import suggest_sessions

        result = suggest_sessions(
            estimate_hours=6.0,
            hours_already_scheduled=0.0,
            start_date=date(2026, 3, 18),
            due_date=date(2026, 3, 20),
            availability={
                date(2026, 3, 18): {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 19): {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 20): {"available_hours": 8.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
        )

        assert len(result["sessions"]) == 3
        for s in result["sessions"]:
            assert s["duration_hours"] == 2.0

    def test_remaining_hours_zero_suggests_nothing(self, default_scheduling_config):
        """When already_scheduled >= estimate, no sessions suggested."""
        from nstd.calendar.scheduler import suggest_sessions

        result = suggest_sessions(
            estimate_hours=4.0,
            hours_already_scheduled=4.0,
            start_date=date(2026, 3, 18),
            due_date=date(2026, 3, 25),
            availability={
                date(2026, 3, 18): {"available_hours": 8.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
        )

        assert len(result["sessions"]) == 0

    def test_session_clamped_to_max_block_hours(self, default_scheduling_config):
        """Session duration capped at max_block_hours (4h)."""
        from nstd.calendar.scheduler import suggest_sessions

        default_scheduling_config.preferred_session_hours = 6.0  # Over max

        result = suggest_sessions(
            estimate_hours=8.0,
            hours_already_scheduled=0.0,
            start_date=date(2026, 3, 18),
            due_date=date(2026, 3, 19),
            availability={
                date(2026, 3, 18): {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 19): {"available_hours": 8.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
        )

        for s in result["sessions"]:
            assert s["duration_hours"] <= 4.0

    def test_session_not_created_below_min_block_hours(self, default_scheduling_config):
        """Day with less than min_block_hours available is skipped."""
        from nstd.calendar.scheduler import suggest_sessions

        result = suggest_sessions(
            estimate_hours=2.0,
            hours_already_scheduled=0.0,
            start_date=date(2026, 3, 18),
            due_date=date(2026, 3, 19),
            availability={
                date(2026, 3, 18): {"available_hours": 0.1, "occupied_slots": []},  # <15min
                date(2026, 3, 19): {"available_hours": 8.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
        )

        # First day skipped, second day gets the session
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["date"] == date(2026, 3, 19)

    def test_tight_window_flags_warning(self, default_scheduling_config):
        """When not enough time to schedule all hours, a warning is flagged."""
        from nstd.calendar.scheduler import suggest_sessions

        result = suggest_sessions(
            estimate_hours=10.0,
            hours_already_scheduled=0.0,
            start_date=date(2026, 3, 18),
            due_date=date(2026, 3, 18),
            availability={
                date(2026, 3, 18): {"available_hours": 2.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
        )

        assert result["warning"] is not None
        assert (
            "not enough time" in result["warning"].lower() or "tight" in result["warning"].lower()
        )

    def test_null_start_date_defaults_to_today(self, default_scheduling_config):
        """When start_date is None, defaults to today."""
        from nstd.calendar.scheduler import suggest_sessions

        today = date(2026, 3, 18)
        result = suggest_sessions(
            estimate_hours=2.0,
            hours_already_scheduled=0.0,
            start_date=None,
            due_date=date(2026, 3, 20),
            availability={
                today: {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 19): {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 20): {"available_hours": 8.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
            today=today,
        )

        assert len(result["sessions"]) >= 1

    def test_null_due_date_uses_14_day_horizon(self, default_scheduling_config):
        """When due_date is None, plans up to 14 days out."""
        from nstd.calendar.scheduler import suggest_sessions

        today = date(2026, 3, 18)
        availability = {}
        for i in range(15):
            d = today + timedelta(days=i)
            availability[d] = {"available_hours": 8.0, "occupied_slots": []}

        result = suggest_sessions(
            estimate_hours=2.0,
            hours_already_scheduled=0.0,
            start_date=None,
            due_date=None,
            availability=availability,
            config=default_scheduling_config,
            today=today,
        )

        assert len(result["sessions"]) >= 1

    def test_session_avoids_occupied_slots(self, default_scheduling_config):
        """Suggested block start time avoids occupied slots."""
        from nstd.calendar.scheduler import suggest_sessions

        day = date(2026, 3, 18)
        result = suggest_sessions(
            estimate_hours=2.0,
            hours_already_scheduled=0.0,
            start_date=day,
            due_date=day,
            availability={
                day: {
                    "available_hours": 6.0,
                    "occupied_slots": [
                        {
                            "start": datetime(2026, 3, 18, 9, 0),
                            "end": datetime(2026, 3, 18, 11, 0),
                        },  # 9-11am occupied
                    ],
                },
            },
            config=default_scheduling_config,
        )

        assert len(result["sessions"]) == 1
        session = result["sessions"][0]
        # Should start at 11:00 or later, not 9:00
        assert session["start_time"] >= time(11, 0)

    def test_past_blocks_excluded_from_remaining_hours(self, default_scheduling_config):
        """remaining_hours = estimate - future_blocks (past blocks excluded)."""
        from nstd.calendar.scheduler import suggest_sessions

        # 10h estimate, 4h already scheduled for the future
        result = suggest_sessions(
            estimate_hours=10.0,
            hours_already_scheduled=4.0,
            start_date=date(2026, 3, 18),
            due_date=date(2026, 3, 25),
            availability={
                date(2026, 3, 18): {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 19): {"available_hours": 8.0, "occupied_slots": []},
                date(2026, 3, 20): {"available_hours": 8.0, "occupied_slots": []},
            },
            config=default_scheduling_config,
        )

        total_suggested = sum(s["duration_hours"] for s in result["sessions"])
        assert total_suggested == pytest.approx(6.0)  # 10 - 4 = 6 remaining


class TestSchedulingNudges:
    """Test scheduling nudge evaluation (§8.5.4)."""

    def test_unscheduled_task_with_estimate(self):
        """Open task with estimate and no future blocks → 'unscheduled'."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="open",
            estimate_hours=4.0,
            due_date="2026-03-25",
            future_block_hours=0.0,
            all_blocks_past=False,
            has_any_blocks=False,
        )

        assert nudge == "unscheduled"

    def test_needs_estimate_nudge(self):
        """Open task with due date but no estimate → 'needs_estimate'."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="open",
            estimate_hours=None,
            due_date="2026-03-25",
            future_block_hours=0.0,
            all_blocks_past=False,
            has_any_blocks=False,
        )

        assert nudge == "needs_estimate"

    def test_time_elapsed_nudge(self):
        """Open task with all blocks in the past → 'time_elapsed'."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="open",
            estimate_hours=4.0,
            due_date="2026-03-25",
            future_block_hours=0.0,
            all_blocks_past=True,
            has_any_blocks=True,
        )

        assert nudge == "time_elapsed"

    @freeze_time("2026-03-26")
    def test_overdue_nudge(self):
        """Open task past its due date → 'overdue'."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="open",
            estimate_hours=4.0,
            due_date="2026-03-25",
            future_block_hours=0.0,
            all_blocks_past=True,
            has_any_blocks=True,
        )

        assert nudge == "overdue"

    def test_on_track_no_nudge(self):
        """Task with future blocks covering estimate → None (on track)."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="open",
            estimate_hours=4.0,
            due_date="2026-03-25",
            future_block_hours=4.0,
            all_blocks_past=False,
            has_any_blocks=True,
        )

        assert nudge is None

    def test_closed_task_no_nudge(self):
        """Closed tasks never get nudges."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="closed",
            estimate_hours=4.0,
            due_date="2026-03-25",
            future_block_hours=0.0,
            all_blocks_past=True,
            has_any_blocks=True,
        )

        assert nudge is None

    def test_partially_scheduled_no_nudge(self):
        """Task with some future blocks but not covering full estimate → no nudge (for now)."""
        from nstd.calendar.scheduler import evaluate_nudge

        nudge = evaluate_nudge(
            state="open",
            estimate_hours=10.0,
            due_date="2026-03-25",
            future_block_hours=4.0,
            all_blocks_past=False,
            has_any_blocks=True,
        )

        assert nudge is None


class TestSlotFinding:
    """Test the slot-finding helper for edge cases."""

    def test_fits_before_first_event(self, default_scheduling_config):
        """Block fits in gap before first occupied slot."""
        from nstd.calendar.scheduler import suggest_sessions

        day = date(2026, 3, 18)
        result = suggest_sessions(
            estimate_hours=1.0,
            hours_already_scheduled=0.0,
            start_date=day,
            due_date=day,
            availability={
                day: {
                    "available_hours": 6.0,
                    "occupied_slots": [
                        {
                            "start": datetime(2026, 3, 18, 11, 0),
                            "end": datetime(2026, 3, 18, 12, 0),
                        },
                    ],
                },
            },
            config=default_scheduling_config,
        )

        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["start_time"] == time(9, 0)

    def test_fits_between_two_events(self, default_scheduling_config):
        """Block fits in gap between two occupied slots."""
        from nstd.calendar.scheduler import suggest_sessions

        day = date(2026, 3, 18)
        result = suggest_sessions(
            estimate_hours=1.0,
            hours_already_scheduled=0.0,
            start_date=day,
            due_date=day,
            availability={
                day: {
                    "available_hours": 5.0,
                    "occupied_slots": [
                        {"start": datetime(2026, 3, 18, 9, 0), "end": datetime(2026, 3, 18, 10, 0)},
                        {
                            "start": datetime(2026, 3, 18, 12, 0),
                            "end": datetime(2026, 3, 18, 14, 0),
                        },
                    ],
                },
            },
            config=default_scheduling_config,
        )

        assert len(result["sessions"]) == 1
        # Should start at 10:00 (after first slot ends)
        assert result["sessions"][0]["start_time"] == time(10, 0)

    def test_day_fully_booked_fallback(self, default_scheduling_config):
        """When no gap exists, falls back to work_start."""
        from nstd.calendar.scheduler import suggest_sessions

        day = date(2026, 3, 18)
        result = suggest_sessions(
            estimate_hours=2.0,
            hours_already_scheduled=0.0,
            start_date=day,
            due_date=day,
            availability={
                day: {
                    "available_hours": 2.0,
                    "occupied_slots": [
                        {"start": datetime(2026, 3, 18, 9, 0), "end": datetime(2026, 3, 18, 17, 0)},
                    ],
                },
            },
            config=default_scheduling_config,
        )

        # Still suggests a session (availability says 2h free), start_time falls back
        assert len(result["sessions"]) == 1
