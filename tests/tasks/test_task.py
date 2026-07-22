from notion_task_tracker.tasks import DurationUnit
from notion_task_tracker.tasks.task import derive_task_end


def test_derive_task_end_leaves_unscheduled_duration_estimate_without_end():
    assert derive_task_end(
        task_label="ALOVYA-1",
        start=None,
        duration=2.5,
        duration_unit=DurationUnit.HOURS,
    ) is None


def test_derive_task_end_adds_fractional_hours_to_timed_start():
    assert derive_task_end(
        task_label="ALOVYA-1",
        start="2026-07-22T09:30:00+01:00",
        duration=2.5,
        duration_unit=DurationUnit.HOURS,
    ) == "2026-07-22T12:00:00+01:00"


def test_derive_task_end_adds_seven_calendar_days_per_week():
    assert derive_task_end(
        task_label="ALOVYA-1",
        start="2026-07-22",
        duration=2,
        duration_unit=DurationUnit.WEEKS,
    ) == "2026-08-05"
