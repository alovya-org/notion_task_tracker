"""Fetch task pages before deriving timeline log writes."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks.task import UPDATE_TIMELINE_LOG_OPERATION_NAME
from notion_task_tracker.tasks.timeline_log import (
    check_fetched_task_page_has_usable_timeline_log,
    parse_timeline_entries_from_fetched_task_page_content,
    parse_timeline_log_ids_from_fetched_task_page_content,
    render_initialised_task_timeline_markdown,
)
from notion_task_tracker.apply_task_command import TaskCommandPlan, apply_command_to_task_tree
from notion_task_tracker.tasks import TaskTree, TimelineEntry


def prepare_task_command_from_fetched_page_bodies(
    command: dict[str, Any],
    task_tree: TaskTree,
    ticket_prefix: str,
    fetched_page_content_by_task_id: dict[str, str],
) -> TaskCommandPlan:
    timeline_task_ids = _task_ids_whose_timelines_are_written(command, task_tree)
    timeline_usability_by_task_id = {}
    existing_log_ids_by_task_id = {}
    current_timeline_entries_by_task_id = {}
    for task_id in timeline_task_ids:
        fetched_page_content = fetched_page_content_by_task_id[task_id]
        timeline_entries = parse_timeline_entries_from_fetched_task_page_content(
            fetched_page_content
        )
        timeline_usability_by_task_id[task_id] = check_fetched_task_page_has_usable_timeline_log(
            fetched_page_content,
            timeline_entries,
        )
        existing_log_ids_by_task_id[task_id] = (
            parse_timeline_log_ids_from_fetched_task_page_content(
                fetched_page_content
            )
        )
        current_timeline_entries_by_task_id[task_id] = [
            TimelineEntry(
                entry_date=timeline_entry["entry_date"],
                heading=timeline_entry["heading"],
            )
            for timeline_entry in timeline_entries
        ]

    command_plan = apply_command_to_task_tree(
        command,
        task_tree,
        ticket_prefix,
        current_timeline_entries_by_task_id,
    )
    replacement_intents = {
        task_id: _build_initialised_task_timeline_write_intent(
            task_id=task_id,
            entry_date=_timeline_entry_for_task(command, task_id)["entry_date"],
            log_id=_timeline_log_id_for_task(command, task_id, command_plan),
            fetched_page_content=fetched_page_content_by_task_id[task_id],
            command_result=command_plan,
        )
        for task_id in timeline_task_ids
        if not timeline_usability_by_task_id[task_id]
    }
    return TaskCommandPlan(
        task_tree=command_plan.task_tree,
        write_intents=[
            replacement_intents.get(
                write_intent.target_page_key.removeprefix("task:"),
                write_intent,
            )
            if write_intent.operation_name == UPDATE_TIMELINE_LOG_OPERATION_NAME
            else write_intent
            for write_intent in command_plan.write_intents
            if not _timeline_write_is_already_present(
                write_intent,
                existing_log_ids_by_task_id,
            )
        ],
        page_registry=command_plan.page_registry,
        warnings=command_plan.warnings,
    )


def _timeline_write_is_already_present(
    write_intent: NotionWriteIntent,
    existing_log_ids_by_task_id: dict[str, set[str]],
) -> bool:
    if write_intent.operation_name != UPDATE_TIMELINE_LOG_OPERATION_NAME:
        return False
    task_id = write_intent.target_page_key.removeprefix("task:")
    log_id = write_intent.operation_key.rsplit(":", 1)[-1]
    return log_id in existing_log_ids_by_task_id[task_id]


def _task_ids_whose_timelines_are_written(
    command: dict[str, Any],
    task_tree: TaskTree,
) -> list[str]:
    if command["command"] in {
        "append_task_timeline_log",
        "complete_task",
        "cancel_task",
    }:
        return [command["task_id"]]
    if command["command"] == "complete_task_with_all_children":
        return [
            task_id
            for task_id in _collect_subtree_task_ids(task_tree, command["task_id"])
            if task_tree.tasks[task_id].status.value not in {"Complete", "Cancelled"}
        ]
    return []


def _collect_subtree_task_ids(task_tree: TaskTree, task_id: str) -> list[str]:
    task_ids = [task_id]
    for child_task_id in task_tree.tasks[task_id].child_task_ids:
        task_ids.extend(_collect_subtree_task_ids(task_tree, child_task_id))
    return task_ids


def _timeline_entry_for_task(command: dict[str, Any], task_id: str) -> dict[str, Any]:
    return command["timeline_entry"]


def _timeline_log_id_for_task(
    command: dict[str, Any],
    task_id: str,
    command_plan: TaskCommandPlan,
) -> str:
    operation_prefix = f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:task:{task_id}:"
    operation_key = next(
        write_intent.operation_key
        for write_intent in command_plan.write_intents
        if write_intent.operation_key.startswith(operation_prefix)
    )
    return operation_key.rsplit(":", 1)[-1]


def _build_initialised_task_timeline_write_intent(
    task_id: str,
    entry_date: str,
    log_id: str,
    fetched_page_content: str,
    command_result: TaskCommandPlan,
) -> NotionWriteIntent:
    timeline_write_intent = _find_task_timeline_write_intent(command_result, task_id, entry_date, log_id)
    return NotionWriteIntent(
        operation_key=timeline_write_intent.operation_key,
        operation_name="replace_page_markdown",
        target_page_key=timeline_write_intent.target_page_key,
        arguments={
            "markdown": render_initialised_task_timeline_markdown(
                entry_date=entry_date,
                timeline_section_markdown=timeline_write_intent.arguments["timeline_section_markdown"],
                fetched_page_content=fetched_page_content,
            ),
        },
    )


def _find_task_timeline_write_intent(
    command_result: TaskCommandPlan,
    task_id: str,
    entry_date: str,
    log_id: str,
) -> NotionWriteIntent:
    operation_key = f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:task:{task_id}:{entry_date}:{log_id}"
    for write_intent in command_result.write_intents:
        if write_intent.operation_key == operation_key:
            return write_intent

    raise ValueError(f"Command result did not include timeline update {operation_key!r}")
