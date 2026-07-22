"""Reconcile concrete Google Calendar event edits into NTT task schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.config import TrackerConfig
from notion_task_tracker.json_file import write_json_file
from notion_task_tracker.notion_operations.reconcile_task_database import (
    refresh_tracker_state_for_task_ids,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.write_executor import execute_command_result_writes
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
    build_task_database_property_refresh_intent,
)
from notion_task_tracker.tasks import DurationUnit, Task, TaskStatus, TaskTree


@dataclass(frozen=True)
class CalendarTaskScheduleChange:
    event_id: str
    task_id: str
    start: str
    duration: float
    duration_unit: DurationUnit


@dataclass(frozen=True)
class CalendarEditReconciliationSummary:
    task_ids: list[str]
    completed_operation_keys: list[str]
    warnings: list[dict[str, str]]


async def reconcile_changed_google_calendar_events(
    changed_events: list[dict[str, Any]],
    config: TrackerConfig,
    tracker_state_path: str | Path,
    notion_client: NotionRestClient,
) -> CalendarEditReconciliationSummary:
    if config.calendar is None:
        raise ValueError("Configure [calendar] before reconciling Google Calendar edits")

    source_tracker_state_path = Path(tracker_state_path)
    tracker_state = json.loads(source_tracker_state_path.read_text(encoding="utf-8"))
    task_ids = task_ids_from_owned_calendar_events(changed_events, config.ticket_prefix)
    refreshed_result = await refresh_tracker_state_for_task_ids(
        task_ids=task_ids,
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    planned_updates = plan_task_schedule_updates_from_calendar_events(
        changed_events=changed_events,
        tracker_state=refreshed_result.tracker_state,
        tracker_id=config.ticket_prefix,
        timezone_name=config.calendar.timezone_name,
    )
    planned_updates = TrackerCommandResult(
        tracker_state=planned_updates.tracker_state,
        write_intents=planned_updates.write_intents,
        page_registry=planned_updates.page_registry,
        warnings=list(refreshed_result.warnings or []),
        refreshed_task_ids=frozenset(task_ids),
    )
    updated_tracker_state, completed_operation_keys = await execute_command_result_writes(
        planned_updates,
        notion_client,
    )
    write_json_file(updated_tracker_state, source_tracker_state_path)
    return CalendarEditReconciliationSummary(
        task_ids=task_ids,
        completed_operation_keys=completed_operation_keys,
        warnings=list(refreshed_result.warnings or []),
    )


def plan_task_schedule_updates_from_calendar_events(
    changed_events: list[dict[str, Any]],
    tracker_state: dict[str, Any],
    tracker_id: str,
    timezone_name: str,
) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    schedule_changes = _derive_unambiguous_task_schedule_changes(
        changed_events,
        task_tree,
        tracker_id,
        ZoneInfo(timezone_name),
    )

    for change in schedule_changes:
        task_tree.replace_task_schedule(
            task_id=change.task_id,
            start=change.start,
            duration=change.duration,
            duration_unit=change.duration_unit,
        )

    updated_tracker_state = dict(tracker_state)
    updated_tracker_state.update(task_tree.to_tracker_state())
    return TrackerCommandResult(
        tracker_state=updated_tracker_state,
        write_intents=[
            build_task_database_property_refresh_intent(task_tree.tasks[change.task_id])
            for change in schedule_changes
        ],
        page_registry=build_page_registry_for_task_tree(task_tree),
    )


def task_ids_from_owned_calendar_events(
    changed_events: list[dict[str, Any]],
    tracker_id: str,
) -> list[str]:
    task_ids = []
    for event in changed_events:
        event_id = _required_event_id(event)
        private_properties = event.get("extendedProperties", {}).get("private", {})
        if private_properties.get("ntt_tracker") != tracker_id:
            raise ValueError(f"Google event {event_id} is not owned by tracker {tracker_id}")
        task_id = private_properties.get("ntt_task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"Google event {event_id} has no stable ntt_task_id")
        if task_id in task_ids:
            raise ValueError(f"Multiple changed Google events claim task identity {task_id}")
        task_ids.append(task_id)
    return task_ids


def _derive_unambiguous_task_schedule_changes(
    changed_events: list[dict[str, Any]],
    task_tree: TaskTree,
    tracker_id: str,
    timezone: ZoneInfo,
) -> list[CalendarTaskScheduleChange]:
    task_ids = task_ids_from_owned_calendar_events(changed_events, tracker_id)
    schedule_changes = []
    for event, task_id in zip(changed_events, task_ids, strict=True):
        task = _calendar_editable_leaf_task(task_tree, task_id)
        schedule_changes.append(_derive_task_schedule_change(event, task, timezone))
    return schedule_changes


def _calendar_editable_leaf_task(task_tree: TaskTree, task_id: str) -> Task:
    task = task_tree.tasks.get(task_id)
    if task is None:
        raise ValueError(f"Google event identifies unknown task {task_id}")
    if task.status != TaskStatus.ACTIVE:
        raise ValueError(f"Google event identifies non-active task {task_id}")
    if task.child_task_ids:
        raise ValueError(f"Google event identifies parent task {task_id}")
    return task


def _derive_task_schedule_change(
    event: dict[str, Any],
    task: Task,
    timezone: ZoneInfo,
) -> CalendarTaskScheduleChange:
    event_id = _required_event_id(event)
    if event.get("status") == "cancelled":
        raise ValueError(f"Google event {event_id} is cancelled and has no schedule to reconcile")

    start_boundary = event.get("start", {})
    end_boundary = event.get("end", {})
    if "dateTime" in start_boundary and "dateTime" in end_boundary:
        start, duration = _timed_schedule_from_event(event_id, start_boundary, end_boundary, timezone)
        duration_unit = DurationUnit.HOURS
    elif "date" in start_boundary and "date" in end_boundary:
        start, duration, duration_unit = _all_day_schedule_from_event(
            event_id,
            start_boundary,
            end_boundary,
            task.duration_unit,
        )
    else:
        raise ValueError(f"Google event {event_id} must have matching timed or all-day boundaries")

    return CalendarTaskScheduleChange(
        event_id=event_id,
        task_id=task.task_id,
        start=start,
        duration=duration,
        duration_unit=duration_unit,
    )


def _timed_schedule_from_event(
    event_id: str,
    start_boundary: dict[str, Any],
    end_boundary: dict[str, Any],
    timezone: ZoneInfo,
) -> tuple[str, float]:
    start_date_time = _aware_date_time(event_id, "start", start_boundary["dateTime"])
    end_date_time = _aware_date_time(event_id, "end", end_boundary["dateTime"])
    duration_hours = (end_date_time.astimezone(UTC) - start_date_time.astimezone(UTC)).total_seconds() / 3600
    if duration_hours <= 0:
        raise ValueError(f"Google event {event_id} must end after it starts")
    return start_date_time.astimezone(timezone).isoformat(), duration_hours


def _all_day_schedule_from_event(
    event_id: str,
    start_boundary: dict[str, Any],
    end_boundary: dict[str, Any],
    existing_duration_unit: DurationUnit | None,
) -> tuple[str, float, DurationUnit]:
    start_date = date.fromisoformat(start_boundary["date"])
    end_date = date.fromisoformat(end_boundary["date"])
    duration_days = (end_date - start_date).days
    if duration_days <= 0:
        raise ValueError(f"Google event {event_id} must end after it starts")
    if existing_duration_unit == DurationUnit.WEEKS and duration_days % 7 == 0:
        return start_date.isoformat(), duration_days / 7, DurationUnit.WEEKS
    return start_date.isoformat(), float(duration_days), DurationUnit.DAYS


def _aware_date_time(event_id: str, boundary_name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Google event {event_id} {boundary_name} dateTime must be a string")
    date_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date_time.tzinfo is None:
        raise ValueError(f"Google event {event_id} {boundary_name} dateTime must include a UTC offset")
    return date_time


def _required_event_id(event: dict[str, Any]) -> str:
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("Changed Google event has no id")
    return event_id
