"""Derive task tree changes for newly created task database pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_task_tracker.tasks import TaskTree, Task
from notion_task_tracker.tasks.task import (
    DurationUnit,
    ExternalCoordination,
    Friction,
    Priority,
    TaskStatus,
    Uncertainty,
    derive_task_end,
    generate_timeline_log_id,
    validate_task_schedule,
)


@dataclass(frozen=True)
class TaskCreation:
    command_name: str
    task_title: str
    configured_priority: Priority
    status: TaskStatus
    parent_task_id: str | None
    dependency_task_ids: list[str]
    dependant_task_ids: list[str]
    deadline: str | None
    start: str | None
    duration: float | None
    duration_unit: DurationUnit | None
    external_coordination: ExternalCoordination
    uncertainty: Uncertainty
    friction: Friction
    initial_child_timeline_entry: dict[str, Any] | None
    parent_timeline_entry: dict[str, Any] | None

    def __post_init__(self) -> None:
        validate_task_schedule(
            task_label=self.task_title,
            start=self.start,
            duration=self.duration,
            duration_unit=self.duration_unit,
        )


def derive_split_task_page_creations(
    command: dict[str, Any],
    task_tree: TaskTree,
    ticket_prefix: str,
) -> list[TaskCreation]:
    command_name = command["command"]
    if command_name == "create_top_level_task":
        return [_derive_parent_task_creation_from_command(command)]

    if command_name == "split_task_into_children":
        return _derive_child_task_creations_from_command(command, task_tree, ticket_prefix)

    if command_name == "split_task_with_sibling":
        return [_derive_sibling_task_creation_from_command(command, task_tree)]

    raise ValueError(f"Unsupported database task creation command {command_name!r}")


def add_created_task_to_tree(
    task_tree: TaskTree,
    task_creation: TaskCreation,
    created_task_id: str,
    created_page_id: str,
) -> None:
    task_tree.add_task(
        Task(
            task_id=created_task_id,
            title=task_creation.task_title,
            configured_priority=task_creation.configured_priority,
            status=task_creation.status,
            dependency_task_ids=list(task_creation.dependency_task_ids),
            dependant_task_ids=list(task_creation.dependant_task_ids),
            deadline=task_creation.deadline,
            start=task_creation.start,
            end=derive_task_end(
                task_label=task_creation.task_title,
                start=task_creation.start,
                duration=task_creation.duration,
                duration_unit=task_creation.duration_unit,
            ),
            duration=task_creation.duration,
            duration_unit=task_creation.duration_unit,
            external_coordination=task_creation.external_coordination,
            uncertainty=task_creation.uncertainty,
            friction=task_creation.friction,
            notion_page_id=created_page_id,
        )
    )
    if task_creation.parent_task_id is not None:
        task_tree.link_parent_to_child(parent_task_id=task_creation.parent_task_id, child_task_id=created_task_id)
    for dependant_task_id in task_creation.dependant_task_ids:
        dependant_task = task_tree.tasks[dependant_task_id]
        if created_task_id not in dependant_task.dependency_task_ids:
            dependant_task.dependency_task_ids.append(created_task_id)
    task_tree.derive_dependant_task_ids_from_dependencies()
    task_tree.validate()
    task_tree.recalculate_display_priorities()


def _derive_parent_task_creation_from_command(command: dict[str, Any]) -> TaskCreation:
    task_command = command["task"]
    return TaskCreation(
        command_name=command["command"],
        task_title=task_command["title"],
        configured_priority=Priority(task_command["configured_priority"]),
        status=TaskStatus(task_command["status"]),
        parent_task_id=None,
        dependency_task_ids=list(task_command.get("dependency_task_ids", [])),
        dependant_task_ids=list(task_command.get("dependant_task_ids", [])),
        deadline=task_command.get("deadline"),
        start=task_command.get("start"),
        duration=task_command.get("duration"),
        duration_unit=_duration_unit_from_task_command(task_command),
        external_coordination=ExternalCoordination(task_command["external_coordination"]),
        uncertainty=Uncertainty(task_command["uncertainty"]),
        friction=Friction(task_command["friction"]),
        initial_child_timeline_entry=None,
        parent_timeline_entry=command.get("timeline_entry"),
    )


def _derive_child_task_creations_from_command(
    command: dict[str, Any],
    task_tree: TaskTree,
    ticket_prefix: str,
) -> list[TaskCreation]:
    child_priority = _derive_child_priority_from_parent(task_tree, command["source_task_id"])
    split_relations = copy_source_task_relations_to_split_tasks(task_tree, command["source_task_id"])
    parent_timeline_entry = command.get("parent_timeline_entry")
    return [
        _derive_split_child_task_creation(
            command=command,
            child_task_command=child_task_command,
            child_priority=child_priority,
            dependency_task_ids=split_relations["dependency_task_ids"],
            dependant_task_ids=split_relations["dependant_task_ids"],
            parent_timeline_entry=_identified_timeline_log_for_split_child(
                parent_timeline_entry,
                child_index,
                ticket_prefix,
            ),
        )
        for child_index, child_task_command in enumerate(command["child_tasks"])
    ]


def _identified_timeline_log_for_split_child(
    timeline_log: dict[str, Any] | None,
    child_index: int,
    ticket_prefix: str,
) -> dict[str, Any] | None:
    if timeline_log is None or child_index == 0:
        return timeline_log

    identified_timeline_log = dict(timeline_log)
    identified_timeline_log["log_id"] = generate_timeline_log_id(ticket_prefix)
    return identified_timeline_log


def _derive_split_child_task_creation(
    command: dict[str, Any],
    child_task_command: dict[str, Any],
    child_priority: Priority,
    dependency_task_ids: list[str],
    dependant_task_ids: list[str],
    parent_timeline_entry: dict[str, Any] | None,
) -> TaskCreation:
    return TaskCreation(
        command_name=command["command"],
        task_title=child_task_command["title"],
        configured_priority=child_priority,
        status=TaskStatus(child_task_command["status"]),
        parent_task_id=command["source_task_id"],
        dependency_task_ids=list(dependency_task_ids),
        dependant_task_ids=list(dependant_task_ids),
        deadline=child_task_command.get("deadline"),
        start=child_task_command.get("start"),
        duration=child_task_command.get("duration"),
        duration_unit=_duration_unit_from_task_command(child_task_command),
        external_coordination=ExternalCoordination(child_task_command["external_coordination"]),
        uncertainty=Uncertainty(child_task_command["uncertainty"]),
        friction=Friction(child_task_command["friction"]),
        initial_child_timeline_entry=parent_timeline_entry,
        parent_timeline_entry=_timeline_entry_date_shell(parent_timeline_entry),
    )


def _duration_unit_from_task_command(task_command: dict[str, Any]) -> DurationUnit | None:
    duration_unit = task_command.get("duration_unit")
    return DurationUnit(duration_unit) if duration_unit is not None else None


def _derive_child_priority_from_parent(task_tree: TaskTree, parent_task_id: str) -> Priority:
    task_tree.recalculate_display_priorities()
    parent_task = task_tree.tasks[parent_task_id]
    return parent_task.displayed_priority or parent_task.configured_priority


def _derive_sibling_task_creation_from_command(command: dict[str, Any], task_tree: TaskTree) -> TaskCreation:
    sibling_task_command = command["sibling_task"]
    source_task = task_tree.tasks[command["source_task_id"]]
    split_relations = copy_source_task_relations_to_split_tasks(task_tree, command["source_task_id"])
    parent_task_id = source_task.parent_task_id
    timeline_entry = command.get("timeline_entry")
    return TaskCreation(
        command_name=command["command"],
        task_title=sibling_task_command["title"],
        configured_priority=Priority(sibling_task_command["configured_priority"]),
        status=TaskStatus(sibling_task_command["status"]),
        parent_task_id=parent_task_id,
        dependency_task_ids=split_relations["dependency_task_ids"],
        dependant_task_ids=split_relations["dependant_task_ids"],
        deadline=sibling_task_command.get("deadline"),
        start=sibling_task_command.get("start"),
        duration=sibling_task_command.get("duration"),
        duration_unit=_duration_unit_from_task_command(sibling_task_command),
        external_coordination=ExternalCoordination(sibling_task_command["external_coordination"]),
        uncertainty=Uncertainty(sibling_task_command["uncertainty"]),
        friction=Friction(sibling_task_command["friction"]),
        initial_child_timeline_entry=timeline_entry,
        parent_timeline_entry=_timeline_entry_date_shell(timeline_entry) if parent_task_id is not None else None,
    )


def copy_source_task_relations_to_split_tasks(task_tree: TaskTree, source_task_id: str) -> dict[str, list[str]]:
    source_task = task_tree.tasks[source_task_id]
    return {
        "dependency_task_ids": list(source_task.dependency_task_ids),
        "dependant_task_ids": list(source_task.dependant_task_ids),
    }

def _timeline_entry_date_shell(timeline_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if timeline_entry is None:
        return None

    return {
        "entry_date": timeline_entry["entry_date"],
        "heading": timeline_entry["heading"],
    }
