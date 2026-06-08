"""Refresh task tracker state from already fetched task database data."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tasks.database import (
    TaskDatabaseRow,
    build_task_tree_from_database_query_results,
)


def refresh_tracker_state_from_database_rows(
    tracker_state: dict[str, Any],
    database_rows: list[dict[str, Any]],
) -> TrackerCommandResult:
    previous_task_tree = TaskTree.from_tracker_state(tracker_state)
    task_tree = build_task_tree_from_database_query_results(
        query_results=database_rows,
        landing_page=previous_task_tree.ongoing_tasks_landing_page.page,
        completed_landing_page=previous_task_tree.completed_tasks_landing_page.page,
        previous_task_tree=previous_task_tree,
    )
    return TrackerCommandResult(
        tracker_state=task_tree.replace_task_tree_in_tracker_state(tracker_state),
        warnings=[],
        refreshed_task_ids=frozenset(task.task_id for task in task_tree.tasks.values()),
    )


def refresh_command_tasks_in_tracker_state(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(find_task_ids_to_refresh_before_command(command, tracker_state)))
    return _refresh_task_ids_in_task_tree(
        task_tree=task_tree,
        tracker_state=tracker_state,
        database_rows_by_task_id=database_rows_by_task_id,
        refreshed_task_ids=refreshed_task_ids,
        pending_task_ids=pending_task_ids,
    )


def refresh_task_ids_in_tracker_state(
    task_ids: list[str],
    tracker_state: dict[str, Any],
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
) -> TrackerCommandResult:
    return _refresh_task_ids_in_task_tree(
        task_tree=TaskTree.from_tracker_state(tracker_state),
        tracker_state=tracker_state,
        database_rows_by_task_id=database_rows_by_task_id,
        refreshed_task_ids=set(),
        pending_task_ids=list(dict.fromkeys(task_ids)),
    )


def _refresh_task_ids_in_task_tree(
    task_tree: TaskTree,
    tracker_state: dict[str, Any],
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
    refreshed_task_ids: set[str],
    pending_task_ids: list[str],
) -> TrackerCommandResult:
    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = _require_database_row_for_known_task(task_id, database_rows_by_task_id, task_tree)
        parent_task_id = _derive_parent_task_id_from_database_row(database_row, task_tree)
        dependency_task_ids = _derive_dependency_task_ids_from_database_row(database_row, task_tree)
        dependant_task_ids = _derive_dependant_task_ids_from_database_row(database_row, task_tree)
        task_tree.refresh_task_from_database_row(
            task_id=task_id,
            title=database_row.title,
            configured_priority=database_row.configured_priority,
            status=database_row.status,
            notion_page_id=database_row.notion_page_id,
            parent_task_id=parent_task_id,
            dependency_task_ids=dependency_task_ids,
            dependant_task_ids=dependant_task_ids,
            deadline=database_row.deadline,
            external_coordination=database_row.external_coordination,
            uncertainty=database_row.uncertainty,
            friction=database_row.friction,
        )
        refreshed_task_ids.add(task_id)

        if parent_task_id is not None and parent_task_id not in refreshed_task_ids:
            pending_task_ids.append(parent_task_id)

    task_tree.validate()
    task_tree.recalculate_display_priorities()
    return TrackerCommandResult(
        tracker_state=task_tree.replace_task_tree_in_tracker_state(tracker_state),
        warnings=[],
        refreshed_task_ids=frozenset(refreshed_task_ids),
    )


def find_task_ids_to_refresh_before_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> list[str]:
    command_name = command["command"]
    if command_name in {"append_task_timeline_log", "complete_task", "cancel_task"}:
        return [command["task_id"]]

    if command_name == "split_task_into_children":
        return [command["source_task_id"]]

    if command_name == "split_task_with_sibling":
        source_task_id = command["source_task_id"]
        source_task = tracker_state.get("tasks", {}).get(source_task_id, {})
        task_ids = [source_task_id]
        if source_task.get("parent_task_id") is not None:
            task_ids.append(source_task["parent_task_id"])
        return task_ids

    return []


def _require_database_row_for_known_task(
    task_id: str,
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
    task_tree: TaskTree,
) -> TaskDatabaseRow:
    if task_id not in task_tree.tasks:
        raise ValueError(f"Task {task_id} is not in local tracker state; run notion_task update")

    database_row = database_rows_by_task_id[task_id]
    if database_row.task_id != task_id:
        raise ValueError(f"Task page for {task_id} now reports {database_row.task_id}; run notion_task update")

    return database_row


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


def _derive_dependency_task_ids_from_database_row(
    database_row: TaskDatabaseRow,
    task_tree: TaskTree,
) -> list[str]:
    dependency_task_ids = []
    for dependency_page_id in database_row.dependency_notion_page_ids:
        dependency_task_id = task_tree.task_id_for_notion_page_id(dependency_page_id)
        if dependency_task_id is None:
            raise ValueError(
                f"Dependency page {dependency_page_id} for task {database_row.task_id} "
                "is not in local tracker state; run notion_task update"
            )
        dependency_task_ids.append(dependency_task_id)

    return dependency_task_ids


def _derive_dependant_task_ids_from_database_row(
    database_row: TaskDatabaseRow,
    task_tree: TaskTree,
) -> list[str]:
    dependant_task_ids = []
    for dependant_page_id in database_row.dependant_notion_page_ids:
        dependant_task_id = task_tree.task_id_for_notion_page_id(dependant_page_id)
        if dependant_task_id is None:
            raise ValueError(
                f"Dependant page {dependant_page_id} for task {database_row.task_id} "
                "is not in local tracker state; run notion_task update"
            )
        dependant_task_ids.append(dependant_task_id)

    return dependant_task_ids
