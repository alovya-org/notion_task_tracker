import asyncio
import pytest

from notion_task_tracker.google_calendar_sync.apply_google_calendar_changes_to_tasks import (
    _read_task_ids_from_owned_calendar_events,
    apply_google_calendar_changes_to_tasks,
    fetch_calendar_changes_with_expired_cursor_recovery,
    plan_task_schedule_updates_from_google_events,
    select_changed_events_owned_by_tracker,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import (
    CalendarEventChanges,
    GoogleCalendarSyncTokenExpiredError,
)
from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    GoogleCalendarEventLedgerEntry,
)
from notion_task_tracker.tasks import DurationUnit, Priority, Task, TaskStatus, TaskTree
from tests.notion_operations.helpers import FakeNotionClient


def test_ignores_native_calendar_events_when_selecting_tracker_changes():
    owned_event = {
        "id": "owned-event",
        "extendedProperties": {
            "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
        },
    }
    native_event = {"id": "native-event", "summary": "Lunch"}

    selected_changes = select_changed_events_owned_by_tracker(
        [native_event, owned_event],
        "ALOVYA",
    )

    assert selected_changes.events_to_apply == [owned_event]
    assert selected_changes.active_event_identities == [("owned-event", "ALOVYA-1")]


def test_includes_deleted_tracker_event_when_selecting_changes():
    deleted_event = {
        "id": "deleted-event",
        "status": "cancelled",
        "extendedProperties": {
            "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
        },
    }

    selected_changes = select_changed_events_owned_by_tracker([deleted_event], "ALOVYA")

    assert selected_changes.events_to_apply == [deleted_event]


def test_resolves_an_id_only_user_cancellation_through_the_durable_ledger():
    selected_changes = select_changed_events_owned_by_tracker(
        [{"id": "deleted-event", "status": "cancelled"}],
        "ALOVYA",
        [_ledger_entry("deleted-event", "ALOVYA-1", "active")],
    )

    assert selected_changes.events_to_apply == [{
        "id": "deleted-event",
        "status": "cancelled",
        "extendedProperties": {
            "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
        },
    }]
    assert selected_changes.acknowledged_cancellation_identities == [
        ("deleted-event", "ALOVYA-1")
    ]


def test_acknowledges_an_ntt_originated_cancellation_without_changing_the_task():
    selected_changes = select_changed_events_owned_by_tracker(
        [{"id": "deleted-event", "status": "cancelled"}],
        "ALOVYA",
        [_ledger_entry("deleted-event", "ALOVYA-1", "deleted_by_ntt")],
    )

    assert selected_changes.events_to_apply == []
    assert selected_changes.acknowledged_cancellation_identities == [
        ("deleted-event", "ALOVYA-1")
    ]


def test_expired_cursor_recovery_treats_a_missing_active_event_as_user_deletion():
    selected_changes = select_changed_events_owned_by_tracker(
        [],
        "ALOVYA",
        [_ledger_entry("missing-event", "ALOVYA-1", "active")],
        rebuilt_event_ledger=True,
    )

    assert selected_changes.events_to_apply[0]["id"] == "missing-event"
    assert selected_changes.events_to_apply[0]["status"] == "cancelled"
    assert selected_changes.events_to_apply[0]["extendedProperties"]["private"] == {
        "ntt_tracker": "ALOVYA",
        "ntt_task_id": "ALOVYA-1",
    }


def test_expired_cursor_recovery_ignores_an_ntt_originated_missing_event():
    selected_changes = select_changed_events_owned_by_tracker(
        [],
        "ALOVYA",
        [_ledger_entry("missing-event", "ALOVYA-1", "deleted_by_ntt")],
        rebuilt_event_ledger=True,
    )

    assert selected_changes.events_to_apply == []


def test_rebuilds_google_change_cursor_after_google_expires_it():
    class ExpiredThenInitialCalendarClient:
        def __init__(self):
            self.google_change_cursors = []

        async def fetch_calendar_event_changes(self, sync_token=None):
            self.google_change_cursors.append(sync_token)
            if sync_token is not None:
                raise GoogleCalendarSyncTokenExpiredError
            return CalendarEventChanges(
                events=[{"id": "current-event"}],
                next_sync_token="rebuilt-sync-token",
            )

    calendar_client = ExpiredThenInitialCalendarClient()

    changes, recovered = asyncio.run(fetch_calendar_changes_with_expired_cursor_recovery(
        calendar_client,
        "expired-sync-token",
    ))

    assert recovered is True
    assert calendar_client.google_change_cursors == ["expired-sync-token", None]
    assert changes.next_sync_token == "rebuilt-sync-token"


def test_timed_event_move_and_resize_updates_the_complete_task_schedule():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))
    event = _owned_event(
        start={"dateTime": "2026-10-25T01:30:00+01:00"},
        end={"dateTime": "2026-10-25T02:30:00+00:00"},
    )

    result = plan_task_schedule_updates_from_google_events(
        [event], task_tree, "ALOVYA", "Europe/London"
    )

    task = result.task_tree.tasks["ALOVYA-1"]
    assert task.start == "2026-10-25T01:30:00+01:00"
    assert task.duration == 2
    assert task.duration_unit == DurationUnit.HOURS
    assert task.end == "2026-10-25T03:30:00+01:00"
    written_properties = result.write_intents[0].arguments["properties"]
    assert written_properties["Start"] == "2026-10-25T01:30:00+01:00"
    assert written_properties["End"] == "2026-10-25T03:30:00+01:00"
    assert written_properties["Duration"] == 2
    assert written_properties["Duration unit"] == "Hours"


def test_all_day_event_uses_days_when_a_timed_task_changes_form():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))

    result = plan_task_schedule_updates_from_google_events(
        [_owned_event(start={"date": "2026-08-03"}, end={"date": "2026-08-06"})],
        task_tree,
        "ALOVYA",
        "Europe/London",
    )

    task = result.task_tree.tasks["ALOVYA-1"]
    assert task.start == "2026-08-03"
    assert task.duration == 3
    assert task.duration_unit == DurationUnit.DAYS
    assert task.end == "2026-08-06"


def test_all_day_event_preserves_week_semantics_when_possible():
    task_tree = _task_tree(_scheduled_task(DurationUnit.WEEKS))

    result = plan_task_schedule_updates_from_google_events(
        [_owned_event(start={"date": "2026-08-03"}, end={"date": "2026-08-17"})],
        task_tree,
        "ALOVYA",
        "Europe/London",
    )

    task = result.task_tree.tasks["ALOVYA-1"]
    assert task.duration == 2
    assert task.duration_unit == DurationUnit.WEEKS


def test_deleted_event_clears_the_complete_task_schedule():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))
    deleted_event = _owned_event()
    deleted_event["status"] = "cancelled"

    result = plan_task_schedule_updates_from_google_events(
        [deleted_event],
        task_tree,
        "ALOVYA",
        "Europe/London",
    )

    task = result.task_tree.tasks["ALOVYA-1"]
    assert task.start is None
    assert task.duration is None
    assert task.duration_unit is None
    assert task.end is None
    written_properties = result.write_intents[0].arguments["properties"]
    assert written_properties["Start"] is None
    assert written_properties["End"] is None
    assert written_properties["Duration"] is None
    assert written_properties["Duration unit"] is None


def test_legacy_cancellation_for_an_already_completed_task_is_a_successful_no_op():
    completed_task = _scheduled_task(DurationUnit.HOURS)
    completed_task.status = TaskStatus.COMPLETE
    task_tree = _task_tree(completed_task)
    deleted_event = _owned_event(task_id="ALOVYA-1")
    deleted_event["status"] = "cancelled"

    result = plan_task_schedule_updates_from_google_events(
        [deleted_event],
        task_tree,
        "ALOVYA",
        "Europe/London",
    )

    assert result.task_tree.tasks["ALOVYA-1"].status == TaskStatus.COMPLETE
    assert result.write_intents == []


def test_foreign_event_identity_fails_clearly():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="not owned by tracker ALOVYA"):
        plan_task_schedule_updates_from_google_events(
            [_owned_event(tracker_id="OTHER")], task_tree, "ALOVYA", "Europe/London"
        )


def test_duplicate_event_identity_fails_clearly():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="Multiple changed Google events"):
        plan_task_schedule_updates_from_google_events(
            [_owned_event(), _owned_event(event_id="event-2")],
            task_tree,
            "ALOVYA",
            "Europe/London",
        )


def test_unknown_task_identity_fails_clearly():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="unknown task ALOVYA-99"):
        plan_task_schedule_updates_from_google_events(
            [_owned_event(task_id="ALOVYA-99")], task_tree, "ALOVYA", "Europe/London"
        )


def test_extracts_owned_task_ids_before_fetching_current_notion_properties():
    assert _read_task_ids_from_owned_calendar_events([_owned_event()], "ALOVYA") == ["ALOVYA-1"]


def test_worker_updates_notion_and_the_supplied_current_task_tree():
    task_tree = _task_tree(_scheduled_task(DurationUnit.HOURS))
    notion_client = FakeNotionClient()

    summary = asyncio.run(apply_google_calendar_changes_to_tasks(
        changed_events=[_owned_event(
            start={"dateTime": "2026-08-04T13:00:00+01:00"},
            end={"dateTime": "2026-08-04T15:30:00+01:00"},
        )],
        task_tree=task_tree,
        tracker_id="ALOVYA",
        timezone_name="Europe/London",
        notion_client=notion_client,
    ))

    task = task_tree.tasks["ALOVYA-1"]
    assert task.start == "2026-08-04T13:00:00+01:00"
    assert task.duration == 2.5
    assert task.end == "2026-08-04T15:30:00+01:00"
    assert summary.task_ids == ["ALOVYA-1"]
    assert summary.completed_operation_keys == ["update_schedule:task:ALOVYA-1"]
    assert summary.warnings == []


def _owned_event(
    event_id="event-1",
    task_id="ALOVYA-1",
    tracker_id="ALOVYA",
    start=None,
    end=None,
):
    return {
        "id": event_id,
        "start": start or {"dateTime": "2026-08-03T09:00:00+01:00"},
        "end": end or {"dateTime": "2026-08-03T10:00:00+01:00"},
        "extendedProperties": {
            "private": {
                "ntt_tracker": tracker_id,
                "ntt_task_id": task_id,
            }
        },
    }


def _ledger_entry(event_id: str, task_id: str, lifecycle_state: str):
    return GoogleCalendarEventLedgerEntry(
        google_event_id=event_id,
        ntt_task_id=task_id,
        lifecycle_state=lifecycle_state,
    )


def _scheduled_task(duration_unit: DurationUnit) -> Task:
    if duration_unit == DurationUnit.HOURS:
        start = "2026-08-03T09:00:00+01:00"
        duration = 1
        end = "2026-08-03T10:00:00+01:00"
    else:
        start = "2026-08-03"
        duration = 1
        end = "2026-08-10"
    return Task(
        task_id="ALOVYA-1",
        title="Scheduled task",
        configured_priority=Priority.P2,
        status=TaskStatus.ACTIVE,
        start=start,
        end=end,
        duration=duration,
        duration_unit=duration_unit,
        notion_page_id="11111111111111111111111111111111",
    )


def _task_tree(task: Task) -> TaskTree:
    task_tree = TaskTree()
    task_tree.add_task(task)
    return task_tree
