from notion_task_tracker import TrackedPage
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    render_completed_landing_page_markdown,
    render_ongoing_landing_page_markdown,
)
from notion_task_tracker.tasks import Priority, Task, TaskStatus


def test_ongoing_tasks_landing_page_renders_priority_sections_and_child_depth():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Root",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            child_task_ids=["ALOVYA-2"],
            notion_page_id="11111111111111111111111111111111",
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Child",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            parent_task_id="ALOVYA-1",
            notion_page_id="22222222222222222222222222222222",
        ),
    }

    markdown = render_ongoing_landing_page_markdown(
        tasks,
        NotionPageRegistry.from_tracked_pages([
            TrackedPage("task:ALOVYA-1", "Root", "11111111111111111111111111111111"),
            TrackedPage("task:ALOVYA-2", "Child", "22222222222222222222222222222222"),
        ]),
    )

    assert markdown == "\n".join([
        "## P1 (high impact)",
        '- [P1] <mention-page url="https://www.notion.so/11111111111111111111111111111111"/>: Active {color="orange"}',
        '\t- [N/A] ~~<mention-page url="https://www.notion.so/22222222222222222222222222222222"/>~~: Complete {color="green"}',
    ])


def test_completed_tasks_landing_page_starts_from_completed_tasks_without_visible_completed_parents():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Ongoing root",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            child_task_ids=["ALOVYA-2"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Completed child",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            parent_task_id="ALOVYA-1",
        ),
    }

    markdown = render_completed_landing_page_markdown(
        tasks,
        _page_registry_for_task_ids(tasks),
    )

    assert markdown == "\n".join([
        "## Completed",
        '- [N/A] ~~<mention-page url="https://www.notion.so/22222222222222222222222222222222"/>~~: Complete {color="green"}',
    ])


def test_ongoing_tasks_landing_page_orders_sibling_roots_by_dependency_without_nesting_them():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="A",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependant_task_ids=["ALOVYA-2"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="B",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependency_task_ids=["ALOVYA-1"],
            dependant_task_ids=["ALOVYA-3"],
        ),
        "ALOVYA-3": Task(
            task_id="ALOVYA-3",
            title="C",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependency_task_ids=["ALOVYA-2"],
        ),
        "ALOVYA-4": Task(
            task_id="ALOVYA-4",
            title="D",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependant_task_ids=["ALOVYA-5"],
        ),
        "ALOVYA-5": Task(
            task_id="ALOVYA-5",
            title="E",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependency_task_ids=["ALOVYA-4"],
        ),
    }

    markdown = render_ongoing_landing_page_markdown(tasks, _page_registry_for_task_ids(tasks))

    assert markdown == "\n".join([
        "## P1 (high impact)",
        '- [P1] <mention-page url="https://www.notion.so/11111111111111111111111111111111"/>: Active {color="orange"}',
        '- [P1] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>: Active {color="orange"}',
        '- [P1] <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>: Active {color="orange"}',
        '- [P1] <mention-page url="https://www.notion.so/44444444444444444444444444444444"/>: Active {color="orange"}',
        '- [P1] <mention-page url="https://www.notion.so/55555555555555555555555555555555"/>: Active {color="orange"}',
    ])


def test_ongoing_tasks_landing_page_orders_children_by_dependency_without_changing_child_depth():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Parent",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            child_task_ids=["ALOVYA-3", "ALOVYA-2", "ALOVYA-4"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Child dependency",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-1",
            dependant_task_ids=["ALOVYA-3"],
        ),
        "ALOVYA-3": Task(
            task_id="ALOVYA-3",
            title="Child dependant",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-1",
            dependency_task_ids=["ALOVYA-2"],
            dependant_task_ids=["ALOVYA-4"],
        ),
        "ALOVYA-4": Task(
            task_id="ALOVYA-4",
            title="Nested dependant",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-1",
            dependency_task_ids=["ALOVYA-3"],
        ),
    }

    markdown = render_ongoing_landing_page_markdown(tasks, _page_registry_for_task_ids(tasks))

    assert markdown == "\n".join([
        "## P1 (high impact)",
        '- [P1] <mention-page url="https://www.notion.so/11111111111111111111111111111111"/>: Active {color="orange"}',
        '\t- [P1] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>: Active {color="orange"}',
        '\t- [P1] <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>: Active {color="orange"}',
        '\t- [P1] <mention-page url="https://www.notion.so/44444444444444444444444444444444"/>: Active {color="orange"}',
    ])


def test_ongoing_tasks_landing_page_orders_sibling_before_task_that_depends_on_its_descendant():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Parent",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            child_task_ids=["ALOVYA-4", "ALOVYA-2"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Sibling containing dependency",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-1",
            child_task_ids=["ALOVYA-3"],
        ),
        "ALOVYA-3": Task(
            task_id="ALOVYA-3",
            title="Nephew dependency",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-2",
            dependant_task_ids=["ALOVYA-4"],
        ),
        "ALOVYA-4": Task(
            task_id="ALOVYA-4",
            title="Task that depends on nephew",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            parent_task_id="ALOVYA-1",
            dependency_task_ids=["ALOVYA-3"],
        ),
    }

    markdown = render_ongoing_landing_page_markdown(tasks, _page_registry_for_task_ids(tasks))

    assert markdown == "\n".join([
        "## P1 (high impact)",
        '- [P1] <mention-page url="https://www.notion.so/11111111111111111111111111111111"/>: Active {color="orange"}',
        '\t- [P1] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>: Active {color="orange"}',
        '\t\t- [P1] <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>: Active {color="orange"}',
        '\t- [P1] <mention-page url="https://www.notion.so/44444444444444444444444444444444"/>: Active {color="orange"}',
    ])


def test_completed_tasks_landing_page_orders_sibling_roots_by_dependency_without_nesting_them():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Completed dependency",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            dependant_task_ids=["ALOVYA-2"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Completed dependant",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            dependency_task_ids=["ALOVYA-1"],
        ),
        "ALOVYA-3": Task(
            task_id="ALOVYA-3",
            title="Cancelled dependency",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.CANCELLED,
            dependant_task_ids=["ALOVYA-4"],
        ),
        "ALOVYA-4": Task(
            task_id="ALOVYA-4",
            title="Cancelled dependant",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.CANCELLED,
            dependency_task_ids=["ALOVYA-3"],
        ),
    }

    markdown = render_completed_landing_page_markdown(tasks, _page_registry_for_task_ids(tasks))

    assert markdown == "\n".join([
        "## Completed",
        '- [N/A] ~~<mention-page url="https://www.notion.so/11111111111111111111111111111111"/>~~: Complete {color="green"}',
        '- [N/A] ~~<mention-page url="https://www.notion.so/22222222222222222222222222222222"/>~~: Complete {color="green"}',
        "## Cancelled",
        '- [N/A] ~~<mention-page url="https://www.notion.so/33333333333333333333333333333333"/>~~: Cancelled {color="gray"}',
        '- [N/A] ~~<mention-page url="https://www.notion.so/44444444444444444444444444444444"/>~~: Cancelled {color="gray"}',
    ])


def _page_registry_for_task_ids(tasks: dict[str, Task]) -> NotionPageRegistry:
    return NotionPageRegistry.from_tracked_pages([
        TrackedPage(
            local_page_key=f"task:{task_id}",
            title=task.title,
            notion_page_id=str(task_number) * 32,
        )
        for task_id, task in tasks.items()
        for task_number in [int(task_id.rpartition("-")[2])]
    ])
