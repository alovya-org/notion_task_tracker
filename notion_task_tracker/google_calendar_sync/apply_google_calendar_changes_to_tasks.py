"""Apply concrete Google Calendar event changes to NTT task schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    CloudflareGoogleCalendarStateClient,
    GoogleCalendarEventLedgerEntry,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import (
    CalendarEventChanges,
    GoogleCalendarClient,
    GoogleCalendarSyncTokenExpiredError,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
    build_task_schedule_update_intent,
)
from notion_task_tracker.apply_task_command import TaskCommandPlan
from notion_task_tracker.tasks import DurationUnit, Task, TaskStatus, TaskTree


@dataclass(frozen=True)
class CalendarTaskScheduleChange:
    event_id: str
    task_id: str
    start: str
    duration: float
    duration_unit: DurationUnit


@dataclass(frozen=True)
class CalendarTaskScheduleRemoval:
    event_id: str
    task_id: str


@dataclass(frozen=True)
class AppliedGoogleCalendarChanges:
    task_ids: list[str]
    completed_operation_keys: list[str]
    warnings: list[dict[str, str]]


@dataclass(frozen=True)
class SelectedGoogleCalendarChanges:
    events_to_apply: list[dict[str, Any]]
    active_event_identities: list[tuple[str, str]]
    acknowledged_cancellation_identities: list[tuple[str, str]]
    warnings: list[dict[str, str]]


async def fetch_calendar_changes_with_expired_cursor_recovery(
    calendar_client: GoogleCalendarClient,
    google_change_cursor: str,
) -> tuple[CalendarEventChanges, bool]:
    try:
        return await calendar_client.fetch_calendar_event_changes(google_change_cursor), False
    except GoogleCalendarSyncTokenExpiredError:
        return await calendar_client.fetch_calendar_event_changes(), True


def select_changed_events_owned_by_tracker(
    changed_events: list[dict[str, Any]],
    tracker_id: str,
    event_ledger: list[GoogleCalendarEventLedgerEntry] | None = None,
    rebuilt_event_ledger: bool = False,
) -> SelectedGoogleCalendarChanges:
    ledger_by_event_id = {
        entry.google_event_id: entry
        for entry in event_ledger or []
    }
    events_to_apply = []
    active_event_identities = []
    acknowledged_cancellation_identities = []
    warnings = []
    for event in changed_events:
        event_id = _required_event_id(event)
        private_properties = event.get("extendedProperties", {}).get("private", {})
        ledger_entry = ledger_by_event_id.get(event_id)
        if event.get("status") == "cancelled":
            if ledger_entry is not None:
                acknowledged_cancellation_identities.append(
                    (ledger_entry.google_event_id, ledger_entry.ntt_task_id)
                )
                if ledger_entry.lifecycle_state == "deleted_by_ntt":
                    continue
                events_to_apply.append(_identify_cancelled_event_from_ledger(
                    event,
                    tracker_id,
                    ledger_entry.ntt_task_id,
                ))
                continue
            if private_properties.get("ntt_tracker") == tracker_id:
                task_id = private_properties.get("ntt_task_id")
                if isinstance(task_id, str) and task_id:
                    events_to_apply.append(event)
                    continue
            warnings.append({
                "kind": "unidentified_cancelled_calendar_event",
                "message": f"Ignored cancelled Google event {event_id} because ownership is unknown",
            })
            continue
        if private_properties.get("ntt_tracker") != tracker_id:
            continue
        task_id = private_properties.get("ntt_task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        if ledger_entry is not None and ledger_entry.ntt_task_id != task_id:
            raise ValueError(
                f"Google event {event_id} identifies {task_id} but the durable ledger identifies "
                f"{ledger_entry.ntt_task_id}"
            )
        events_to_apply.append(event)
        active_event_identities.append((event_id, task_id))

    if rebuilt_event_ledger:
        current_event_ids = {event_id for event_id, _task_id in active_event_identities}
        for ledger_entry in ledger_by_event_id.values():
            if ledger_entry.lifecycle_state != "active":
                continue
            if ledger_entry.google_event_id in current_event_ids:
                continue
            events_to_apply.append(_identify_cancelled_event_from_ledger(
                {"id": ledger_entry.google_event_id, "status": "cancelled"},
                tracker_id,
                ledger_entry.ntt_task_id,
            ))

    return SelectedGoogleCalendarChanges(
        events_to_apply=events_to_apply,
        active_event_identities=active_event_identities,
        acknowledged_cancellation_identities=acknowledged_cancellation_identities,
        warnings=warnings,
    )


def _identify_cancelled_event_from_ledger(
    event: dict[str, Any],
    tracker_id: str,
    task_id: str,
) -> dict[str, Any]:
    identified_event = dict(event)
    identified_event["extendedProperties"] = {
        "private": {
            "ntt_tracker": tracker_id,
            "ntt_task_id": task_id,
        }
    }
    return identified_event


async def persist_processed_google_calendar_event_identities(
    state_client: CloudflareGoogleCalendarStateClient,
    tracker_user: str,
    calendar_id: str,
    selected_changes: SelectedGoogleCalendarChanges,
    rebuilt_event_ledger: bool,
) -> None:
    if rebuilt_event_ledger:
        await state_client.replace_google_calendar_event_ledger_snapshot(
            tracker_user,
            calendar_id,
            [
                {"google_event_id": event_id, "ntt_task_id": task_id}
                for event_id, task_id in selected_changes.active_event_identities
            ],
        )
        return

    for event_id, task_id in selected_changes.active_event_identities:
        await state_client.record_active_google_calendar_event(
            tracker_user,
            calendar_id,
            event_id,
            task_id,
        )
    for event_id, task_id in selected_changes.acknowledged_cancellation_identities:
        await state_client.delete_google_calendar_event_mapping(
            tracker_user,
            calendar_id,
            event_id,
            task_id,
        )


async def apply_google_calendar_changes_to_tasks(
    changed_events: list[dict[str, Any]],
    task_tree: TaskTree,
    tracker_id: str,
    timezone_name: str,
    notion_client: NotionRestClient,
) -> AppliedGoogleCalendarChanges:
    task_ids = _read_task_ids_from_owned_calendar_events(changed_events, tracker_id)
    planned_updates = plan_task_schedule_updates_from_google_events(
        changed_events=changed_events,
        task_tree=task_tree,
        tracker_id=tracker_id,
        timezone_name=timezone_name,
    )
    if planned_updates.write_intents:
        write_result = await notion_client.execute_command_result(planned_updates)
        if write_result.blocked_operation_count:
            raise ValueError("Calendar schedule writes cannot depend on captured page identifiers")
        completed_operation_keys = list(write_result.completed_operation_keys)
    else:
        completed_operation_keys = []
    return AppliedGoogleCalendarChanges(
        task_ids=task_ids,
        completed_operation_keys=completed_operation_keys,
        warnings=[],
    )


def plan_task_schedule_updates_from_google_events(
    changed_events: list[dict[str, Any]],
    task_tree: TaskTree,
    tracker_id: str,
    timezone_name: str,
) -> TaskCommandPlan:
    schedule_changes = _derive_unambiguous_task_schedule_changes(
        changed_events,
        task_tree,
        tracker_id,
        ZoneInfo(timezone_name),
    )

    for change in schedule_changes:
        if isinstance(change, CalendarTaskScheduleRemoval):
            task_tree.clear_task_start(change.task_id)
            task_tree.clear_task_duration(change.task_id)
        else:
            task_tree.replace_task_schedule(
                task_id=change.task_id,
                start=change.start,
                duration=change.duration,
                duration_unit=change.duration_unit,
            )

    return TaskCommandPlan(
        task_tree=task_tree,
        write_intents=[
            build_task_schedule_update_intent(task_tree.tasks[change.task_id])
            for change in schedule_changes
        ],
        page_registry=build_page_registry_for_task_tree(task_tree),
    )


def _read_task_ids_from_owned_calendar_events(
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
) -> list[CalendarTaskScheduleChange | CalendarTaskScheduleRemoval]:
    task_ids = _read_task_ids_from_owned_calendar_events(changed_events, tracker_id)
    schedule_changes = []
    for event, task_id in zip(changed_events, task_ids, strict=True):
        if event.get("status") == "cancelled":
            task = task_tree.tasks.get(task_id)
            if (
                task is None
                or task.status != TaskStatus.ACTIVE
                or task.child_task_ids
            ):
                continue
            schedule_changes.append(CalendarTaskScheduleRemoval(
                event_id=_required_event_id(event),
                task_id=task.task_id,
            ))
        else:
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
