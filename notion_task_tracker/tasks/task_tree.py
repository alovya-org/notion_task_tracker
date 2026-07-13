"""Task tree metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from notion_task_tracker.external_links import (
    external_link_from_tracker_state,
    external_link_to_tracker_state,
)
from notion_task_tracker.errors import NotionPlanningError
from notion_task_tracker.fixed_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    COMPLETED_LANDING_PAGE_TITLE,
    ONGOING_LANDING_PAGE_LOCAL_KEY,
    ONGOING_LANDING_PAGE_TITLE,
)
from notion_task_tracker.tasks.landing_pages import CompletedTasksLandingPage, OngoingTasksLandingPage
from notion_task_tracker.tasks.task import (
    ExternalCoordination,
    Friction,
    Priority,
    Task,
    TaskCompletionChange,
    TaskStatus,
    TimelineEntry,
    TimelineLogChange,
    Uncertainty,
    _PRIORITY_RANK_BY_VALUE,
    task_id_sort_key,
)
from notion_task_tracker.tracked_pages import (
    TrackedPage,
    fixed_tracked_page_from_tracker_state,
    tracked_page_to_tracker_state,
    validate_fixed_tracked_page,
)


@dataclass
class TaskTree:
    """Task tree and task landing-page registry."""

    ongoing_tasks_landing_page: OngoingTasksLandingPage = field(
        default_factory=lambda: OngoingTasksLandingPage(
            page=TrackedPage(
                local_page_key=ONGOING_LANDING_PAGE_LOCAL_KEY,
                title=ONGOING_LANDING_PAGE_TITLE,
            )
        )
    )
    completed_tasks_landing_page: CompletedTasksLandingPage = field(
        default_factory=lambda: CompletedTasksLandingPage(
            page=TrackedPage(
                local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
                title=COMPLETED_LANDING_PAGE_TITLE,
            )
        )
    )
    tasks: dict[str, Task] = field(default_factory=dict)

    @classmethod
    def from_tracker_state(cls, tracker_state: dict[str, Any]) -> TaskTree:
        task_tree = cls(
            ongoing_tasks_landing_page=OngoingTasksLandingPage(
                page=fixed_tracked_page_from_tracker_state(
                    tracker_state=tracker_state["ongoing_landing_page"],
                    local_page_key=ONGOING_LANDING_PAGE_LOCAL_KEY,
                )
            ),
            completed_tasks_landing_page=CompletedTasksLandingPage(
                page=fixed_tracked_page_from_tracker_state(
                    tracker_state=tracker_state["completed_landing_page"],
                    local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
                )
            ),
        )
        for task_state in tracker_state.get("tasks", {}).values():
            task_tree.tasks[task_state["task_id"]] = _task_from_tracker_state(task_state)
        task_tree._normalise_task_timelines()
        task_tree.derive_dependant_task_ids_from_dependencies()
        task_tree.validate()
        task_tree.recalculate_display_priorities()
        return task_tree

    def to_tracker_state(self) -> dict[str, Any]:
        return {
            "ongoing_landing_page": tracked_page_to_tracker_state(self.ongoing_tasks_landing_page.page),
            "completed_landing_page": tracked_page_to_tracker_state(self.completed_tasks_landing_page.page),
            "tasks": {
                task_id: _task_to_tracker_state(task)
                for task_id, task in sorted(self.tasks.items(), key=lambda item: task_id_sort_key(item[0]))
            },
        }

    @classmethod
    def changes_between_tracker_states(
        cls,
        before_tracker_state: dict[str, Any],
        after_tracker_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        changes = []
        before_tasks = before_tracker_state["tasks"]
        after_tasks = after_tracker_state["tasks"]

        for task_id in sorted(set(before_tasks) | set(after_tasks), key=task_id_sort_key):
            before_task = before_tasks.get(task_id)
            after_task = after_tasks.get(task_id)

            if before_task is None:
                changes.append({"task_id": task_id, "change": "added"})
                continue

            if after_task is None:
                changes.append({"task_id": task_id, "change": "removed"})
                continue

            changed_fields = _changed_task_tree_fields(before_task, after_task)
            if changed_fields:
                changes.append({"task_id": task_id, "fields": changed_fields})

        return changes

    def replace_task_tree_in_tracker_state(self, tracker_state: dict[str, Any]) -> dict[str, Any]:
        updated_tracker_state = json.loads(json.dumps(tracker_state))
        task_tree_state = self.to_tracker_state()
        updated_tracker_state["ongoing_landing_page"] = task_tree_state["ongoing_landing_page"]
        updated_tracker_state["completed_landing_page"] = task_tree_state["completed_landing_page"]
        updated_tracker_state["tasks"] = task_tree_state["tasks"]
        return updated_tracker_state

    def add_task(self, task: Task) -> None:
        if task.task_id in self.tasks:
            raise NotionPlanningError(f"Task {task.task_id} already exists")
        self.tasks[task.task_id] = task
        self.derive_dependant_task_ids_from_dependencies()

    def link_parent_to_child(self, parent_task_id: str, child_task_id: str) -> None:
        parent_task = self.tasks[parent_task_id]
        child_task = self.tasks[child_task_id]
        if child_task_id not in parent_task.child_task_ids:
            parent_task.child_task_ids.append(child_task_id)
        child_task.parent_task_id = parent_task_id

    def set_task_parent(self, task_id: str, parent_task_id: str | None) -> None:
        for task in self.tasks.values():
            if task_id in task.child_task_ids:
                task.child_task_ids.remove(task_id)

        self.tasks[task_id].parent_task_id = None
        if parent_task_id is not None:
            self.link_parent_to_child(parent_task_id=parent_task_id, child_task_id=task_id)

        for task in self.tasks.values():
            task.child_task_ids.sort(key=task_id_sort_key)

    def refresh_task_from_database_row(
        self,
        task_id: str,
        title: str,
        configured_priority: Priority,
        status: TaskStatus,
        notion_page_id: str,
        parent_task_id: str | None,
        dependency_task_ids: list[str],
        dependant_task_ids: list[str],
        deadline: str | None,
        start_date_time: str | None,
        end_date_time: str | None,
        external_coordination: ExternalCoordination,
        uncertainty: Uncertainty,
        friction: Friction,
    ) -> None:
        task = self.tasks[task_id]
        task.title = title
        task.configured_priority = configured_priority
        task.status = status
        task.notion_page_id = notion_page_id
        task.dependency_task_ids = list(dependency_task_ids)
        self._replace_task_dependants(task_id, list(dependant_task_ids))
        task.deadline = deadline
        task.start_date_time = start_date_time
        task.end_date_time = end_date_time
        task.external_coordination = external_coordination
        task.uncertainty = uncertainty
        task.friction = friction
        self.set_task_parent(task_id, parent_task_id)
        self.derive_dependant_task_ids_from_dependencies()

    def append_task_timeline_log(
        self,
        task_id: str,
        timeline_entry: TimelineEntry,
    ) -> TimelineLogChange:
        task = self.tasks[task_id]
        timeline_log_change = task.append_timeline_log(timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return timeline_log_change

    def complete_task(
        self,
        task_id: str,
        timeline_entry: TimelineEntry,
    ) -> TaskCompletionChange:
        task = self.tasks[task_id]
        completion_change = task.complete_with_timeline_log(timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return completion_change

    def cancel_task(
        self,
        task_id: str,
        timeline_entry: TimelineEntry,
    ) -> TaskCompletionChange:
        task = self.tasks[task_id]
        cancellation_change = task.cancel_with_timeline_log(timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return cancellation_change

    def delete_task(self, task_id: str) -> None:
        deleted_task = self.tasks[task_id]
        replacement_parent_task_id = deleted_task.parent_task_id

        for child_task_id in list(deleted_task.child_task_ids):
            self.set_task_parent(child_task_id, replacement_parent_task_id)

        for task in self.tasks.values():
            if task_id in task.dependency_task_ids:
                task.dependency_task_ids.remove(task_id)

        if replacement_parent_task_id is not None:
            self.tasks[replacement_parent_task_id].child_task_ids.remove(task_id)

        del self.tasks[task_id]
        self._validate_after_task_field_change()

    def set_task_dependencies(self, task_id: str, dependency_task_ids: list[str]) -> None:
        self.tasks[task_id].dependency_task_ids = list(dependency_task_ids)
        self._validate_after_task_field_change()

    def set_task_dependants(self, task_id: str, dependant_task_ids: list[str]) -> None:
        self._replace_task_dependants(task_id, dependant_task_ids)
        self._validate_after_task_field_change()

    def set_task_deadline(self, task_id: str, deadline: str) -> None:
        self.tasks[task_id].deadline = deadline
        self._validate_after_task_field_change()

    def clear_task_deadline(self, task_id: str) -> None:
        self.tasks[task_id].deadline = None
        self._validate_after_task_field_change()

    def set_task_external_coordination(self, task_id: str, external_coordination: str) -> None:
        self.tasks[task_id].external_coordination = ExternalCoordination(external_coordination)
        self._validate_after_task_field_change()

    def set_task_uncertainty(self, task_id: str, uncertainty: str) -> None:
        self.tasks[task_id].uncertainty = Uncertainty(uncertainty)
        self._validate_after_task_field_change()

    def set_task_friction(self, task_id: str, friction: str) -> None:
        self.tasks[task_id].friction = Friction(friction)
        self._validate_after_task_field_change()

    def task_ids_grouped_for_landing_page(self) -> dict[Priority, list[str]]:
        self.recalculate_display_priorities()
        return self.ongoing_tasks_landing_page.task_ids_grouped_by_priority(self.tasks)

    def completed_task_ids_for_landing_page(self) -> list[str]:
        return self.completed_tasks_landing_page.completed_landing_root_task_ids(self.tasks)

    def cancelled_task_ids_for_landing_page(self) -> list[str]:
        return self.completed_tasks_landing_page.cancelled_landing_root_task_ids(self.tasks)

    def repair_operation_keys_for_changes(self, task_tree_changes: list[dict[str, Any]]) -> list[str]:
        task_ids_to_repair = set()

        for task_tree_change in task_tree_changes:
            task_id = task_tree_change["task_id"]
            task_ids_to_repair.add(task_id)
            task_ids_to_repair.update(self._ancestor_task_ids(task_id))

            changed_fields = set(task_tree_change.get("fields", {}))
            if "parent_task_id" in changed_fields:
                task_ids_to_repair.update(_parent_task_ids_from_change(task_tree_change))

        return [
            "replace:ongoing_landing_page",
            "replace:completed_landing_page",
            *[
                operation_key
                for task_id in sorted(task_ids_to_repair, key=task_id_sort_key)
                for operation_key in [f"update_properties:task:{task_id}"]
                if task_id in self.tasks
            ],
        ]

    def task_id_for_notion_page_id(self, notion_page_id: str) -> str | None:
        target_page_id = _compact_notion_page_id(notion_page_id)
        for task in self.tasks.values():
            if task.notion_page_id is None:
                continue
            if _compact_notion_page_id(task.notion_page_id) == target_page_id:
                return task.task_id

        return None

    def validate(self) -> None:
        self._validate_fixed_page_keys_and_titles()
        self._validate_task_keys_match_task_values()
        self._validate_parent_child_links()
        self._validate_dependency_dependant_links()
        self._validate_task_hierarchy_has_no_cycles()

    def recalculate_display_priorities(self) -> None:
        for task in self.tasks.values():
            task.displayed_priority = task.configured_priority
        for task_id in sorted(self.tasks, key=task_id_sort_key, reverse=True):
            self.tasks[task_id].displayed_priority = self._calculate_priority_visible_on_task(self.tasks[task_id])

    def derive_dependant_task_ids_from_dependencies(self) -> None:
        for task in self.tasks.values():
            task.dependency_task_ids = _normalised_task_ids(task.dependency_task_ids)
            task.dependant_task_ids = []

        for dependant_task in self.tasks.values():
            for dependency_task_id in dependant_task.dependency_task_ids:
                dependency_task = self.tasks.get(dependency_task_id)
                if dependency_task is None:
                    continue
                dependency_task.dependant_task_ids.append(dependant_task.task_id)

        for task in self.tasks.values():
            task.dependant_task_ids = _normalised_task_ids(task.dependant_task_ids)

    def _validate_fixed_page_keys_and_titles(self) -> None:
        validate_fixed_tracked_page(
            page=self.ongoing_tasks_landing_page.page,
            expected_local_page_key=ONGOING_LANDING_PAGE_LOCAL_KEY,
        )
        validate_fixed_tracked_page(
            page=self.completed_tasks_landing_page.page,
            expected_local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
        )

    def _validate_task_keys_match_task_values(self) -> None:
        for task_id, task in self.tasks.items():
            if task_id != task.task_id:
                raise NotionPlanningError(f"Task key {task_id!r} does not match task id {task.task_id!r}")

    def _validate_parent_child_links(self) -> None:
        for task_id, task in self.tasks.items():
            if task.parent_task_id is not None:
                self._validate_task_exists(task.parent_task_id)
                parent_task = self.tasks[task.parent_task_id]
                if task_id not in parent_task.child_task_ids:
                    raise NotionPlanningError(
                        f"Task {task_id} should be listed as child of {task.parent_task_id}"
                    )
            for child_task_id in task.child_task_ids:
                self._validate_task_exists(child_task_id)
                child_task = self.tasks[child_task_id]
                if child_task.parent_task_id != task_id:
                    raise NotionPlanningError(
                        f"Task {child_task_id} should have parent {task_id}"
                    )

    def _validate_dependency_dependant_links(self) -> None:
        for task_id, task in self.tasks.items():
            if task_id in task.dependency_task_ids:
                raise NotionPlanningError(f"Task {task_id} cannot depend on itself")

            for dependency_task_id in task.dependency_task_ids:
                self._validate_task_exists(dependency_task_id)
                dependency_task = self.tasks[dependency_task_id]
                if task_id not in dependency_task.dependant_task_ids:
                    raise NotionPlanningError(
                        f"Task {dependency_task_id} should list {task_id} as a dependant"
                    )

            for dependant_task_id in task.dependant_task_ids:
                self._validate_task_exists(dependant_task_id)
                dependant_task = self.tasks[dependant_task_id]
                if task_id not in dependant_task.dependency_task_ids:
                    raise NotionPlanningError(
                        f"Task {dependant_task_id} should depend on {task_id}"
                    )

    def _validate_task_exists(self, task_id: str) -> None:
        if task_id not in self.tasks:
            raise NotionPlanningError(f"Task {task_id} does not exist")

    def _validate_task_hierarchy_has_no_cycles(self) -> None:
        for task_id in self.tasks:
            visited_task_ids = set()
            current_task_id = task_id
            while current_task_id is not None:
                if current_task_id in visited_task_ids:
                    raise NotionPlanningError("Task hierarchy has a cycle")
                visited_task_ids.add(current_task_id)
                current_task_id = self.tasks[current_task_id].parent_task_id

    def _calculate_priority_visible_on_task(self, task: Task) -> Priority:
        if not task.child_task_ids:
            return task.configured_priority

        priorities_visible_in_subtree = []
        for child_task_id in task.child_task_ids:
            child_task = self.tasks[child_task_id]
            if child_task.should_contribute_priority_to_ancestors():
                priorities_visible_in_subtree.append(child_task.displayed_priority or child_task.configured_priority)
        if not priorities_visible_in_subtree:
            return task.configured_priority

        return _highest_priority(priorities_visible_in_subtree)

    def _normalise_task_timelines(self) -> None:
        for task in self.tasks.values():
            task.normalise_timeline_entries()

    def _ancestor_task_ids(self, task_id: str) -> list[str]:
        ancestor_task_ids = []
        current_task = self.tasks.get(task_id)

        while current_task and current_task.parent_task_id is not None:
            parent_task_id = current_task.parent_task_id
            ancestor_task_ids.append(parent_task_id)
            current_task = self.tasks.get(parent_task_id)

        return ancestor_task_ids

    def _validate_after_task_field_change(self) -> None:
        self.derive_dependant_task_ids_from_dependencies()
        self.validate()
        self.recalculate_display_priorities()

    def _replace_task_dependants(self, task_id: str, dependant_task_ids: list[str]) -> None:
        for task in self.tasks.values():
            if task_id in task.dependency_task_ids:
                task.dependency_task_ids.remove(task_id)

        for dependant_task_id in dependant_task_ids:
            dependant_task = self.tasks[dependant_task_id]
            if task_id not in dependant_task.dependency_task_ids:
                dependant_task.dependency_task_ids.append(task_id)


def _highest_priority(priorities: list[Priority]) -> Priority:
    return min(priorities, key=lambda priority: _PRIORITY_RANK_BY_VALUE[priority])


def _normalised_task_ids(task_ids: list[str]) -> list[str]:
    return sorted(dict.fromkeys(task_ids), key=task_id_sort_key)


def _compact_notion_page_id(notion_page_id: str) -> str:
    return notion_page_id.replace("-", "").lower()


def _parent_task_ids_from_change(task_tree_change: dict[str, Any]) -> list[str]:
    parent_change = task_tree_change.get("fields", {}).get("parent_task_id", {})
    return [
        task_id
        for task_id in [parent_change.get("before"), parent_change.get("after")]
        if task_id is not None
    ]


def _changed_task_tree_fields(
    before_task: dict[str, Any],
    after_task: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    changed_fields = {}
    for field_name in [
        "parent_task_id",
        "child_task_ids",
        "dependency_task_ids",
        "dependant_task_ids",
        "deadline",
        "start_date_time",
        "end_date_time",
        "external_coordination",
        "uncertainty",
        "friction",
        "configured_priority",
        "status",
        "title",
    ]:
        if before_task.get(field_name) != after_task.get(field_name):
            changed_fields[field_name] = {
                "before": before_task.get(field_name),
                "after": after_task.get(field_name),
            }
    return changed_fields


def _task_to_tracker_state(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "configured_priority": task.configured_priority.value,
        "displayed_priority": task.displayed_priority.value if task.displayed_priority else None,
        "status": task.status.value,
        "status_update": task.status_update,
        "parent_task_id": task.parent_task_id,
        "child_task_ids": list(task.child_task_ids),
        "dependency_task_ids": list(task.dependency_task_ids),
        "dependant_task_ids": list(task.dependant_task_ids),
        "deadline": task.deadline,
        "start_date_time": task.start_date_time,
        "end_date_time": task.end_date_time,
        "external_coordination": task.external_coordination.value,
        "uncertainty": task.uncertainty.value,
        "friction": task.friction.value,
        "timeline_entries": [
            timeline_entry.to_tracker_state()
            for timeline_entry in task.timeline_entries
        ],
        "links": [
            external_link_to_tracker_state(link)
            for link in task.links
        ],
        "notion_page_id": task.notion_page_id,
    }


def _task_from_tracker_state(tracker_state: dict[str, Any]) -> Task:
    displayed_priority = tracker_state["displayed_priority"]
    return Task(
        task_id=tracker_state["task_id"],
        title=tracker_state["title"],
        configured_priority=Priority(tracker_state["configured_priority"]),
        displayed_priority=Priority(displayed_priority) if displayed_priority else None,
        status=TaskStatus(tracker_state["status"]),
        status_update=tracker_state["status_update"],
        parent_task_id=tracker_state["parent_task_id"],
        child_task_ids=list(tracker_state["child_task_ids"]),
        dependency_task_ids=list(tracker_state["dependency_task_ids"]),
        dependant_task_ids=list(tracker_state["dependant_task_ids"]),
        deadline=tracker_state["deadline"],
        start_date_time=tracker_state["start_date_time"],
        end_date_time=tracker_state["end_date_time"],
        external_coordination=ExternalCoordination(tracker_state["external_coordination"]),
        uncertainty=Uncertainty(tracker_state["uncertainty"]),
        friction=Friction(tracker_state["friction"]),
        timeline_entries=[
            TimelineEntry.from_tracker_state(derived_timeline_log)
            for derived_timeline_log in tracker_state["timeline_entries"]
        ],
        links=[
            external_link_from_tracker_state(link_state)
            for link_state in tracker_state["links"]
        ],
        notion_page_id=tracker_state["notion_page_id"],
    )
