"""Notion REST client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from notion_client import AsyncClient
from notion_client.errors import APIResponseError

from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_operations.page_registry import (
    NotionPageRegistry,
    canonical_notion_page_id,
    notion_page_id_from_url,
)
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.notion_operations.database_properties import (
    plain_text_from_rich_text_items,
    rich_text_items,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
    task_database_data_source_id_from_tracker_state,
)


DEFAULT_NOTION_API_BASE_URL = "https://api.notion.com"
DEFAULT_NOTION_API_VERSION = "2026-03-11"


@dataclass(frozen=True)
class CreatedTaskDatabasePage:
    notion_page_id: str
    operation_keys: list[str]


@dataclass(frozen=True)
class NotionWriteExecutionResult:
    completed_operation_keys: list[str] = field(default_factory=list)
    captured_page_ids: dict[str, str] = field(default_factory=dict)
    blocked_operation_count: int = 0


class NotionRestClient:
    def __init__(self, access_token: str, base_url: str, notion_version: str) -> None:
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.notion_version = notion_version
        self.client = AsyncClient(
            auth=access_token,
            base_url=self.base_url,
            notion_version=notion_version,
        )

    @classmethod
    def from_environment(cls) -> "NotionRestClient":
        return cls(
            access_token=_notion_rest_access_token_from_environment(),
            base_url=DEFAULT_NOTION_API_BASE_URL,
            notion_version=DEFAULT_NOTION_API_VERSION,
        )

    async def fetch_task_page_content(self, page_id: str) -> str:
        page = await self.fetch_page(page_id)
        markdown = await self.fetch_page_markdown(page_id)
        return _fetched_database_page_content(page, markdown)

    async def fetch_page(self, page_id: str) -> dict[str, Any]:
        return await self._send_json("GET", f"/v1/pages/{page_id}", None)

    async def fetch_database(self, database_id: str) -> dict[str, Any]:
        return await self._send_json("GET", f"/v1/databases/{database_id}", None)

    async def fetch_data_source(self, data_source_id: str) -> dict[str, Any]:
        return await self._send_json("GET", f"/v1/data_sources/{data_source_id}", None)

    async def fetch_page_markdown(self, page_id: str) -> str:
        response = await self._send_json("GET", f"/v1/pages/{page_id}/markdown", None)
        return _markdown_from_sdk_response(response)

    async def query_data_source(self, data_source_url: str, query: str) -> list[dict[str, Any]]:
        return await self.query_data_source_id(_data_source_id_from_url(data_source_url))

    async def query_task_database_rows(self, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.query_data_source_id(
            task_database_data_source_id_from_tracker_state(tracker_state)
        )

    async def query_data_source_id(self, data_source_id: str) -> list[dict[str, Any]]:
        rows = []
        next_cursor = None

        while True:
            body = {"page_size": 100}
            if next_cursor:
                body["start_cursor"] = next_cursor
            response = await self._send_json("POST", f"/v1/data_sources/{data_source_id}/query", body)
            rows.extend(_task_database_rows_from_rest_pages(response.get("results", [])))
            if not response.get("has_more"):
                return rows
            next_cursor = response.get("next_cursor")

    async def execute_write_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        if write_intent.operation_name == "create_page":
            return await self._execute_create_page_intent(write_intent, page_registry)
        if write_intent.operation_name == "replace_page_markdown":
            return await self._execute_replace_page_markdown_intent(write_intent, page_registry)
        if write_intent.operation_name == "update_page_properties":
            return await self._execute_update_page_properties_intent(write_intent, page_registry)
        if write_intent.operation_name == "update_timeline_log":
            return await self._execute_timeline_log_update_intent(write_intent, page_registry)
        if write_intent.operation_name == "append_miscellaneous_context":
            return await self._execute_miscellaneous_context_append_intent(write_intent, page_registry)
        if write_intent.operation_name == "create_synthesis_page":
            return await self._execute_synthesis_page_creation_intent(write_intent, page_registry)
        raise ValueError(f"Notion REST client cannot execute write intent {write_intent.operation_name!r}")

    async def create_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        markdown: str,
    ) -> dict[str, Any]:
        return await self.create_page(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=properties,
            markdown=markdown,
        )

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        content: str,
        operation_key: str,
    ) -> CreatedTaskDatabasePage:
        created_page = await self.create_database_page(
            data_source_id=data_source_id,
            properties=properties,
            markdown=content,
        )
        return CreatedTaskDatabasePage(
            notion_page_id=created_page["id"],
            operation_keys=[operation_key],
        )

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ) -> str:
        await self.update_page_properties(
            page_id=page_id,
            properties={title_property or TASK_DATABASE_TITLE_PROPERTY: title},
        )
        return operation_key

    async def execute_command_result(self, command_result: TrackerCommandResult) -> NotionWriteExecutionResult:
        if command_result.page_registry is None:
            raise ValueError("REST write execution requires a page registry")

        executed_operation_keys = []
        captured_page_ids = {}
        for write_intent in command_result.write_intents:
            write_result = await self.execute_write_intent(write_intent, command_result.page_registry)
            executed_operation_keys.append(write_result["operation_key"])
            if write_result.get("captured_page_key") is not None:
                captured_page_ids[write_result["captured_page_key"]] = write_result["captured_page_id"]

        return NotionWriteExecutionResult(
            completed_operation_keys=executed_operation_keys,
            captured_page_ids=captured_page_ids,
        )

    async def _execute_create_page_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        arguments = write_intent.arguments
        created_page = await self.create_page(
            parent=_rest_parent_from_page_key(arguments.get("parent_page_key"), page_registry),
            properties={"title": arguments["title"]},
            markdown=arguments.get("markdown", ""),
        )
        return _write_result(write_intent.operation_key, arguments["local_page_key"], created_page)

    async def _execute_replace_page_markdown_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        await self.replace_page_content(
            page_id=page_registry.page_id(_required_target_page_key(write_intent)),
            markdown=write_intent.arguments["markdown"],
        )
        return _write_result(write_intent.operation_key)

    async def _execute_update_page_properties_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        updated_page = await self.update_page_properties(
            page_id=page_registry.page_id(_required_target_page_key(write_intent)),
            properties=write_intent.arguments["properties"],
            page_registry=page_registry,
        )
        return _write_result(write_intent.operation_key, None, updated_page)

    async def _execute_timeline_log_update_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        page_id = page_registry.page_id(_required_target_page_key(write_intent))
        arguments = write_intent.arguments
        if "old_timeline_section_markdown" in arguments:
            await self.replace_markdown_section(
                page_id=page_id,
                old_markdown=arguments["old_timeline_section_markdown"],
                new_markdown=arguments["new_timeline_section_markdown"],
            )
        else:
            await self.insert_markdown_after_anchor(
                page_id=page_id,
                anchor_markdown=f"## {arguments['timeline_log_heading']}",
                inserted_markdown=arguments["timeline_section_markdown"],
            )
        return _write_result(write_intent.operation_key)

    async def _execute_miscellaneous_context_append_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        dated_page = write_intent.arguments["dated_page"]
        dated_page_key = dated_page["local_page_key"]
        if not _page_has_id(page_registry, dated_page_key):
            return await self._execute_create_page_intent(
                NotionWriteIntent(
                    operation_key=f"create:{dated_page_key}",
                    operation_name="create_page",
                    target_page_key=None,
                    arguments={
                        "local_page_key": dated_page_key,
                        "title": dated_page["title"],
                        "parent_page_key": dated_page.get("parent_page_key"),
                        "markdown": write_intent.arguments["dated_page_markdown"],
                    },
                ),
                page_registry,
            )

        await self.replace_page_content(
            page_registry.page_id(dated_page_key),
            write_intent.arguments["dated_page_markdown"],
        )
        if write_intent.arguments.get("root_page_markdown") is not None:
            await self.replace_page_content(
                page_registry.page_id(write_intent.arguments["root_page_key"]),
                write_intent.arguments["root_page_markdown"],
            )
        return _write_result(write_intent.operation_key)

    async def _execute_synthesis_page_creation_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        synthesis_page = write_intent.arguments["page"]
        synthesis_page_key = synthesis_page["local_page_key"]
        if not _page_has_id(page_registry, synthesis_page_key):
            return await self._execute_create_page_intent(
                NotionWriteIntent(
                    operation_key=f"create:{synthesis_page_key}",
                    operation_name="create_page",
                    target_page_key=None,
                    arguments={
                        "local_page_key": synthesis_page_key,
                        "title": synthesis_page["title"],
                        "parent_page_key": synthesis_page.get("parent_page_key"),
                        "markdown": write_intent.arguments["markdown"],
                    },
                ),
                page_registry,
            )

        await self.replace_page_content(
            page_registry.page_id(synthesis_page_key),
            write_intent.arguments["markdown"],
        )
        if write_intent.arguments.get("root_page_markdown") is not None:
            await self.replace_page_content(
                page_registry.page_id(write_intent.arguments["root_page_key"]),
                write_intent.arguments["root_page_markdown"],
            )
        return _write_result(write_intent.operation_key)

    async def create_page(
        self,
        parent: dict[str, Any],
        properties: dict[str, Any],
        markdown: str,
    ) -> dict[str, Any]:
        return await self._send_json(
            "POST",
            "/v1/pages",
            {
                "parent": parent,
                "properties": _rest_database_properties(properties, page_registry=None),
                "markdown": markdown,
            },
        )

    async def update_page_properties(
        self,
        page_id: str,
        properties: dict[str, Any],
        page_registry: NotionPageRegistry | None = None,
    ) -> dict[str, Any]:
        return await self._send_json(
            "PATCH",
            f"/v1/pages/{page_id}",
            {"properties": _rest_database_properties(properties, page_registry)},
        )

    async def replace_page_content(
        self,
        page_id: str,
        markdown: str,
    ) -> None:
        await self.replace_page_markdown(
            page_id=page_id,
            markdown=markdown,
        )

    async def replace_page_markdown(self, page_id: str, markdown: str) -> None:
        await self._send_json(
            "PATCH",
            f"/v1/pages/{page_id}/markdown",
            {
                "type": "replace_content",
                "replace_content": {"new_str": markdown},
            },
        )

    async def update_page_markdown_content(self, page_id: str, old_markdown: str, new_markdown: str) -> None:
        await self._send_json(
            "PATCH",
            f"/v1/pages/{page_id}/markdown",
            {
                "type": "update_content",
                "update_content": {
                    "content_updates": [
                        {
                            "old_str": old_markdown,
                            "new_str": new_markdown,
                        }
                    ]
                },
            },
        )

    async def insert_markdown_after_anchor(
        self,
        page_id: str,
        anchor_markdown: str,
        inserted_markdown: str,
    ) -> None:
        await self.update_page_markdown_content(
            page_id=page_id,
            old_markdown=anchor_markdown,
            new_markdown=f"{anchor_markdown}\n{inserted_markdown}",
        )

    async def replace_markdown_section(
        self,
        page_id: str,
        old_markdown: str,
        new_markdown: str,
    ) -> None:
        await self.update_page_markdown_content(
            page_id=page_id,
            old_markdown=old_markdown,
            new_markdown=new_markdown,
        )

    async def _send_json(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return await self._send_sdk_request(method, path, body or {})
        except APIResponseError as error:
            raise ValueError(
                _notion_rest_error_message(method, path, error.status, error.body)
            ) from error

    async def _send_sdk_request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        parsed_path = urlparse(path)
        path_parts = parsed_path.path.strip("/").split("/")

        if method == "GET" and path_parts[:2] == ["v1", "pages"] and path_parts[3:] == ["markdown"]:
            return await self.client.pages.retrieve_markdown(page_id=path_parts[2])

        if method == "PATCH" and path_parts[:2] == ["v1", "pages"] and path_parts[3:] == ["markdown"]:
            return await self.client.pages.update_markdown(page_id=path_parts[2], **body)

        if method == "GET" and path_parts[:2] == ["v1", "pages"]:
            return await self.client.pages.retrieve(page_id=path_parts[2])

        if method == "GET" and path_parts[:2] == ["v1", "databases"]:
            return await self.client.databases.retrieve(database_id=path_parts[2])

        if method == "GET" and path_parts[:2] == ["v1", "data_sources"]:
            return await self.client.data_sources.retrieve(data_source_id=path_parts[2])

        if method == "PATCH" and path_parts[:2] == ["v1", "pages"]:
            return await self.client.pages.update(page_id=path_parts[2], **body)

        if method == "POST" and path_parts == ["v1", "pages"]:
            return await self.client.pages.create(**body)

        if method == "POST" and path_parts[:2] == ["v1", "data_sources"] and path_parts[3:] == ["query"]:
            return await self.client.data_sources.query(data_source_id=path_parts[2], **body)

        raise ValueError(f"Unsupported Notion REST SDK request {method} {path}")


def _notion_rest_access_token_from_environment() -> str:
    access_token = os.environ.get("NOTION_API_KEY")
    if access_token:
        return access_token

    raise PermissionError("Set NOTION_API_KEY to the ntn_ Notion integration token before using the REST client.")


def _task_database_rows_from_rest_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _task_database_row_from_rest_page(page)
        for page in pages
    ]


def _task_database_row_from_rest_page(page: dict[str, Any]) -> dict[str, Any]:
    properties = page.get("properties", {})
    return {
        TASK_DATABASE_TITLE_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_TITLE_PROPERTY)),
        TASK_DATABASE_TICKET_ID_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_TICKET_ID_PROPERTY)),
        TASK_DATABASE_PRIORITY_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_PRIORITY_PROPERTY)),
        TASK_DATABASE_STATUS_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_STATUS_PROPERTY)),
        TASK_DATABASE_PARENT_PROPERTY: json.dumps(_relation_urls_from_property(properties.get(TASK_DATABASE_PARENT_PROPERTY))),
        TASK_DATABASE_DEPENDENCIES_PROPERTY: json.dumps(
            _relation_urls_from_property(properties.get(TASK_DATABASE_DEPENDENCIES_PROPERTY))
        ),
        TASK_DATABASE_DEPENDANTS_PROPERTY: json.dumps(
            _relation_urls_from_property(properties.get(TASK_DATABASE_DEPENDANTS_PROPERTY))
        ),
        TASK_DATABASE_DEADLINE_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_DEADLINE_PROPERTY)),
        TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY: _plain_property_value(
            properties.get(TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY)
        ),
        TASK_DATABASE_UNCERTAINTY_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_UNCERTAINTY_PROPERTY)),
        TASK_DATABASE_FRICTION_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_FRICTION_PROPERTY)),
        "url": page.get("url") or f"https://www.notion.so/{canonical_notion_page_id(page['id'])}",
    }


def _rest_database_properties(
    properties: dict[str, Any],
    page_registry: NotionPageRegistry | None,
) -> dict[str, Any]:
    rest_properties = {}
    for property_name, property_value in properties.items():
        if property_name in {"title", TASK_DATABASE_TITLE_PROPERTY}:
            rest_properties[property_name] = {"title": _title_rich_text_items(property_value)}
        elif property_name == TASK_DATABASE_PRIORITY_PROPERTY:
            rest_properties[property_name] = {"select": {"name": str(property_value)}}
        elif property_name == TASK_DATABASE_STATUS_PROPERTY:
            rest_properties[property_name] = {"select": {"name": str(property_value)}}
        elif property_name in {TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY, TASK_DATABASE_UNCERTAINTY_PROPERTY}:
            rest_properties[property_name] = {"select": {"name": str(property_value)}}
        elif property_name == TASK_DATABASE_FRICTION_PROPERTY:
            rest_properties[property_name] = {"select": {"name": str(property_value)}}
        elif property_name == TASK_DATABASE_DEADLINE_PROPERTY:
            rest_properties[property_name] = {"date": None if property_value in {None, ""} else {"start": str(property_value)}}
        elif property_name in {
            TASK_DATABASE_PARENT_PROPERTY,
            TASK_DATABASE_DEPENDENCIES_PROPERTY,
            TASK_DATABASE_DEPENDANTS_PROPERTY,
        }:
            rest_properties[property_name] = {
                "relation": _convert_relation_property_to_notion_page_references(property_value, page_registry)
            }
        else:
            rest_properties[property_name] = property_value
    return rest_properties


def _title_rich_text_items(property_value: Any) -> list[dict[str, Any]]:
    if isinstance(property_value, dict) and "rich_text" in property_value:
        return list(property_value["rich_text"])

    return rich_text_items(str(property_value))


def _plain_property_value(property_value: dict[str, Any] | None) -> str:
    if not property_value:
        return ""

    property_type = property_value.get("type")
    value = property_value.get(property_type)
    if property_type == "title":
        return plain_text_from_rich_text_items(value)
    if property_type == "rich_text":
        return plain_text_from_rich_text_items(value)
    if property_type in {"select", "status"}:
        return "" if value is None else str(value.get("name", ""))
    if property_type == "unique_id":
        return str(value.get("number", ""))
    if property_type == "number":
        return "" if value is None else str(value)
    if property_type == "url":
        return "" if value is None else str(value)
    if property_type == "relation":
        return json.dumps(_relation_urls_from_property(property_value))
    if property_type == "date":
        return "" if value is None else str(value.get("start", ""))

    return "" if value is None else str(value)


def _relation_urls_from_property(property_value: dict[str, Any] | None) -> list[str]:
    if not property_value or property_value.get("type") != "relation":
        return []

    return [
        f"https://www.notion.so/{canonical_notion_page_id(relation['id'])}"
        for relation in property_value.get("relation", [])
    ]


def _convert_relation_property_to_notion_page_references(
    property_value: Any,
    page_registry: NotionPageRegistry | None,
) -> list[dict[str, str]]:
    if property_value is None or property_value == "":
        return []

    page_urls_or_keys = json.loads(property_value) if isinstance(property_value, str) else list(property_value)
    return [
        {"id": _resolve_relation_page_id(page_url_or_key, page_registry)}
        for page_url_or_key in page_urls_or_keys
    ]


def _resolve_relation_page_id(
    page_url_or_key: str,
    page_registry: NotionPageRegistry | None,
) -> str:
    if page_url_or_key.startswith("task:"):
        if page_registry is None:
            raise ValueError(f"Cannot resolve local relation key {page_url_or_key!r} without a page registry")
        return page_registry.page_id(page_url_or_key)

    return notion_page_id_from_url(page_url_or_key)


def _fetched_database_page_content(page: dict[str, Any], markdown: str) -> str:
    return "\n".join(
        [
            "<page>",
            "<properties>",
            json.dumps(_task_database_row_from_rest_page(page)),
            "</properties>",
            "<content>",
            markdown,
            "</content>",
            "</page>",
        ]
    )


def _markdown_from_sdk_response(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ["markdown", "content"]:
            if key in response:
                return str(response[key])
    return str(response)


def _rest_parent_from_page_key(
    parent_page_key: str | None,
    page_registry: NotionPageRegistry,
) -> dict[str, str]:
    if parent_page_key is None:
        raise ValueError("REST page creation requires a parent page key")

    return {
        "type": "page_id",
        "page_id": page_registry.page_id(parent_page_key),
    }


def _required_target_page_key(write_intent: NotionWriteIntent) -> str:
    if write_intent.target_page_key is None:
        raise ValueError(f"Write intent {write_intent.operation_key!r} has no target page key")

    return write_intent.target_page_key


def _page_has_id(page_registry: NotionPageRegistry, page_key: str) -> bool:
    try:
        page_registry.page_id(page_key)
    except ValueError:
        return False

    return True


def _data_source_id_from_url(data_source_url: str) -> str:
    if data_source_url.startswith("collection://"):
        return data_source_url.removeprefix("collection://")
    return data_source_url.rsplit("/", 1)[-1]


def _write_result(
    operation_key: str,
    captured_page_key: str | None = None,
    page: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {"operation_key": operation_key}
    if captured_page_key is not None:
        if page is None:
            raise ValueError(f"Write {operation_key!r} captured a page key but returned no page")
        result["captured_page_key"] = captured_page_key
        result["captured_page_id"] = canonical_notion_page_id(page["id"])
    return result


def _notion_rest_error_message(method: str, path: str, status_code: int | None, error_text: str) -> str:
    permission_hint = _notion_rest_permission_hint(status_code)
    return json.dumps(
        {
            "method": method,
            "path": path,
            "status_code": status_code,
            "error": error_text[:2000],
            "permission_hint": permission_hint,
        },
        indent=2,
        sort_keys=True,
    )


def _notion_rest_permission_hint(status_code: int | None) -> str | None:
    if status_code == 401:
        return "Check that NOTION_API_KEY contains a valid ntn_ integration token."
    if status_code == 403:
        return "Check that the Notion integration can access the page or data source and has read, update, and insert-content capability."
    if status_code == 404:
        return "Check that the target page, block, or data source is shared with the Notion integration."
    return None
