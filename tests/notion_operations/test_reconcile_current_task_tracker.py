import asyncio

from notion_task_tracker.notion_operations.reconcile_current_task_tracker import (
    execute_notion_intents_and_reconcile_managed_pages,
)


def test_ordinary_command_boundary_accepts_primary_write_intents(monkeypatch):
    async def record_managed_page_reconciliation(
        task_tree,
        resources,
        notion_client,
    ):
        return ["reconcile:managed_pages"]

    monkeypatch.setattr(
        "notion_task_tracker.notion_operations.reconcile_current_task_tracker."
        "reconcile_managed_pages_from_current_tree",
        record_managed_page_reconciliation,
    )

    completed_operations = asyncio.run(
        execute_notion_intents_and_reconcile_managed_pages(
            task_tree="current-task-tree",
            primary_write_intents=[],
            resources="resolved-resources",
            notion_client="notion-client",
        )
    )

    assert completed_operations == ["reconcile:managed_pages"]
