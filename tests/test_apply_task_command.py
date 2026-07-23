from notion_task_tracker.apply_task_command import apply_command_to_task_tree
from notion_task_tracker.tasks import TaskTree
from tests.tasks.build_task_command_fixtures import (
    build_tracker_state_with_root_and_child_task,
)


def test_set_dependants_writes_authored_dependencies_on_affected_tasks():
    task_tree = TaskTree.from_tracker_state(
        build_tracker_state_with_root_and_child_task()
    )

    command_plan = apply_command_to_task_tree(
        command={
            "command": "set_task_dependants",
            "task_id": "ALOVYA-1",
            "dependant_task_ids": ["ALOVYA-2"],
        },
        task_tree=task_tree,
        ticket_prefix="ALOVYA",
    )

    assert task_tree.tasks["ALOVYA-2"].dependency_task_ids == ["ALOVYA-1"]
    assert [
        write_intent.operation_key
        for write_intent in command_plan.write_intents
    ] == ["update_dependencies:task:ALOVYA-2"]
