import asyncio

from notion_task_tracker.notion_operations.create_task_database_page import (
    create_tasks_in_current_tree,
)
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree
from .helpers import FakeNotionClient


def test_create_tasks_in_current_tree_fetches_missing_parent_page_for_sibling_creation():
    task_tree = _build_child_task_tree()
    notion_client = FakeNotionClient(
        created_page_ids=["33333333333333333333333333333333"],
        fetched_page_content_by_id={
            "11111111111111111111111111111111": _fetched_task_page_content(
                task_number="1",
            ),
            "33333333333333333333333333333333": _fetched_task_page_content(
                task_number="3",
            ),
        },
    )

    completed_operation_keys = asyncio.run(
        create_tasks_in_current_tree(
            command={
                "command": "split_task_with_sibling",
                "source_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Measure sibling creation",
                    "configured_priority": "P1",
                    "status": "Active",
                    "deadline": None,
                    "start": None,
                    "duration": None,
                    "duration_unit": None,
                    "external_coordination": "No",
                    "uncertainty": "Low",
                    "friction": "None",
                },
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-09c41014-3381-4ae6-b620-cb53ce8ab12e",
                    "title": "Sibling task creation",
                    "entry_date": "2026-07-29",
                    "heading": '<mention-date start="2026-07-29"/>',
                    "lines": ["Created a sibling task."],
                },
            },
            task_tree=task_tree,
            ticket_prefix="ALOVYA",
            task_data_source_id="task-data-source",
            fetched_page_content_by_task_id={
                "ALOVYA-2": _fetched_task_page_content(task_number="2"),
            },
            notion_client=notion_client,
        )
    )

    assert "11111111111111111111111111111111" in notion_client.fetched_pages
    assert task_tree.tasks["ALOVYA-3"].parent_task_id == "ALOVYA-1"
    assert "ALOVYA-3" in task_tree.tasks["ALOVYA-1"].child_task_ids
    assert any(
        operation_key.startswith("update_timeline_log:task:ALOVYA-1:2026-07-29:")
        for operation_key in completed_operation_keys
    )


def _build_child_task_tree() -> TaskTree:
    task_tree = TaskTree()
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Parent task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="11111111111111111111111111111111",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Existing child",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    task_tree.link_parent_to_child(
        parent_task_id="ALOVYA-1",
        child_task_id="ALOVYA-2",
    )
    return task_tree


def _fetched_task_page_content(task_number: str) -> str:
    return "\n".join(
        [
            "<page>",
            "<properties>",
            f'{{"Task ID":"{task_number}","Task page":"Task {task_number}"}}',
            "</properties>",
            "<content>",
            "## Timeline log",
            "</content>",
            "</page>",
        ]
    )
