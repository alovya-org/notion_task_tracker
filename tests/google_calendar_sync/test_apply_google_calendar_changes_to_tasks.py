import asyncio
import json

import pytest

from notion_task_tracker.config import CalendarConfig, TrackerConfig
from notion_task_tracker.google_calendar_sync.apply_google_calendar_changes_to_tasks import (
    _apply_changed_google_calendar_events_to_tasks,
    _fetch_calendar_changes_with_expired_cursor_recovery,
    _plan_task_schedule_updates_from_google_events,
    _read_task_ids_from_owned_calendar_events,
    _select_changed_events_owned_by_tracker,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import (
    CalendarEventChanges,
    GoogleCalendarSyncTokenExpiredError,
)
from notion_task_tracker.tasks import DurationUnit, Priority, Task, TaskStatus, TaskTree
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import build_fetched_task_page


def test_ignores_native_calendar_events_when_selecting_tracker_changes():
    owned_event = {
        "id": "owned-event",
        "extendedProperties": {
            "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
        },
    }
    native_event = {"id": "native-event", "summary": "Lunch"}

    selected_events = _select_changed_events_owned_by_tracker(
        [native_event, owned_event],
        "ALOVYA",
    )

    assert selected_events == [owned_event]


def test_includes_deleted_tracker_event_when_selecting_changes():
    deleted_event = {
        "id": "deleted-event",
        "status": "cancelled",
        "extendedProperties": {
            "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
        },
    }

    assert _select_changed_events_owned_by_tracker([deleted_event], "ALOVYA") == [deleted_event]


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

    changes, recovered = asyncio.run(_fetch_calendar_changes_with_expired_cursor_recovery(
        calendar_client,
        "expired-sync-token",
    ))

    assert recovered is True
    assert calendar_client.google_change_cursors == ["expired-sync-token", None]
    assert changes.next_sync_token == "rebuilt-sync-token"


def test_timed_event_move_and_resize_updates_the_complete_task_schedule():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))
    event = _owned_event(
        start={"dateTime": "2026-10-25T01:30:00+01:00"},
        end={"dateTime": "2026-10-25T02:30:00+00:00"},
    )

    result = _plan_task_schedule_updates_from_google_events(
        [event], tracker_state, "ALOVYA", "Europe/London"
    )

    task = result.tracker_state["tasks"]["ALOVYA-1"]
    assert task["start"] == "2026-10-25T01:30:00+01:00"
    assert task["duration"] == 2
    assert task["duration_unit"] == "Hours"
    assert task["end"] == "2026-10-25T03:30:00+01:00"
    written_properties = result.write_intents[0].arguments["properties"]
    assert written_properties["Start"] == "2026-10-25T01:30:00+01:00"
    assert written_properties["End"] == "2026-10-25T03:30:00+01:00"
    assert written_properties["Duration"] == 2
    assert written_properties["Duration unit"] == "Hours"


def test_all_day_event_uses_days_when_a_timed_task_changes_form():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    result = _plan_task_schedule_updates_from_google_events(
        [_owned_event(start={"date": "2026-08-03"}, end={"date": "2026-08-06"})],
        tracker_state,
        "ALOVYA",
        "Europe/London",
    )

    task = result.tracker_state["tasks"]["ALOVYA-1"]
    assert task["start"] == "2026-08-03"
    assert task["duration"] == 3
    assert task["duration_unit"] == "Days"
    assert task["end"] == "2026-08-06"


def test_all_day_event_preserves_week_semantics_when_possible():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.WEEKS))

    result = _plan_task_schedule_updates_from_google_events(
        [_owned_event(start={"date": "2026-08-03"}, end={"date": "2026-08-17"})],
        tracker_state,
        "ALOVYA",
        "Europe/London",
    )

    task = result.tracker_state["tasks"]["ALOVYA-1"]
    assert task["duration"] == 2
    assert task["duration_unit"] == "Weeks"


def test_deleted_event_clears_the_complete_task_schedule():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))
    deleted_event = _owned_event()
    deleted_event["status"] = "cancelled"

    result = _plan_task_schedule_updates_from_google_events(
        [deleted_event],
        tracker_state,
        "ALOVYA",
        "Europe/London",
    )

    task = result.tracker_state["tasks"]["ALOVYA-1"]
    assert task["start"] is None
    assert task["duration"] is None
    assert task["duration_unit"] is None
    assert task["end"] is None
    written_properties = result.write_intents[0].arguments["properties"]
    assert written_properties["Start"] is None
    assert written_properties["End"] is None
    assert written_properties["Duration"] is None
    assert written_properties["Duration unit"] is None


def test_foreign_event_identity_fails_clearly():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="not owned by tracker ALOVYA"):
        _plan_task_schedule_updates_from_google_events(
            [_owned_event(tracker_id="OTHER")], tracker_state, "ALOVYA", "Europe/London"
        )


def test_duplicate_event_identity_fails_clearly():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="Multiple changed Google events"):
        _plan_task_schedule_updates_from_google_events(
            [_owned_event(), _owned_event(event_id="event-2")],
            tracker_state,
            "ALOVYA",
            "Europe/London",
        )


def test_unknown_task_identity_fails_clearly():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="unknown task ALOVYA-99"):
        _plan_task_schedule_updates_from_google_events(
            [_owned_event(task_id="ALOVYA-99")], tracker_state, "ALOVYA", "Europe/London"
        )


def test_extracts_owned_task_ids_before_fetching_current_notion_properties():
    assert _read_task_ids_from_owned_calendar_events([_owned_event()], "ALOVYA") == ["ALOVYA-1"]


def test_worker_refreshes_notion_then_writes_and_persists_the_calendar_schedule(tmp_path):
    tracker_state_path = tmp_path / "tracker_state.json"
    tracker_state_path.write_text(
        json.dumps(_tracker_state(_scheduled_task(DurationUnit.HOURS))),
        encoding="utf-8",
    )
    notion_client = FakeNotionClient(fetched_page_content_by_id={
        "11111111111111111111111111111111": build_fetched_task_page(
            ticket_id="1",
            title="Scheduled task",
            priority="P2",
            status="Active",
            parent_urls=[],
        )
    })
    config = TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/parent",
        task_database_url="https://www.notion.so/database",
        calendar=CalendarConfig(calendar_id="test", timezone_name="Europe/London"),
    )

    summary = asyncio.run(_apply_changed_google_calendar_events_to_tasks(
        changed_events=[_owned_event(
            start={"dateTime": "2026-08-04T13:00:00+01:00"},
            end={"dateTime": "2026-08-04T15:30:00+01:00"},
        )],
        config=config,
        tracker_state_path=tracker_state_path,
        notion_client=notion_client,
    ))

    persisted_task = json.loads(tracker_state_path.read_text(encoding="utf-8"))["tasks"]["ALOVYA-1"]
    assert persisted_task["start"] == "2026-08-04T13:00:00+01:00"
    assert persisted_task["duration"] == 2.5
    assert persisted_task["end"] == "2026-08-04T15:30:00+01:00"
    assert summary.task_ids == ["ALOVYA-1"]
    assert summary.completed_operation_keys == ["update_properties:task:ALOVYA-1"]
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


def _tracker_state(task: Task) -> dict:
    task_tree = TaskTree()
    task_tree.add_task(task)
    return {
        "identity": {"display_name": "Alovya", "ticket_prefix": "ALOVYA"},
        "task_database": {"data_source_id": "database"},
        **task_tree.to_tracker_state(),
    }
