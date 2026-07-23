"""Create task database pages and execute the Notion writes caused by creation."""

from __future__ import annotations

import json
from typing import Any

from notion_task_tracker.apply_task_command import TaskCommandPlan
from notion_task_tracker.notion_operations.markdown import bullet, heading, join_markdown_blocks
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
    build_task_dependencies_update_intent,
    render_timeline_log_toggle_markdown,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tasks.create_task import (
    TaskCreation,
    derive_split_task_page_creations,
    add_created_task_to_tree,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_DURATION_PROPERTY,
    TASK_DATABASE_DURATION_UNIT_PROPERTY,
    TASK_DATABASE_END_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_START_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
    task_id_from_fetched_task_database_page,
)
from notion_task_tracker.tasks.task import (
    TASK_PAGE_TIMELINE_LOG_HEADING,
    TimelineLog,
    derive_task_end,
    generate_timeline_log_id,
    render_task_database_page_title,
)


async def create_tasks_in_current_tree(
    command: dict[str, Any],
    task_tree: TaskTree,
    ticket_prefix: str,
    task_data_source_id: str,
    fetched_page_content_by_task_id: dict[str, str],
    notion_client: NotionRestClient,
) -> list[str]:
    task_creations = derive_split_task_page_creations(
        command,
        task_tree,
        ticket_prefix,
    )
    initial_page_content = [
        _render_new_task_page_initial_content(
            task_creation.initial_child_timeline_entry,
            task_creation.parent_task_id,
            task_tree,
        )
        for task_creation in task_creations
    ]
    for task_creation in task_creations:
        _validate_task_creation_parent_timeline(task_creation, ticket_prefix)

    completed_operation_keys = []
    for task_creation, page_content in zip(
        task_creations,
        initial_page_content,
        strict=True,
    ):
        created_page_id, created_task_id, create_operation_keys = (
            await _create_current_task_database_page(
                task_creation,
                task_tree,
                ticket_prefix,
                task_data_source_id,
                page_content,
                notion_client,
            )
        )
        add_created_task_to_tree(
            task_tree,
            task_creation,
            created_task_id,
            created_page_id,
        )
        completed_operation_keys.extend(create_operation_keys)
        completed_operation_keys.extend(
            await _write_current_task_creation_timeline(
                task_creation,
                created_task_id,
                task_tree,
                ticket_prefix,
                fetched_page_content_by_task_id,
                notion_client,
            )
        )

    if command["command"] == "split_task_into_children":
        completed_operation_keys.extend(
            await _clear_current_split_source_relations(
                task_tree,
                command["source_task_id"],
                notion_client,
            )
        )
    return completed_operation_keys


def _validate_task_creation_parent_timeline(
    task_creation: TaskCreation,
    ticket_prefix: str,
) -> None:
    if task_creation.parent_timeline_entry is None:
        return
    timeline_entry = dict(task_creation.parent_timeline_entry)
    if task_creation.command_name in {
        "split_task_into_children",
        "split_task_with_sibling",
    }:
        timeline_entry = {
            "log_id": generate_timeline_log_id(ticket_prefix),
            "title": "Created child task",
            "entry_date": task_creation.parent_timeline_entry["entry_date"],
            "heading": task_creation.parent_timeline_entry["heading"],
            "lines": ["Created task link is resolved after Notion assigns its page id."],
        }
    render_timeline_log_toggle_markdown(TimelineLog.from_command(timeline_entry))


async def _create_current_task_database_page(
    task_creation: TaskCreation,
    task_tree: TaskTree,
    ticket_prefix: str,
    task_data_source_id: str,
    page_content: str,
    notion_client: NotionRestClient,
) -> tuple[str, str, list[str]]:
    create_operation_key = f"create_database_task:{task_creation.command_name}"
    created_page = await notion_client.create_task_database_page(
        data_source_id=task_data_source_id,
        properties=_build_new_task_database_row_properties(
            task_title=task_creation.task_title,
            configured_priority=task_creation.configured_priority.value,
            status=task_creation.status.value,
            parent_task_id=task_creation.parent_task_id,
            dependency_task_ids=task_creation.dependency_task_ids,
            dependant_task_ids=task_creation.dependant_task_ids,
            deadline=task_creation.deadline,
            start=task_creation.start,
            end=derive_task_end(
                task_label=task_creation.task_title,
                start=task_creation.start,
                duration=task_creation.duration,
                duration_unit=task_creation.duration_unit,
            ),
            duration=task_creation.duration,
            duration_unit=(
                task_creation.duration_unit.value
                if task_creation.duration_unit is not None
                else None
            ),
            external_coordination=task_creation.external_coordination.value,
            uncertainty=task_creation.uncertainty.value,
            friction=task_creation.friction.value,
            task_tree=task_tree,
        ),
        content=page_content,
        operation_key=create_operation_key,
    )
    fetched_page_content = await notion_client.fetch_task_page_content(
        created_page.notion_page_id
    )
    created_task_id = task_id_from_fetched_task_database_page(
        fetched_page_content,
        ticket_prefix=ticket_prefix,
    )
    update_title_operation_key = f"update_properties:task:{created_task_id}"
    completed_title_operation_key = (
        await notion_client.update_task_database_page_title(
            page_id=created_page.notion_page_id,
            title_property=TASK_DATABASE_TITLE_PROPERTY,
            title=render_task_database_page_title(
                created_task_id,
                task_creation.task_title,
            ),
            operation_key=update_title_operation_key,
        )
    )
    return (
        created_page.notion_page_id,
        created_task_id,
        [*created_page.operation_keys, completed_title_operation_key],
    )


async def _write_current_task_creation_timeline(
    task_creation: TaskCreation,
    created_task_id: str,
    task_tree: TaskTree,
    ticket_prefix: str,
    fetched_page_content_by_task_id: dict[str, str],
    notion_client: NotionRestClient,
) -> list[str]:
    timeline_command = _build_created_task_timeline_command(
        task_creation,
        _build_task_notion_url(task_tree, created_task_id),
        ticket_prefix,
    )
    if timeline_command is None:
        return []
    timeline_owner_task_id = task_creation.parent_task_id or created_task_id
    if timeline_owner_task_id == created_task_id:
        fetched_page_content_by_task_id[created_task_id] = (
            await notion_client.fetch_task_page_content(
                task_tree.tasks[created_task_id].notion_page_id
            )
        )
    from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import (
        prepare_task_command_from_fetched_page_bodies,
    )

    timeline_plan = prepare_task_command_from_fetched_page_bodies(
        command={
            "command": "append_task_timeline_log",
            "task_id": timeline_owner_task_id,
            "timeline_entry": timeline_command,
        },
        task_tree=task_tree,
        ticket_prefix=ticket_prefix,
        fetched_page_content_by_task_id=fetched_page_content_by_task_id,
    )
    write_result = await notion_client.execute_command_result(timeline_plan)
    return list(write_result.completed_operation_keys)


async def _clear_current_split_source_relations(
    task_tree: TaskTree,
    source_task_id: str,
    notion_client: NotionRestClient,
) -> list[str]:
    dependant_task_ids = list(task_tree.tasks[source_task_id].dependant_task_ids)
    task_tree.set_task_dependencies(source_task_id, [])
    task_tree.set_task_dependants(source_task_id, [])
    relation_plan = TaskCommandPlan(
        task_tree=task_tree,
        write_intents=[
            build_task_dependencies_update_intent(task_tree.tasks[source_task_id]),
            *[
                build_task_dependencies_update_intent(
                    task_tree.tasks[dependant_task_id]
                )
                for dependant_task_id in dependant_task_ids
            ],
        ],
        page_registry=build_page_registry_for_task_tree(task_tree),
    )
    write_result = await notion_client.execute_command_result(relation_plan)
    return list(write_result.completed_operation_keys)


def _render_new_task_page_initial_content(
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    task_tree: TaskTree,
) -> str:
    if initial_timeline_entry is None:
        return f"## {TASK_PAGE_TIMELINE_LOG_HEADING}"

    timeline_log = TimelineLog.from_command(initial_timeline_entry)
    return join_markdown_blocks(
        [
            heading(2, TASK_PAGE_TIMELINE_LOG_HEADING),
            heading(3, timeline_log.heading),
            _render_new_task_initial_timeline_log(timeline_log, parent_task_id, task_tree),
        ]
    )


def _render_new_task_initial_timeline_log(
    timeline_log: TimelineLog,
    parent_task_id: str | None,
    task_tree: TaskTree,
) -> str:
    if parent_task_id is None:
        return render_timeline_log_toggle_markdown(timeline_log)

    parent_page_url = _build_task_notion_url(task_tree, parent_task_id)
    return render_timeline_log_toggle_markdown(
        timeline_log,
        leading_content_markdown=bullet(
            f'Spawned from parent task: <mention-page url="{parent_page_url}"/>.'
        ),
    )


def _build_created_task_timeline_command(
    task_creation: TaskCreation,
    created_task_url: str,
    ticket_prefix: str,
) -> dict[str, Any] | None:
    if task_creation.parent_timeline_entry is None:
        return None

    if task_creation.command_name not in {"split_task_into_children", "split_task_with_sibling"}:
        return task_creation.parent_timeline_entry

    return {
        "log_id": generate_timeline_log_id(ticket_prefix),
        "title": "Created child task",
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
    start: str | None,
    end: str | None,
    duration: float | None,
    duration_unit: str | None,
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
        TASK_DATABASE_START_PROPERTY: start,
        TASK_DATABASE_END_PROPERTY: end,
        TASK_DATABASE_DURATION_PROPERTY: duration,
        TASK_DATABASE_DURATION_UNIT_PROPERTY: duration_unit,
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
