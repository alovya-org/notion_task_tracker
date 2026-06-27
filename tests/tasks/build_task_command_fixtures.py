import json

from notion_task_tracker.tasks import Priority, Task, TaskTree, TaskStatus


def build_tracker_state_with_root_task() -> dict:
    task_tree = TaskTree()
    task_tree.ongoing_tasks_landing_page.page.notion_page_id = "11111111111111111111111111111111"
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    tracker_state = task_tree.to_tracker_state()
    tracker_state["identity"] = {"display_name": "Alovya", "ticket_prefix": "ALOVYA"}
    return tracker_state


def build_tracker_state_with_root_and_child_task() -> dict:
    task_tree = TaskTree()
    task_tree.ongoing_tasks_landing_page.page.notion_page_id = "11111111111111111111111111111111"
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Child task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="33333333333333333333333333333333",
        )
    )
    task_tree.link_parent_to_child(parent_task_id="ALOVYA-1", child_task_id="ALOVYA-2")
    tracker_state = task_tree.to_tracker_state()
    tracker_state["identity"] = {"display_name": "Alovya", "ticket_prefix": "ALOVYA"}
    return tracker_state


def build_fetched_task_page(
    ticket_id: str,
    title: str,
    priority: str,
    status: str,
    parent_urls: list[str],
) -> str:
    return "\n".join(
        [
            "<page>",
            "<properties>",
            json.dumps(
                {
                    "Ticket ID": ticket_id,
                    "Ticket page": title,
                    "Priority": priority,
                    "Status": status,
                    "Parent": json.dumps(parent_urls),
                    "Dependencies": "[]",
                    "Deadline": "",
                    "External coordination": "No",
                    "Uncertainty": "Low",
                    "Friction": "None",
                }
            ),
            "</properties>",
            "<content>",
            "## Timeline log",
            "</content>",
            "</page>",
        ]
    )
