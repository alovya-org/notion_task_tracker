"""Execute canonical task repairs and reconcile managed Notion pages."""

from __future__ import annotations

from notion_task_tracker.apply_task_command import TaskCommandPlan
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
)
from notion_task_tracker.notion_operations.reconcile_task_execution_order_page import (
    reconcile_task_execution_order_page,
)
from notion_task_tracker.notion_operations.reconcile_task_landing_pages import (
    plan_task_landing_page_reconciliation,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import TaskTree


async def execute_notion_intents(
    task_tree: TaskTree,
    write_intents,
    notion_client: NotionRestClient,
) -> list[str]:
    if not write_intents:
        return []

    plan = TaskCommandPlan(
        task_tree=task_tree,
        write_intents=list(write_intents),
        page_registry=build_page_registry_for_task_tree(task_tree),
    )
    result = await notion_client.execute_command_result(plan)
    if result.blocked_operation_count:
        raise ValueError(
            "Ordinary task writes cannot depend on newly captured page identifiers"
        )
    return list(result.completed_operation_keys)


async def execute_notion_intents_and_reconcile_managed_pages(
    task_tree: TaskTree,
    primary_write_intents,
    resources: ResolvedTrackerResources,
    notion_client: NotionRestClient,
) -> list[str]:
    completed_operation_keys = await execute_notion_intents(
        task_tree,
        primary_write_intents,
        notion_client,
    )
    completed_operation_keys.extend(
        await reconcile_managed_pages_from_current_tree(
            task_tree,
            resources,
            notion_client,
        )
    )
    return completed_operation_keys


async def reconcile_managed_pages_from_current_tree(
    task_tree: TaskTree,
    resources: ResolvedTrackerResources,
    notion_client: NotionRestClient,
) -> list[str]:
    landing_page_intents = await plan_task_landing_page_reconciliation(
        task_tree,
        notion_client,
    )
    completed_operation_keys = await execute_notion_intents(
        task_tree,
        landing_page_intents,
        notion_client,
    )
    completed_operation_keys.extend(
        await reconcile_task_execution_order_page(
            task_tree=task_tree,
            task_data_source_id=resources.task_data_source_id,
            ready_priority_page=resources.ready_priority_page,
            notion_client=notion_client,
        )
    )
    return completed_operation_keys
