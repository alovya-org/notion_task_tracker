import asyncio

from notion_task_tracker.notion_operations.reconcile_task_execution_order_page import (
    reconcile_task_execution_order_page,
)
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree


def test_reconcile_task_execution_order_page_preserves_user_order_and_changes_only_membership():
    task_tree = _task_tree_with_ready_blocked_and_container_tasks()
    notion_client = _PriorityPageClient([
        _numbered_task_item("block-2", "22222222222222222222222222222222"),
        _blank_paragraph("blank-block"),
        _numbered_task_item("block-3", "33333333333333333333333333333333"),
        _numbered_task_item("block-1", "11111111111111111111111111111111"),
    ])

    operation_keys = asyncio.run(
        reconcile_task_execution_order_page(_tracker_state(task_tree), notion_client)
    )

    assert notion_client.deleted_block_ids == [
        "blank-block",
        "block-3",
    ]
    assert notion_client.append_calls == [{
        "parent_block_id": "99999999999999999999999999999999",
        "mentioned_page_ids": [
            "66666666666666666666666666666666",
            "77777777777777777777777777777777",
        ],
        "after_block_id": "block-1",
        "plain_text": [
            "[P2] : Active",
            "[P2] : Active",
        ],
        "colours": ["yellow", "yellow"],
        "types": [
            "numbered_list_item",
            "numbered_list_item",
        ],
    }]
    assert operation_keys == [
        "delete:ready_priority_page:block:blank-block",
        "delete:ready_priority_page:block:block-3",
        "append:ready_priority_page",
    ]


def test_reconcile_task_execution_order_page_populates_an_empty_page_with_every_ready_leaf():
    task_tree = _task_tree_with_ready_blocked_and_container_tasks()
    notion_client = _PriorityPageClient([])

    asyncio.run(reconcile_task_execution_order_page(_tracker_state(task_tree), notion_client))

    assert notion_client.deleted_block_ids == []
    assert notion_client.append_calls == [{
        "parent_block_id": "99999999999999999999999999999999",
        "mentioned_page_ids": [
            "11111111111111111111111111111111",
            "22222222222222222222222222222222",
            "66666666666666666666666666666666",
            "77777777777777777777777777777777",
        ],
        "after_block_id": None,
        "plain_text": [
            "[P2] : Active",
            "[P2] [2026-08-15] : Active",
            "[P2] : Active",
            "[P2] : Active",
        ],
        "colours": ["yellow", "yellow", "yellow", "yellow"],
        "types": [
            "numbered_list_item",
            "numbered_list_item",
            "numbered_list_item",
            "numbered_list_item",
        ],
    }]


def _task_tree_with_ready_blocked_and_container_tasks() -> TaskTree:
    task_tree = TaskTree()
    for task_id, status, notion_page_id in [
        ("ALOVYA-1", TaskStatus.ACTIVE, "11111111111111111111111111111111"),
        ("ALOVYA-2", TaskStatus.ACTIVE, "22222222222222222222222222222222"),
        ("ALOVYA-3", TaskStatus.ACTIVE, "33333333333333333333333333333333"),
        ("ALOVYA-4", TaskStatus.ACTIVE, "44444444444444444444444444444444"),
        ("ALOVYA-5", TaskStatus.COMPLETE, "55555555555555555555555555555555"),
        ("ALOVYA-6", TaskStatus.ACTIVE, "66666666666666666666666666666666"),
        ("ALOVYA-7", TaskStatus.ACTIVE, "77777777777777777777777777777777"),
    ]:
        task_tree.add_task(Task(
            task_id=task_id,
            title=f"Task {task_id}",
            configured_priority=Priority.P2,
            status=status,
            notion_page_id=notion_page_id,
        ))

    task_tree.set_task_dependencies("ALOVYA-2", ["ALOVYA-5"])
    task_tree.set_task_deadline("ALOVYA-2", "2026-08-15")
    task_tree.set_task_dependencies("ALOVYA-3", ["ALOVYA-6"])
    task_tree.link_parent_to_child("ALOVYA-4", "ALOVYA-7")
    return task_tree


def _tracker_state(task_tree: TaskTree) -> dict:
    return {
        **task_tree.to_tracker_state(),
        "ready_priority_page": {
            "local_page_key": "ready_priority_page",
            "title": "Tasks in execution order",
            "notion_page_id": "99999999999999999999999999999999",
            "parent_page_key": None,
        },
    }


def _numbered_task_item(block_id: str, notion_page_id: str) -> dict:
    return {
        "id": block_id,
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [{
                "type": "mention",
                "mention": {"type": "page", "page": {"id": notion_page_id}},
            }],
        },
    }


def _blank_paragraph(block_id: str) -> dict:
    return {
        "id": block_id,
        "type": "paragraph",
        "paragraph": {"rich_text": []},
    }


class _PriorityPageClient:
    def __init__(self, priority_blocks: list[dict]) -> None:
        self.priority_blocks = priority_blocks
        self.deleted_block_ids = []
        self.append_calls = []

    async def fetch_block_children(self, parent_block_id: str) -> list[dict]:
        assert parent_block_id == "99999999999999999999999999999999"
        return self.priority_blocks

    async def delete_block(self, block_id: str) -> None:
        self.deleted_block_ids.append(block_id)

    async def append_block_children(
        self,
        parent_block_id: str,
        children: list[dict],
        after_block_id: str | None,
    ) -> None:
        self.append_calls.append({
            "parent_block_id": parent_block_id,
            "mentioned_page_ids": [
                next(
                    rich_text["mention"]["page"]["id"]
                    for rich_text in child[child["type"]]["rich_text"]
                    if rich_text["type"] == "mention"
                )
                for child in children
            ],
            "after_block_id": after_block_id,
            "plain_text": [
                "".join(
                    rich_text.get("text", {}).get("content", "")
                    or rich_text.get("plain_text", "")
                    for rich_text in child[child["type"]]["rich_text"]
                )
                for child in children
            ],
            "colours": [child[child["type"]]["color"] for child in children],
            "types": [child["type"] for child in children],
        })
