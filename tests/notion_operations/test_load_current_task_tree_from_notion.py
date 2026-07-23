import asyncio
import json

from notion_task_tracker.config import ManagedPageUrls, TrackerConfig
from notion_task_tracker.notion_operations.load_current_task_tree_from_notion import (
    load_current_task_tree_from_notion,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_TITLE_STRIKETHROUGH_VALUE,
)
from notion_task_tracker.tracked_pages import TrackedPage


def test_load_current_task_tree_from_notion_queries_once_and_plans_no_repairs_for_canonical_rows():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(),
        _task_database_row(
            task_number=2,
            page_id="22222222222222222222222222222222",
            title="[2] Child task",
            parent_page_ids=["11111111111111111111111111111111"],
        ),
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    assert notion_client.queried_data_source_ids == [
        "cccccccccccccccccccccccccccccccc"
    ]
    assert [row.task_id for row in result.raw_database_rows] == [
        "ALOVYA-1",
        "ALOVYA-2",
    ]
    assert result.task_tree.tasks["ALOVYA-1"].child_task_ids == ["ALOVYA-2"]
    assert result.task_tree.tasks["ALOVYA-2"].parent_task_id == "ALOVYA-1"
    assert result.repair_intents == []
    assert result.warnings == []


def test_load_current_task_tree_from_notion_repairs_only_a_genuine_derived_end_mismatch():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(
            start="2026-07-23T11:00:00+01:00",
            end="2026-07-23T13:00:00+01:00",
            duration=1,
            duration_unit="Hours",
        )
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    assert [
        (
            repair_intent.operation_key,
            repair_intent.arguments["properties"],
        )
        for repair_intent in result.repair_intents
    ] == [
        (
            "repair:end:task:ALOVYA-1",
            {"End": "2026-07-23T12:00:00+01:00"},
        )
    ]


def test_load_current_task_tree_from_notion_accepts_equivalent_end_with_zero_milliseconds():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(
            start="2026-07-23T11:00:00.000+01:00",
            end="2026-07-23T12:00:00.000+01:00",
            duration=1,
            duration_unit="Hours",
        )
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    assert result.repair_intents == []


def test_load_current_task_tree_from_notion_repairs_only_a_missing_title_prefix():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(title="Canonical task")
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    assert [
        repair_intent.arguments["properties"]
        for repair_intent in result.repair_intents
    ] == [{"Task page": "[1] Canonical task"}]


def test_load_current_task_tree_from_notion_repairs_completed_title_strikethrough():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(
            title="[1] Finished task",
            status="Complete",
            title_is_struck_through=False,
        )
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    title_property = result.repair_intents[0].arguments["properties"]["Task page"]
    assert result.repair_intents[0].operation_key == "repair:title:task:ALOVYA-1"
    assert set(result.repair_intents[0].arguments["properties"]) == {"Task page"}
    assert title_property["rich_text"][0]["text"]["content"] == "[1] Finished task"
    assert title_property["rich_text"][0]["annotations"]["strikethrough"] is True


def test_load_current_task_tree_from_notion_does_not_materialise_blank_defaults():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(
            priority="",
            status="",
            external_coordination="",
            uncertainty="",
            friction="",
        )
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    task = result.task_tree.tasks["ALOVYA-1"]
    assert task.configured_priority.value == "P3"
    assert task.status.value == "Active"
    assert task.external_coordination.value == "No"
    assert task.uncertainty.value == "Low"
    assert task.friction.value == "None"
    assert result.repair_intents == []


def test_load_current_task_tree_from_notion_keeps_authored_priority_separate_from_display_priority():
    notion_client = _CurrentTaskDatabaseClient([
        _task_database_row(
            priority="P3",
        ),
        _task_database_row(
            task_number=2,
            page_id="22222222222222222222222222222222",
            title="[2] Urgent dependant",
            priority="P0",
            parent_page_ids=["11111111111111111111111111111111"],
        ),
    ])

    result = asyncio.run(
        load_current_task_tree_from_notion(_resolved_resources(), notion_client)
    )

    root_task = result.task_tree.tasks["ALOVYA-1"]
    assert root_task.configured_priority.value == "P3"
    assert root_task.displayed_priority.value == "P0"
    assert result.repair_intents == []


class _CurrentTaskDatabaseClient:
    def __init__(self, database_rows: list[dict]) -> None:
        self.database_rows = database_rows
        self.queried_data_source_ids: list[str] = []

    async def query_data_source_id(self, data_source_id: str) -> list[dict]:
        self.queried_data_source_ids.append(data_source_id)
        return self.database_rows


def _resolved_resources() -> ResolvedTrackerResources:
    config = TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/parent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        pages=ManagedPageUrls(),
    )
    return ResolvedTrackerResources(
        config=config,
        task_database_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        task_data_source_id="cccccccccccccccccccccccccccccccc",
        ongoing_tasks_page=TrackedPage(
            local_page_key="ongoing_landing_page",
            title="Alovya's ongoing tasks",
            notion_page_id="66666666666666666666666666666666",
        ),
        completed_tasks_page=TrackedPage(
            local_page_key="completed_landing_page",
            title="Alovya's completed tasks",
            notion_page_id="77777777777777777777777777777777",
        ),
        ready_priority_page=TrackedPage(
            local_page_key="ready_priority_page",
            title="Alovya's tasks in execution order",
            notion_page_id="88888888888888888888888888888888",
        ),
    )


def _task_database_row(
    task_number: int = 1,
    page_id: str = "11111111111111111111111111111111",
    title: str = "[1] Canonical task",
    title_is_struck_through: bool = False,
    priority: str = "P1",
    status: str = "Active",
    parent_page_ids: list[str] | None = None,
    dependency_page_ids: list[str] | None = None,
    dependant_page_ids: list[str] | None = None,
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
        TASK_DATABASE_TITLE_STRIKETHROUGH_VALUE: title_is_struck_through,
        "Task ID": str(task_number),
        "Priority": priority,
        "Status": status,
        "Parent": _relation_urls(parent_page_ids or []),
        "Dependencies": _relation_urls(dependency_page_ids or []),
        "Dependants": _relation_urls(dependant_page_ids or []),
        "Deadline": "",
        "Start": start,
        "End": end,
        "Duration": duration,
        "Duration unit": duration_unit,
        "External coordination": external_coordination,
        "Uncertainty": uncertainty,
        "Friction": friction,
        "url": f"https://www.notion.so/{page_id}",
    }


def _relation_urls(page_ids: list[str]) -> str:
    return json.dumps([
        f"https://www.notion.so/{page_id}"
        for page_id in page_ids
    ])
