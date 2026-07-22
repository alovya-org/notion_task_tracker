from datetime import date, datetime

from notion_task_tracker.derive_calendar_events import derive_desired_calendar_events
from notion_task_tracker.tasks import DurationUnit, Priority, Task, TaskStatus, TaskTree


def test_derives_timed_and_all_day_events_for_active_scheduled_leaves():
    task_tree = TaskTree()
    task_tree.add_task(_scheduled_task("ALOVYA-1", "Timed work", "2026-07-30T23:30:00+01:00", 2.5, DurationUnit.HOURS))
    task_tree.add_task(_scheduled_task("ALOVYA-2", "Calendar week", "2026-08-03", 1, DurationUnit.WEEKS))

    events = derive_desired_calendar_events(task_tree, "Europe/London")

    assert events[0].start_date_time == datetime.fromisoformat("2026-07-30T23:30:00+01:00")
    assert events[0].end_date_time == datetime.fromisoformat("2026-07-31T02:00:00+01:00")
    assert events[0].title == "[NTT] Timed work"
    assert events[0].transparency == "transparent"
    assert events[1].start_date == date(2026, 8, 3)
    assert events[1].end_date == date(2026, 8, 10)


def test_excludes_parents_incomplete_schedules_and_finished_tasks():
    task_tree = TaskTree()
    parent = _scheduled_task("ALOVYA-1", "Parent", "2026-08-03", 1, DurationUnit.DAYS)
    child = _scheduled_task("ALOVYA-2", "Child", "2026-08-04", 1, DurationUnit.DAYS)
    incomplete = Task("ALOVYA-3", "Estimate only", Priority.P2, TaskStatus.ACTIVE, duration=2, duration_unit=DurationUnit.HOURS)
    complete = _scheduled_task("ALOVYA-4", "Finished", "2026-08-05", 1, DurationUnit.DAYS, TaskStatus.COMPLETE)
    for task in [parent, child, incomplete, complete]:
        task_tree.add_task(task)
    task_tree.link_parent_to_child("ALOVYA-1", "ALOVYA-2")

    events = derive_desired_calendar_events(task_tree, "Europe/London")

    assert [event.task_id for event in events] == ["ALOVYA-2"]


def test_hour_duration_keeps_elapsed_time_across_daylight_saving_change():
    task_tree = TaskTree()
    task_tree.add_task(
        _scheduled_task(
            "ALOVYA-1",
            "Cross the spring clock change",
            "2026-03-29T00:30:00+00:00",
            2,
            DurationUnit.HOURS,
        )
    )

    event = derive_desired_calendar_events(task_tree, "Europe/London")[0]

    assert event.start_date_time == datetime.fromisoformat("2026-03-29T00:30:00+00:00")
    assert event.end_date_time == datetime.fromisoformat("2026-03-29T03:30:00+01:00")


def _scheduled_task(
    task_id: str,
    title: str,
    start: str,
    duration: float,
    duration_unit: DurationUnit,
    status: TaskStatus = TaskStatus.ACTIVE,
) -> Task:
    from notion_task_tracker.tasks.task import derive_task_end

    return Task(
        task_id=task_id,
        title=title,
        configured_priority=Priority.P2,
        status=status,
        start=start,
        end=derive_task_end(task_id, start, duration, duration_unit),
        duration=duration,
        duration_unit=duration_unit,
    )
