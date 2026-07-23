import asyncio
import json

import pytest

from notion_task_tracker import NotionPageReference, NotionPageRegistry, NotionWriteIntent
from notion_task_tracker.apply_task_command import TaskCommandPlan
from notion_task_tracker.notion_operations.rest_client import (
    NotionRestClient,
    _notion_rest_access_token_from_environment,
    _notion_rest_error_message,
    _task_database_row_from_rest_page,
)
from notion_task_tracker.tasks import TaskTree


def test_execute_command_result_reports_operations_completed_before_failure():
    notion_client = _PartiallyFailingWriteClient()
    command_result = TaskCommandPlan(
        task_tree=TaskTree(),
        write_intents=[
            NotionWriteIntent(
                operation_key="first",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={},
            ),
            NotionWriteIntent(
                operation_key="second",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={},
            ),
        ],
        page_registry=NotionPageRegistry(pages={}),
    )

    with pytest.raises(
        ValueError,
        match="Notion write 'second' failed after completed operations: first",
    ):
        asyncio.run(notion_client.execute_command_result(command_result))


def test_fetch_task_page_content_uses_page_properties_and_markdown():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "url": "https://www.notion.so/22222222222222222222222222222222",
                "properties": _task_properties(ticket_number=1),
            },
            {"markdown": "## Timeline log"},
        ]
    )

    fetched_page_content = asyncio.run(
        notion_client.fetch_task_page_content("22222222222222222222222222222222")
    )

    assert '"Task ID": "1"' in fetched_page_content
    assert "_ntt_title_strikethrough" not in fetched_page_content
    assert "## Timeline log" in fetched_page_content
    assert notion_client.requests == [
        ("GET", "/v1/pages/22222222222222222222222222222222", None),
        ("GET", "/v1/pages/22222222222222222222222222222222/markdown", None),
    ]


def test_fetch_page_goes_through_notion_sdk_page_endpoint():
    notion_client = NotionRestClient(
        access_token="ntn_test",
        base_url="https://api.notion.test",
        notion_version="2026-03-11",
    )
    notion_client.client = _FakeNotionSdkClient(
        page_result={"id": "22222222222222222222222222222222"}
    )

    page = asyncio.run(notion_client.fetch_page("22222222222222222222222222222222"))

    assert page == {"id": "22222222222222222222222222222222"}
    assert notion_client.client.pages.requests == [
        ("retrieve", "22222222222222222222222222222222")
    ]


def test_append_block_children_uses_current_position_object():
    notion_client = NotionRestClient(
        access_token="ntn_test",
        base_url="https://api.notion.test",
        notion_version="2026-03-11",
    )
    notion_client.client = _FakeNotionSdkClient(page_result={})
    children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}]

    asyncio.run(notion_client.append_block_children(
        parent_block_id="page-a",
        children=children,
        after_block_id="heading-a",
    ))

    assert notion_client.client.blocks.children.requests == [
        {
            "block_id": "page-a",
            "children": children,
            "position": {
                "type": "after_block",
                "after_block": {"id": "heading-a"},
            },
        }
    ]


def test_append_block_children_omits_position_for_an_empty_page():
    notion_client = NotionRestClient(
        access_token="ntn_test",
        base_url="https://api.notion.test",
        notion_version="2026-03-11",
    )
    notion_client.client = _FakeNotionSdkClient(page_result={})
    children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}]

    asyncio.run(notion_client.append_block_children(
        parent_block_id="page-a",
        children=children,
        after_block_id=None,
    ))

    assert notion_client.client.blocks.children.requests == [{
        "block_id": "page-a",
        "children": children,
    }]


def test_from_environment_uses_notion_api_key(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test")

    notion_client = NotionRestClient.from_environment()

    assert notion_client.access_token == "ntn_test"


def test_from_environment_requires_notion_api_key(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)

    try:
        NotionRestClient.from_environment()
    except PermissionError as error:
        assert "Set NOTION_API_KEY" in str(error)
    else:
        raise AssertionError("Expected PermissionError")


def test_rest_auth_ignores_credentials_file_without_notion_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    token_file = tmp_path / ".credentials.json"
    token_file.write_text(
        json.dumps({"Notion|workspace": {"access_token": "ntn_from_file"}}),
        encoding="utf-8",
    )

    try:
        _notion_rest_access_token_from_environment()
    except PermissionError as error:
        assert "Set NOTION_API_KEY" in str(error)
    else:
        raise AssertionError("Expected PermissionError")


def test_query_data_source_maps_rest_pages_to_database_rows():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "results": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "url": "https://www.notion.so/22222222222222222222222222222222",
                        "properties": _task_properties(ticket_number=7),
                    }
                ],
                "has_more": False,
            }
        ]
    )

    rows = asyncio.run(notion_client.query_data_source("collection://data-source-a", "ignored"))

    assert rows == [
        {
            "Deadline": "2026-06-15",
            "Start": "2026-06-15T09:30:00+06:00",
            "End": "2026-06-15T12:00:00+06:00",
            "Duration": "2.5",
            "Duration unit": "Hours",
            "Dependencies": '["https://www.notion.so/33333333333333333333333333333333"]',
            "Dependants": '["https://www.notion.so/44444444444444444444444444444444"]',
            "External coordination": "Yes",
            "Friction": "Charged",
                "Task page": "Root task",
                "_ntt_title_strikethrough": False,
            "Task ID": "7",
            "Priority": "P1",
            "Status": "Active",
            "Parent": "[]",
            "Uncertainty": "High",
            "url": "https://www.notion.so/22222222222222222222222222222222",
        }
    ]
    assert notion_client.requests == [
        ("POST", "/v1/data_sources/data-source-a/query", {"page_size": 100})
    ]


def test_query_row_preserves_completed_title_strikethrough_for_canonical_comparison():
    properties = _task_properties(ticket_number=7)
    properties["Task page"]["title"][0]["annotations"] = {
        "strikethrough": True,
    }

    row = _task_database_row_from_rest_page({
        "id": "22222222-2222-2222-2222-222222222222",
        "properties": properties,
    })

    assert row["Task page"] == "Root task"
    assert row["_ntt_title_strikethrough"] is True


def test_update_properties_call_uses_rest_page_property_shape():
    notion_client = _FakeNotionRestClient(
        responses=[{"id": "22222222-2222-2222-2222-222222222222"}]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="update_properties:task:ALOVYA-1",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={
                    "properties": {
                        "Task page": "Root task",
                        "Priority": "P2",
                        "Status": "Blocked",
                        "Dependencies": ["task:ALOVYA-2"],
                        "Dependants": ["task:ALOVYA-3"],
                        "Deadline": "2026-06-15",
                        "Start": "2026-06-15T09:30:00+06:00",
                        "End": "2026-06-15T12:30:00+06:00",
                        "Duration": 3.0,
                        "Duration unit": "Hours",
                        "External coordination": "Yes",
                        "Uncertainty": "High",
                        "Friction": "Charged",
                    },
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
            "PATCH",
            "/v1/pages/22222222222222222222222222222222",
            {
                "properties": {
                    "Task page": {"title": [{"type": "text", "text": {"content": "Root task"}}]},
                    "Priority": {"select": {"name": "P2"}},
                    "Status": {"select": {"name": "Blocked"}},
                    "Dependencies": {
                        "relation": [{"id": "33333333333333333333333333333333"}],
                    },
                    "Dependants": {
                        "relation": [{"id": "44444444444444444444444444444444"}],
                    },
                    "Deadline": {"date": {"start": "2026-06-15"}},
                    "Start": {"date": {"start": "2026-06-15T09:30:00+06:00"}},
                    "End": {"date": {"start": "2026-06-15T12:30:00+06:00"}},
                    "Duration": {"number": 3.0},
                    "Duration unit": {"select": {"name": "Hours"}},
                    "External coordination": {"select": {"name": "Yes"}},
                    "Uncertainty": {"select": {"name": "High"}},
                    "Friction": {"select": {"name": "Charged"}},
                }
            },
        )
    ]


def test_update_properties_call_preserves_structured_title_rich_text():
    notion_client = _FakeNotionRestClient(
        responses=[{"id": "22222222-2222-2222-2222-222222222222"}]
    )
    title_rich_text = [
        {
            "type": "text",
            "text": {"content": "[1] Root task"},
            "annotations": {
                "bold": False,
                "italic": False,
                "strikethrough": True,
                "underline": False,
                "code": False,
                "color": "default",
            },
        }
    ]

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="update_properties:task:ALOVYA-1",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={"properties": {"Task page": {"rich_text": title_rich_text}}},
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
            "PATCH",
            "/v1/pages/22222222222222222222222222222222",
            {"properties": {"Task page": {"title": title_rich_text}}},
        )
    ]


def test_trash_page_moves_database_page_to_trash():
    notion_client = _FakeNotionRestClient(
        responses=[{"id": "22222222-2222-2222-2222-222222222222", "in_trash": True}]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="trash:task:ALOVYA-1",
                operation_name="trash_page",
                target_page_key="task:ALOVYA-1",
                arguments={},
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
            "PATCH",
            "/v1/pages/22222222222222222222222222222222",
            {"in_trash": True},
        )
    ]

def test_replace_content_uses_page_markdown_endpoint():
    notion_client = _FakeNotionRestClient(
        responses=[{}]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="replace:ongoing_landing_page",
                operation_name="replace_page_markdown",
                target_page_key="ongoing_landing_page",
                arguments={
                    "markdown": "## P1\n- Active task",
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
        "PATCH",
        "/v1/pages/11111111111111111111111111111111/markdown",
        {
            "type": "replace_content",
            "replace_content": {"new_str": "## P1\n- Active task"},
        },
        )
    ]


def test_update_content_inserts_new_markdown_after_matching_heading():
    notion_client = _FakeNotionRestClient(
        responses=[
            {},
        ]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="update_timeline_log:task:ALOVYA-1:2026-05-26",
                operation_name="update_timeline_log",
                target_page_key="task:ALOVYA-1",
                arguments={
                    "timeline_log_heading": "Timeline log",
                    "timeline_section_markdown": '### <mention-date start="2026-05-26"/>\n- New log.',
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
        "PATCH",
        "/v1/pages/22222222222222222222222222222222/markdown",
        {
            "type": "update_content",
            "update_content": {
                "content_updates": [
                    {
                        "old_str": "## Timeline log",
                        "new_str": '## Timeline log\n### <mention-date start="2026-05-26"/>\n- New log.',
                    }
                ]
            },
        },
        ),
    ]


def test_create_pages_call_creates_database_page_with_children():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "url": "https://www.notion.so/33333333333333333333333333333333",
            }
        ]
    )

    result = asyncio.run(
        notion_client.create_database_page(
            data_source_id="data-source-a",
            properties={
                "Task page": "Child task",
                "Priority": "P1",
                "Status": "Active",
                "Parent": json.dumps([
                    "https://www.notion.so/22222222222222222222222222222222"
                ]),
            },
            markdown="## Timeline log",
        )
    )

    assert result["url"] == "https://www.notion.so/33333333333333333333333333333333"
    assert notion_client.requests[0][0:2] == ("POST", "/v1/pages")
    assert notion_client.requests[0][2]["properties"]["Parent"] == {
        "relation": [{"id": "22222222222222222222222222222222"}]
    }
    assert notion_client.requests[0][2]["markdown"] == "## Timeline log"


def test_notion_rest_error_message_includes_request_context():
    error_message = _notion_rest_error_message(
        method="PATCH",
        path="/v1/pages/page-a/markdown",
        status_code=400,
        error_text='{"code":"validation_error","message":"old_str not found"}',
    )

    assert "PATCH" in error_message
    assert "/v1/pages/page-a/markdown" in error_message
    assert "validation_error" in error_message


def test_notion_rest_error_message_includes_permission_hint():
    error_message = _notion_rest_error_message(
        method="PATCH",
        path="/v1/blocks/block-a/children",
        status_code=403,
        error_text='{"code":"restricted_resource"}',
    )

    assert "insert-content" in error_message


def test_notion_rest_error_message_includes_not_found_hint():
    error_message = _notion_rest_error_message(
        method="GET",
        path="/v1/blocks/page-a/children",
        status_code=404,
        error_text='{"code":"object_not_found"}',
    )

    assert "shared with the Notion integration" in error_message


class _FakeNotionRestClient(NotionRestClient):
    def __init__(self, responses: list[dict]):
        super().__init__(
            access_token="ntn_test",
            base_url="https://api.notion.test",
            notion_version="2026-03-11",
        )
        self.responses = list(responses)
        self.requests = []

    async def _send_json(self, method: str, path: str, body: dict | None):
        self.requests.append((method, path, body))
        return self.responses.pop(0)


class _FakeNotionSdkClient:
    def __init__(self, page_result: dict):
        self.pages = _FakePagesEndpoint(page_result)
        self.blocks = _FakeBlocksEndpoint()


class _FakePagesEndpoint:
    def __init__(self, page_result: dict):
        self.page_result = page_result
        self.requests = []

    async def retrieve(self, page_id: str):
        self.requests.append(("retrieve", page_id))
        return self.page_result


class _FakeBlocksEndpoint:
    def __init__(self):
        self.children = _FakeBlockChildrenEndpoint()


class _FakeBlockChildrenEndpoint:
    def __init__(self):
        self.requests = []

    async def append(self, **arguments):
        self.requests.append(arguments)


def _page_registry() -> NotionPageRegistry:
    return NotionPageRegistry(
        pages={
            "ongoing_landing_page": NotionPageReference(
                local_page_key="ongoing_landing_page",
                title="Landing page",
                notion_page_id="11111111111111111111111111111111",
            ),
            "task:ALOVYA-1": NotionPageReference(
                local_page_key="task:ALOVYA-1",
                title="Root task",
                notion_page_id="22222222222222222222222222222222",
            ),
            "task:ALOVYA-2": NotionPageReference(
                local_page_key="task:ALOVYA-2",
                title="Dependency task",
                notion_page_id="33333333333333333333333333333333",
            ),
            "task:ALOVYA-3": NotionPageReference(
                local_page_key="task:ALOVYA-3",
                title="Dependant task",
                notion_page_id="44444444444444444444444444444444",
            ),
        }
    )


def _task_properties(ticket_number: int) -> dict:
    return {
        "Task page": {
            "type": "title",
            "title": [{"plain_text": "Root task"}],
        },
        "Task ID": {
            "type": "unique_id",
            "unique_id": {"number": ticket_number},
        },
        "Priority": {
            "type": "select",
            "select": {"name": "P1"},
        },
        "Status": {
            "type": "status",
            "status": {"name": "Active"},
        },
        "Parent": {
            "type": "relation",
            "relation": [],
        },
        "Dependencies": {
            "type": "relation",
            "relation": [
                {"id": "33333333-3333-3333-3333-333333333333"},
            ],
        },
        "Dependants": {
            "type": "relation",
            "relation": [
                {"id": "44444444-4444-4444-4444-444444444444"},
            ],
        },
        "Deadline": {
            "type": "date",
            "date": {"start": "2026-06-15"},
        },
        "Start": {
            "type": "date",
            "date": {"start": "2026-06-15T09:30:00+06:00"},
        },
        "End": {
            "type": "date",
            "date": {"start": "2026-06-15T12:00:00+06:00"},
        },
        "Duration": {
            "type": "number",
            "number": 2.5,
        },
        "Duration unit": {
            "type": "select",
            "select": {"name": "Hours"},
        },
        "External coordination": {
            "type": "select",
            "select": {"name": "Yes"},
        },
        "Uncertainty": {
            "type": "select",
            "select": {"name": "High"},
        },
        "Friction": {
            "type": "select",
            "select": {"name": "Charged"},
        },
    }


class _PartiallyFailingWriteClient(NotionRestClient):
    def __init__(self) -> None:
        pass

    async def execute_write_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict:
        del page_registry
        if write_intent.operation_key == "second":
            raise RuntimeError("Transport stopped")
        return {"operation_key": write_intent.operation_key}
