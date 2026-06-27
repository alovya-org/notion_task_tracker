import asyncio

import pytest

from notion_task_tracker.notion_operations.reconcile_task_database import (
    refresh_tracker_state_for_task_command,
    refresh_tracker_state_from_notion_task_database,
)
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import (
    build_fetched_task_page,
    build_tracker_state_with_root_and_child_task,
    build_tracker_state_with_root_task,
)
from notion_task_tracker.tasks.database import build_task_database_tracker_state


def test_refresh_tracker_state_from_notion_task_database_uses_configured_data_source():
    tracker_state = build_tracker_state_with_root_task()
    tracker_state["task_database"] = _task_database_state()
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Ticket page": "Root task edited in database",
                "Ticket ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "Dependencies": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(
        refresh_tracker_state_from_notion_task_database(tracker_state, notion_client)
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["title"] == "Root task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Blocked"
    assert notion_client.queries == [{"data_source_id": "configured-data-source-id"}]
    assert notion_client.fetched_pages == []


def test_refresh_tracker_state_from_notion_task_database_does_not_depend_on_view_url():
    tracker_state = build_tracker_state_with_root_task()
    tracker_state["task_database"] = _task_database_state()
    assert "view_url" not in tracker_state["task_database"]
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Ticket page": "Root task edited in database",
                "Ticket ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "Dependencies": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(
        refresh_tracker_state_from_notion_task_database(tracker_state, notion_client)
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert notion_client.view_queries == []
    assert notion_client.queries == [{"data_source_id": "configured-data-source-id"}]


def test_refresh_tracker_state_for_task_command_fetches_only_relevant_pages():
    tracker_state = build_tracker_state_with_root_and_child_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": build_fetched_task_page(
                ticket_id="1",
                title="Root task",
                priority="P1",
                status="Active",
                parent_urls=[],
            ),
            "33333333333333333333333333333333": build_fetched_task_page(
                ticket_id="2",
                title="Child task edited in database",
                priority="P2",
                status="Blocked",
                parent_urls=["https://www.notion.so/22222222222222222222222222222222"],
            ),
        }
    )

    command_result = asyncio.run(
        refresh_tracker_state_for_task_command(
            command={
                "command": "split_task_with_sibling",
                "source_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Sibling task",
                    "configured_priority": "P2",
                    "status": "Active",
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["title"] == "Child task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["status"] == "Blocked"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["parent_task_id"] == "ALOVYA-1"
    assert notion_client.fetched_pages == [
        "33333333333333333333333333333333",
        "22222222222222222222222222222222",
    ]
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def test_refresh_tracker_state_for_task_command_requires_known_tasks():
    tracker_state = build_tracker_state_with_root_task()
    notion_client = FakeNotionClient()

    with pytest.raises(ValueError, match="ALOVYA-99"):
        asyncio.run(
            refresh_tracker_state_for_task_command(
                command={
                    "command": "complete_task",
                    "task_id": "ALOVYA-99",
                    "timeline_entry": {
                        "entry_date": "2026-05-26",
                        "heading": '<mention-date start="2026-05-26"/>',
                        "lines": ["Completed missing task."],
                    },
                },
                tracker_state=tracker_state,
                notion_client=notion_client,
            )
        )

    assert notion_client.fetched_pages == []
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def _task_database_state() -> dict:
    return build_task_database_tracker_state(
        data_source_id="configured-data-source-id",
    )
