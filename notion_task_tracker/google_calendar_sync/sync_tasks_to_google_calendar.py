"""Sync scheduled tracker tasks to owned Google Calendar events."""

from __future__ import annotations

import json
from typing import Protocol
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from notion_task_tracker.config import TrackerConfig, load_config
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import GoogleCalendarClient
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import DurationUnit, Task, TaskStatus, TaskTree
from notion_task_tracker.tracker_action_execution_summary import TrackerActionExecutionSummary


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


@dataclass(frozen=True)
class CalendarEventReplacement:
    event_id: str
    event: dict[str, Any]


@dataclass(frozen=True)
class GoogleCalendarUpdatePlan:
    events_to_create: list[dict[str, Any]]
    events_to_replace: list[CalendarEventReplacement]
    event_ids_to_delete: list[str]
    warnings: list[dict[str, str]]


class _RefreshTasksFromNotion(Protocol):
    async def __call__(
        self,
        config: TrackerConfig | None,
        tracker_state_path: str | Path,
        output_path: str | Path,
        backup_path: str | Path | None,
        notion_client: NotionRestClient | None,
    ) -> TrackerActionExecutionSummary: ...


async def sync_tasks_to_google_calendar(
    config: TrackerConfig | None,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: NotionRestClient | None,
    google_calendar_client: GoogleCalendarClient | None,
    refresh_tasks_from_notion: _RefreshTasksFromNotion,
) -> TrackerActionExecutionSummary:
    configured_tracker = config or load_config()
    if configured_tracker.calendar is None:
        raise ValueError("Configure [calendar] before syncing tasks to Google Calendar")

    refresh_summary = await refresh_tasks_from_notion(
        config=configured_tracker,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        backup_path=backup_path,
        notion_client=notion_client,
    )
    refreshed_tracker_state = _read_json(Path(tracker_state_path))
    desired_events = derive_desired_calendar_events(
        TaskTree.from_tracker_state(refreshed_tracker_state),
        configured_tracker.calendar.timezone_name,
    )
    calendar_client = google_calendar_client or GoogleCalendarClient.from_environment(
        configured_tracker.calendar.calendar_id,
    )
    existing_events = await calendar_client.list_all_calendar_events({
        "privateExtendedProperty": f"ntt_tracker={configured_tracker.ticket_prefix}",
        "showDeleted": "false",
    })
    update_plan = plan_google_calendar_updates(
        desired_events=desired_events,
        existing_events=existing_events,
        tracker_id=configured_tracker.ticket_prefix,
        timezone_name=configured_tracker.calendar.timezone_name,
        colour_id=configured_tracker.calendar.colour_id,
    )
    calendar_operation_keys = await _execute_google_calendar_updates(
        update_plan,
        calendar_client,
    )

    execution_summary = TrackerActionExecutionSummary(
        action_name="sync_tasks_to_google_calendar",
        output_path=Path(output_path),
        tracker_state_path=Path(tracker_state_path),
        warnings=[*refresh_summary.warnings, *update_plan.warnings],
        backup_path=refresh_summary.backup_path,
        completed_operation_keys=refresh_summary.completed_operation_keys,
        task_tree_changes=refresh_summary.task_tree_changes,
        task_count=refresh_summary.task_count,
        repair_operation_count=refresh_summary.repair_operation_count,
        calendar_operation_keys=calendar_operation_keys,
        desired_calendar_event_count=len(desired_events),
    )
    _write_json(Path(output_path), execution_summary.to_json_summary())
    return execution_summary


def derive_desired_calendar_events(
    task_tree: TaskTree,
    timezone_name: str,
) -> list[DesiredCalendarEvent]:
    timezone = ZoneInfo(timezone_name)
    eligible_tasks = _select_calendar_eligible_leaf_tasks(task_tree)
    return [_derive_calendar_event_for_task(task, timezone) for task in eligible_tasks]


def plan_google_calendar_updates(
    desired_events: list[DesiredCalendarEvent],
    existing_events: list[dict[str, Any]],
    tracker_id: str,
    timezone_name: str,
    colour_id: str | None = None,
) -> GoogleCalendarUpdatePlan:
    desired_resources_by_task_id = {
        event.task_id: _google_event_resource(event, tracker_id, timezone_name, colour_id)
        for event in desired_events
    }
    existing_events_by_task_id, ambiguous_task_ids, warnings = _group_unambiguous_owned_events(
        existing_events,
        tracker_id,
    )

    events_to_create = []
    events_to_replace = []
    event_ids_to_delete = []
    for task_id, desired_resource in desired_resources_by_task_id.items():
        existing_event = existing_events_by_task_id.pop(task_id, None)
        if existing_event is None:
            if task_id not in ambiguous_task_ids:
                events_to_create.append(desired_resource)
            continue
        if _calendar_fields_from_existing_event(existing_event) != desired_resource:
            events_to_replace.append(
                CalendarEventReplacement(event_id=existing_event["id"], event=desired_resource)
            )

    event_ids_to_delete.extend(
        existing_event["id"]
        for existing_event in existing_events_by_task_id.values()
    )
    return GoogleCalendarUpdatePlan(
        events_to_create=events_to_create,
        events_to_replace=events_to_replace,
        event_ids_to_delete=event_ids_to_delete,
        warnings=warnings,
    )


async def _execute_google_calendar_updates(
    plan: GoogleCalendarUpdatePlan,
    calendar_client: GoogleCalendarClient,
) -> list[str]:
    completed_operation_keys = []
    for event in plan.events_to_create:
        await calendar_client.create_calendar_event(event)
        task_id = event["extendedProperties"]["private"]["ntt_task_id"]
        completed_operation_keys.append(f"create:calendar_event:{task_id}")
    for replacement in plan.events_to_replace:
        await calendar_client.replace_calendar_event(replacement.event_id, replacement.event)
        task_id = replacement.event["extendedProperties"]["private"]["ntt_task_id"]
        completed_operation_keys.append(f"replace:calendar_event:{task_id}")
    for event_id in plan.event_ids_to_delete:
        await calendar_client.delete_calendar_event(event_id)
        completed_operation_keys.append(f"delete:calendar_event:{event_id}")
    return completed_operation_keys


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


def _google_event_resource(
    event: DesiredCalendarEvent,
    tracker_id: str,
    timezone_name: str,
    colour_id: str | None,
) -> dict[str, Any]:
    resource = {
        "summary": event.title,
        "description": event.description,
        "transparency": event.transparency,
        "start": _google_event_boundary(event.start_date_time, event.start_date, timezone_name),
        "end": _google_event_boundary(event.end_date_time, event.end_date, timezone_name),
        "extendedProperties": {
            "private": {
                "ntt_tracker": tracker_id,
                "ntt_task_id": event.task_id,
            }
        },
    }
    if colour_id is not None:
        resource["colorId"] = colour_id
    return resource


def _google_event_boundary(
    date_time: datetime | None,
    calendar_date: date | None,
    timezone_name: str,
) -> dict[str, str]:
    if date_time is not None:
        return {
            "dateTime": date_time.isoformat(),
            "timeZone": timezone_name,
        }
    if calendar_date is None:
        raise ValueError("Calendar event boundary requires a date or date-time")
    return {"date": calendar_date.isoformat()}


def _group_unambiguous_owned_events(
    existing_events: list[dict[str, Any]],
    tracker_id: str,
) -> tuple[dict[str, dict[str, Any]], set[str], list[dict[str, str]]]:
    events_by_task_id: dict[str, list[dict[str, Any]]] = {}
    warnings = []
    for event in existing_events:
        private_properties = event.get("extendedProperties", {}).get("private", {})
        if private_properties.get("ntt_tracker") != tracker_id:
            continue
        task_id = private_properties.get("ntt_task_id")
        if not task_id:
            warnings.append({
                "kind": "ambiguous_calendar_event",
                "message": (
                    f"Preserved NTT-owned Google event {event.get('id', '<unknown>')} "
                    "without ntt_task_id"
                ),
            })
            continue
        events_by_task_id.setdefault(task_id, []).append(event)

    unambiguous_events = {}
    ambiguous_task_ids = set()
    for task_id, matching_events in events_by_task_id.items():
        if len(matching_events) == 1 and matching_events[0].get("id"):
            unambiguous_events[task_id] = matching_events[0]
            continue
        warnings.append({
            "kind": "ambiguous_calendar_event",
            "message": f"Preserved {len(matching_events)} Google events claiming task identity {task_id}",
        })
        ambiguous_task_ids.add(task_id)
    return unambiguous_events, ambiguous_task_ids, warnings


def _calendar_fields_from_existing_event(event: dict[str, Any]) -> dict[str, Any]:
    comparable_fields: dict[str, Any] = {
        field_name: event[field_name]
        for field_name in [
            "summary",
            "description",
            "transparency",
            "start",
            "end",
            "colorId",
        ]
        if field_name in event
    }
    private_properties = event.get("extendedProperties", {}).get("private")
    if private_properties is not None:
        comparable_fields["extendedProperties"] = {"private": private_properties}
    return comparable_fields


def _read_json(source_path: Path) -> dict[str, Any]:
    return json.loads(source_path.read_text(encoding="utf-8"))


def _write_json(destination_path: Path, tracker_state: dict[str, Any]) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(
        json.dumps(tracker_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
