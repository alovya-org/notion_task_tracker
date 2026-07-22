import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from notion_task_tracker.config import ManagedPageUrls, TrackerConfig, load_config
from notion_task_tracker.initialise_tracker import (
    add_configured_ready_priority_page_to_tracker_state,
    initialise_tracker,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
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


def test_initialise_tracker_creates_managed_pages_and_writes_local_configuration(tmp_path: Path) -> None:
    notion_client = _NotionInitialisationClient()
    config_path = tmp_path / "config.toml"
    tracker_state_path = tmp_path / "notion_tasks_tree.json"

    result = asyncio.run(
        initialise_tracker(
            display_name="Alovya",
            ticket_prefix="ALOVYA",
            parent_page_url="https://www.notion.so/tracker-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            config_path=config_path,
            tracker_state_path=tracker_state_path,
            notion_client=notion_client,
        )
    )

    config = load_config(config_path)
    tracker_state = json.loads(tracker_state_path.read_text(encoding="utf-8"))
    assert [created_page["properties"]["title"] for created_page in notion_client.created_pages] == [
        "Alovya's ongoing tasks",
        "Alovya's completed tasks",
        "Alovya's tasks in execution order",
        "Alovya's miscellaneous notes",
        "Alovya's synthesis notes",
    ]
    assert all(
        created_page["parent"] == {
            "type": "page_id",
            "page_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }
        for created_page in notion_client.created_pages
    )
    assert config.pages.ongoing_tasks_url == (
        "https://www.notion.so/created-00000000000000000000000000000001"
    )
    assert config.pages.ready_priority_page_url == (
        "https://www.notion.so/created-00000000000000000000000000000003"
    )
    assert tracker_state["identity"] == {"display_name": "Alovya", "ticket_prefix": "ALOVYA"}
    assert tracker_state["task_database"]["data_source_id"] == "cccccccccccccccccccccccccccccccc"
    assert tracker_state["ongoing_landing_page"]["notion_page_id"] == (
        "00000000000000000000000000000001"
    )
    assert tracker_state["ready_priority_page"]["notion_page_id"] == (
        "00000000000000000000000000000003"
    )
    assert tracker_state["tasks"] == {}
    assert result.config_path == config_path
    assert result.tracker_state_path == tracker_state_path


def test_initialise_tracker_rejects_database_without_the_fixed_schema(tmp_path: Path) -> None:
    notion_client = _NotionInitialisationClient(
        properties={TASK_DATABASE_TITLE_PROPERTY: {"type": "title"}}
    )

    with pytest.raises(ValueError, match="missing required properties"):
        asyncio.run(
            initialise_tracker(
                display_name="Alovya",
                ticket_prefix="ALOVYA",
                parent_page_url="https://www.notion.so/tracker-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                config_path=tmp_path / "config.toml",
                tracker_state_path=tmp_path / "notion_tasks_tree.json",
                notion_client=notion_client,
            )
        )

    assert notion_client.created_pages == []


def test_add_configured_ready_priority_page_to_existing_tracker_state() -> None:
    configured_tracker = TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/parent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        pages=ManagedPageUrls(
            ready_priority_page_url=(
                "https://www.notion.so/execution-cccccccccccccccccccccccccccccccc"
            ),
        ),
    )

    tracker_state = add_configured_ready_priority_page_to_tracker_state(
        {"tasks": {}},
        configured_tracker,
    )

    assert tracker_state["ready_priority_page"] == {
        "local_page_key": "ready_priority_page",
        "title": "Alovya's tasks in execution order",
        "notion_page_id": "cccccccccccccccccccccccccccccccc",
        "parent_page_key": None,
    }


def test_initialise_tracker_rejects_incompatible_fixed_property_type(tmp_path: Path) -> None:
    properties = _fixed_database_properties()
    properties[TASK_DATABASE_STATUS_PROPERTY] = {"type": "status"}
    notion_client = _NotionInitialisationClient(properties=properties)

    with pytest.raises(ValueError, match="Status must be select, found status"):
        asyncio.run(
            initialise_tracker(
                display_name="Alovya",
                ticket_prefix="ALOVYA",
                parent_page_url="https://www.notion.so/tracker-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                config_path=tmp_path / "config.toml",
                tracker_state_path=tmp_path / "notion_tasks_tree.json",
                notion_client=notion_client,
            )
        )

    assert notion_client.created_pages == []


class _NotionInitialisationClient:
    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or _fixed_database_properties()
        self.created_pages: list[dict[str, Any]] = []

    async def fetch_database(self, database_id: str) -> dict[str, Any]:
        assert database_id == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        return {"data_sources": [{"id": "cccccccccccccccccccccccccccccccc"}]}

    async def fetch_data_source(self, data_source_id: str) -> dict[str, Any]:
        assert data_source_id == "cccccccccccccccccccccccccccccccc"
        return {"properties": self.properties}

    async def create_page(
        self,
        parent: dict[str, Any],
        properties: dict[str, Any],
        markdown: str,
    ) -> dict[str, Any]:
        page_number = len(self.created_pages) + 1
        self.created_pages.append(
            {"parent": parent, "properties": properties, "markdown": markdown}
        )
        return {
            "id": f"0000000000000000000000000000000{page_number}",
            "url": f"https://www.notion.so/created-0000000000000000000000000000000{page_number}",
        }


def _fixed_database_properties() -> dict[str, Any]:
    return {
        TASK_DATABASE_TITLE_PROPERTY: {"type": "title"},
        TASK_DATABASE_TICKET_ID_PROPERTY: {"type": "unique_id"},
        TASK_DATABASE_PRIORITY_PROPERTY: {"type": "select"},
        TASK_DATABASE_STATUS_PROPERTY: {"type": "select"},
        TASK_DATABASE_PARENT_PROPERTY: {"type": "relation"},
        TASK_DATABASE_DEPENDENCIES_PROPERTY: {"type": "relation"},
        TASK_DATABASE_DEPENDANTS_PROPERTY: {"type": "relation"},
        TASK_DATABASE_DEADLINE_PROPERTY: {"type": "date"},
        TASK_DATABASE_START_PROPERTY: {"type": "date"},
        TASK_DATABASE_END_PROPERTY: {"type": "date"},
        TASK_DATABASE_DURATION_PROPERTY: {"type": "number"},
        TASK_DATABASE_DURATION_UNIT_PROPERTY: {"type": "select"},
        TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY: {"type": "select"},
        TASK_DATABASE_UNCERTAINTY_PROPERTY: {"type": "select"},
        TASK_DATABASE_FRICTION_PROPERTY: {"type": "select"},
    }
