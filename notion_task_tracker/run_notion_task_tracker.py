"""Run the Notion task tracker CLI and tracker commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.build_tracker_command import build_tracker_command_from_cli_action
from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.install_skill import install_skill
from notion_task_tracker.config import TrackerConfig, load_config, resolve_config_path
from notion_task_tracker.initialise_tracker import (
    add_configured_ready_priority_page_to_tracker_state,
    create_tracker_state_from_configured_pages,
    initialise_tracker,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.move_task_timeline_log import move_task_timeline_log
from notion_task_tracker.notion_operations.create_task_database_page import (
    should_create_task_database_page_for_command,
    execute_create_task_database_page_command,
)
from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import (
    prepare_command_result_from_current_task_page,
    merge_context_repairs_into_command_result,
    plan_context_repair_result,
)
from notion_task_tracker.notion_operations.reconcile_task_database import (
    plan_repairs_for_task_tree_changes,
    refresh_tracker_state_for_task_ids,
    refresh_tracker_state_for_task_command,
    refresh_tracker_state_from_notion_task_database,
)
from notion_task_tracker.notion_operations.reconcile_task_execution_order_page import (
    reconcile_task_execution_order_page,
)
from notion_task_tracker.notion_operations.write_executor import execute_command_result_writes
from notion_task_tracker.tasks import DEFAULT_TASK_PRIORITY, ExternalCoordination, Friction, TaskTree, Uncertainty
from notion_task_tracker.tasks.timeline_log import parse_timeline_entries_from_fetched_task_page_content


APP_HOME_PATH = Path.home() / ".notion-task-tracker"
TRACKER_STATE_FILE_NAME = "notion_tasks_tree.json"
DEFAULT_TRACKER_STATE_PATH = APP_HOME_PATH / TRACKER_STATE_FILE_NAME
DEFAULT_OUTPUT_PATH = Path("/tmp/notion_task_refreshed_result.json")
LANDING_PAGE_REPLACEMENT_OPERATION_KEYS = frozenset({
    "replace:ongoing_landing_page",
    "replace:completed_landing_page",
})


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
    action_group.add_argument("--reconcile-from-notion", action="store_true")
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
    action_group.add_argument("--set-start-date-time", action="store_true")
    action_group.add_argument("--clear-start-date-time", action="store_true")
    action_group.add_argument("--set-end-date-time", action="store_true")
    action_group.add_argument("--clear-end-date-time", action="store_true")
    action_group.add_argument("--set-external-coordination", action="store_true")
    action_group.add_argument("--set-uncertainty", action="store_true")
    action_group.add_argument("--set-friction", action="store_true")
    action_group.add_argument("--reparent", action="store_true")
    action_group.add_argument("--parent", action="store_true")
    action_group.add_argument("--child", action="store_true")
    action_group.add_argument("--sibling", action="store_true")
    action_group.add_argument("--misc", action="store_true")
    action_group.add_argument("--synth", action="store_true")
    action_group.add_argument("--move-logs", action="store_true")
    parser.add_argument("--tracker-state-path")
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
    parser.add_argument("--start-date-time")
    parser.add_argument("--end-date-time")
    parser.add_argument("--external-coordination", choices=_enum_values(ExternalCoordination))
    parser.add_argument("--uncertainty", choices=_enum_values(Uncertainty))
    parser.add_argument("--friction", choices=_enum_values(Friction))
    parser.add_argument("--content-path")
    parser.add_argument("--synthesis-key")
    parser.add_argument("--entry-date")
    parser.add_argument("--destination-ticket-number", type=int)
    parser.add_argument("--log-id")
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
        tracker_state_path=args.tracker_state_path,
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
            tracker_state_path=resolve_tracker_state_path(arguments.tracker_state_path),
            notion_client=NotionRestClient.from_environment(),
        )
    )
    print(json.dumps(initialisation_result.to_json_summary(), indent=2, sort_keys=True))


def execute_tracker_command(
    command: dict[str, Any],
    tracker_state_path: str | Path | None = None,
    output_path: str | Path | None = None,
    backup_path: str | Path | None = None,
    notion_client: NotionRestClient | None = None,
    config: TrackerConfig | None = None,
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_tracker_command(
        command=command,
        config=config,
        tracker_state_path=resolve_tracker_state_path(tracker_state_path),
        output_path=resolve_output_path(output_path),
        backup_path=backup_path,
        notion_client=notion_client,
    ))


def refresh_task_tracker_from_notion(
    tracker_state_path: str | Path | None = None,
    output_path: str | Path | None = None,
    backup_path: str | Path | None = None,
    notion_client: NotionRestClient | None = None,
    config: TrackerConfig | None = None,
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_reconcile_tracker_from_notion_command(
        config=config,
        tracker_state_path=resolve_tracker_state_path(tracker_state_path),
        output_path=resolve_output_path(output_path),
        backup_path=backup_path,
        notion_client=notion_client,
    ))


def read_task_pages(
    task_ids: list[str],
    tracker_state_path: str | Path | None = None,
    output_path: str | Path | None = None,
    notion_client: NotionRestClient | None = None,
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_read_task_pages(
        action_name="read",
        task_ids=task_ids,
        tracker_state_path=resolve_tracker_state_path(tracker_state_path),
        output_path=resolve_output_path(output_path),
        notion_client=notion_client,
    ))


def resolve_tracker_state_path(tracker_state_path: str | Path | None = None) -> Path:
    if tracker_state_path:
        return Path(tracker_state_path).expanduser()

    return DEFAULT_TRACKER_STATE_PATH


def resolve_output_path(output_path: str | Path | None = None) -> Path:
    if output_path:
        return Path(output_path).expanduser()

    return DEFAULT_OUTPUT_PATH


async def _run_tracker_command(
    command: dict[str, Any],
    config: TrackerConfig | None,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: NotionRestClient | None,
) -> "TrackerActionExecutionSummary":
    if command["command"] == "reconcile_from_notion":
        return await _run_reconcile_tracker_from_notion_command(
            config=config,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            backup_path=backup_path,
            notion_client=notion_client,
        )

    if command["command"] in {"read_tasks", "read_all_tasks", "work_task"}:
        return await _run_read_task_pages_command(
            command=command,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            notion_client=notion_client,
        )

    if command["command"] == "move_task_timeline_log":
        return await _run_move_task_timeline_log_command(
            command=command,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            notion_client=notion_client,
        )

    return await _run_write_tracker_command(
        command=command,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        backup_path=backup_path,
        notion_client=notion_client,
    )


async def _run_move_task_timeline_log_command(
    command: dict[str, Any],
    tracker_state_path: str | Path,
    output_path: str | Path,
    notion_client: NotionRestClient | None,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    tracker_state = _read_json(source_tracker_state_path)
    client = _notion_rest_client_from_optional_instance(notion_client)

    refreshed_result = await refresh_tracker_state_for_task_ids(
        task_ids=[command["source_task_id"], command["destination_task_id"]],
        tracker_state=tracker_state,
        notion_client=client,
    )
    refreshed_tracker_state = refreshed_result.tracker_state
    movement_result = await move_task_timeline_log(
        source_page_id=_task_notion_page_id(refreshed_tracker_state, command["source_task_id"]),
        destination_page_id=_task_notion_page_id(refreshed_tracker_state, command["destination_task_id"]),
        requested_log_id=command["log_id"],
        notion_client=client,
    )

    _write_json(source_tracker_state_path, refreshed_tracker_state)
    execution_summary = TrackerActionExecutionSummary(
        action_name="move_logs",
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        warnings=list(refreshed_result.warnings or []),
        movement=movement_result,
    )
    _write_json(destination_output_path, execution_summary.to_json_summary())
    return execution_summary


def _task_notion_page_id(tracker_state: dict[str, Any], task_id: str) -> str:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id; run notion_task update")
    return notion_page_id


async def _run_reconcile_tracker_from_notion_command(
    config: TrackerConfig | None,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: NotionRestClient | None,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()
    client = _notion_rest_client_from_optional_instance(notion_client)

    tracker_state = await _read_or_create_reconcile_tracker_state(
        source_tracker_state_path=source_tracker_state_path,
        config=config,
        notion_client=client,
    )
    _write_json(destination_backup_path, tracker_state)

    refreshed_result = await refresh_tracker_state_from_notion_task_database(tracker_state, client)
    return await repair_and_write_refreshed_tracker_state(
        source_tracker_state_path=source_tracker_state_path,
        destination_output_path=destination_output_path,
        destination_backup_path=destination_backup_path,
        before_tracker_state=tracker_state,
        refreshed_result=refreshed_result,
        notion_client=client,
    )


async def _read_or_create_reconcile_tracker_state(
    source_tracker_state_path: Path,
    config: TrackerConfig | None,
    notion_client: NotionRestClient,
) -> dict[str, Any]:
    if source_tracker_state_path.exists():
        tracker_state = _read_json(source_tracker_state_path)
        if "ready_priority_page" in tracker_state:
            return tracker_state

        configured_tracker = config or load_config()
        return add_configured_ready_priority_page_to_tracker_state(
            tracker_state,
            configured_tracker,
        )

    configured_tracker = config or load_config()
    return await create_tracker_state_from_configured_pages(
        configured_tracker=configured_tracker,
        tracker_state_path=source_tracker_state_path,
        notion_client=notion_client,
    )


async def _run_read_task_pages_command(
    command: dict[str, Any],
    tracker_state_path: str | Path,
    output_path: str | Path,
    notion_client: NotionRestClient | None,
) -> "TrackerActionExecutionSummary":
    return await _run_read_task_pages(
        action_name=_action_name_from_tracker_command(command),
        task_ids=list(command["task_ids"]),
        include_full_page_content=command["command"] == "read_all_tasks",
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        notion_client=notion_client,
    )


async def _run_write_tracker_command(
    command: dict[str, Any],
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: NotionRestClient | None,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    client = _notion_rest_client_from_optional_instance(notion_client)
    command_ready_result = await refresh_tracker_state_for_task_command(
        command=command,
        tracker_state=tracker_state,
        notion_client=client,
    )
    command_ready_tracker_state = command_ready_result.tracker_state

    command_tracker_state, command_operation_keys, command_warnings = await _run_notion_writes_for_write_command(
        command=command,
        before_tracker_state=tracker_state,
        command_ready_result=command_ready_result,
        command_ready_tracker_state=command_ready_tracker_state,
        notion_client=client,
    )

    _write_json(source_tracker_state_path, command_tracker_state)
    execution_summary = TrackerActionExecutionSummary(
        action_name=_action_name_from_tracker_command(command),
        backup_path=destination_backup_path,
        completed_operation_keys=command_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        warnings=list(command_ready_result.warnings or []) + list(command_warnings),
    )
    _write_json(destination_output_path, execution_summary.to_json_summary())
    return execution_summary


async def _run_notion_writes_for_write_command(
    command: dict[str, Any],
    before_tracker_state: dict[str, Any],
    command_ready_result,
    command_ready_tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    if should_create_task_database_page_for_command(command, command_ready_tracker_state):
        command_tracker_state, command_operation_keys = await execute_create_task_database_page_command(
            command=command,
            tracker_state=command_ready_tracker_state,
            notion_client=notion_client,
        )
        command_operation_keys.extend(
            await reconcile_task_execution_order_page(command_tracker_state, notion_client)
        )
        return command_tracker_state, command_operation_keys, []

    context_repair_result = plan_context_repair_result(
        before_tracker_state=before_tracker_state,
        command_ready_result=command_ready_result,
    )
    command_result = await prepare_command_result_from_current_task_page(
        command=command,
        tracker_state=command_ready_tracker_state,
        notion_client=notion_client,
    )
    command_result = merge_context_repairs_into_command_result(context_repair_result, command_result)
    command_tracker_state, command_operation_keys = await _execute_command_writes_with_fresh_landing_page_render(
        command_result,
        notion_client,
    )
    command_operation_keys.extend(
        await reconcile_task_execution_order_page(command_result.tracker_state, notion_client)
    )
    return command_tracker_state, command_operation_keys, command_result.warnings or []


async def _execute_command_writes_with_fresh_landing_page_render(
    command_result: TrackerCommandResult,
    notion_client: NotionRestClient,
) -> tuple[dict[str, Any], list[str]]:
    landing_operation_keys = _landing_page_replacement_keys_in_write_order(command_result)
    if not landing_operation_keys:
        return await execute_command_result_writes(command_result, notion_client)

    command_result_without_landing_pages = _command_result_without_landing_page_replacements(command_result)
    tracker_state_after_command_writes, command_operation_keys = await execute_command_result_writes(
        command_result_without_landing_pages,
        notion_client,
    )
    refreshed_result = await refresh_tracker_state_from_notion_task_database(
        tracker_state_after_command_writes,
        notion_client,
    )
    landing_refresh_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": landing_operation_keys,
        },
        tracker_state=refreshed_result.tracker_state,
    )
    tracker_state_after_landing_pages, landing_operation_keys = await execute_command_result_writes(
        landing_refresh_result,
        notion_client,
    )
    return tracker_state_after_landing_pages, command_operation_keys + landing_operation_keys


def _landing_page_replacement_keys_in_write_order(command_result: TrackerCommandResult) -> list[str]:
    return [
        write_intent.operation_key
        for write_intent in command_result.write_intents
        if write_intent.operation_key in LANDING_PAGE_REPLACEMENT_OPERATION_KEYS
    ]


def _command_result_without_landing_page_replacements(command_result: TrackerCommandResult) -> TrackerCommandResult:
    return TrackerCommandResult(
        tracker_state=command_result.tracker_state,
        write_intents=[
            write_intent
            for write_intent in command_result.write_intents
            if write_intent.operation_key not in LANDING_PAGE_REPLACEMENT_OPERATION_KEYS
        ],
        page_registry=command_result.page_registry,
        warnings=command_result.warnings,
        refreshed_task_ids=command_result.refreshed_task_ids,
    )


async def _run_read_task_pages(
    action_name: str,
    task_ids: list[str],
    tracker_state_path: str | Path,
    output_path: str | Path,
    notion_client: NotionRestClient | None,
    include_full_page_content: bool = False,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    tracker_state = _read_json(source_tracker_state_path)

    client = _notion_rest_client_from_optional_instance(notion_client)
    refreshed_result = await refresh_tracker_state_for_task_ids(
        task_ids=task_ids,
        tracker_state=tracker_state,
        notion_client=client,
    )
    refreshed_tracker_state = refreshed_result.tracker_state
    page_content_by_task_id = await _fetch_task_page_content_by_task_id(
        task_ids=task_ids,
        tracker_state=refreshed_tracker_state,
        notion_client=client,
    )

    _write_json(source_tracker_state_path, refreshed_tracker_state)
    read_summary = TrackerActionExecutionSummary(
        action_name=action_name,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        tasks=[
            _task_read_item_from_tracker_state(
                task_id=task_id,
                tracker_state=refreshed_tracker_state,
                fetched_page_content=page_content_by_task_id[task_id],
                include_full_page_content=include_full_page_content,
            )
            for task_id in task_ids
        ],
        warnings=refreshed_result.warnings or [],
    )
    _write_json(destination_output_path, read_summary.to_json_summary())
    return read_summary


async def _fetch_task_page_content_by_task_id(
    task_ids: list[str],
    tracker_state: dict[str, Any],
    notion_client: NotionRestClient,
) -> dict[str, str]:
    page_content_by_task_id = {}
    for task_id in task_ids:
        notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
        if notion_page_id is None:
            raise ValueError(f"Task {task_id} has no Notion page id; run notion_task update")
        page_content_by_task_id[task_id] = await notion_client.fetch_task_page_content(notion_page_id)
    return page_content_by_task_id


def _task_read_item_from_tracker_state(
    task_id: str,
    tracker_state: dict[str, Any],
    fetched_page_content: str,
    include_full_page_content: bool,
) -> dict[str, Any]:
    task = tracker_state["tasks"][task_id]
    timeline_entries = parse_timeline_entries_from_fetched_task_page_content(fetched_page_content)
    task_read_item = {
        "task_id": task_id,
        "ticket_number": _ticket_number_from_task_id(task_id),
        "title": task["title"],
        "status": task["status"],
        "configured_priority": task["configured_priority"],
        "displayed_priority": task["displayed_priority"],
        "parent_task_id": task["parent_task_id"],
        "child_task_ids": list(task["child_task_ids"]),
        "notion_url": _task_notion_url(task),
        "recent_timeline_headings": [
            timeline_entry["heading"]
            for timeline_entry in timeline_entries[:5]
        ],
        "summary": _summarise_fetched_page_content(fetched_page_content),
    }
    if include_full_page_content:
        task_read_item["full_page_content"] = fetched_page_content
    return task_read_item


def _task_notion_url(task: dict[str, Any]) -> str | None:
    notion_page_id = task.get("notion_page_id")
    if notion_page_id is None:
        return None

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


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


async def repair_and_write_refreshed_tracker_state(
    source_tracker_state_path: Path,
    destination_output_path: Path,
    destination_backup_path: Path,
    before_tracker_state: dict[str, Any],
    refreshed_result,
    notion_client: NotionRestClient,
) -> "TrackerActionExecutionSummary":
    task_changes = TaskTree.changes_between_tracker_states(
        before_tracker_state,
        refreshed_result.tracker_state,
    )
    repair_result = plan_repairs_for_task_tree_changes(
        refreshed_result=refreshed_result,
        task_tree_changes=task_changes,
    )
    repaired_tracker_state, completed_operation_keys = await execute_command_result_writes(repair_result, notion_client)
    completed_operation_keys.extend(
        await reconcile_task_execution_order_page(repaired_tracker_state, notion_client)
    )
    _write_json(source_tracker_state_path, repaired_tracker_state)

    refresh_summary = TrackerActionExecutionSummary(
        action_name="reconcile_from_notion",
        backup_path=destination_backup_path,
        completed_operation_keys=completed_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        task_tree_changes=task_changes,
        task_count=len(repaired_tracker_state["tasks"]),
        warnings=refreshed_result.warnings or [],
        repair_operation_count=len(repair_result.write_intents),
    )
    _write_json(destination_output_path, refresh_summary.to_json_summary())
    return refresh_summary


@dataclass(frozen=True)
class TrackerActionExecutionSummary:
    action_name: str
    output_path: Path
    tracker_state_path: Path
    warnings: list[dict[str, str]]
    backup_path: Path | None = None
    completed_operation_keys: list[str] | None = None
    tasks: list[dict[str, Any]] | None = None
    task_tree_changes: list[dict[str, Any]] | None = None
    task_count: int | None = None
    repair_operation_count: int | None = None
    movement: dict[str, Any] | None = None

    def to_json_summary(self) -> dict[str, Any]:
        summary = {
            "action_name": self.action_name,
            "output_path": str(self.output_path),
            "tracker_state_path": str(self.tracker_state_path),
            "warnings": list(self.warnings),
        }
        if self.backup_path is not None:
            summary["backup_path"] = str(self.backup_path)
        if self.completed_operation_keys is not None:
            summary["completed_operations"] = list(self.completed_operation_keys)
        if self.tasks is not None:
            summary["tasks"] = self.tasks
        if self.task_tree_changes is not None:
            summary["task_tree_changes"] = self.task_tree_changes
        if self.task_count is not None:
            summary["task_count"] = self.task_count
        if self.repair_operation_count is not None:
            summary["repair_operation_count"] = self.repair_operation_count
        if self.movement is not None:
            summary["movement"] = self.movement
        return summary


def _action_name_from_tracker_command(command: dict[str, Any]) -> str:
    return {
        "reconcile_from_notion": "reconcile_from_notion",
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
        "set_task_start_date_time": "set_start_date_time",
        "clear_task_start_date_time": "clear_start_date_time",
        "set_task_end_date_time": "set_end_date_time",
        "clear_task_end_date_time": "clear_end_date_time",
        "set_task_external_coordination": "set_external_coordination",
        "set_task_uncertainty": "set_uncertainty",
        "set_task_friction": "set_friction",
        "reparent_task": "reparent",
        "refresh_task_pages": "refresh_task_pages",
        "create_top_level_task": "parent",
        "split_task_into_children": "child",
        "split_task_with_sibling": "sibling",
        "append_miscellaneous_note": "misc",
        "create_synthesis_page": "synth",
        "move_task_timeline_log": "move_logs",
    }[command["command"]]


def _timestamped_backup_path() -> Path:
    return Path("/tmp") / f"notion_tasks_tree_before_refresh_{int(time.time())}.json"


def _read_json(source_path: Path) -> dict[str, Any]:
    return json.loads(source_path.read_text(encoding="utf-8"))


def _write_json(destination_path: Path, tracker_state: dict[str, Any]) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(
        json.dumps(tracker_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _notion_rest_client_from_optional_instance(
    notion_client: NotionRestClient | None,
) -> NotionRestClient:
    if notion_client is None:
        return NotionRestClient.from_environment()

    return notion_client


if __name__ == "__main__":
    main()
