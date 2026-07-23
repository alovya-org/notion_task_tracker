import asyncio

import pytest

from notion_task_tracker.notion_operations.reconcile_task_landing_pages import (
    plan_task_landing_page_reconciliation,
)
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree


def test_plan_task_landing_page_reconciliation_skips_semantically_matching_pages():
    task_tree = _task_tree_with_one_active_task()
    notion_client = _LandingPageClient({
        "66666666666666666666666666666666": "\r\n".join([
            "## P1 (high impact)",
            "",
            (
                '- \\[P1\\] <mention-page url="https://app.notion.com/p/'
                '11111111-1111-1111-1111-111111111111"/>: Active {color="orange"}'
            ),
            "",
        ]),
        "77777777777777777777777777777777": "No completed tasks yet.\n",
    })

    write_intents = asyncio.run(
        plan_task_landing_page_reconciliation(task_tree, notion_client)
    )

    assert notion_client.fetched_page_ids == [
        "66666666666666666666666666666666",
        "77777777777777777777777777777777",
    ]
    assert write_intents == []


def test_plan_task_landing_page_reconciliation_replaces_only_stale_managed_content():
    task_tree = _task_tree_with_one_active_task()
    notion_client = _LandingPageClient({
        "66666666666666666666666666666666": "\n".join([
            "## P1 (high impact)",
            (
                '- [P1] <mention-page url="https://www.notion.so/'
                '11111111111111111111111111111111"/>: Blocked {color="orange"}'
            ),
        ]),
        "77777777777777777777777777777777": "No completed tasks yet.",
    })

    write_intents = asyncio.run(
        plan_task_landing_page_reconciliation(task_tree, notion_client)
    )

    assert [
        (
            write_intent.operation_key,
            write_intent.target_page_key,
            write_intent.arguments["markdown"],
        )
        for write_intent in write_intents
    ] == [
        (
            "replace:ongoing_landing_page",
            "ongoing_landing_page",
            "\n".join([
                "## P1 (high impact)",
                (
                    '- [P1] <mention-page url="https://www.notion.so/'
                    '11111111111111111111111111111111"/>: Active {color="orange"}'
                ),
            ]),
        )
    ]


def test_plan_task_landing_page_reconciliation_rejects_unmanaged_additional_content():
    task_tree = _task_tree_with_one_active_task()
    notion_client = _LandingPageClient({
        "66666666666666666666666666666666": "Do not overwrite this handwritten note.",
        "77777777777777777777777777777777": "No completed tasks yet.",
    })

    with pytest.raises(
        ValueError,
        match="contains unsupported content",
    ):
        asyncio.run(
            plan_task_landing_page_reconciliation(task_tree, notion_client)
        )


class _LandingPageClient:
    def __init__(self, markdown_by_page_id: dict[str, str]) -> None:
        self.markdown_by_page_id = markdown_by_page_id
        self.fetched_page_ids: list[str] = []

    async def fetch_page_markdown(self, page_id: str) -> str:
        self.fetched_page_ids.append(page_id)
        return self.markdown_by_page_id[page_id]


def _task_tree_with_one_active_task() -> TaskTree:
    task_tree = TaskTree()
    task_tree.ongoing_tasks_landing_page.page.title = "Alovya's ongoing tasks"
    task_tree.ongoing_tasks_landing_page.page.notion_page_id = (
        "66666666666666666666666666666666"
    )
    task_tree.completed_tasks_landing_page.page.title = "Alovya's completed tasks"
    task_tree.completed_tasks_landing_page.page.notion_page_id = (
        "77777777777777777777777777777777"
    )
    task_tree.add_task(Task(
        task_id="ALOVYA-1",
        title="Active task",
        configured_priority=Priority.P1,
        displayed_priority=Priority.P1,
        status=TaskStatus.ACTIVE,
        notion_page_id="11111111111111111111111111111111",
    ))
    return task_tree
