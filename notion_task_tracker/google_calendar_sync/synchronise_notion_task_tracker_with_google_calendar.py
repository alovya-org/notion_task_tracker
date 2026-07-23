"""Run one complete two-way synchronisation from current authoritative data."""

from __future__ import annotations

from pathlib import Path

from notion_task_tracker.apply_task_command import TaskCommandPlan
from notion_task_tracker.config import TrackerConfig, load_config
from notion_task_tracker.google_calendar_sync.apply_google_calendar_changes_to_tasks import (
    apply_google_calendar_changes_to_tasks,
    fetch_calendar_changes_with_expired_cursor_recovery,
    persist_processed_google_calendar_event_identities,
    select_changed_events_owned_by_tracker,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import GoogleCalendarClient
from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    CloudflareGoogleCalendarStateClient,
)
from notion_task_tracker.google_calendar_sync.sync_tasks_to_google_calendar import (
    project_current_tasks_into_google_calendar,
)
from notion_task_tracker.json_file import write_json_file
from notion_task_tracker.notion_operations.load_current_task_tree_from_notion import (
    load_current_task_tree_from_notion,
)
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
    resolve_tracker_resources,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tracker_action_execution_summary import TrackerActionExecutionSummary


async def synchronise_notion_task_tracker_with_google_calendar(
    tracker_user: str,
    output_path: str | Path,
    config: TrackerConfig | None = None,
    notion_client: NotionRestClient | None = None,
    google_calendar_client: GoogleCalendarClient | None = None,
    google_calendar_state_client: CloudflareGoogleCalendarStateClient | None = None,
) -> TrackerActionExecutionSummary:
    client = notion_client or NotionRestClient.from_environment()
    configured_tracker = config or load_config()
    if configured_tracker.calendar is None:
        raise ValueError("Configure [calendar] before synchronising with Google Calendar")

    resources = await resolve_tracker_resources(configured_tracker, client)
    current_tasks = await load_current_task_tree_from_notion(resources, client)
    completed_notion_operations = await _execute_notion_intents(
        current_tasks.task_tree,
        current_tasks.repair_intents,
        client,
    )

    calendar_client = google_calendar_client or GoogleCalendarClient.from_environment(
        configured_tracker.calendar.calendar_id,
    )
    state_client = (
        google_calendar_state_client
        or CloudflareGoogleCalendarStateClient.from_environment()
    )
    synchronisation_state = await state_client.read_google_calendar_synchronisation_state(
        tracker_user,
        configured_tracker.calendar.calendar_id,
    )
    calendar_changes, recovered_cursor = (
        await fetch_calendar_changes_with_expired_cursor_recovery(
            calendar_client,
            synchronisation_state.google_change_cursor,
        )
    )
    selected_changes = select_changed_events_owned_by_tracker(
        calendar_changes.events,
        configured_tracker.ticket_prefix,
        synchronisation_state.event_ledger,
        recovered_cursor,
    )
    applied_changes = await apply_google_calendar_changes_to_tasks(
        changed_events=selected_changes.events_to_apply,
        task_tree=current_tasks.task_tree,
        tracker_id=configured_tracker.ticket_prefix,
        timezone_name=configured_tracker.calendar.timezone_name,
        notion_client=client,
    )
    completed_notion_operations.extend(applied_changes.completed_operation_keys)
    completed_notion_operations.extend(
        await _reconcile_managed_pages_from_current_tree(
            current_tasks.task_tree,
            resources.task_data_source_id,
            resources.ready_priority_page,
            client,
        )
    )

    await persist_processed_google_calendar_event_identities(
        state_client,
        tracker_user,
        configured_tracker.calendar.calendar_id,
        selected_changes,
        recovered_cursor,
    )
    calendar_operations, projection_warnings, desired_event_count = (
        await project_current_tasks_into_google_calendar(
            task_tree=current_tasks.task_tree,
            tracker_user=tracker_user,
            tracker_id=configured_tracker.ticket_prefix,
            calendar_id=configured_tracker.calendar.calendar_id,
            timezone_name=configured_tracker.calendar.timezone_name,
            colour_id=configured_tracker.calendar.colour_id,
            google_calendar_client=calendar_client,
            google_calendar_state_client=state_client,
        )
    )
    await state_client.advance_google_calendar_change_cursor(
        tracker_user=tracker_user,
        calendar_id=configured_tracker.calendar.calendar_id,
        previous_google_change_cursor=synchronisation_state.google_change_cursor,
        next_google_change_cursor=calendar_changes.next_sync_token,
    )

    summary = TrackerActionExecutionSummary(
        action_name="synchronise_notion_task_tracker_with_google_calendar",
        output_path=Path(output_path),
        warnings=[
            *current_tasks.warnings,
            *selected_changes.warnings,
            *applied_changes.warnings,
            *projection_warnings,
        ],
        notion_operation_keys=completed_notion_operations,
        calendar_operation_keys=calendar_operations,
        task_count=len(current_tasks.task_tree.tasks),
        repair_operation_count=len(current_tasks.repair_intents),
        desired_calendar_event_count=desired_event_count,
        recovered_expired_google_change_cursor=recovered_cursor,
    )
    write_json_file(summary.to_json_summary(), output_path)
    return summary


async def _execute_notion_intents(
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
        raise ValueError("Calendar synchronisation writes cannot depend on captured page identifiers")
    return list(result.completed_operation_keys)


async def _reconcile_managed_pages_from_current_tree(
    task_tree: TaskTree,
    task_data_source_id: str,
    ready_priority_page,
    notion_client: NotionRestClient,
) -> list[str]:
    landing_page_intents = await plan_task_landing_page_reconciliation(
        task_tree,
        notion_client,
    )
    completed_operations = await _execute_notion_intents(
        task_tree,
        landing_page_intents,
        notion_client,
    )
    completed_operations.extend(
        await reconcile_task_execution_order_page(
            task_tree=task_tree,
            task_data_source_id=task_data_source_id,
            ready_priority_page=ready_priority_page,
            notion_client=notion_client,
        )
    )
    return completed_operations
