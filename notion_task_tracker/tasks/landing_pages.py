"""Task landing-page groupings derived from the task tree."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from notion_task_tracker.tasks.task import Priority, Task, TaskStatus, task_id_sort_key
from notion_task_tracker.tracked_pages import TrackedPage


@dataclass
class OngoingTasksLandingPage:
    page: TrackedPage

    def task_ids_grouped_by_priority(self, tasks: dict[str, Task]) -> dict[Priority, list[str]]:
        return {
            priority: [
                task_id
                for task_id in order_landing_task_ids_by_dependency(
                    tasks,
                    _landing_root_task_ids_matching(tasks, _task_should_start_ongoing_landing_tree),
                    _task_should_start_ongoing_landing_tree,
                )
                if tasks[task_id].displayed_priority == priority
            ]
            for priority in Priority
        }


@dataclass
class CompletedTasksLandingPage:
    page: TrackedPage

    def completed_landing_root_task_ids(self, tasks: dict[str, Task]) -> list[str]:
        task_should_be_visible = lambda task: task.status == TaskStatus.COMPLETE
        return order_landing_task_ids_by_dependency(
            tasks,
            _landing_root_task_ids_matching(tasks, task_should_be_visible),
            task_should_be_visible,
        )

    def cancelled_landing_root_task_ids(self, tasks: dict[str, Task]) -> list[str]:
        task_should_be_visible = lambda task: task.status == TaskStatus.CANCELLED
        return order_landing_task_ids_by_dependency(
            tasks,
            _landing_root_task_ids_matching(tasks, task_should_be_visible),
            task_should_be_visible,
        )


def visible_ongoing_landing_task_ids(tasks: dict[str, Task]) -> list[str]:
    return order_landing_task_ids_by_dependency(
        tasks,
        _landing_root_task_ids_matching(tasks, _task_should_start_ongoing_landing_tree),
        _task_should_start_ongoing_landing_tree,
    )


def task_should_appear_inside_ongoing_landing_tree(task: Task) -> bool:
    return True


def landing_root_task_ids_matching(
    tasks: dict[str, Task],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    return order_landing_task_ids_by_dependency(
        tasks,
        _landing_root_task_ids_matching(tasks, task_should_be_visible),
        task_should_be_visible,
    )


def order_landing_task_ids_by_dependency(
    tasks: dict[str, Task],
    task_ids: list[str],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    unsorted_task_ids = set(task_ids)
    ordered_task_ids = []

    while unsorted_task_ids:
        next_task_id = _find_least_dependent_task_id(
            tasks,
            unsorted_task_ids,
            task_should_be_visible,
        )
        ordered_task_ids.append(next_task_id)
        unsorted_task_ids.remove(next_task_id)

    return ordered_task_ids


def _landing_root_task_ids_matching(
    tasks: dict[str, Task],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    return [
        task.task_id
        for task in sorted(tasks.values(), key=lambda task: task_id_sort_key(task.task_id))
        if task_should_be_visible(task)
        and _parent_is_not_visible_on_same_landing(tasks, task, task_should_be_visible)
    ]


def _parent_is_not_visible_on_same_landing(
    tasks: dict[str, Task],
    task: Task,
    task_should_be_visible: Callable[[Task], bool],
) -> bool:
    return task.parent_task_id is None or not task_should_be_visible(tasks[task.parent_task_id])


def _find_least_dependent_task_id(
    tasks: dict[str, Task],
    candidate_task_ids: set[str],
    task_should_be_visible: Callable[[Task], bool],
) -> str:
    return min(
        candidate_task_ids,
        key=lambda task_id: (
            _count_remaining_visible_dependencies(
                tasks,
                task_id,
                candidate_task_ids,
                task_should_be_visible,
            ),
            task_id_sort_key(task_id),
        ),
    )


def _count_remaining_visible_dependencies(
    tasks: dict[str, Task],
    task_id: str,
    candidate_task_ids: set[str],
    task_should_be_visible: Callable[[Task], bool],
) -> int:
    return sum(
        1
        for dependency_task_id in tasks[task_id].dependency_task_ids
        if dependency_task_id in candidate_task_ids
        and dependency_task_id in tasks
        and task_should_be_visible(tasks[dependency_task_id])
    )


def _task_should_start_ongoing_landing_tree(task: Task) -> bool:
    return task.status not in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}
