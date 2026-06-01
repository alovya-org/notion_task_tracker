"""Derive task graph changes for newly created task database pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_task_tracker.tasks import TaskDependencyGraph, Task, TimelineEntry
from notion_task_tracker.tasks.task import ExternalCoordination, Friction, Priority, TaskStatus, Uncertainty
from notion_task_tracker.tasks.timeline_log import build_timeline_entry_for_date


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
    external_coordination: ExternalCoordination
    uncertainty: Uncertainty
    friction: Friction
    initial_child_timeline_entry: dict[str, Any] | None
    parent_timeline_entry: dict[str, Any] | None


def derive_task_creation_from_command(command: dict[str, Any], work_graph: TaskDependencyGraph) -> TaskCreation:
    command_name = command["command"]
    if command_name == "create_top_level_task":
        return _derive_parent_task_creation_from_command(command)

    if command_name == "create_child_task":
        return _derive_child_task_creation_from_command(command)

    if command_name == "create_sibling_task":
        return _derive_sibling_task_creation_from_command(command, work_graph)

    raise ValueError(f"Unsupported database task creation command {command_name!r}")


def add_created_task_to_tracker_state(
    tracker_state: dict[str, Any],
    task_creation: TaskCreation,
    created_task_id: str,
    created_page_id: str,
) -> dict[str, Any]:
    work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    work_graph.add_task(
        Task(
            task_id=created_task_id,
            title=task_creation.task_title,
            configured_priority=task_creation.configured_priority,
            status=task_creation.status,
            dependency_task_ids=list(task_creation.dependency_task_ids),
            dependant_task_ids=list(task_creation.dependant_task_ids),
            deadline=task_creation.deadline,
            external_coordination=task_creation.external_coordination,
            uncertainty=task_creation.uncertainty,
            friction=task_creation.friction,
            timeline_entries=_derive_timeline_entries_for_created_task(task_creation.initial_child_timeline_entry),
            notion_page_id=created_page_id,
        )
    )
    if task_creation.parent_task_id is not None:
        work_graph.link_parent_to_child(parent_task_id=task_creation.parent_task_id, child_task_id=created_task_id)
    for dependant_task_id in task_creation.dependant_task_ids:
        dependant_task = work_graph.tasks[dependant_task_id]
        if created_task_id not in dependant_task.dependency_task_ids:
            dependant_task.dependency_task_ids.append(created_task_id)
    work_graph.derive_dependant_task_ids_from_dependencies()
    work_graph.validate()
    work_graph.recalculate_display_priorities()
    return work_graph.replace_task_graph_in_tracker_state(tracker_state)


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
        external_coordination=ExternalCoordination(task_command["external_coordination"]),
        uncertainty=Uncertainty(task_command["uncertainty"]),
        friction=Friction(task_command["friction"]),
        initial_child_timeline_entry=None,
        parent_timeline_entry=command.get("timeline_entry"),
    )


def _derive_child_task_creation_from_command(command: dict[str, Any]) -> TaskCreation:
    child_task_command = command["child_task"]
    parent_timeline_entry = command.get("parent_timeline_entry")
    return TaskCreation(
        command_name=command["command"],
        task_title=child_task_command["title"],
        configured_priority=Priority(child_task_command["configured_priority"]),
        status=TaskStatus(child_task_command["status"]),
        parent_task_id=command["parent_task_id"],
        dependency_task_ids=list(child_task_command.get("dependency_task_ids", [])),
        dependant_task_ids=list(child_task_command.get("dependant_task_ids", [])),
        deadline=child_task_command.get("deadline"),
        external_coordination=ExternalCoordination(child_task_command["external_coordination"]),
        uncertainty=Uncertainty(child_task_command["uncertainty"]),
        friction=Friction(child_task_command["friction"]),
        initial_child_timeline_entry=parent_timeline_entry,
        parent_timeline_entry=parent_timeline_entry,
    )


def _derive_sibling_task_creation_from_command(command: dict[str, Any], work_graph: TaskDependencyGraph) -> TaskCreation:
    sibling_task_command = command["sibling_task"]
    parent_task_id = work_graph.tasks[command["sibling_task_id"]].parent_task_id
    timeline_entry = command.get("timeline_entry")
    return TaskCreation(
        command_name=command["command"],
        task_title=sibling_task_command["title"],
        configured_priority=Priority(sibling_task_command["configured_priority"]),
        status=TaskStatus(sibling_task_command["status"]),
        parent_task_id=parent_task_id,
        dependency_task_ids=list(sibling_task_command.get("dependency_task_ids", [])),
        dependant_task_ids=list(sibling_task_command.get("dependant_task_ids", [])),
        deadline=sibling_task_command.get("deadline"),
        external_coordination=ExternalCoordination(sibling_task_command["external_coordination"]),
        uncertainty=Uncertainty(sibling_task_command["uncertainty"]),
        friction=Friction(sibling_task_command["friction"]),
        initial_child_timeline_entry=timeline_entry if parent_task_id is not None else None,
        parent_timeline_entry=timeline_entry,
    )


def _derive_timeline_entries_for_created_task(
    initial_timeline_entry: dict[str, Any] | None,
) -> list[TimelineEntry]:
    if initial_timeline_entry is None:
        return []

    timeline_entry = build_timeline_entry_for_date(initial_timeline_entry["entry_date"])
    return [
        TimelineEntry(
            entry_date=timeline_entry["entry_date"],
            heading=timeline_entry["heading"],
        )
    ]
