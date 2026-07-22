import asyncio
import json

import pytest

from notion_task_tracker.config import CalendarConfig, TrackerConfig
from notion_task_tracker.reconcile_calendar_edits import (
    plan_task_schedule_updates_from_calendar_events,
    reconcile_changed_google_calendar_events,
    task_ids_from_owned_calendar_events,
)
from notion_task_tracker.tasks import DurationUnit, Priority, Task, TaskStatus, TaskTree
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import build_fetched_task_page


def test_timed_event_move_and_resize_updates_the_complete_task_schedule():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))
    event = _owned_event(
        start={"dateTime": "2026-10-25T01:30:00+01:00"},
        end={"dateTime": "2026-10-25T02:30:00+00:00"},
    )

    result = plan_task_schedule_updates_from_calendar_events(
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

    result = plan_task_schedule_updates_from_calendar_events(
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

    result = plan_task_schedule_updates_from_calendar_events(
        [_owned_event(start={"date": "2026-08-03"}, end={"date": "2026-08-17"})],
        tracker_state,
        "ALOVYA",
        "Europe/London",
    )

    task = result.tracker_state["tasks"]["ALOVYA-1"]
    assert task["duration"] == 2
    assert task["duration_unit"] == "Weeks"


def test_foreign_event_identity_fails_clearly():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="not owned by tracker ALOVYA"):
        plan_task_schedule_updates_from_calendar_events(
            [_owned_event(tracker_id="OTHER")], tracker_state, "ALOVYA", "Europe/London"
        )


def test_duplicate_event_identity_fails_clearly():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="Multiple changed Google events"):
        plan_task_schedule_updates_from_calendar_events(
            [_owned_event(), _owned_event(event_id="event-2")],
            tracker_state,
            "ALOVYA",
            "Europe/London",
        )


def test_unknown_task_identity_fails_clearly():
    tracker_state = _tracker_state(_scheduled_task(DurationUnit.HOURS))

    with pytest.raises(ValueError, match="unknown task ALOVYA-99"):
        plan_task_schedule_updates_from_calendar_events(
            [_owned_event(task_id="ALOVYA-99")], tracker_state, "ALOVYA", "Europe/London"
        )


def test_extracts_owned_task_ids_before_fetching_current_notion_properties():
    assert task_ids_from_owned_calendar_events([_owned_event()], "ALOVYA") == ["ALOVYA-1"]


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

    summary = asyncio.run(reconcile_changed_google_calendar_events(
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
