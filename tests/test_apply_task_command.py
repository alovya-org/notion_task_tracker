from notion_task_tracker.apply_task_command import apply_command_to_task_tree
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree


def test_set_dependants_writes_authored_dependencies_on_affected_tasks():
    task_tree = TaskTree()
    task_tree.add_task(
        Task("ALOVYA-1", "Root", Priority.P1, TaskStatus.ACTIVE)
    )
    task_tree.add_task(
        Task(
            "ALOVYA-2",
            "Child",
            Priority.P1,
            TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-1",
        )
    )
    task_tree.tasks["ALOVYA-1"].child_task_ids = ["ALOVYA-2"]

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
