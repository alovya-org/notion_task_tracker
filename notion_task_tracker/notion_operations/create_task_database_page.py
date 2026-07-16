"""Create task database pages and execute the Notion writes caused by creation."""

from __future__ import annotations

import json
from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_operations.markdown import bullet, heading, join_markdown_blocks
from notion_task_tracker.notion_operations.plan_task_page_write_intents import render_timeline_entry_content_markdown
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import prepare_command_result_from_current_task_page
from notion_task_tracker.notion_operations.reconcile_task_database import refresh_tracker_state_from_notion_task_database
from notion_task_tracker.notion_operations.write_executor import execute_command_result_writes
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tasks.create_task import (
    TaskCreation,
    derive_split_task_page_creations,
    add_created_task_to_tracker_state,
    clear_split_source_task_relations,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_END_DATE_TIME_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_START_DATE_TIME_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
    task_database_data_source_id_from_tracker_state,
    task_id_from_fetched_task_database_page,
)
from notion_task_tracker.tasks.task import (
    TASK_PAGE_TIMELINE_LOG_HEADING,
    TimelineEntry,
    render_task_database_page_title,
)


async def execute_create_task_database_page_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> tuple[dict[str, Any], list[str]]:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    task_creations = derive_split_task_page_creations(command, task_tree)
    updated_tracker_state = tracker_state
    executed_operation_keys = []
    for task_creation in task_creations:
        create_task_tree = TaskTree.from_tracker_state(updated_tracker_state)
        created_page_id, created_task_id, create_operation_keys = await _create_database_page_and_read_ticket_id(
            task_creation=task_creation,
            tracker_state=updated_tracker_state,
            task_tree=create_task_tree,
            notion_client=notion_client,
        )
        updated_tracker_state = add_created_task_to_tracker_state(
            tracker_state=updated_tracker_state,
            task_creation=task_creation,
            created_task_id=created_task_id,
            created_page_id=created_page_id,
        )
        updated_tracker_state, timeline_operation_keys = await _write_task_creation_timeline_entry(
            task_creation=task_creation,
            tracker_state=updated_tracker_state,
            created_task_id=created_task_id,
            notion_client=notion_client,
        )
        executed_operation_keys.extend(create_operation_keys + timeline_operation_keys)

    if command["command"] == "split_task_into_children":
        updated_tracker_state, clear_relation_operation_keys = await _clear_child_split_source_relations(
            updated_tracker_state,
            command["source_task_id"],
            notion_client,
        )
        executed_operation_keys.extend(clear_relation_operation_keys)

    tracker_state_after_refreshing_task_landing_pages, landing_operation_keys = await _refresh_derived_task_landing_pages(
        updated_tracker_state,
        notion_client,
    )
    return tracker_state_after_refreshing_task_landing_pages, executed_operation_keys + landing_operation_keys


def should_create_task_database_page_for_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> bool:
    if command.get("command") not in {
        "create_top_level_task",
        "split_task_into_children",
        "split_task_with_sibling",
    }:
        return False

    if "task_database" not in tracker_state:
        raise ValueError("Task creation requires task_database in tracker state")

    return True


async def _create_database_page_and_read_ticket_id(
    task_creation: TaskCreation,
    tracker_state: dict[str, Any],
    task_tree: TaskTree,
    notion_client: NotionRestClient,
) -> tuple[str, str, list[str]]:
    create_operation_key = f"create_database_task:{task_creation.command_name}"
    created_page = await notion_client.create_task_database_page(
        data_source_id=task_database_data_source_id_from_tracker_state(tracker_state),
        properties=_build_new_task_database_row_properties(
            task_title=task_creation.task_title,
            configured_priority=task_creation.configured_priority.value,
            status=task_creation.status.value,
            parent_task_id=task_creation.parent_task_id,
            dependency_task_ids=task_creation.dependency_task_ids,
            dependant_task_ids=task_creation.dependant_task_ids,
            deadline=task_creation.deadline,
            start_date_time=task_creation.start_date_time,
            end_date_time=task_creation.end_date_time,
            external_coordination=task_creation.external_coordination.value,
            uncertainty=task_creation.uncertainty.value,
            friction=task_creation.friction.value,
            task_tree=task_tree,
        ),
        content=_render_new_task_page_initial_content(
            initial_timeline_entry=task_creation.initial_child_timeline_entry,
            parent_task_id=task_creation.parent_task_id,
            task_tree=task_tree,
        ),
        operation_key=create_operation_key,
    )
    fetched_page_content = await notion_client.fetch_task_page_content(created_page.notion_page_id)
    created_task_id = task_id_from_fetched_task_database_page(
        fetched_page_content,
        ticket_prefix=tracker_state["identity"]["ticket_prefix"],
    )
    update_title_operation_key = f"update_properties:task:{created_task_id}"
    completed_update_operation_key = await notion_client.update_task_database_page_title(
        page_id=created_page.notion_page_id,
        title_property=TASK_DATABASE_TITLE_PROPERTY,
        title=render_task_database_page_title(created_task_id, task_creation.task_title),
        operation_key=update_title_operation_key,
    )
    return (
        created_page.notion_page_id,
        created_task_id,
        [*created_page.operation_keys, completed_update_operation_key],
    )


async def _write_task_creation_timeline_entry(
    task_creation: TaskCreation,
    tracker_state: dict[str, Any],
    created_task_id: str,
    notion_client: NotionRestClient,
) -> tuple[dict[str, Any], list[str]]:
    timeline_command = _build_created_task_timeline_command(
        task_creation=task_creation,
        created_task_url=_build_task_notion_url_from_tracker_state(tracker_state, created_task_id),
    )
    if timeline_command is None:
        return tracker_state, []

    timeline_owner_task_id = task_creation.parent_task_id or created_task_id
    timeline_result = await prepare_command_result_from_current_task_page(
        command={
            "command": "append_task_timeline_log",
            "task_id": timeline_owner_task_id,
            "timeline_entry": timeline_command,
        },
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    return await execute_command_result_writes(timeline_result, notion_client)


async def _refresh_derived_task_landing_pages(
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> tuple[dict[str, Any], list[str]]:
    refreshed_result = await refresh_tracker_state_from_notion_task_database(tracker_state, notion_client)
    landing_refresh_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": ["replace:ongoing_landing_page", "replace:completed_landing_page"],
        },
        tracker_state=refreshed_result.tracker_state,
    )
    return await execute_command_result_writes(landing_refresh_result, notion_client)


async def _clear_child_split_source_relations(
    tracker_state: dict[str, Any],
    source_task_id: str,
    notion_client: NotionRestClient,
) -> tuple[dict[str, Any], list[str]]:
    relation_tracker_state = clear_split_source_task_relations(tracker_state, source_task_id)
    dependency_result = apply_command_to_tracker_state(
        command={
            "command": "set_task_dependencies",
            "task_id": source_task_id,
            "dependency_task_ids": [],
        },
        tracker_state=tracker_state,
    )
    dependant_result = apply_command_to_tracker_state(
        command={
            "command": "set_task_dependants",
            "task_id": source_task_id,
            "dependant_task_ids": [],
        },
        tracker_state=dependency_result.tracker_state,
    )
    dependant_result = TrackerCommandResult(
        tracker_state=relation_tracker_state,
        write_intents=[*dependency_result.write_intents, *dependant_result.write_intents],
        page_registry=dependant_result.page_registry,
        warnings=[*dependency_result.warnings, *dependant_result.warnings],
    )
    return await execute_command_result_writes(dependant_result, notion_client)


def _render_new_task_page_initial_content(
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    task_tree: TaskTree,
) -> str:
    if initial_timeline_entry is None:
        return f"## {TASK_PAGE_TIMELINE_LOG_HEADING}"

    timeline_entry = TimelineEntry.from_command(initial_timeline_entry)
    return join_markdown_blocks(
        [
            heading(2, TASK_PAGE_TIMELINE_LOG_HEADING),
            heading(3, timeline_entry.heading),
            _render_new_task_initial_timeline_content(timeline_entry, parent_task_id, task_tree),
        ]
    )


def _render_new_task_initial_timeline_content(
    timeline_entry: TimelineEntry,
    parent_task_id: str | None,
    task_tree: TaskTree,
) -> str:
    timeline_content = render_timeline_entry_content_markdown(timeline_entry)
    if parent_task_id is None:
        return timeline_content

    parent_page_url = _build_task_notion_url(task_tree, parent_task_id)
    return join_markdown_blocks([
        bullet(f'Spawned from parent task: <mention-page url="{parent_page_url}"/>.'),
        timeline_content,
    ])


def _build_created_task_timeline_command(
    task_creation: TaskCreation,
    created_task_url: str,
) -> dict[str, Any] | None:
    if task_creation.parent_timeline_entry is None:
        return None

    if task_creation.command_name not in {"split_task_into_children", "split_task_with_sibling"}:
        return task_creation.parent_timeline_entry

    return {
        "entry_date": task_creation.parent_timeline_entry["entry_date"],
        "heading": task_creation.parent_timeline_entry["heading"],
        "lines": [f'Spawned child task: <mention-page url="{created_task_url}"/>.'],
    }


def _build_new_task_database_row_properties(
    task_title: str,
    configured_priority: str,
    status: str,
    parent_task_id: str | None,
    dependency_task_ids: list[str],
    dependant_task_ids: list[str],
    deadline: str | None,
    start_date_time: str | None,
    end_date_time: str | None,
    external_coordination: str,
    uncertainty: str,
    friction: str,
    task_tree: TaskTree,
) -> dict[str, Any]:
    properties = {
        TASK_DATABASE_TITLE_PROPERTY: task_title,
        TASK_DATABASE_PRIORITY_PROPERTY: configured_priority,
        TASK_DATABASE_STATUS_PROPERTY: status,
        TASK_DATABASE_DEADLINE_PROPERTY: deadline,
        TASK_DATABASE_START_DATE_TIME_PROPERTY: start_date_time,
        TASK_DATABASE_END_DATE_TIME_PROPERTY: end_date_time,
        TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY: external_coordination,
        TASK_DATABASE_UNCERTAINTY_PROPERTY: uncertainty,
        TASK_DATABASE_FRICTION_PROPERTY: friction,
    }
    if dependency_task_ids:
        properties[TASK_DATABASE_DEPENDENCIES_PROPERTY] = json.dumps([
            _build_task_notion_url(task_tree, dependency_task_id)
            for dependency_task_id in dependency_task_ids
        ])
    if dependant_task_ids:
        properties[TASK_DATABASE_DEPENDANTS_PROPERTY] = json.dumps([
            _build_task_notion_url(task_tree, dependant_task_id)
            for dependant_task_id in dependant_task_ids
        ])
    if parent_task_id is not None:
        properties[TASK_DATABASE_PARENT_PROPERTY] = json.dumps([
            _build_task_notion_url(task_tree, parent_task_id)
        ])
    return properties


def _build_task_notion_url(task_tree: TaskTree, task_id: str) -> str:
    notion_page_id = task_tree.tasks[task_id].notion_page_id
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id")

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


def _build_task_notion_url_from_tracker_state(tracker_state: dict[str, Any], task_id: str) -> str:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id")

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"
