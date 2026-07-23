"""Task tree metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    DurationUnit,
    Friction,
    Priority,
    Task,
    TaskCompletionChange,
    TaskStatus,
    TimelineEntry,
    TimelineLog,
    TimelineLogChange,
    Uncertainty,
    _PRIORITY_RANK_BY_VALUE,
    task_id_sort_key,
    derive_task_end,
    validate_task_schedule,
)
from notion_task_tracker.tracked_pages import TrackedPage, validate_fixed_tracked_page


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
        start: str | None,
        duration: float | None,
        duration_unit: DurationUnit | None,
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
        task.start = start
        task.duration = duration
        task.duration_unit = duration_unit
        task.end = derive_task_end(
            task_label=task.task_id,
            start=task.start,
            duration=task.duration,
            duration_unit=task.duration_unit,
        )
        task.external_coordination = external_coordination
        task.uncertainty = uncertainty
        task.friction = friction
        self.set_task_parent(task_id, parent_task_id)
        self.derive_dependant_task_ids_from_dependencies()

    def append_task_timeline_log(
        self,
        task_id: str,
        timeline_log: TimelineLog,
        current_timeline_entries: list[TimelineEntry],
    ) -> TimelineLogChange:
        task = self.tasks[task_id]
        timeline_log_change = task.append_timeline_log(
            timeline_log,
            current_timeline_entries,
        )
        self.validate()
        self.recalculate_display_priorities()
        return timeline_log_change

    def complete_task(
        self,
        task_id: str,
        timeline_log: TimelineLog,
        current_timeline_entries: list[TimelineEntry],
    ) -> TaskCompletionChange:
        task = self.tasks[task_id]
        completion_change = task.complete_with_timeline_log(
            timeline_log,
            current_timeline_entries,
        )
        self.validate()
        self.recalculate_display_priorities()
        return completion_change

    def cancel_task(
        self,
        task_id: str,
        timeline_log: TimelineLog,
        current_timeline_entries: list[TimelineEntry],
    ) -> TaskCompletionChange:
        task = self.tasks[task_id]
        cancellation_change = task.cancel_with_timeline_log(
            timeline_log,
            current_timeline_entries,
        )
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

    def set_task_start(self, task_id: str, start: str) -> None:
        task = self.tasks[task_id]
        task.start = start
        self._derive_end_after_schedule_change(task)

    def clear_task_start(self, task_id: str) -> None:
        task = self.tasks[task_id]
        task.start = None
        self._derive_end_after_schedule_change(task)

    def set_task_duration(self, task_id: str, duration: float, duration_unit: str) -> None:
        task = self.tasks[task_id]
        task.duration = duration
        task.duration_unit = DurationUnit(duration_unit)
        self._derive_end_after_schedule_change(task)

    def replace_task_schedule(
        self,
        task_id: str,
        start: str,
        duration: float,
        duration_unit: DurationUnit,
    ) -> None:
        task = self.tasks[task_id]
        task.start = start
        task.duration = duration
        task.duration_unit = duration_unit
        self._derive_end_after_schedule_change(task)

    def clear_task_duration(self, task_id: str) -> None:
        task = self.tasks[task_id]
        task.duration = None
        task.duration_unit = None
        self._derive_end_after_schedule_change(task)

    def _derive_end_after_schedule_change(self, task: Task) -> None:
        task.end = derive_task_end(
            task_label=task.task_id,
            start=task.start,
            duration=task.duration,
            duration_unit=task.duration_unit,
        )
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
        self._validate_task_scheduling_fields()

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

    def _validate_task_scheduling_fields(self) -> None:
        for task in self.tasks.values():
            validate_task_schedule(
                task_label=task.task_id,
                start=task.start,
                duration=task.duration,
                duration_unit=task.duration_unit,
            )
            expected_end = derive_task_end(
                task_label=task.task_id,
                start=task.start,
                duration=task.duration,
                duration_unit=task.duration_unit,
            )
            if task.end != expected_end:
                raise NotionPlanningError(
                    f"Task {task.task_id} End must equal Start plus Duration"
                )

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
