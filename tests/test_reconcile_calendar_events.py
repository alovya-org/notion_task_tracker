from datetime import date, datetime

from notion_task_tracker.derive_calendar_events import DesiredCalendarEvent
from notion_task_tracker.reconcile_calendar_events import plan_calendar_event_reconciliation


def test_plans_create_replace_and_unambiguously_orphaned_delete_changes():
    desired_events = [
        _timed_event("ALOVYA-1", "Keep unchanged"),
        _timed_event("ALOVYA-2", "Replace changed"),
        _all_day_event("ALOVYA-3", "Create missing"),
    ]
    existing_events = [
        {
            "id": "keep",
            **_timed_resource("ALOVYA-1", "Keep unchanged"),
            "extendedProperties": {
                "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
                "shared": {"calendar_owner_metadata": "preserved"},
            },
        },
        {"id": "replace", **_timed_resource("ALOVYA-2", "Old title")},
        {"id": "delete", **_timed_resource("ALOVYA-4", "Orphan")},
        {"id": "foreign", **_timed_resource("OTHER-1", "Foreign", tracker_id="OTHER")},
    ]

    plan = plan_calendar_event_reconciliation(
        desired_events,
        existing_events,
        tracker_id="ALOVYA",
        timezone_name="Europe/London",
        colour_id="8",
    )

    assert [event["extendedProperties"]["private"]["ntt_task_id"] for event in plan.events_to_create] == [
        "ALOVYA-3"
    ]
    assert [(replacement.event_id, replacement.event["summary"]) for replacement in plan.events_to_replace] == [
        ("replace", "[NTT] Replace changed")
    ]
    assert plan.event_ids_to_delete == ["delete"]
    assert plan.warnings == []
    assert plan.events_to_create[0]["start"] == {"date": "2026-08-03"}
    assert plan.events_to_create[0]["end"] == {"date": "2026-08-04"}


def test_preserves_owned_events_when_task_identity_is_missing_or_duplicated():
    existing_events = [
        {"id": "missing-task", "extendedProperties": {"private": {"ntt_tracker": "ALOVYA"}}},
        {"id": "duplicate-one", **_timed_resource("ALOVYA-8", "Duplicate")},
        {"id": "duplicate-two", **_timed_resource("ALOVYA-8", "Duplicate")},
    ]

    plan = plan_calendar_event_reconciliation(
        [_timed_event("ALOVYA-8", "Duplicate")],
        existing_events,
        tracker_id="ALOVYA",
        timezone_name="Europe/London",
    )

    assert plan.events_to_create == []
    assert plan.events_to_replace == []
    assert plan.event_ids_to_delete == []
    assert [warning["kind"] for warning in plan.warnings] == [
        "ambiguous_calendar_event",
        "ambiguous_calendar_event",
    ]


def _timed_event(task_id: str, title: str) -> DesiredCalendarEvent:
    return DesiredCalendarEvent(
        task_id=task_id,
        title=f"[NTT] {title}",
        description="This is a personal task. Feel free to schedule a meeting over this slot.",
        transparency="transparent",
        start_date_time=datetime.fromisoformat("2026-08-03T09:00:00+01:00"),
        end_date_time=datetime.fromisoformat("2026-08-03T10:00:00+01:00"),
    )


def _all_day_event(task_id: str, title: str) -> DesiredCalendarEvent:
    return DesiredCalendarEvent(
        task_id=task_id,
        title=f"[NTT] {title}",
        description="This is a personal task. Feel free to schedule a meeting over this slot.",
        transparency="transparent",
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 4),
    )


def _timed_resource(task_id: str, title: str, tracker_id: str = "ALOVYA") -> dict:
    return {
        "summary": f"[NTT] {title}",
        "description": "This is a personal task. Feel free to schedule a meeting over this slot.",
        "transparency": "transparent",
        "start": {"dateTime": "2026-08-03T09:00:00+01:00", "timeZone": "Europe/London"},
        "end": {"dateTime": "2026-08-03T10:00:00+01:00", "timeZone": "Europe/London"},
        "colorId": "8",
        "extendedProperties": {
            "private": {
                "ntt_tracker": tracker_id,
                "ntt_task_id": task_id,
            }
        },
    }
