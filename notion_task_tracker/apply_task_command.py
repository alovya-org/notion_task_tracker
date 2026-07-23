"""Apply one ordinary task command to the current in-memory task tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from notion_task_tracker.errors import NotionPlanningError
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
    build_task_database_property_refresh_intent,
    build_task_deadline_update_intent,
    build_task_dependencies_update_intent,
    build_task_duration_update_intent,
    build_task_external_coordination_update_intent,
    build_task_friction_update_intent,
    build_task_parent_update_intent,
    build_task_start_update_intent,
    build_task_trash_intent,
    build_task_uncertainty_update_intent,
    build_timeline_log_write_intent,
)
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks import TaskStatus, TaskTree, TimelineLog
from notion_task_tracker.tasks.task import generate_timeline_log_id


@dataclass(frozen=True)
class TaskCommandPlan:
    task_tree: TaskTree
    write_intents: list[NotionWriteIntent]
    page_registry: NotionPageRegistry
    warnings: list[dict[str, str]] = field(default_factory=list)


def apply_command_to_task_tree(
    command: dict,
    task_tree: TaskTree,
    ticket_prefix: str,
) -> TaskCommandPlan:
    command_name = command["command"]

    if command_name == "append_task_timeline_log":
        timeline_change = task_tree.append_task_timeline_log(
            command["task_id"],
            TimelineLog.from_command(command["timeline_entry"]),
        )
        return _build_task_command_plan(
            task_tree,
            [build_timeline_log_write_intent(timeline_change)],
        )

    if command_name in {"complete_task", "cancel_task"}:
        return _apply_task_completion(command, task_tree)

    if command_name == "complete_task_with_all_children":
        return _complete_task_subtree(command, task_tree, ticket_prefix)

    if command_name == "delete_task":
        return _delete_task(command, task_tree)

    if command_name == "set_task_dependencies":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_dependencies(
                command["task_id"],
                list(command["dependency_task_ids"]),
            ),
            build_task_dependencies_update_intent,
        )

    if command_name == "set_task_dependants":
        return _set_task_dependants_from_derived_dependencies(
            command,
            task_tree,
        )

    if command_name == "set_task_deadline":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_deadline(command["task_id"], command["deadline"]),
            build_task_deadline_update_intent,
        )

    if command_name == "clear_task_deadline":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.clear_task_deadline(command["task_id"]),
            build_task_deadline_update_intent,
        )

    if command_name == "set_task_start":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_start(command["task_id"], command["start"]),
            build_task_start_update_intent,
        )

    if command_name == "clear_task_start":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.clear_task_start(command["task_id"]),
            build_task_start_update_intent,
        )

    if command_name == "set_task_duration":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_duration(
                command["task_id"],
                command["duration"],
                command["duration_unit"],
            ),
            build_task_duration_update_intent,
        )

    if command_name == "clear_task_duration":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.clear_task_duration(command["task_id"]),
            build_task_duration_update_intent,
        )

    if command_name == "set_task_external_coordination":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_external_coordination(
                command["task_id"],
                command["external_coordination"],
            ),
            build_task_external_coordination_update_intent,
        )

    if command_name == "set_task_uncertainty":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_uncertainty(
                command["task_id"],
                command["uncertainty"],
            ),
            build_task_uncertainty_update_intent,
        )

    if command_name == "set_task_friction":
        return _apply_property_change(
            command,
            task_tree,
            lambda: task_tree.set_task_friction(command["task_id"], command["friction"]),
            build_task_friction_update_intent,
        )

    if command_name == "reparent_task":
        task_tree.set_task_parent(command["task_id"], command["parent_task_id"])
        task_tree.validate()
        task_tree.recalculate_display_priorities()
        return _build_task_command_plan(
            task_tree,
            [build_task_parent_update_intent(task_tree.tasks[command["task_id"]])],
        )

    raise NotionPlanningError(f"Unsupported ordinary task command {command_name!r}")


def _apply_task_completion(
    command: dict,
    task_tree: TaskTree,
) -> TaskCommandPlan:
    timeline_log = TimelineLog.from_command(command["timeline_entry"])
    if command["command"] == "complete_task":
        completion_change = task_tree.complete_task(command["task_id"], timeline_log)
    else:
        completion_change = task_tree.cancel_task(command["task_id"], timeline_log)
    task = task_tree.tasks[completion_change.task_id]
    return _build_task_command_plan(
        task_tree,
        [
            build_task_database_property_refresh_intent(task),
            build_timeline_log_write_intent(completion_change.timeline_log_change),
        ],
    )


def _complete_task_subtree(
    command: dict,
    task_tree: TaskTree,
    ticket_prefix: str,
) -> TaskCommandPlan:
    write_intents = []
    for task_id in _collect_task_ids_in_subtree_postorder(task_tree, command["task_id"]):
        if task_tree.tasks[task_id].status in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}:
            continue
        timeline_entry = dict(command["timeline_entry"])
        if task_id != command["task_id"]:
            timeline_entry["log_id"] = generate_timeline_log_id(ticket_prefix)
        completion_change = task_tree.complete_task(
            task_id,
            TimelineLog.from_command(timeline_entry),
        )
        write_intents.extend([
            build_task_database_property_refresh_intent(task_tree.tasks[task_id]),
            build_timeline_log_write_intent(completion_change.timeline_log_change),
        ])
    return _build_task_command_plan(task_tree, write_intents)


def _collect_task_ids_in_subtree_postorder(
    task_tree: TaskTree,
    task_id: str,
) -> list[str]:
    task_ids = []
    for child_task_id in task_tree.tasks[task_id].child_task_ids:
        task_ids.extend(_collect_task_ids_in_subtree_postorder(task_tree, child_task_id))
    task_ids.append(task_id)
    return task_ids


def _delete_task(command: dict, task_tree: TaskTree) -> TaskCommandPlan:
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
    ]
    return TaskCommandPlan(
        task_tree=task_tree,
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _set_task_dependants_from_derived_dependencies(
    command: dict,
    task_tree: TaskTree,
) -> TaskCommandPlan:
    task_id = command["task_id"]
    affected_task_ids = set(task_tree.tasks[task_id].dependant_task_ids)
    affected_task_ids.update(command["dependant_task_ids"])
    task_tree.set_task_dependants(
        task_id,
        list(command["dependant_task_ids"]),
    )
    return _build_task_command_plan(
        task_tree,
        [
            build_task_dependencies_update_intent(task_tree.tasks[dependant_task_id])
            for dependant_task_id in sorted(affected_task_ids)
        ],
    )


def _apply_property_change(
    command: dict,
    task_tree: TaskTree,
    apply_change: Callable[[], None],
    build_write_intent: Callable,
) -> TaskCommandPlan:
    apply_change()
    return _build_task_command_plan(
        task_tree,
        [build_write_intent(task_tree.tasks[command["task_id"]])],
    )


def _build_task_command_plan(
    task_tree: TaskTree,
    write_intents: list[NotionWriteIntent],
) -> TaskCommandPlan:
    return TaskCommandPlan(
        task_tree=task_tree,
        write_intents=write_intents,
        page_registry=build_page_registry_for_task_tree(task_tree),
    )
