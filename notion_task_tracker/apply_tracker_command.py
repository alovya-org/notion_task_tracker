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
    build_task_dependencies_update_intent,
    build_task_dependants_update_intent,
    build_task_external_coordination_update_intent,
    build_task_friction_update_intent,
    build_task_parent_update_intent,
    build_task_uncertainty_update_intent,
    build_timeline_log_write_intent,
    plan_completion_write_intents,
    plan_completed_landing_page_refresh_intents,
    plan_notion_writes_for_task_tree,
)
from notion_task_tracker.notion_operations.miscellaneous_writes import (
    miscellaneous_note_append_write_intent,
    notion_write_plan_for_miscellaneous_notes,
    page_registry_for_miscellaneous_notes,
)
from notion_task_tracker.notion_operations.synthesis_writes import (
    notion_write_plan_for_synthesis_notes,
    page_registry_for_synthesis_notes,
    synthesis_page_creation_write_intent,
)
from notion_task_tracker.miscellaneous_pages import MiscellaneousNotesMetadata
from notion_task_tracker.synthesis_pages import SynthesisNotesMetadata, SynthesisPageMetadata, SynthesisSource
from notion_task_tracker.tasks import (
    TaskCompletionChange,
    TaskStatus,
    TaskTree,
    TimelineEntry,
    TimelineLogChange,
)


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

    if command_name == "append_miscellaneous_note":
        return _apply_miscellaneous_command(command, tracker_state)

    if command_name == "refresh_miscellaneous_pages":
        return _refresh_miscellaneous_pages(command, tracker_state)

    if command_name == "create_synthesis_page":
        return _apply_synthesis_command(command, tracker_state)

    if command_name == "reconcile_synthesis_root_page_mentions":
        return _reconcile_synthesis_root_page_mentions(command, tracker_state)

    if command_name == "refresh_synthesis_pages":
        return _refresh_synthesis_pages(command, tracker_state)

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

    if local_page_key == "miscellaneous_notes":
        _record_miscellaneous_notes_page_id(updated_tracker_state, notion_page_id)
        return TrackerCommandResult(tracker_state=updated_tracker_state)

    if local_page_key.startswith("miscellaneous:"):
        note_date = local_page_key.removeprefix("miscellaneous:")
        _record_miscellaneous_dated_page_id(updated_tracker_state, note_date, notion_page_id)
        return TrackerCommandResult(tracker_state=updated_tracker_state)

    if local_page_key == "synthesis_notes":
        _record_synthesis_notes_page_id(updated_tracker_state, notion_page_id)
        return TrackerCommandResult(tracker_state=updated_tracker_state)

    if local_page_key.startswith("synthesis:"):
        synthesis_key = local_page_key.removeprefix("synthesis:")
        _record_synthesis_page_id(updated_tracker_state, synthesis_key, notion_page_id)
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
        timeline_entry=TimelineEntry.from_command(command["timeline_entry"]),
    )


def _complete_task(
    task_tree: TaskTree,
    command: dict[str, Any],
):
    return task_tree.complete_task(
        task_id=command["task_id"],
        timeline_entry=TimelineEntry.from_command(command["timeline_entry"]),
    )


def _cancel_task(
    task_tree: TaskTree,
    command: dict[str, Any],
):
    return task_tree.cancel_task(
        task_id=command["task_id"],
        timeline_entry=TimelineEntry.from_command(command["timeline_entry"]),
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
    for task_id in _collect_task_ids_in_subtree_postorder(task_tree, command["task_id"]):
        if task_tree.tasks[task_id].status in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}:
            continue
        completion_changes.append(
            task_tree.complete_task(
                task_id=task_id,
                timeline_entry=TimelineEntry.from_command(command["timeline_entry"]),
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


def _apply_miscellaneous_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    miscellaneous_notes = MiscellaneousNotesMetadata.from_tracker_state(tracker_state["miscellaneous_notes"])
    dated_page, note_entry = miscellaneous_notes.append_to_dated_page(
        note_date=command["note_date"],
        lines=list(command["lines"]),
        source_page_id=command.get("source_page_id"),
        source_block_id=command.get("source_block_id"),
    )
    write_intent = miscellaneous_note_append_write_intent(miscellaneous_notes, dated_page, note_entry)
    page_registry = page_registry_for_miscellaneous_notes(miscellaneous_notes)
    return TrackerCommandResult(
        tracker_state=_replace_miscellaneous_notes_in_tracker_state(tracker_state, miscellaneous_notes),
        write_intents=[write_intent],
        page_registry=page_registry,
    )


def _refresh_miscellaneous_pages(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    miscellaneous_notes = MiscellaneousNotesMetadata.from_tracker_state(tracker_state["miscellaneous_notes"])
    write_intents = _filter_write_intents(
        notion_write_plan_for_miscellaneous_notes(miscellaneous_notes),
        command.get("operation_keys"),
    )
    page_registry = page_registry_for_miscellaneous_notes(miscellaneous_notes)
    return TrackerCommandResult(
        tracker_state=_replace_miscellaneous_notes_in_tracker_state(tracker_state, miscellaneous_notes),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _apply_synthesis_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    synthesis_notes = SynthesisNotesMetadata.from_tracker_state(tracker_state["synthesis_notes"])
    synthesis_page = synthesis_notes.create_synthesis_page(
        SynthesisPageMetadata(
            synthesis_key=command["synthesis_key"],
            title=command["title"],
            summary=command.get("summary", ""),
            lines=list(command.get("lines", [])),
            sources=[
                _synthesis_source_from_command(source_command)
                for source_command in command.get("sources", [])
            ],
        )
    )
    write_intent = synthesis_page_creation_write_intent(synthesis_notes, synthesis_page)
    page_registry = _page_registry_for_synthesis_command(tracker_state, synthesis_notes)
    return TrackerCommandResult(
        tracker_state=_replace_synthesis_notes_in_tracker_state(tracker_state, synthesis_notes),
        write_intents=[write_intent],
        page_registry=page_registry,
    )


def _reconcile_synthesis_root_page_mentions(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    synthesis_notes = SynthesisNotesMetadata.from_tracker_state(tracker_state["synthesis_notes"])
    synthesis_notes.reconcile_root_page_mentions_from_content(
        root_page_content=command["root_page_content"],
        page_titles_by_id=command.get("page_titles_by_id", {}),
    )
    return TrackerCommandResult(
        tracker_state=_replace_synthesis_notes_in_tracker_state(tracker_state, synthesis_notes),
    )


def _refresh_synthesis_pages(command: dict[str, Any], tracker_state: dict[str, Any]) -> TrackerCommandResult:
    synthesis_notes = SynthesisNotesMetadata.from_tracker_state(tracker_state["synthesis_notes"])
    write_intents = _filter_write_intents(
        notion_write_plan_for_synthesis_notes(synthesis_notes),
        command.get("operation_keys"),
    )
    page_registry = _page_registry_for_synthesis_command(tracker_state, synthesis_notes)
    return TrackerCommandResult(
        tracker_state=_replace_synthesis_notes_in_tracker_state(tracker_state, synthesis_notes),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _record_miscellaneous_notes_page_id(tracker_state: dict[str, Any], notion_page_id: str) -> None:
    tracker_state["miscellaneous_notes"]["page"]["notion_page_id"] = notion_page_id


def _record_miscellaneous_dated_page_id(
    tracker_state: dict[str, Any],
    note_date: str,
    notion_page_id: str,
) -> None:
    tracker_state["miscellaneous_notes"]["dated_pages"][note_date]["notion_page_id"] = notion_page_id


def _record_synthesis_notes_page_id(tracker_state: dict[str, Any], notion_page_id: str) -> None:
    tracker_state["synthesis_notes"]["page"]["notion_page_id"] = notion_page_id


def _record_synthesis_page_id(
    tracker_state: dict[str, Any],
    synthesis_key: str,
    notion_page_id: str,
) -> None:
    tracker_state["synthesis_notes"]["pages"][synthesis_key]["notion_page_id"] = notion_page_id


def _replace_task_pages_in_tracker_state(tracker_state: dict[str, Any], task_tree: TaskTree) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_state = task_tree.to_tracker_state()
    updated_tracker_state["ongoing_landing_page"] = task_state["ongoing_landing_page"]
    updated_tracker_state["completed_landing_page"] = task_state["completed_landing_page"]
    updated_tracker_state["tasks"] = task_state["tasks"]
    return updated_tracker_state


def _replace_miscellaneous_notes_in_tracker_state(
    tracker_state: dict[str, Any],
    miscellaneous_notes: MiscellaneousNotesMetadata,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    updated_tracker_state["miscellaneous_notes"] = miscellaneous_notes.to_tracker_state()
    return updated_tracker_state


def _replace_synthesis_notes_in_tracker_state(
    tracker_state: dict[str, Any],
    synthesis_notes: SynthesisNotesMetadata,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    updated_tracker_state["synthesis_notes"] = synthesis_notes.to_tracker_state()
    return updated_tracker_state


def _page_registry_for_synthesis_command(
    tracker_state: dict[str, Any],
    synthesis_notes: SynthesisNotesMetadata,
) -> NotionPageRegistry:
    return _merge_page_registries(
        build_page_registry_for_task_tree(TaskTree.from_tracker_state(tracker_state)),
        page_registry_for_miscellaneous_notes(
            MiscellaneousNotesMetadata.from_tracker_state(tracker_state["miscellaneous_notes"])
        ),
        page_registry_for_synthesis_notes(synthesis_notes),
    )


def _merge_page_registries(*page_registries: NotionPageRegistry) -> NotionPageRegistry:
    pages = {}

    for page_registry in page_registries:
        pages.update(page_registry.pages)

    return NotionPageRegistry(pages=pages)


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


def _synthesis_source_from_command(command: dict[str, Any]) -> SynthesisSource:
    return SynthesisSource(
        source_type=command["source_type"],
        label=command["label"],
        page_key=command.get("page_key"),
        external_url=command.get("external_url"),
    )
