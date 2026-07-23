"""Build one command's canonical task tree and genuine repair plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from notion_task_tracker.notion_operations.database_properties import (
    strikethrough_rich_text_items,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks import TaskStatus, TaskTree
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_END_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TaskDatabaseRow,
    build_task_tree_from_database_rows,
    task_database_rows_from_query_results,
)


@dataclass(frozen=True)
class CurrentTaskTreeLoadResult:
    raw_database_rows: list[TaskDatabaseRow]
    task_tree: TaskTree
    warnings: list[dict[str, str]]
    repair_intents: list[NotionWriteIntent]


async def load_current_task_tree_from_notion(
    resources: ResolvedTrackerResources,
    notion_client: NotionRestClient,
) -> CurrentTaskTreeLoadResult:
    query_results = await notion_client.query_data_source_id(
        resources.task_data_source_id
    )
    raw_database_rows = task_database_rows_from_query_results(
        query_results,
        resources.config.ticket_prefix,
    )
    task_tree = build_task_tree_from_database_rows(
        database_rows=raw_database_rows,
        landing_page=resources.ongoing_tasks_page,
        completed_landing_page=resources.completed_tasks_page,
    )
    repair_intents = _plan_repairs_for_current_notion_values(
        raw_database_rows,
        task_tree,
    )
    return CurrentTaskTreeLoadResult(
        raw_database_rows=raw_database_rows,
        task_tree=task_tree,
        warnings=[],
        repair_intents=repair_intents,
    )


def _plan_repairs_for_current_notion_values(
    raw_database_rows: list[TaskDatabaseRow],
    task_tree: TaskTree,
) -> list[NotionWriteIntent]:
    repair_intents = []
    for database_row in raw_database_rows:
        task = task_tree.tasks[database_row.task_id]
        repair_intents.extend(
            _plan_derived_end_repair(database_row, task.end)
        )
        repair_intents.extend(
            _plan_title_presentation_repair(
                database_row,
                task.render_page_title(),
                task.status,
            )
        )
    return repair_intents


def _plan_derived_end_repair(
    database_row: TaskDatabaseRow,
    canonical_end: str | None,
) -> list[NotionWriteIntent]:
    if _notion_date_matches_canonical_value(database_row.end, canonical_end):
        return []

    return [
        _build_narrow_task_repair(
            task_id=database_row.task_id,
            repair_name="end",
            repaired_property_name=TASK_DATABASE_END_PROPERTY,
            repaired_property_value=canonical_end,
        )
    ]


def _notion_date_matches_canonical_value(
    notion_value: str | None,
    canonical_value: str | None,
) -> bool:
    if notion_value is None or canonical_value is None:
        return notion_value == canonical_value

    notion_has_time = "T" in notion_value
    canonical_has_time = "T" in canonical_value
    if notion_has_time != canonical_has_time:
        return False
    if notion_has_time:
        return datetime.fromisoformat(
            notion_value.replace("Z", "+00:00")
        ) == datetime.fromisoformat(
            canonical_value.replace("Z", "+00:00")
        )
    return date.fromisoformat(notion_value) == date.fromisoformat(canonical_value)


def _plan_title_presentation_repair(
    database_row: TaskDatabaseRow,
    canonical_title: str,
    status: TaskStatus,
) -> list[NotionWriteIntent]:
    title_should_be_struck_through = status is TaskStatus.COMPLETE
    title_text_matches = database_row.fetched_title == canonical_title
    title_strikethrough_matches = (
        database_row.fetched_title_is_struck_through
        is title_should_be_struck_through
    )
    if title_text_matches and title_strikethrough_matches:
        return []

    task_title_property: str | dict = canonical_title
    if title_should_be_struck_through:
        task_title_property = {
            "rich_text": strikethrough_rich_text_items(canonical_title)
        }

    return [
        _build_narrow_task_repair(
            task_id=database_row.task_id,
            repair_name="title",
            repaired_property_name=TASK_DATABASE_TITLE_PROPERTY,
            repaired_property_value=task_title_property,
        )
    ]


def _build_narrow_task_repair(
    task_id: str,
    repair_name: str,
    repaired_property_name: str,
    repaired_property_value: object,
) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"repair:{repair_name}:task:{task_id}",
        operation_name="update_page_properties",
        target_page_key=f"task:{task_id}",
        arguments={
            "properties": {
                repaired_property_name: repaired_property_value,
            }
        },
    )
