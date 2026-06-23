"""Fetch Notion task data, then hand pure rows to task refresh actions."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tasks.refresh_task_tracker_state import (
    find_task_ids_to_refresh_before_command,
    refresh_tracker_state_from_database_rows,
    refresh_command_tasks_in_tracker_state,
    refresh_task_ids_in_tracker_state,
)
from notion_task_tracker.tasks.database import (
    TaskDatabaseRow,
    task_database_row_from_fetched_task_database_page,
)


async def refresh_tracker_state_from_notion_task_database(
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> TrackerCommandResult:
    if "task_database" not in tracker_state:
        raise ValueError("Task reconciliation requires task_database in tracker state")

    database_rows = await notion_client.query_task_database_rows(tracker_state)
    return refresh_tracker_state_from_database_rows(tracker_state, database_rows)


def plan_repairs_for_task_tree_changes(
    refreshed_result: TrackerCommandResult,
    task_tree_changes: list[dict[str, Any]],
) -> TrackerCommandResult:
    operation_keys = TaskTree.from_tracker_state(
        refreshed_result.tracker_state
    ).repair_operation_keys_for_changes(task_tree_changes)
    if refreshed_result.refreshed_task_ids:
        operation_keys = _keep_only_safe_repair_operation_keys(
            operation_keys,
            refreshed_result.refreshed_task_ids,
        )
    repair_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": operation_keys,
        },
        tracker_state=refreshed_result.tracker_state,
    )
    return TrackerCommandResult(
        tracker_state=repair_result.tracker_state,
        write_intents=repair_result.write_intents,
        page_registry=repair_result.page_registry,
        warnings=refreshed_result.warnings,
        refreshed_task_ids=refreshed_result.refreshed_task_ids,
    )


def _keep_only_safe_repair_operation_keys(
    operation_keys: list[str],
    refreshed_task_ids: frozenset[str],
) -> list[str]:
    safe_operation_keys = []
    for operation_key in operation_keys:
        if not operation_key.startswith("update_properties:task:"):
            safe_operation_keys.append(operation_key)
            continue

        task_id = operation_key.removeprefix("update_properties:task:")
        if task_id in refreshed_task_ids:
            safe_operation_keys.append(operation_key)

    return safe_operation_keys


async def refresh_tracker_state_for_task_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> TrackerCommandResult:
    if not _needs_task_context_for_command(command):
        return TrackerCommandResult(tracker_state=tracker_state, warnings=[])

    database_rows_by_task_id = await _fetch_database_rows_for_command_tasks(
        command,
        tracker_state,
        notion_client,
    )
    return refresh_command_tasks_in_tracker_state(
        command=command,
        tracker_state=tracker_state,
        database_rows_by_task_id=database_rows_by_task_id,
    )


async def refresh_tracker_state_for_task_ids(
    task_ids: list[str],
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> TrackerCommandResult:
    database_rows_by_task_id = await _fetch_database_rows_for_task_ids(
        task_ids=task_ids,
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    return refresh_task_ids_in_tracker_state(
        task_ids=list(database_rows_by_task_id),
        tracker_state=tracker_state,
        database_rows_by_task_id=database_rows_by_task_id,
    )


async def _fetch_database_rows_for_command_tasks(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> dict[str, TaskDatabaseRow]:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    database_rows_by_task_id = {}
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(find_task_ids_to_refresh_before_command(command, tracker_state)))

    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = await _fetch_known_task_database_row(task_id, task_tree, notion_client)
        database_rows_by_task_id[task_id] = database_row
        refreshed_task_ids.add(task_id)

        parent_task_id = _derive_parent_task_id_from_database_row(database_row, task_tree)
        if parent_task_id is not None and parent_task_id not in refreshed_task_ids:
            pending_task_ids.append(parent_task_id)

    return database_rows_by_task_id


async def _fetch_database_rows_for_task_ids(
    task_ids: list[str],
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> dict[str, TaskDatabaseRow]:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    database_rows_by_task_id = {}
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(task_ids))

    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = await _fetch_known_task_database_row(task_id, task_tree, notion_client)
        database_rows_by_task_id[task_id] = database_row
        refreshed_task_ids.add(task_id)

        parent_task_id = _derive_parent_task_id_from_database_row(database_row, task_tree)
        if parent_task_id is not None and parent_task_id not in refreshed_task_ids:
            pending_task_ids.append(parent_task_id)

    return database_rows_by_task_id


async def _fetch_known_task_database_row(
    task_id: str,
    task_tree: TaskTree,
    notion_client: NotionRestClient,
) -> TaskDatabaseRow:
    if task_id not in task_tree.tasks:
        raise ValueError(f"Task {task_id} is not in local tracker state; run notion_task update")

    notion_page_id = task_tree.tasks[task_id].notion_page_id
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id; run notion_task update")

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    return task_database_row_from_fetched_task_database_page(
        fetched_page_content=fetched_page_content,
        notion_page_id=notion_page_id,
    )


def _derive_parent_task_id_from_database_row(database_row: TaskDatabaseRow, task_tree: TaskTree) -> str | None:
    if len(database_row.parent_notion_page_ids) > 1:
        raise ValueError(f"Task {database_row.task_id} has more than one parent")

    if not database_row.parent_notion_page_ids:
        return None

    parent_page_id = database_row.parent_notion_page_ids[0]
    parent_task_id = task_tree.task_id_for_notion_page_id(parent_page_id)
    if parent_task_id is None:
        raise ValueError(
            f"Parent page {parent_page_id} for task {database_row.task_id} is not in local tracker state; "
            "run notion_task update"
        )

    return parent_task_id


def _needs_task_context_for_command(command: dict[str, Any]) -> bool:
    return command["command"] in {
        "append_task_timeline_log",
        "complete_task",
        "cancel_task",
        "complete_task_with_all_children",
        "split_task_into_children",
        "split_task_with_sibling",
    }
