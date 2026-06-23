from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree
from notion_task_tracker.tasks.refresh_task_tracker_state import find_task_ids_to_refresh_before_command


def test_find_task_ids_to_refresh_before_command_for_reparent_task_includes_moved_task_and_both_parents():
    tracker_state = _tracker_state_with_child_and_new_parent()

    task_ids = find_task_ids_to_refresh_before_command(
        {
            "command": "reparent_task",
            "task_id": "ALOVYA-2",
            "parent_task_id": "ALOVYA-3",
        },
        tracker_state,
    )

    assert task_ids == ["ALOVYA-2", "ALOVYA-3", "ALOVYA-1"]


def test_find_task_ids_to_refresh_before_command_for_complete_task_with_all_children_includes_root_and_descendants():
    tracker_state = _tracker_state_with_child_and_new_parent()

    task_ids = find_task_ids_to_refresh_before_command(
        {
            "command": "complete_task_with_all_children",
            "task_id": "ALOVYA-1",
        },
        tracker_state,
    )

    assert task_ids == ["ALOVYA-1", "ALOVYA-2"]


def _tracker_state_with_child_and_new_parent() -> dict:
    task_tree = TaskTree()
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Old parent",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="11111111111111111111111111111111",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Moved child",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-3",
            title="New parent",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="33333333333333333333333333333333",
        )
    )
    task_tree.link_parent_to_child(parent_task_id="ALOVYA-1", child_task_id="ALOVYA-2")
    return task_tree.to_tracker_state()
