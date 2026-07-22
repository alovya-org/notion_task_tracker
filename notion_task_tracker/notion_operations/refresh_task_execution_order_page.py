"""Render ready leaf tasks through a linked database view."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.notion_operations.notion_id import canonical_notion_page_id
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import TaskStatus, TaskTree
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DURATION_PROPERTY,
    TASK_DATABASE_DURATION_UNIT_PROPERTY,
    TASK_DATABASE_END_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_START_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
    task_database_data_source_id_from_tracker_state,
)


TASK_DATABASE_EXECUTION_ORDER_PROPERTY = "In execution order"
_VISIBLE_EXECUTION_ORDER_PROPERTIES = [
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
]
_HIDDEN_EXECUTION_ORDER_PROPERTIES = [
    TASK_DATABASE_START_PROPERTY,
    TASK_DATABASE_END_PROPERTY,
    TASK_DATABASE_DURATION_PROPERTY,
    TASK_DATABASE_DURATION_UNIT_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_EXECUTION_ORDER_PROPERTY,
]


async def refresh_task_execution_order_page(
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> list[str]:
    """Make the linked view show exactly the locally derived ready leaf tasks."""
    page_id = _ready_priority_page_id(tracker_state)
    data_source_id = task_database_data_source_id_from_tracker_state(tracker_state)
    task_tree = TaskTree.from_tracker_state(tracker_state)
    page_blocks = await notion_client.fetch_block_children(page_id)
    page_contains_linked_database = _page_contains_linked_database(page_blocks)

    properties, property_was_created = await notion_client.ensure_checkbox_property(
        data_source_id,
        TASK_DATABASE_EXECUTION_ORDER_PROPERTY,
    )
    completed_operation_keys = (
        ["create:task_database_property:in_execution_order"]
        if property_was_created
        else []
    )

    if not page_contains_linked_database:
        for blank_paragraph_id in _blank_paragraph_ids(page_blocks):
            await notion_client.delete_block(blank_paragraph_id)
        await notion_client.create_linked_execution_order_view(
            page_id=page_id,
            data_source_id=data_source_id,
            property_ids_by_name={
                property_name: property_definition["id"]
                for property_name, property_definition in properties.items()
            },
            visible_property_names=_VISIBLE_EXECUTION_ORDER_PROPERTIES,
            hidden_property_names=_HIDDEN_EXECUTION_ORDER_PROPERTIES,
            membership_property_name=TASK_DATABASE_EXECUTION_ORDER_PROPERTY,
        )
        completed_operation_keys.append("create:ready_priority_page:linked_database_view")

    ready_task_ids = set(_ready_leaf_task_ids(task_tree))
    currently_included_page_ids = await notion_client.query_checkbox_page_ids(
        data_source_id,
        TASK_DATABASE_EXECUTION_ORDER_PROPERTY,
    )
    for task in task_tree.tasks.values():
        if task.notion_page_id is None:
            raise ValueError(f"Task {task.task_id} must have a Notion page id")
        page_id = canonical_notion_page_id(task.notion_page_id)
        should_be_included = task.task_id in ready_task_ids
        if (page_id in currently_included_page_ids) == should_be_included:
            continue
        await notion_client.update_page_properties(
            page_id,
            {TASK_DATABASE_EXECUTION_ORDER_PROPERTY: {"checkbox": should_be_included}},
        )
        completed_operation_keys.append(f"update:execution_order_membership:task:{task.task_id}")

    return completed_operation_keys


def _ready_leaf_task_ids(task_tree: TaskTree) -> list[str]:
    return [
        task.task_id
        for task in task_tree.tasks.values()
        if task.status not in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}
        and not task.child_task_ids
        and all(
            task_tree.tasks[dependency_task_id].status == TaskStatus.COMPLETE
            for dependency_task_id in task.dependency_task_ids
        )
    ]


def _ready_priority_page_id(tracker_state: dict[str, Any]) -> str:
    priority_page = tracker_state.get("ready_priority_page")
    if not isinstance(priority_page, dict) or not priority_page.get("notion_page_id"):
        raise ValueError("Tracker state has no configured ready priority page; run `ntt --init`")
    return canonical_notion_page_id(priority_page["notion_page_id"])


def _page_contains_linked_database(page_blocks: list[dict[str, Any]]) -> bool:
    if not page_blocks or len(_blank_paragraph_ids(page_blocks)) == len(page_blocks):
        return False
    if len(page_blocks) == 1 and page_blocks[0].get("type") == "child_database":
        return True
    raise ValueError("Task execution-order page must be empty or contain only its linked database")


def _blank_paragraph_ids(page_blocks: list[dict[str, Any]]) -> list[str]:
    return [
        page_block["id"]
        for page_block in page_blocks
        if page_block.get("type") == "paragraph"
        and not page_block.get("paragraph", {}).get("rich_text")
    ]
