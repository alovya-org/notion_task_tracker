"""Refresh the complete tracker lifecycle in its configured mode."""

from __future__ import annotations

from pathlib import Path

from notion_task_tracker.config import TrackerConfig, load_config
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import (
    GoogleCalendarClient,
)
from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    CloudflareGoogleCalendarStateClient,
)
from notion_task_tracker.google_calendar_sync.continue_synchronisation_with_google_calendar import (
    continue_synchronisation_with_google_calendar,
)
from notion_task_tracker.json_file import write_json_file
from notion_task_tracker.notion_operations.load_current_task_tree_from_notion import (
    load_current_task_tree_from_notion,
)
from notion_task_tracker.notion_operations.reconcile_current_task_tracker import (
    execute_notion_intents,
    reconcile_managed_pages_from_current_tree,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    resolve_tracker_resources,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tracker_action_execution_summary import (
    TrackerActionExecutionSummary,
)


async def refresh_notion_task_tracker(
    tracker_user: str,
    output_path: str | Path,
    config: TrackerConfig | None = None,
    notion_client: NotionRestClient | None = None,
    google_calendar_client: GoogleCalendarClient | None = None,
    google_calendar_state_client: CloudflareGoogleCalendarStateClient | None = None,
) -> TrackerActionExecutionSummary:
    client = notion_client or NotionRestClient.from_environment()
    configured_tracker = config or load_config()

    resources = await resolve_tracker_resources(configured_tracker, client)
    current_tasks = await load_current_task_tree_from_notion(resources, client)
    completed_notion_operations = await execute_notion_intents(
        current_tasks.task_tree,
        current_tasks.repair_intents,
        client,
    )

    if configured_tracker.calendar is not None:
        return await continue_synchronisation_with_google_calendar(
            tracker_user=tracker_user,
            output_path=output_path,
            resources=resources,
            current_tasks=current_tasks,
            completed_notion_operations=completed_notion_operations,
            notion_client=client,
            google_calendar_client=google_calendar_client,
            google_calendar_state_client=google_calendar_state_client,
        )

    completed_notion_operations.extend(
        await reconcile_managed_pages_from_current_tree(
            current_tasks.task_tree,
            resources,
            client,
        )
    )
    summary = TrackerActionExecutionSummary(
        action_name="refresh_notion_task_tracker",
        output_path=Path(output_path),
        warnings=current_tasks.warnings,
        notion_operation_keys=completed_notion_operations,
        calendar_operation_keys=[],
        task_count=len(current_tasks.task_tree.tasks),
        repair_operation_count=len(current_tasks.repair_intents),
        desired_calendar_event_count=0,
        recovered_expired_google_change_cursor=False,
    )
    write_json_file(summary.to_json_summary(), output_path)
    return summary
