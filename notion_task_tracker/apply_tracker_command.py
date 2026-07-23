"""Apply narrow JSON commands and produce tracker updates plus Notion writes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from notion_task_tracker.errors import NotionPlanningError
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_ongoing_landing_page_refresh_intent,
    build_page_registry_for_task_tree,
    build_task_trash_intent,
    build_task_database_property_refresh_intent,
    build_task_deadline_update_intent,
    build_task_duration_update_intent,
    build_task_dependencies_update_intent,
    build_task_dependants_update_intent,
    build_task_external_coordination_update_intent,
    build_task_friction_update_intent,
    build_task_parent_update_intent,
    build_task_start_update_intent,
    build_task_uncertainty_update_intent,
    build_timeline_log_write_intent,
    plan_completion_write_intents,
    plan_completed_landing_page_refresh_intents,
    plan_notion_writes_for_task_tree,
)
from notion_task_tracker.tasks import (
    TaskCompletionChange,
    TaskStatus,
    TaskTree,
    TimelineLog,
    TimelineLogChange,
)
from notion_task_tracker.tasks.task import generate_timeline_log_id


@dataclass(frozen=True)
class TrackerCommandResult:
    """Tracker state candidate and exact Notion writes from one command."""

    tracker_state: dict[str, Any]
    write_intents: list[NotionWriteIntent] = field(default_factory=list)
    page_registry: NotionPageRegistry | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)
    refreshed_task_ids: frozenset[str] = frozenset()


def apply_command_to_tracker_state(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    command_name = command["command"]

    if command_name == "record_page_id":
        return _record_page_id_in_tracker_state(command, tracker_state)

    if command_name == "append_task_timeline_log":
        return _apply_task_command(command, tracker_state, _append_task_timeline_log)

    if command_name == "complete_task":
        return _apply_task_command(command, tracker_state, _complete_task)

    if command_name == "complete_task_with_all_children":
        return _complete_task_with_all_children(command, tracker_state)

    if command_name == "cancel_task":
        return _apply_task_command(command, tracker_state, _cancel_task)

    if command_name == "delete_task":
        return _delete_task(command, tracker_state)

    if command_name == "set_task_dependencies":
        return _set_task_dependencies(command, tracker_state)

    if command_name == "set_task_dependants":
        return _set_task_dependants(command, tracker_state)

    if command_name == "set_task_deadline":
        return _set_task_deadline(command, tracker_state)

    if command_name == "clear_task_deadline":
        return _clear_task_deadline(command, tracker_state)

    if command_name == "set_task_start":
        return _set_task_start(command, tracker_state)

    if command_name == "clear_task_start":
        return _clear_task_start(command, tracker_state)

    if command_name == "set_task_duration":
        return _set_task_duration(command, tracker_state)

    if command_name == "clear_task_duration":
        return _clear_task_duration(command, tracker_state)

    if command_name == "set_task_external_coordination":
        return _set_task_external_coordination(command, tracker_state)

    if command_name == "set_task_uncertainty":
        return _set_task_uncertainty(command, tracker_state)

    if command_name == "set_task_friction":
        return _set_task_friction(command, tracker_state)

    if command_name == "reparent_task":
        return _reparent_task(command, tracker_state)

    if command_name == "refresh_task_pages":
        return _refresh_task_pages(command, tracker_state)

    raise NotionPlanningError(f"Unsupported command {command_name!r}")


def _record_page_id_in_tracker_state(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    local_page_key = command["local_page_key"]
    notion_page_id = command["notion_page_id"]

    if local_page_key == "ongoing_landing_page":
        updated_tracker_state["ongoing_landing_page"]["notion_page_id"] = notion_page_id
        return TrackerCommandResult(tracker_state=updated_tracker_state)

    if local_page_key == "completed_landing_page":
        updated_tracker_state["completed_landing_page"]["notion_page_id"] = notion_page_id
        return TrackerCommandResult(tracker_state=updated_tracker_state)

    raise NotionPlanningError(f"Cannot record page id for unknown local page key {local_page_key!r}")


def _apply_task_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    command_handler,
) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    task_command_change = command_handler(task_tree, command)
    write_intents = _write_intents_from_task_command(task_tree, task_command_change)
    page_registry = build_page_registry_for_task_tree(task_tree)
    return TrackerCommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, task_tree),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _write_intents_from_task_command(task_tree: TaskTree, command_result) -> list[NotionWriteIntent]:
    if isinstance(command_result, TimelineLogChange):
        return [build_timeline_log_write_intent(command_result)]

    if isinstance(command_result, TaskCompletionChange):
        return plan_completion_write_intents(task_tree, command_result)

    raise NotionPlanningError(f"Unsupported task command result {command_result!r}")


def _append_task_timeline_log(
    task_tree: TaskTree,
    command: dict[str, Any],
):
    return task_tree.append_task_timeline_log(
        task_id=command["task_id"],
        timeline_log=TimelineLog.from_command(command["timeline_entry"]),
    )


def _complete_task(
    task_tree: TaskTree,
    command: dict[str, Any],
):
    return task_tree.complete_task(
        task_id=command["task_id"],
        timeline_log=TimelineLog.from_command(command["timeline_entry"]),
    )


def _cancel_task(
    task_tree: TaskTree,
    command: dict[str, Any],
):
    return task_tree.cancel_task(
        task_id=command["task_id"],
        timeline_log=TimelineLog.from_command(command["timeline_entry"]),
    )


def _delete_task(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    deleted_task = task_tree.tasks[command["task_id"]]
    child_task_ids = list(deleted_task.child_task_ids)
    dependant_task_ids = list(deleted_task.dependant_task_ids)
    page_registry = build_page_registry_for_task_tree(task_tree)

    task_tree.delete_task(deleted_task.task_id)
    write_intents = [
        *[
            build_task_parent_update_intent(task_tree.tasks[child_task_id])
            for child_task_id in child_task_ids
        ],
        *[
            build_task_dependencies_update_intent(task_tree.tasks[dependant_task_id])
            for dependant_task_id in dependant_task_ids
        ],
        build_task_trash_intent(deleted_task),
        build_ongoing_landing_page_refresh_intent(task_tree, page_registry),
        *plan_completed_landing_page_refresh_intents(task_tree, page_registry),
    ]
    return TrackerCommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, task_tree),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _complete_task_with_all_children(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    completion_changes = []
    ticket_prefix = tracker_state["identity"]["ticket_prefix"]
    for task_id in _collect_task_ids_in_subtree_postorder(task_tree, command["task_id"]):
        if task_tree.tasks[task_id].status in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}:
            continue
        timeline_log_command = dict(command["timeline_entry"])
        if task_id != command["task_id"]:
            timeline_log_command["log_id"] = generate_timeline_log_id(ticket_prefix)
        completion_changes.append(
            task_tree.complete_task(
                task_id=task_id,
                timeline_log=TimelineLog.from_command(timeline_log_command),
            )
        )

    page_registry = build_page_registry_for_task_tree(task_tree)
    write_intents = [
        write_intent
        for completion_change in completion_changes
        for write_intent in [
            build_task_database_property_refresh_intent(task_tree.tasks[completion_change.task_id]),
            build_timeline_log_write_intent(completion_change.timeline_log_change),
        ]
    ]
    write_intents.extend([
        build_ongoing_landing_page_refresh_intent(task_tree, page_registry),
        *plan_completed_landing_page_refresh_intents(task_tree, page_registry),
    ])
    return TrackerCommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, task_tree),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _collect_task_ids_in_subtree_postorder(task_tree: TaskTree, task_id: str) -> list[str]:
    task_ids = []
    for child_task_id in task_tree.tasks[task_id].child_task_ids:
        task_ids.extend(_collect_task_ids_in_subtree_postorder(task_tree, child_task_id))
    task_ids.append(task_id)
    return task_ids


def _set_task_dependencies(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_dependencies(
            command["task_id"],
            list(command["dependency_task_ids"]),
        ),
        build_write_intent=build_task_dependencies_update_intent,
    )


def _set_task_dependants(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_dependants(
            command["task_id"],
            list(command["dependant_task_ids"]),
        ),
        build_write_intent=build_task_dependants_update_intent,
    )


def _set_task_deadline(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_deadline(command["task_id"], command["deadline"]),
        build_write_intent=build_task_deadline_update_intent,
    )


def _clear_task_deadline(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.clear_task_deadline(command["task_id"]),
        build_write_intent=build_task_deadline_update_intent,
    )


def _set_task_start(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_start(command["task_id"], command["start"]),
        build_write_intent=build_task_start_update_intent,
    )


def _clear_task_start(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.clear_task_start(command["task_id"]),
        build_write_intent=build_task_start_update_intent,
    )


def _set_task_duration(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_duration(
            command["task_id"], command["duration"], command["duration_unit"]
        ),
        build_write_intent=build_task_duration_update_intent,
    )


def _clear_task_duration(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.clear_task_duration(command["task_id"]),
        build_write_intent=build_task_duration_update_intent,
    )


def _set_task_external_coordination(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_external_coordination(
            command["task_id"],
            command["external_coordination"],
        ),
        build_write_intent=build_task_external_coordination_update_intent,
    )


def _set_task_uncertainty(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_uncertainty(command["task_id"], command["uncertainty"]),
        build_write_intent=build_task_uncertainty_update_intent,
    )


def _set_task_friction(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    return _apply_task_property_update(
        command=command,
        tracker_state=tracker_state,
        update_task=lambda task_tree: task_tree.set_task_friction(command["task_id"], command["friction"]),
        build_write_intent=build_task_friction_update_intent,
    )


def _reparent_task(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    task_tree.set_task_parent(
        task_id=command["task_id"],
        parent_task_id=command["parent_task_id"],
    )
    task_tree.validate()
    task_tree.recalculate_display_priorities()
    page_registry = build_page_registry_for_task_tree(task_tree)
    return TrackerCommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, task_tree),
        write_intents=[
            build_task_parent_update_intent(task_tree.tasks[command["task_id"]]),
            build_ongoing_landing_page_refresh_intent(task_tree, page_registry),
            *plan_completed_landing_page_refresh_intents(task_tree, page_registry),
        ],
        page_registry=page_registry,
    )


def _apply_task_property_update(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    update_task,
    build_write_intent,
) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    update_task(task_tree)
    page_registry = build_page_registry_for_task_tree(task_tree)
    return TrackerCommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, task_tree),
        write_intents=[build_write_intent(task_tree.tasks[command["task_id"]])],
        page_registry=page_registry,
    )


def _refresh_task_pages(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    write_intents = _filter_write_intents(plan_notion_writes_for_task_tree(task_tree), command.get("operation_keys"))
    page_registry = build_page_registry_for_task_tree(task_tree)
    return TrackerCommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, task_tree),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _replace_task_pages_in_tracker_state(tracker_state: dict[str, Any], task_tree: TaskTree) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_state = task_tree.to_tracker_state()
    updated_tracker_state["ongoing_landing_page"] = task_state["ongoing_landing_page"]
    updated_tracker_state["completed_landing_page"] = task_state["completed_landing_page"]
    updated_tracker_state["tasks"] = task_state["tasks"]
    return updated_tracker_state


def _filter_write_intents(
    write_intents,
    operation_keys: list[str] | None,
):
    if operation_keys is None:
        return write_intents

    operation_key_set = set(operation_keys)
    return [
        write_intent
        for write_intent in write_intents
        if write_intent.operation_key in operation_key_set
    ]
