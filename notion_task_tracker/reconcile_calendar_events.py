"""Plan Google Calendar changes from desired NTT task events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from notion_task_tracker.derive_calendar_events import DesiredCalendarEvent


@dataclass(frozen=True)
class CalendarEventReplacement:
    event_id: str
    event: dict[str, Any]


@dataclass(frozen=True)
class CalendarReconciliationPlan:
    events_to_create: list[dict[str, Any]]
    events_to_replace: list[CalendarEventReplacement]
    event_ids_to_delete: list[str]
    warnings: list[dict[str, str]]


def plan_calendar_event_reconciliation(
    desired_events: list[DesiredCalendarEvent],
    existing_events: list[dict[str, Any]],
    tracker_id: str,
    timezone_name: str,
    colour_id: str | None = None,
) -> CalendarReconciliationPlan:
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
    return CalendarReconciliationPlan(
        events_to_create=events_to_create,
        events_to_replace=events_to_replace,
        event_ids_to_delete=event_ids_to_delete,
        warnings=warnings,
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
                "message": f"Preserved NTT-owned Google event {event.get('id', '<unknown>')} without ntt_task_id",
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
