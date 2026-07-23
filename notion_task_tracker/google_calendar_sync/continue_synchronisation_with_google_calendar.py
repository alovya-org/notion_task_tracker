"""Continue a loaded tracker refresh through Google Calendar."""

from __future__ import annotations

from pathlib import Path

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
    CurrentTaskTreeLoadResult,
)
from notion_task_tracker.notion_operations.reconcile_current_task_tracker import (
    reconcile_managed_pages_from_current_tree,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tracker_action_execution_summary import TrackerActionExecutionSummary


async def continue_synchronisation_with_google_calendar(
    tracker_user: str,
    output_path: str | Path,
    resources: ResolvedTrackerResources,
    current_tasks: CurrentTaskTreeLoadResult,
    completed_notion_operations: list[str],
    notion_client: NotionRestClient,
    google_calendar_client: GoogleCalendarClient | None = None,
    google_calendar_state_client: CloudflareGoogleCalendarStateClient | None = None,
) -> TrackerActionExecutionSummary:
    calendar_config = resources.config.calendar
    if calendar_config is None:
        raise ValueError("Configure [calendar] before synchronising with Google Calendar")

    calendar_client = google_calendar_client or GoogleCalendarClient.from_environment(
        calendar_config.calendar_id,
    )
    state_client = (
        google_calendar_state_client
        or CloudflareGoogleCalendarStateClient.from_environment()
    )
    synchronisation_state = await state_client.read_google_calendar_synchronisation_state(
        tracker_user,
        calendar_config.calendar_id,
    )
    calendar_changes, recovered_cursor = (
        await fetch_calendar_changes_with_expired_cursor_recovery(
            calendar_client,
            synchronisation_state.google_change_cursor,
        )
    )
    selected_changes = select_changed_events_owned_by_tracker(
        calendar_changes.events,
        resources.config.ticket_prefix,
        synchronisation_state.event_ledger,
        recovered_cursor,
    )
    applied_changes = await apply_google_calendar_changes_to_tasks(
        changed_events=selected_changes.events_to_apply,
        task_tree=current_tasks.task_tree,
        tracker_id=resources.config.ticket_prefix,
        timezone_name=calendar_config.timezone_name,
        notion_client=notion_client,
    )
    completed_notion_operations.extend(applied_changes.completed_operation_keys)
    completed_notion_operations.extend(
        await reconcile_managed_pages_from_current_tree(
            current_tasks.task_tree,
            resources,
            notion_client,
        )
    )

    await persist_processed_google_calendar_event_identities(
        state_client,
        tracker_user,
        calendar_config.calendar_id,
        selected_changes,
        recovered_cursor,
    )
    calendar_operations, projection_warnings, desired_event_count = (
        await project_current_tasks_into_google_calendar(
            task_tree=current_tasks.task_tree,
            tracker_user=tracker_user,
            tracker_id=resources.config.ticket_prefix,
            calendar_id=calendar_config.calendar_id,
            timezone_name=calendar_config.timezone_name,
            colour_id=calendar_config.colour_id,
            google_calendar_client=calendar_client,
            google_calendar_state_client=state_client,
        )
    )
    await state_client.advance_google_calendar_change_cursor(
        tracker_user=tracker_user,
        calendar_id=calendar_config.calendar_id,
        previous_google_change_cursor=synchronisation_state.google_change_cursor,
        next_google_change_cursor=calendar_changes.next_sync_token,
    )

    summary = TrackerActionExecutionSummary(
        action_name="refresh_notion_task_tracker",
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
