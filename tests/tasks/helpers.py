from __future__ import annotations

from notion_task_tracker.tasks import (
    Priority,
    Task,
    TaskStatus,
    TimelineEntry,
    TaskTree,
)


def _build_recursive_task_tree() -> TaskTree:
    task_tree = TaskTree()
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Activation quantisation stack",
            configured_priority=Priority.P2,
            status=TaskStatus.ACTIVE,
            status_update="Resolving the ONNX/QNN activation mismatch in ALOVYA-5.",
            notion_page_id="22222222222222222222222222222222",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-3",
            title="Find activation mismatch",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            timeline_entries=[
                TimelineEntry(
                    entry_date="2026-05-24",
                    heading="2026-05-24",
                    lines=["Updated ALOVYA-5: investigated issue X."],
                )
            ],
            notion_page_id="33333333333333333333333333333333",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-4",
            title="Complete calibration branch",
            configured_priority=Priority.P3,
            status=TaskStatus.COMPLETE,
            notion_page_id="44444444444444444444444444444444",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-5",
            title="Debug ONNX/QNN activation mismatch",
            configured_priority=Priority.P0,
            status=TaskStatus.BLOCKED,
            notion_page_id="55555555555555555555555555555555",
        )
    )

    task_tree.link_parent_to_child(parent_task_id="ALOVYA-2", child_task_id="ALOVYA-3")
    task_tree.link_parent_to_child(parent_task_id="ALOVYA-2", child_task_id="ALOVYA-4")
    task_tree.link_parent_to_child(parent_task_id="ALOVYA-3", child_task_id="ALOVYA-5")
    return task_tree

