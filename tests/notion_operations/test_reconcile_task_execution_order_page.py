import asyncio

from notion_task_tracker.notion_operations.reconcile_task_execution_order_page import (
    TASK_DATABASE_EXECUTION_ORDER_PROPERTY,
    reconcile_task_execution_order_page,
)
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DURATION_PROPERTY,
    TASK_DATABASE_DURATION_UNIT_PROPERTY,
    TASK_DATABASE_END_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_START_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
)


def test_reconcile_task_execution_order_page_creates_filtered_table_on_notions_empty_page():
    task_tree = _task_tree_with_ready_blocked_and_container_tasks()
    notion_client = _ExecutionOrderClient(
        page_blocks=[
            {"id": "empty-paragraph", "type": "paragraph", "paragraph": {"rich_text": []}},
        ],
        included_page_ids={"22222222222222222222222222222222"},
        property_was_created=True,
    )

    operation_keys = asyncio.run(
        reconcile_task_execution_order_page(_tracker_state(task_tree), notion_client)
    )

    assert notion_client.deleted_block_ids == ["empty-paragraph"]
    assert notion_client.created_view == {
        "page_id": "99999999999999999999999999999999",
        "data_source_id": "88888888888888888888888888888888",
        "visible_property_names": [
            "Task page", "Priority", "Deadline", "Status", "Parent", "Dependencies",
            "Dependants", "External coordination", "Uncertainty", "Friction",
        ],
        "hidden_property_names": [
            "Start", "End", "Duration", "Duration unit", "Task ID", "In execution order",
        ],
        "membership_property_name": "In execution order",
    }
    assert notion_client.membership_updates == [
        ("11111111111111111111111111111111", True),
        ("66666666666666666666666666666666", True),
        ("77777777777777777777777777777777", True),
    ]
    assert operation_keys == [
        "create:task_database_property:in_execution_order",
        "create:ready_priority_page:linked_database_view",
        "update:execution_order_membership:task:ALOVYA-1",
        "update:execution_order_membership:task:ALOVYA-6",
        "update:execution_order_membership:task:ALOVYA-7",
    ]


def test_reconcile_task_execution_order_page_changes_membership_without_recreating_view():
    task_tree = _task_tree_with_ready_blocked_and_container_tasks()
    notion_client = _ExecutionOrderClient(
        page_blocks=[{"id": "linked-database", "type": "child_database"}],
        included_page_ids={
            "11111111111111111111111111111111",
            "22222222222222222222222222222222",
            "33333333333333333333333333333333",
            "66666666666666666666666666666666",
            "77777777777777777777777777777777",
        },
    )

    operation_keys = asyncio.run(
        reconcile_task_execution_order_page(_tracker_state(task_tree), notion_client)
    )

    assert notion_client.created_view is None
    assert notion_client.membership_updates == [
        ("33333333333333333333333333333333", False),
    ]
    assert operation_keys == ["update:execution_order_membership:task:ALOVYA-3"]


def _task_tree_with_ready_blocked_and_container_tasks() -> TaskTree:
    task_tree = TaskTree()
    for task_id, status, notion_page_id in [
        ("ALOVYA-1", TaskStatus.ACTIVE, "11111111111111111111111111111111"),
        ("ALOVYA-2", TaskStatus.ACTIVE, "22222222222222222222222222222222"),
        ("ALOVYA-3", TaskStatus.ACTIVE, "33333333333333333333333333333333"),
        ("ALOVYA-4", TaskStatus.ACTIVE, "44444444444444444444444444444444"),
        ("ALOVYA-5", TaskStatus.COMPLETE, "55555555555555555555555555555555"),
        ("ALOVYA-6", TaskStatus.ACTIVE, "66666666666666666666666666666666"),
        ("ALOVYA-7", TaskStatus.ACTIVE, "77777777777777777777777777777777"),
    ]:
        task_tree.add_task(Task(
            task_id=task_id,
            title=f"Task {task_id}",
            configured_priority=Priority.P2,
            status=status,
            notion_page_id=notion_page_id,
        ))
    task_tree.set_task_dependencies("ALOVYA-2", ["ALOVYA-5"])
    task_tree.set_task_dependencies("ALOVYA-3", ["ALOVYA-6"])
    task_tree.link_parent_to_child("ALOVYA-4", "ALOVYA-7")
    return task_tree


def _tracker_state(task_tree: TaskTree) -> dict:
    return {
        **task_tree.to_tracker_state(),
        "task_database": {"data_source_id": "88888888888888888888888888888888"},
        "ready_priority_page": {
            "notion_page_id": "99999999999999999999999999999999",
        },
    }


class _ExecutionOrderClient:
    def __init__(
        self,
        page_blocks: list[dict],
        included_page_ids: set[str],
        property_was_created: bool = False,
    ) -> None:
        self.page_blocks = page_blocks
        self.included_page_ids = included_page_ids
        self.property_was_created = property_was_created
        self.deleted_block_ids = []
        self.created_view = None
        self.membership_updates = []

    async def ensure_checkbox_property(self, data_source_id: str, property_name: str):
        assert data_source_id == "88888888888888888888888888888888"
        assert property_name == TASK_DATABASE_EXECUTION_ORDER_PROPERTY
        property_names = [
            TASK_DATABASE_TITLE_PROPERTY, TASK_DATABASE_PRIORITY_PROPERTY,
            TASK_DATABASE_DEADLINE_PROPERTY, TASK_DATABASE_STATUS_PROPERTY,
            TASK_DATABASE_PARENT_PROPERTY, TASK_DATABASE_DEPENDENCIES_PROPERTY,
            TASK_DATABASE_DEPENDANTS_PROPERTY, TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
            TASK_DATABASE_UNCERTAINTY_PROPERTY, TASK_DATABASE_FRICTION_PROPERTY,
            TASK_DATABASE_START_PROPERTY, TASK_DATABASE_END_PROPERTY,
            TASK_DATABASE_DURATION_PROPERTY,
            TASK_DATABASE_DURATION_UNIT_PROPERTY,
            TASK_DATABASE_TICKET_ID_PROPERTY, TASK_DATABASE_EXECUTION_ORDER_PROPERTY,
        ]
        return ({name: {"id": f"property-{index}"} for index, name in enumerate(property_names)}, self.property_was_created)

    async def fetch_block_children(self, page_id: str):
        return self.page_blocks

    async def delete_block(self, block_id: str):
        self.deleted_block_ids.append(block_id)

    async def create_linked_execution_order_view(self, **arguments):
        arguments.pop("property_ids_by_name")
        self.created_view = arguments

    async def query_checkbox_page_ids(self, data_source_id: str, property_name: str):
        return self.included_page_ids

    async def update_page_properties(self, page_id: str, properties: dict):
        self.membership_updates.append(
            (page_id, properties[TASK_DATABASE_EXECUTION_ORDER_PROPERTY]["checkbox"])
        )
