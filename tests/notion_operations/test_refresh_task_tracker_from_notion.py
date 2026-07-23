import asyncio

import pytest

from notion_task_tracker.notion_operations.refresh_task_tracker_from_notion import (
    plan_repairs_for_task_tree_changes,
    refresh_tracker_state_for_task_command,
    refresh_tracker_state_from_notion_task_database,
)
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tasks.database import build_task_database_tracker_state
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import (
    build_fetched_task_page,
    build_tracker_state_with_root_and_child_task,
    build_tracker_state_with_root_task,
)


_STATE_FREE_REPAIR_REASON = (
    "ALOVYA-147 item 3 will compare current raw Notion rows with one canonical in-memory tree"
)


@pytest.mark.xfail(strict=True, reason=_STATE_FREE_REPAIR_REASON)
def test_scratch_refresh_of_canonical_notion_rows_plans_no_task_property_writes():
    before_tracker_state = _empty_tracker_state()
    refreshed_result = _refresh_tracker_state(
        before_tracker_state,
        [_task_database_row()],
    )

    repair_result = _plan_current_repairs(before_tracker_state, refreshed_result)

    assert _task_property_repairs(repair_result) == []


@pytest.mark.xfail(strict=True, reason=_STATE_FREE_REPAIR_REASON)
def test_scratch_refresh_repairs_only_a_genuine_derived_end_mismatch():
    before_tracker_state = _empty_tracker_state()
    refreshed_result = _refresh_tracker_state(
        before_tracker_state,
        [
            _task_database_row(
                start="2026-07-23T11:00:00+01:00",
                end="2026-07-23T13:00:00+01:00",
                duration=1,
                duration_unit="Hours",
            )
        ],
    )

    repair_result = _plan_current_repairs(before_tracker_state, refreshed_result)

    assert [
        write_intent.arguments["properties"]
        for write_intent in _task_property_repairs(repair_result)
    ] == [{"End": "2026-07-23T12:00:00+01:00"}]


@pytest.mark.xfail(strict=True, reason=_STATE_FREE_REPAIR_REASON)
def test_scratch_refresh_repairs_only_a_missing_canonical_title_prefix():
    before_tracker_state = _empty_tracker_state()
    refreshed_result = _refresh_tracker_state(
        before_tracker_state,
        [_task_database_row(title="Canonical task")],
    )

    repair_result = _plan_current_repairs(before_tracker_state, refreshed_result)

    assert [
        write_intent.arguments["properties"]
        for write_intent in _task_property_repairs(repair_result)
    ] == [{"Task page": "ALOVYA-1: Canonical task"}]


@pytest.mark.xfail(strict=True, reason=_STATE_FREE_REPAIR_REASON)
def test_scratch_refresh_repairs_only_missing_strikethrough_for_a_completed_title():
    before_tracker_state = _empty_tracker_state()
    refreshed_result = _refresh_tracker_state(
        before_tracker_state,
        [_task_database_row(title="ALOVYA-1: Finished task", status="Complete")],
    )

    repair_result = _plan_current_repairs(before_tracker_state, refreshed_result)

    task_property_repairs = _task_property_repairs(repair_result)
    title_property = task_property_repairs[0].arguments["properties"]["Task page"]
    assert title_property["rich_text"][0]["annotations"]["strikethrough"] is True
    assert set(task_property_repairs[0].arguments["properties"]) == {"Task page"}


@pytest.mark.xfail(strict=True, reason=_STATE_FREE_REPAIR_REASON)
def test_scratch_refresh_does_not_materialise_intentionally_blank_default_properties():
    before_tracker_state = _empty_tracker_state()
    refreshed_result = _refresh_tracker_state(
        before_tracker_state,
        [
            _task_database_row(
                priority="",
                status="",
                external_coordination="",
                uncertainty="",
                friction="",
            )
        ],
    )

    repair_result = _plan_current_repairs(before_tracker_state, refreshed_result)

    assert _task_property_repairs(repair_result) == []


def test_refresh_tracker_state_from_notion_task_database_uses_configured_data_source():
    tracker_state = build_tracker_state_with_root_task()
    tracker_state["task_database"] = _task_database_state()
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Task page": "Root task edited in database",
                "Task ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "Dependencies": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(
        refresh_tracker_state_from_notion_task_database(tracker_state, notion_client)
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["title"] == "Root task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Blocked"
    assert notion_client.queries == [{"data_source_id": "configured-data-source-id"}]
    assert notion_client.fetched_pages == []


def test_refresh_tracker_state_from_notion_task_database_does_not_depend_on_view_url():
    tracker_state = build_tracker_state_with_root_task()
    tracker_state["task_database"] = _task_database_state()
    assert "view_url" not in tracker_state["task_database"]
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Task page": "Root task edited in database",
                "Task ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "Dependencies": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(
        refresh_tracker_state_from_notion_task_database(tracker_state, notion_client)
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert notion_client.view_queries == []
    assert notion_client.queries == [{"data_source_id": "configured-data-source-id"}]


def test_refresh_tracker_state_for_task_command_fetches_only_relevant_pages():
    tracker_state = build_tracker_state_with_root_and_child_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": build_fetched_task_page(
                ticket_id="1",
                title="Root task",
                priority="P1",
                status="Active",
                parent_urls=[],
            ),
            "33333333333333333333333333333333": build_fetched_task_page(
                ticket_id="2",
                title="Child task edited in database",
                priority="P2",
                status="Blocked",
                parent_urls=["https://www.notion.so/22222222222222222222222222222222"],
            ),
        }
    )

    command_result = asyncio.run(
        refresh_tracker_state_for_task_command(
            command={
                "command": "split_task_with_sibling",
                "source_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Sibling task",
                    "configured_priority": "P2",
                    "status": "Active",
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["title"] == "Child task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["status"] == "Blocked"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["parent_task_id"] == "ALOVYA-1"
    assert notion_client.fetched_pages == [
        "33333333333333333333333333333333",
        "22222222222222222222222222222222",
    ]
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def test_refresh_tracker_state_for_task_command_requires_known_tasks():
    tracker_state = build_tracker_state_with_root_task()
    notion_client = FakeNotionClient()

    with pytest.raises(ValueError, match="ALOVYA-99"):
        asyncio.run(
            refresh_tracker_state_for_task_command(
                command={
                    "command": "complete_task",
                    "task_id": "ALOVYA-99",
                    "timeline_entry": {
                        "entry_date": "2026-05-26",
                        "heading": '<mention-date start="2026-05-26"/>',
                        "lines": ["Completed missing task."],
                    },
                },
                tracker_state=tracker_state,
                notion_client=notion_client,
            )
        )

    assert notion_client.fetched_pages == []
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def test_refresh_tracker_state_for_setting_dependencies_reads_current_task_page():
    tracker_state = build_tracker_state_with_root_and_child_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "33333333333333333333333333333333": build_fetched_task_page(
                ticket_id="2",
                title="Child task edited in database",
                priority="P2",
                status="Active",
                parent_urls=["https://www.notion.so/22222222222222222222222222222222"],
            ),
            "22222222222222222222222222222222": build_fetched_task_page(
                ticket_id="1",
                title="Root task",
                priority="P1",
                status="Active",
                parent_urls=[],
            ),
        }
    )

    command_result = asyncio.run(
        refresh_tracker_state_for_task_command(
            command={
                "command": "set_task_dependencies",
                "task_id": "ALOVYA-2",
                "dependency_task_ids": ["ALOVYA-1"],
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["title"] == "Child task edited in database"
    assert notion_client.fetched_pages == [
        "33333333333333333333333333333333",
        "22222222222222222222222222222222",
    ]


def _task_database_state() -> dict:
    return build_task_database_tracker_state(
        data_source_id="configured-data-source-id",
    )


def _empty_tracker_state() -> dict:
    tracker_state = build_tracker_state_with_root_task()
    tracker_state["tasks"] = {}
    tracker_state["identity"] = {
        "display_name": "Alovya",
        "ticket_prefix": "ALOVYA",
    }
    tracker_state["task_database"] = _task_database_state()
    return tracker_state


def _task_database_row(
    title: str = "ALOVYA-1: Canonical task",
    priority: str = "P1",
    status: str = "Active",
    start: str = "",
    end: str = "",
    duration: float | str = "",
    duration_unit: str = "",
    external_coordination: str = "No",
    uncertainty: str = "Low",
    friction: str = "None",
) -> dict:
    return {
        "Task page": title,
        "Task ID": "1",
        "Priority": priority,
        "Status": status,
        "Parent": "[]",
        "Dependencies": "[]",
        "Dependants": "[]",
        "Deadline": "",
        "Start": start,
        "End": end,
        "Duration": duration,
        "Duration unit": duration_unit,
        "External coordination": external_coordination,
        "Uncertainty": uncertainty,
        "Friction": friction,
        "url": "https://www.notion.so/22222222222222222222222222222222",
    }


def _refresh_tracker_state(
    before_tracker_state: dict,
    database_rows: list[dict],
) -> TrackerCommandResult:
    notion_client = FakeNotionClient(database_rows=database_rows)
    return asyncio.run(
        refresh_tracker_state_from_notion_task_database(
            before_tracker_state,
            notion_client,
        )
    )


def _plan_current_repairs(
    before_tracker_state: dict,
    refreshed_result: TrackerCommandResult,
) -> TrackerCommandResult:
    task_tree_changes = TaskTree.changes_between_tracker_states(
        before_tracker_state,
        refreshed_result.tracker_state,
    )
    return plan_repairs_for_task_tree_changes(refreshed_result, task_tree_changes)


def _task_property_repairs(
    command_result: TrackerCommandResult,
) -> list[NotionWriteIntent]:
    return [
        write_intent
        for write_intent in command_result.write_intents
        if write_intent.operation_name == "update_page_properties"
    ]
