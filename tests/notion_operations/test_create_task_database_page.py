import asyncio

from notion_task_tracker.notion_operations.create_task_database_page import execute_create_task_database_page_command
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import (
    build_tracker_state_with_root_and_child_task,
    build_tracker_state_with_root_task,
)
from notion_task_tracker.tasks.database import build_task_database_tracker_state
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree


def test_execute_create_task_database_page_command_creates_child_split_rows_then_refreshes_landing():
    tracker_state = _tracker_state_with_split_relations(build_tracker_state_with_root_task(), "ALOVYA-1")
    tracker_state["task_database"] = _task_database_state()
    notion_client = FakeNotionClient(
        created_page_ids=[
            "33333333333333333333333333333333",
            "44444444444444444444444444444444",
        ],
        fetched_page_content_by_id={
            "33333333333333333333333333333333": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Task ID":"72","Task page":"Child task"}',
                    "</properties>",
                    "</page>",
                ]
            ),
            "44444444444444444444444444444444": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Task ID":"73","Task page":"Other child task"}',
                    "</properties>",
                    "</page>",
                ]
            ),
        },
    )

    updated_tracker_state, completed_operation_keys = asyncio.run(
        execute_create_task_database_page_command(
            command={
                "command": "split_task_into_children",
                "source_task_id": "ALOVYA-1",
                "child_tasks": [
                    {
                        "title": "Child task",
                        "configured_priority": "P2",
                        "status": "Active",
                        "dependency_task_ids": [],
                        "dependant_task_ids": [],
                        "deadline": None,
                        "external_coordination": "No",
                        "uncertainty": "Low",
                        "friction": "None",
                    },
                    {
                        "title": "Other child task",
                        "configured_priority": "P2",
                        "status": "Active",
                        "dependency_task_ids": [],
                        "dependant_task_ids": [],
                        "deadline": None,
                        "external_coordination": "No",
                        "uncertainty": "Low",
                        "friction": "None",
                    },
                ],
                "parent_timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000001",
                    "title": "Child task creation",
                    "entry_date": "2026-05-25",
                    "heading": '<mention-date start="2026-05-25"/>',
                    "lines": ["Spawned child task."],
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-72"]["parent_task_id"] == "ALOVYA-1"
    assert updated_tracker_state["tasks"]["ALOVYA-73"]["parent_task_id"] == "ALOVYA-1"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["configured_priority"] == "P1"
    assert updated_tracker_state["tasks"]["ALOVYA-73"]["configured_priority"] == "P1"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["dependency_task_ids"] == ["ALOVYA-10"]
    assert updated_tracker_state["tasks"]["ALOVYA-73"]["dependency_task_ids"] == ["ALOVYA-10"]
    assert updated_tracker_state["tasks"]["ALOVYA-20"]["dependency_task_ids"] == ["ALOVYA-72", "ALOVYA-73"]
    assert updated_tracker_state["tasks"]["ALOVYA-1"]["dependency_task_ids"] == []
    assert updated_tracker_state["tasks"]["ALOVYA-1"]["dependant_task_ids"] == []
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["notion_page_id"] == "33333333333333333333333333333333"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-25",
            "heading": '<mention-date start="2026-05-25"/>',
            "lines": [],
        }
    ]
    assert completed_operation_keys[:2] == [
        "create_database_task:split_task_into_children",
        "update_properties:task:ALOVYA-72",
    ]
    assert completed_operation_keys[2].startswith(
        "update_timeline_log:task:ALOVYA-1:2026-05-25:ALOVYA-LOG-"
    )
    assert completed_operation_keys[3:5] == [
        "create_database_task:split_task_into_children",
        "update_properties:task:ALOVYA-73",
    ]
    assert completed_operation_keys[5].startswith(
        "update_timeline_log:task:ALOVYA-1:2026-05-25:ALOVYA-LOG-"
    )
    assert completed_operation_keys[6:] == [
        "update_dependencies:task:ALOVYA-1",
        "update_dependants:task:ALOVYA-1",
        "replace:ongoing_landing_page",
    ]
    assert notion_client.calls[0].operation_name == "create_task_database_page"
    assert notion_client.calls[0].arguments["data_source_id"] == "configured-data-source-id"
    assert notion_client.calls[0].arguments["properties"] == {
        "Deadline": None,
        "Start": None,
        "End": None,
        "Duration": None,
        "Duration unit": None,
        "External coordination": "No",
        "Friction": "None",
        "Task page": "Child task",
        "Priority": "P1",
        "Status": "Active",
        "Parent": '["https://www.notion.so/22222222222222222222222222222222"]',
        "Dependencies": '["https://www.notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
        "Dependants": '["https://www.notion.so/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]',
        "Uncertainty": "Low",
    }
    assert notion_client.calls[0].arguments["content"] == "\n".join(
        [
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            "<details>",
            "<summary>Child task creation · ALOVYA-LOG-00000000-0000-4000-8000-000000000001</summary>",
            '\t- Spawned from parent task: <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>.',
            "\t- Spawned child task.",
            "</details>",
        ]
    )
    assert notion_client.calls[1].arguments["properties"] == {
        "Task page": "[72] Child task",
    }
    assert notion_client.calls[2].operation_name == "replace_page_markdown"
    assert notion_client.calls[2].arguments["markdown"].startswith(
        "\n".join([
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            "<details>",
            "<summary>Created child task · ALOVYA-LOG-",
        ])
    )
    assert (
        '\t- Spawned child task: <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>.'
        in notion_client.calls[2].arguments["markdown"]
    )
    assert notion_client.calls[6].operation_name == "update_page_properties"
    assert notion_client.calls[6].arguments["properties"] == {"Dependencies": []}
    assert notion_client.calls[7].operation_name == "update_page_properties"
    assert notion_client.calls[7].arguments["properties"] == {"Dependants": []}
    assert notion_client.calls[-1].operation_name == "replace_page_markdown"


def test_execute_create_task_database_page_command_renders_landing_from_full_fresh_database():
    tracker_state = build_tracker_state_with_root_task()
    tracker_state["task_database"] = _task_database_state()
    notion_client = FakeNotionClient(
        created_page_ids=["33333333333333333333333333333333"],
        database_rows=[
            {
                "Task page": "Remote priority task",
                "Task ID": "1",
                "Priority": "P2",
                "Status": "Active",
                "Parent": "[]",
                "Dependencies": "[]",
                "Dependants": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            },
            {
                "Task page": "Created task",
                "Task ID": "72",
                "Priority": "P1",
                "Status": "Active",
                "Parent": "[]",
                "Dependencies": "[]",
                "Dependants": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/33333333333333333333333333333333",
            },
        ],
        fetched_page_content_by_id={
            "33333333333333333333333333333333": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Task ID":"72","Task page":"Created task"}',
                    "</properties>",
                    "</page>",
                ]
            )
        },
    )

    updated_tracker_state, _completed_operation_keys = asyncio.run(
        execute_create_task_database_page_command(
            command={
                "command": "create_top_level_task",
                "task": {
                    "title": "Created task",
                    "configured_priority": "P1",
                    "status": "Active",
                    "deadline": None,
                    "external_coordination": "No",
                    "uncertainty": "Low",
                    "friction": "None",
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    landing_markdown = notion_client.calls[-1].arguments["markdown"]
    assert updated_tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["title"] == "Created task"
    assert "[P2]" in landing_markdown
    assert "22222222222222222222222222222222" in landing_markdown
    assert "[P1]" in landing_markdown
    assert "33333333333333333333333333333333" in landing_markdown


def test_execute_create_task_database_page_command_keeps_sibling_detail_on_new_task():
    tracker_state = build_tracker_state_with_root_and_child_task()
    tracker_state["task_database"] = _task_database_state()
    notion_client = FakeNotionClient(
        created_page_ids=["44444444444444444444444444444444"],
        fetched_page_content_by_id={
            "44444444444444444444444444444444": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Task ID":"73","Task page":"Sibling task"}',
                    "</properties>",
                    "</page>",
                ]
            )
        },
    )

    updated_tracker_state, completed_operation_keys = asyncio.run(
        execute_create_task_database_page_command(
            command={
                "command": "split_task_with_sibling",
                "source_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Sibling task",
                    "configured_priority": "P1",
                    "status": "Active",
                    "dependency_task_ids": [],
                    "dependant_task_ids": [],
                    "deadline": None,
                    "external_coordination": "No",
                    "uncertainty": "Low",
                    "friction": "None",
                },
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000002",
                    "title": "Sibling implementation",
                    "entry_date": "2026-05-25",
                    "heading": '<mention-date start="2026-05-25"/>',
                    "blocks": [
                        {
                            "type": "paragraph",
                            "text": "Detailed implementation notes belong on the new sibling.",
                        },
                        {
                            "type": "code",
                            "language": "text",
                            "text": "pytest result: passed",
                        },
                    ],
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-73"]["parent_task_id"] == "ALOVYA-1"
    assert completed_operation_keys[:2] == [
        "create_database_task:split_task_with_sibling",
        "update_properties:task:ALOVYA-73",
    ]
    assert completed_operation_keys[2].startswith(
        "update_timeline_log:task:ALOVYA-1:2026-05-25:ALOVYA-LOG-"
    )
    assert completed_operation_keys[3:] == [
        "replace:ongoing_landing_page",
    ]
    assert notion_client.calls[0].arguments["content"] == "\n".join(
        [
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            "<details>",
            "<summary>Sibling implementation · ALOVYA-LOG-00000000-0000-4000-8000-000000000002</summary>",
            '\t- Spawned from parent task: <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>.',
            "\tDetailed implementation notes belong on the new sibling.",
            "\t```text",
            "\tpytest result: passed",
            "\t```",
            "</details>",
        ]
    )
    assert notion_client.calls[2].arguments["markdown"].startswith(
        "\n".join([
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            "<details>",
            "<summary>Created child task · ALOVYA-LOG-",
        ])
    )
    assert (
        '\t- Spawned child task: <mention-page url="https://www.notion.so/44444444444444444444444444444444"/>.'
        in notion_client.calls[2].arguments["markdown"]
    )


def test_execute_create_task_database_page_command_copies_sibling_split_relations():
    tracker_state = _tracker_state_with_split_relations(build_tracker_state_with_root_and_child_task(), "ALOVYA-2")
    tracker_state["task_database"] = _task_database_state()
    notion_client = FakeNotionClient(
        created_page_ids=["55555555555555555555555555555555"],
        fetched_page_content_by_id={
            "55555555555555555555555555555555": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Task ID":"74","Task page":"Sibling task"}',
                    "</properties>",
                    "</page>",
                ]
            )
        },
    )

    updated_tracker_state, _completed_operation_keys = asyncio.run(
        execute_create_task_database_page_command(
            command={
                "command": "split_task_with_sibling",
                "source_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Sibling task",
                    "configured_priority": "P1",
                    "status": "Active",
                    "dependency_task_ids": [],
                    "dependant_task_ids": [],
                    "deadline": None,
                    "external_coordination": "No",
                    "uncertainty": "Low",
                    "friction": "None",
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-74"]["dependency_task_ids"] == ["ALOVYA-10"]
    assert updated_tracker_state["tasks"]["ALOVYA-20"]["dependency_task_ids"] == ["ALOVYA-2", "ALOVYA-74"]
    assert updated_tracker_state["tasks"]["ALOVYA-2"]["dependency_task_ids"] == ["ALOVYA-10"]
    assert notion_client.calls[0].arguments["properties"]["Dependencies"] == (
        '["https://www.notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]'
    )
    assert notion_client.calls[0].arguments["properties"]["Dependants"] == (
        '["https://www.notion.so/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]'
    )


def _tracker_state_with_split_relations(tracker_state: dict, source_task_id: str) -> dict:
    task_tree = TaskTree.from_tracker_state(tracker_state)
    task_tree.add_task(
        Task(
            task_id="ALOVYA-10",
            title="Upstream task",
            configured_priority=Priority.P3,
            status=TaskStatus.ACTIVE,
            notion_page_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-20",
            title="Downstream task",
            configured_priority=Priority.P3,
            status=TaskStatus.ACTIVE,
            notion_page_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            dependency_task_ids=[source_task_id],
        )
    )
    task_tree.tasks[source_task_id].dependency_task_ids = ["ALOVYA-10"]
    task_tree.derive_dependant_task_ids_from_dependencies()
    task_tree.validate()
    return task_tree.replace_task_tree_in_tracker_state(tracker_state)


def _task_database_state() -> dict:
    return build_task_database_tracker_state(
        data_source_id="configured-data-source-id",
    )
