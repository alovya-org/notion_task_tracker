"""Derive desired calendar events from scheduled leaf tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from notion_task_tracker.tasks import DurationUnit, Task, TaskStatus, TaskTree


NTT_EVENT_DESCRIPTION = "This is a personal task. Feel free to schedule a meeting over this slot."


@dataclass(frozen=True)
class DesiredCalendarEvent:
    task_id: str
    title: str
    description: str
    transparency: str
    start_date_time: datetime | None = None
    end_date_time: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None


def derive_desired_calendar_events(
    task_tree: TaskTree,
    timezone_name: str,
) -> list[DesiredCalendarEvent]:
    timezone = ZoneInfo(timezone_name)
    eligible_tasks = _select_calendar_eligible_leaf_tasks(task_tree)
    return [
        _derive_calendar_event_for_task(task, timezone)
        for task in eligible_tasks
    ]


def _select_calendar_eligible_leaf_tasks(task_tree: TaskTree) -> list[Task]:
    return [
        task
        for task in task_tree.tasks.values()
        if task.status == TaskStatus.ACTIVE
        and not task.child_task_ids
        and task.start is not None
        and task.end is not None
        and task.duration is not None
        and task.duration_unit is not None
    ]


def _derive_calendar_event_for_task(task: Task, timezone: ZoneInfo) -> DesiredCalendarEvent:
    common_fields = {
        "task_id": task.task_id,
        "title": f"[NTT] {task.title}",
        "description": NTT_EVENT_DESCRIPTION,
        "transparency": "transparent",
    }
    if task.duration_unit == DurationUnit.HOURS:
        start_date_time = datetime.fromisoformat(task.start).astimezone(timezone)
        end_date_time = (
            start_date_time.astimezone(UTC) + timedelta(hours=task.duration)
        ).astimezone(timezone)
        return DesiredCalendarEvent(
            **common_fields,
            start_date_time=start_date_time,
            end_date_time=end_date_time,
        )

    duration_days = int(task.duration)
    if task.duration_unit == DurationUnit.WEEKS:
        duration_days *= 7
    start_date = date.fromisoformat(task.start)
    return DesiredCalendarEvent(
        **common_fields,
        start_date=start_date,
        end_date=start_date + timedelta(days=duration_days),
    )
