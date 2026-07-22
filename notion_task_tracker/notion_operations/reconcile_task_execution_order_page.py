"""Keep the ready-task priority page aligned without disturbing user ordering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_task_tracker.notion_operations.notion_id import canonical_notion_page_id
from notion_task_tracker.notion_operations.database_properties import rich_text_items
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import Task, TaskStatus, TaskTree
from notion_task_tracker.tasks.task import LANDING_COLOR_BY_PRIORITY, task_id_sort_key


async def reconcile_task_execution_order_page(
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> list[str]:
    priority_page_id = _ready_priority_page_id(tracker_state)
    task_tree = TaskTree.from_tracker_state(tracker_state)
    ready_leaf_task_ids = _ready_leaf_task_ids(task_tree)
    priority_blocks = await notion_client.fetch_block_children(priority_page_id)
    task_id_by_page_id = _task_id_by_page_id(task_tree)
    blank_paragraph_block_ids = [
        priority_block["id"]
        for priority_block in priority_blocks
        if _block_is_blank_paragraph(priority_block)
    ]
    priority_task_blocks = [
        _read_priority_task_block(priority_block, task_id_by_page_id)
        for priority_block in priority_blocks
        if not _block_is_blank_paragraph(priority_block)
    ]
    preserved_task_blocks, removed_task_blocks = _separate_preserved_and_removed_task_blocks(
        priority_task_blocks,
        ready_leaf_task_ids,
    )

    completed_operation_keys = []
    for blank_paragraph_block_id in blank_paragraph_block_ids:
        await notion_client.delete_block(blank_paragraph_block_id)
        completed_operation_keys.append(
            f"delete:ready_priority_page:block:{blank_paragraph_block_id}"
        )
    for removed_task_block in removed_task_blocks:
        await notion_client.delete_block(removed_task_block.block_id)
        completed_operation_keys.append(
            f"delete:ready_priority_page:block:{removed_task_block.block_id}"
        )

    preserved_task_ids = {task_block.task_id for task_block in preserved_task_blocks}
    missing_ready_task_ids = [
        task_id
        for task_id in ready_leaf_task_ids
        if task_id not in preserved_task_ids
    ]
    if missing_ready_task_ids:
        await notion_client.append_block_children(
            parent_block_id=priority_page_id,
            children=[
                _numbered_execution_order_item_for_task(task_tree.tasks[task_id])
                for task_id in missing_ready_task_ids
            ],
            after_block_id=(
                preserved_task_blocks[-1].block_id
                if preserved_task_blocks
                else None
            ),
        )
        completed_operation_keys.append("append:ready_priority_page")

    return completed_operation_keys


def _ready_leaf_task_ids(task_tree: TaskTree) -> list[str]:
    return [
        task.task_id
        for task in sorted(task_tree.tasks.values(), key=lambda task: task_id_sort_key(task.task_id))
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


def _task_id_by_page_id(task_tree: TaskTree) -> dict[str, str]:
    return {
        canonical_notion_page_id(task.notion_page_id): task.task_id
        for task in task_tree.tasks.values()
        if task.notion_page_id is not None
    }


@dataclass(frozen=True)
class _PriorityTaskBlock:
    block_id: str
    task_id: str


def _block_is_blank_paragraph(priority_block: dict[str, Any]) -> bool:
    return (
        priority_block.get("type") == "paragraph"
        and not priority_block.get("paragraph", {}).get("rich_text")
    )


def _read_priority_task_block(
    priority_block: dict[str, Any],
    task_id_by_page_id: dict[str, str],
) -> _PriorityTaskBlock:
    if priority_block.get("type") != "numbered_list_item":
        raise ValueError("Task execution-order page may contain only numbered task items")

    page_ids = [
        canonical_notion_page_id(rich_text["mention"]["page"]["id"])
        for rich_text in priority_block["numbered_list_item"].get("rich_text", [])
        if rich_text.get("type") == "mention"
        and rich_text.get("mention", {}).get("type") == "page"
    ]
    if len(page_ids) != 1 or page_ids[0] not in task_id_by_page_id:
        raise ValueError("Each execution-order item must mention exactly one known task page")
    return _PriorityTaskBlock(
        block_id=priority_block["id"],
        task_id=task_id_by_page_id[page_ids[0]],
    )


def _separate_preserved_and_removed_task_blocks(
    priority_task_blocks: list[_PriorityTaskBlock],
    ready_leaf_task_ids: list[str],
) -> tuple[list[_PriorityTaskBlock], list[_PriorityTaskBlock]]:
    preserved_task_blocks = []
    removed_task_blocks = []
    preserved_task_ids = set()
    for priority_task_block in priority_task_blocks:
        if (
            priority_task_block.task_id in ready_leaf_task_ids
            and priority_task_block.task_id not in preserved_task_ids
        ):
            preserved_task_blocks.append(priority_task_block)
            preserved_task_ids.add(priority_task_block.task_id)
        else:
            removed_task_blocks.append(priority_task_block)
    return preserved_task_blocks, removed_task_blocks


def _numbered_execution_order_item_for_task(task: Task) -> dict[str, Any]:
    if task.notion_page_id is None:
        raise ValueError("A ready task must have a Notion page id")
    displayed_priority = task.displayed_priority or task.configured_priority
    task_page_url = f"https://www.notion.so/{canonical_notion_page_id(task.notion_page_id)}"
    deadline_label = f" [{task.deadline}]" if task.deadline else ""
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": rich_text_items(
                f"[{displayed_priority.value}]{deadline_label} "
                f"<mention-page url=\"{task_page_url}\"/>: {task.status.value}"
            ),
            "color": LANDING_COLOR_BY_PRIORITY[displayed_priority],
        },
    }
