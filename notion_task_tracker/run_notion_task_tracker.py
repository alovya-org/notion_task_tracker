"""Run the Notion task tracker CLI and tracker commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from notion_task_tracker.build_tracker_command import build_tracker_command_from_cli_action
from notion_task_tracker.apply_task_command import TaskCommandPlan
from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    CloudflareGoogleCalendarStateClient,
)
from notion_task_tracker.install_skill import install_skill
from notion_task_tracker.json_file import write_json_file
from notion_task_tracker.config import TrackerConfig, load_config, resolve_config_path
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import (
    GoogleCalendarClient,
)
from notion_task_tracker.initialise_tracker import initialise_tracker
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.move_task_timeline_log import move_task_timeline_log
from notion_task_tracker.notion_operations.create_task_database_page import (
    create_tasks_in_current_tree,
)
from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import (
    prepare_task_command_from_fetched_page_bodies,
)
from notion_task_tracker.notion_operations.load_current_task_tree_from_notion import (
    load_current_task_tree_from_notion,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
    resolve_tracker_resources,
)
from notion_task_tracker.notion_operations.reconcile_task_execution_order_page import (
    reconcile_task_execution_order_page,
)
from notion_task_tracker.notion_operations.reconcile_task_landing_pages import (
    plan_task_landing_page_reconciliation,
)
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
)
from notion_task_tracker.google_calendar_sync.synchronise_notion_task_tracker_with_google_calendar import (
    synchronise_notion_task_tracker_with_google_calendar,
)
from notion_task_tracker.google_calendar_sync.maintain_google_calendar_notification_channel import (
    maintain_google_calendar_notification_channel,
)
from notion_task_tracker.tasks import (
    DEFAULT_TASK_PRIORITY,
    DurationUnit,
    ExternalCoordination,
    Friction,
    TaskTree,
    TaskStatus,
    Uncertainty,
)
from notion_task_tracker.tasks.timeline_log import parse_timeline_entries_from_fetched_task_page_content
from notion_task_tracker.tracker_action_execution_summary import TrackerActionExecutionSummary


STATE_FREE_TASK_COMMAND_NAMES = frozenset({
    "append_task_timeline_log",
    "complete_task",
    "complete_task_with_all_children",
    "cancel_task",
    "delete_task",
    "set_task_dependencies",
    "set_task_dependants",
    "set_task_deadline",
    "clear_task_deadline",
    "set_task_start",
    "clear_task_start",
    "set_task_duration",
    "clear_task_duration",
    "set_task_external_coordination",
    "set_task_uncertainty",
    "set_task_friction",
    "reparent_task",
    "create_top_level_task",
    "split_task_into_children",
    "split_task_with_sibling",
})


DEFAULT_OUTPUT_PATH = Path("/tmp/notion_task_refreshed_result.json")


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_argument_parser()
    args = parse_args(argv, parser)

    try:
        _run_requested_cli_action(args)
    except FileExistsError as error:
        parser.exit(1, f"{error}\n")
    except FileNotFoundError as error:
        parser.exit(1, f"{error}\n")
    except PermissionError as error:
        parser.exit(1, f"{error}\n")
    except ValueError as error:
        parser.exit(2, f"{error}\n")


def parse_args(
    argv: Sequence[str] | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> argparse.Namespace:
    parser = parser or _build_argument_parser()
    return parser.parse_args(argv)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--init", action="store_true")
    action_group.add_argument("--install-skill", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite existing skill files")
    action_group.add_argument("--refresh-notion-task-tracker", action="store_true")
    action_group.add_argument(
        "--synchronise-notion-task-tracker-with-google-calendar",
        action="store_true",
    )
    action_group.add_argument(
        "--maintain-google-calendar-notification-channel",
        action="store_true",
    )
    action_group.add_argument("--read", action="store_true")
    action_group.add_argument("--read-all", action="store_true")
    action_group.add_argument("--work", action="store_true")
    action_group.add_argument("--log", action="store_true")
    action_group.add_argument("--complete", action="store_true")
    action_group.add_argument("--complete-with-all-children", action="store_true")
    action_group.add_argument("--cancel", action="store_true")
    action_group.add_argument("--delete", action="store_true")
    action_group.add_argument("--set-dependencies", action="store_true")
    action_group.add_argument("--set-dependants", action="store_true")
    action_group.add_argument("--set-deadline", action="store_true")
    action_group.add_argument("--clear-deadline", action="store_true")
    action_group.add_argument("--set-start", action="store_true")
    action_group.add_argument("--clear-start", action="store_true")
    action_group.add_argument("--set-duration", action="store_true")
    action_group.add_argument("--clear-duration", action="store_true")
    action_group.add_argument("--set-external-coordination", action="store_true")
    action_group.add_argument("--set-uncertainty", action="store_true")
    action_group.add_argument("--set-friction", action="store_true")
    action_group.add_argument("--reparent", action="store_true")
    action_group.add_argument("--parent", action="store_true")
    action_group.add_argument("--child", action="store_true")
    action_group.add_argument("--sibling", action="store_true")
    action_group.add_argument("--move-logs", action="store_true")
    parser.add_argument("--config-path")
    parser.add_argument("--output-path")
    parser.add_argument("--display-name")
    parser.add_argument("--ticket-prefix")
    parser.add_argument("--parent-page-url")
    parser.add_argument("--task-database-url")
    parser.add_argument("--ticket-number", action="append", type=int, default=[])
    parser.add_argument("--parent-ticket-number", type=int)
    parser.add_argument("--sibling-ticket-number", type=int)
    parser.add_argument("--title", action="append", default=[])
    parser.add_argument("--priority", choices=["P0", "P1", "P2", "P3"], default=DEFAULT_TASK_PRIORITY.value)
    parser.add_argument("--dependency-ticket-number", action="append", type=int, default=[])
    parser.add_argument("--dependant-ticket-number", action="append", type=int, default=[])
    parser.add_argument("--deadline")
    parser.add_argument("--start")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--duration-unit", choices=_enum_values(DurationUnit))
    parser.add_argument("--external-coordination", choices=_enum_values(ExternalCoordination))
    parser.add_argument("--uncertainty", choices=_enum_values(Uncertainty))
    parser.add_argument("--friction", choices=_enum_values(Friction))
    parser.add_argument("--content-path")
    parser.add_argument("--entry-date")
    parser.add_argument("--destination-ticket-number", type=int)
    parser.add_argument("--log-id")
    parser.add_argument("--tracker-user")
    parser.add_argument("--calendar-notification-url")
    return parser


def _enum_values(enum_type) -> list[str]:
    return [enum_value.value for enum_value in enum_type]


def _run_requested_cli_action(args: argparse.Namespace) -> None:
    if args.init:
        _run_initialise_tracker_action(args)
        return

    if args.install_skill:
        install_skill(force=args.force)
        return

    config = load_config(args.config_path)
    command = build_tracker_command_from_cli_action(args, ticket_prefix=config.ticket_prefix)
    execution_summary = execute_tracker_command(
        command=command,
        config=config,
        output_path=args.output_path,
    )
    print(json.dumps(execution_summary.to_json_summary(), indent=2, sort_keys=True))


def _run_initialise_tracker_action(arguments: argparse.Namespace) -> None:
    required_values = {
        "--display-name": arguments.display_name,
        "--ticket-prefix": arguments.ticket_prefix,
        "--parent-page-url": arguments.parent_page_url,
        "--task-database-url": arguments.task_database_url,
    }
    missing_flags = [flag for flag, value in required_values.items() if not value]
    if missing_flags:
        raise ValueError("--init requires " + ", ".join(missing_flags))

    initialisation_result = asyncio.run(
        initialise_tracker(
            display_name=arguments.display_name,
            ticket_prefix=arguments.ticket_prefix,
            parent_page_url=arguments.parent_page_url,
            task_database_url=arguments.task_database_url,
            config_path=resolve_config_path(arguments.config_path),
            notion_client=NotionRestClient.from_environment(),
        )
    )
    print(json.dumps(initialisation_result.to_json_summary(), indent=2, sort_keys=True))


def execute_tracker_command(
    command: dict[str, Any],
    output_path: str | Path | None = None,
    notion_client: NotionRestClient | None = None,
    config: TrackerConfig | None = None,
    google_calendar_client: GoogleCalendarClient | None = None,
    google_calendar_state_client: CloudflareGoogleCalendarStateClient | None = None,
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_tracker_command(
        command=command,
        config=config,
        output_path=resolve_output_path(output_path),
        notion_client=notion_client,
        google_calendar_client=google_calendar_client,
        google_calendar_state_client=google_calendar_state_client,
    ))


def refresh_task_tracker_from_notion(
    output_path: str | Path | None = None,
    notion_client: NotionRestClient | None = None,
    config: TrackerConfig | None = None,
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_state_free_task_command(
        command={"command": "refresh_notion_task_tracker"},
        config=config,
        output_path=resolve_output_path(output_path),
        notion_client=notion_client,
    ))


def read_task_pages(
    task_ids: list[str],
    output_path: str | Path | None = None,
    notion_client: NotionRestClient | None = None,
    config: TrackerConfig | None = None,
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_state_free_task_command(
        command={"command": "read_tasks", "task_ids": task_ids},
        config=config,
        output_path=resolve_output_path(output_path),
        notion_client=notion_client,
    ))


def resolve_output_path(output_path: str | Path | None = None) -> Path:
    if output_path:
        return Path(output_path).expanduser()

    return DEFAULT_OUTPUT_PATH


async def _run_tracker_command(
    command: dict[str, Any],
    config: TrackerConfig | None,
    output_path: str | Path,
    notion_client: NotionRestClient | None,
    google_calendar_client: GoogleCalendarClient | None,
    google_calendar_state_client: CloudflareGoogleCalendarStateClient | None,
) -> "TrackerActionExecutionSummary":
    if command["command"] == "maintain_google_calendar_notification_channel":
        return await maintain_google_calendar_notification_channel(
            tracker_user=command["tracker_user"],
            notification_url=command["notification_url"],
            current_time_milliseconds=int(time.time() * 1000),
            replace_within_milliseconds=2 * 24 * 60 * 60 * 1000,
            config=config,
            output_path=output_path,
            google_calendar_client=google_calendar_client,
            google_calendar_state_client=google_calendar_state_client,
        )

    if command["command"] == "synchronise_notion_task_tracker_with_google_calendar":
        return await synchronise_notion_task_tracker_with_google_calendar(
            tracker_user=command["tracker_user"],
            config=config,
            output_path=output_path,
            notion_client=notion_client,
            google_calendar_client=google_calendar_client,
            google_calendar_state_client=google_calendar_state_client,
        )

    if command["command"] == "refresh_notion_task_tracker":
        return await _run_state_free_task_command(
            command=command,
            config=config,
            output_path=output_path,
            notion_client=notion_client,
        )

    if command["command"] in {"read_tasks", "read_all_tasks", "work_task"}:
        return await _run_state_free_task_command(
            command=command,
            config=config,
            output_path=output_path,
            notion_client=notion_client,
        )

    if command["command"] == "move_task_timeline_log":
        return await _run_state_free_task_command(
            command=command,
            config=config,
            output_path=output_path,
            notion_client=notion_client,
        )

    if command["command"] in STATE_FREE_TASK_COMMAND_NAMES:
        return await _run_state_free_task_command(
            command=command,
            config=config,
            output_path=output_path,
            notion_client=notion_client,
        )

    raise ValueError(f"Unsupported tracker command {command['command']!r}")


async def _run_state_free_task_command(
    command: dict[str, Any],
    config: TrackerConfig | None,
    output_path: str | Path,
    notion_client: NotionRestClient | None,
) -> "TrackerActionExecutionSummary":
    client = _notion_rest_client_from_optional_instance(notion_client)
    configured_tracker = config or load_config()
    resources = await resolve_tracker_resources(configured_tracker, client)
    current_tasks = await load_current_task_tree_from_notion(resources, client)

    if command["command"] in {"read_tasks", "read_all_tasks", "work_task"}:
        return await _read_current_task_pages(
            command,
            current_tasks.task_tree,
            current_tasks.repair_intents,
            current_tasks.warnings,
            output_path,
            client,
        )

    if command["command"] == "refresh_notion_task_tracker":
        return await _reconcile_current_task_tracker(
            current_tasks.task_tree,
            current_tasks.repair_intents,
            current_tasks.warnings,
            resources,
            output_path,
            client,
        )

    if command["command"] == "move_task_timeline_log":
        return await _move_current_task_timeline_log(
            command,
            current_tasks.task_tree,
            current_tasks.repair_intents,
            current_tasks.warnings,
            resources,
            output_path,
            client,
        )

    if command["command"] in {
        "create_top_level_task",
        "split_task_into_children",
        "split_task_with_sibling",
    }:
        return await _create_current_tasks(
            command,
            current_tasks.task_tree,
            current_tasks.repair_intents,
            current_tasks.warnings,
            resources,
            output_path,
            client,
        )

    fetched_page_content_by_task_id = await _fetch_required_task_page_bodies(
        command,
        current_tasks.task_tree,
        client,
    )
    command_plan = prepare_task_command_from_fetched_page_bodies(
        command=command,
        task_tree=current_tasks.task_tree,
        ticket_prefix=resources.config.ticket_prefix,
        fetched_page_content_by_task_id=fetched_page_content_by_task_id,
    )
    completed_operation_keys = await _execute_current_task_write_plan(
        task_tree=command_plan.task_tree,
        primary_write_intents=[
            *current_tasks.repair_intents,
            *command_plan.write_intents,
        ],
        resources=resources,
        notion_client=client,
    )
    return _write_task_action_summary(
        action_name=_action_name_from_tracker_command(command),
        output_path=output_path,
        notion_operation_keys=completed_operation_keys,
        warnings=[*current_tasks.warnings, *command_plan.warnings],
    )


async def _create_current_tasks(
    command: dict[str, Any],
    task_tree: TaskTree,
    repair_intents,
    warnings: list[dict[str, str]],
    resources: ResolvedTrackerResources,
    output_path: str | Path,
    notion_client: NotionRestClient,
) -> "TrackerActionExecutionSummary":
    timeline_owner_task_ids = _existing_timeline_owner_task_ids_for_creation(
        command
    )
    fetched_page_content_by_task_id = (
        await _fetch_task_page_content_from_current_tree(
            timeline_owner_task_ids,
            task_tree,
            notion_client,
        )
    )
    completed_operation_keys = await create_tasks_in_current_tree(
        command=command,
        task_tree=task_tree,
        ticket_prefix=resources.config.ticket_prefix,
        task_data_source_id=resources.task_data_source_id,
        fetched_page_content_by_task_id=fetched_page_content_by_task_id,
        notion_client=notion_client,
    )
    completed_operation_keys.extend(
        await _execute_task_command_plan(
            TaskCommandPlan(
                task_tree=task_tree,
                write_intents=list(repair_intents),
                page_registry=build_page_registry_for_task_tree(task_tree),
            ),
            notion_client,
        )
    )
    completed_operation_keys.extend(
        await _reconcile_current_managed_pages(
            task_tree,
            resources,
            notion_client,
        )
    )
    return _write_task_action_summary(
        action_name=_action_name_from_tracker_command(command),
        output_path=output_path,
        notion_operation_keys=completed_operation_keys,
        warnings=warnings,
    )


def _existing_timeline_owner_task_ids_for_creation(
    command: dict[str, Any],
) -> list[str]:
    if command["command"] == "split_task_into_children":
        return [command["source_task_id"]]
    if command["command"] == "split_task_with_sibling":
        return [command["source_task_id"]]
    return []


async def _read_current_task_pages(
    command: dict[str, Any],
    task_tree: TaskTree,
    repair_intents,
    warnings: list[dict[str, str]],
    output_path: str | Path,
    notion_client: NotionRestClient,
) -> "TrackerActionExecutionSummary":
    task_ids = list(dict.fromkeys(command["task_ids"]))
    fetched_page_content_by_task_id = await _fetch_task_page_content_from_current_tree(
        task_ids,
        task_tree,
        notion_client,
    )
    repair_plan = TaskCommandPlan(
        task_tree=task_tree,
        write_intents=list(repair_intents),
        page_registry=build_page_registry_for_task_tree(task_tree),
    )
    completed_operation_keys = await _execute_task_command_plan(
        repair_plan,
        notion_client,
    )
    summary = TrackerActionExecutionSummary(
        action_name=_action_name_from_tracker_command(command),
        output_path=Path(output_path),
        notion_operation_keys=completed_operation_keys,
        tasks=[
            _task_read_item_from_current_tree(
                task_tree.tasks[task_id],
                fetched_page_content_by_task_id[task_id],
                include_full_page_content=command["command"] == "read_all_tasks",
            )
            for task_id in task_ids
        ],
        warnings=warnings,
    )
    write_json_file(summary.to_json_summary(), output_path)
    return summary


async def _reconcile_current_task_tracker(
    task_tree: TaskTree,
    repair_intents,
    warnings: list[dict[str, str]],
    resources: ResolvedTrackerResources,
    output_path: str | Path,
    notion_client: NotionRestClient,
) -> "TrackerActionExecutionSummary":
    completed_operation_keys = await _execute_current_task_write_plan(
        task_tree,
        list(repair_intents),
        resources,
        notion_client,
    )
    summary = TrackerActionExecutionSummary(
        action_name="refresh_notion_task_tracker",
        output_path=Path(output_path),
        notion_operation_keys=completed_operation_keys,
        task_count=len(task_tree.tasks),
        repair_operation_count=len(repair_intents),
        warnings=warnings,
    )
    write_json_file(summary.to_json_summary(), output_path)
    return summary


async def _move_current_task_timeline_log(
    command: dict[str, Any],
    task_tree: TaskTree,
    repair_intents,
    warnings: list[dict[str, str]],
    resources: ResolvedTrackerResources,
    output_path: str | Path,
    notion_client: NotionRestClient,
) -> "TrackerActionExecutionSummary":
    source_task = task_tree.tasks[command["source_task_id"]]
    destination_task = task_tree.tasks[command["destination_task_id"]]
    movement = await move_task_timeline_log(
        source_page_id=_required_current_task_page_id(source_task),
        destination_page_id=_required_current_task_page_id(destination_task),
        requested_log_id=command["log_id"],
        notion_client=notion_client,
    )
    completed_operation_keys = await _execute_current_task_write_plan(
        task_tree,
        list(repair_intents),
        resources,
        notion_client,
    )
    summary = TrackerActionExecutionSummary(
        action_name="move_logs",
        output_path=Path(output_path),
        completed_operation_keys=completed_operation_keys,
        movement=movement,
        warnings=warnings,
    )
    write_json_file(summary.to_json_summary(), output_path)
    return summary


async def _fetch_required_task_page_bodies(
    command: dict[str, Any],
    task_tree: TaskTree,
    notion_client: NotionRestClient,
) -> dict[str, str]:
    command_name = command["command"]
    if command_name in {"append_task_timeline_log", "complete_task", "cancel_task"}:
        task_ids = [command["task_id"]]
    elif command_name == "complete_task_with_all_children":
        task_ids = _unfinished_task_ids_in_subtree(task_tree, command["task_id"])
    else:
        task_ids = []
    return await _fetch_task_page_content_from_current_tree(
        task_ids,
        task_tree,
        notion_client,
    )


def _unfinished_task_ids_in_subtree(task_tree: TaskTree, task_id: str) -> list[str]:
    task = task_tree.tasks[task_id]
    task_ids = []
    for child_task_id in task.child_task_ids:
        task_ids.extend(
            _unfinished_task_ids_in_subtree(task_tree, child_task_id)
        )
    if task.status not in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}:
        task_ids.append(task_id)
    return task_ids


async def _fetch_task_page_content_from_current_tree(
    task_ids: list[str],
    task_tree: TaskTree,
    notion_client: NotionRestClient,
) -> dict[str, str]:
    return {
        task_id: await notion_client.fetch_task_page_content(
            _required_current_task_page_id(task_tree.tasks[task_id])
        )
        for task_id in task_ids
    }


def _required_current_task_page_id(task) -> str:
    if task.notion_page_id is None:
        raise ValueError(f"Task {task.task_id} has no current Notion page id")
    return task.notion_page_id


async def _execute_current_task_write_plan(
    task_tree: TaskTree,
    primary_write_intents,
    resources: ResolvedTrackerResources,
    notion_client: NotionRestClient,
) -> list[str]:
    primary_plan = TaskCommandPlan(
        task_tree=task_tree,
        write_intents=list(primary_write_intents),
        page_registry=build_page_registry_for_task_tree(task_tree),
    )
    completed_operation_keys = await _execute_task_command_plan(
        primary_plan,
        notion_client,
    )
    completed_operation_keys.extend(
        await _reconcile_current_managed_pages(
            task_tree,
            resources,
            notion_client,
        )
    )
    return completed_operation_keys


async def _reconcile_current_managed_pages(
    task_tree: TaskTree,
    resources: ResolvedTrackerResources,
    notion_client: NotionRestClient,
) -> list[str]:
    landing_page_intents = await plan_task_landing_page_reconciliation(
        task_tree,
        notion_client,
    )
    landing_plan = TaskCommandPlan(
        task_tree=task_tree,
        write_intents=landing_page_intents,
        page_registry=build_page_registry_for_task_tree(task_tree),
    )
    completed_operation_keys = await _execute_task_command_plan(
        landing_plan,
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


async def _execute_task_command_plan(
    command_plan: TaskCommandPlan,
    notion_client: NotionRestClient,
) -> list[str]:
    if not command_plan.write_intents:
        return []
    write_result = await notion_client.execute_command_result(command_plan)
    if write_result.blocked_operation_count:
        raise ValueError("Ordinary task writes cannot depend on newly captured page identifiers")
    return list(write_result.completed_operation_keys)


def _write_task_action_summary(
    action_name: str,
    output_path: str | Path,
    completed_operation_keys: list[str],
    warnings: list[dict[str, str]],
) -> "TrackerActionExecutionSummary":
    summary = TrackerActionExecutionSummary(
        action_name=action_name,
        output_path=Path(output_path),
        completed_operation_keys=completed_operation_keys,
        warnings=warnings,
    )
    write_json_file(summary.to_json_summary(), output_path)
    return summary


def _task_read_item_from_current_tree(
    task,
    fetched_page_content: str,
    include_full_page_content: bool,
) -> dict[str, Any]:
    timeline_entries = parse_timeline_entries_from_fetched_task_page_content(
        fetched_page_content
    )
    task_read_item = {
        "task_id": task.task_id,
        "ticket_number": _ticket_number_from_task_id(task.task_id),
        "title": task.title,
        "status": task.status.value,
        "configured_priority": task.configured_priority.value,
        "displayed_priority": task.displayed_priority.value,
        "parent_task_id": task.parent_task_id,
        "child_task_ids": list(task.child_task_ids),
        "notion_url": (
            f"https://www.notion.so/{task.notion_page_id.replace('-', '')}"
            if task.notion_page_id
            else None
        ),
        "recent_timeline_headings": [
            timeline_entry["heading"]
            for timeline_entry in timeline_entries[:5]
        ],
        "summary": _summarise_fetched_page_content(fetched_page_content),
    }
    if include_full_page_content:
        task_read_item["full_page_content"] = fetched_page_content
    return task_read_item


def _ticket_number_from_task_id(task_id: str) -> int:
    _ticket_prefix, separator, ticket_number = task_id.rpartition("-")
    if not separator or not ticket_number.isdigit():
        raise ValueError(f"Task id {task_id!r} must end with a numeric ticket number")
    return int(ticket_number)


def _summarise_fetched_page_content(fetched_page_content: str) -> list[str]:
    summary_lines = []
    inside_content = False
    for raw_line in fetched_page_content.splitlines():
        line = raw_line.strip()
        if line == "<content>":
            inside_content = True
            continue
        if line == "</content>":
            break
        if not inside_content:
            continue
        if not line or line.startswith("<") or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:]
        summary_lines.append(line)
        if len(summary_lines) == 5:
            break
    return summary_lines


def _action_name_from_tracker_command(command: dict[str, Any]) -> str:
    return {
        "synchronise_notion_task_tracker_with_google_calendar": (
            "synchronise_notion_task_tracker_with_google_calendar"
        ),
        "maintain_google_calendar_notification_channel": (
            "maintain_google_calendar_notification_channel"
        ),
        "refresh_notion_task_tracker": "refresh_notion_task_tracker",
        "read_tasks": "read",
        "read_all_tasks": "read_all",
        "work_task": "work",
        "append_task_timeline_log": "log",
        "complete_task": "complete",
        "complete_task_with_all_children": "complete_with_all_children",
        "cancel_task": "cancel",
        "delete_task": "delete",
        "set_task_dependencies": "set_dependencies",
        "set_task_dependants": "set_dependants",
        "set_task_deadline": "set_deadline",
        "clear_task_deadline": "clear_deadline",
        "set_task_start": "set_start",
        "clear_task_start": "clear_start",
        "set_task_duration": "set_duration",
        "clear_task_duration": "clear_duration",
        "set_task_external_coordination": "set_external_coordination",
        "set_task_uncertainty": "set_uncertainty",
        "set_task_friction": "set_friction",
        "reparent_task": "reparent",
        "refresh_task_pages": "refresh_task_pages",
        "create_top_level_task": "parent",
        "split_task_into_children": "child",
        "split_task_with_sibling": "sibling",
        "move_task_timeline_log": "move_logs",
    }[command["command"]]


def _notion_rest_client_from_optional_instance(
    notion_client: NotionRestClient | None,
) -> NotionRestClient:
    if notion_client is None:
        return NotionRestClient.from_environment()

    return notion_client


if __name__ == "__main__":
    main()
