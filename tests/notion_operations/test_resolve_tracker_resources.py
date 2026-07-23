import asyncio
from pathlib import Path
from typing import Any

import pytest

from notion_task_tracker.config import ManagedPageUrls, TrackerConfig, write_config
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    resolve_configured_tracker_resources,
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


def test_resolve_configured_tracker_resources_loads_and_validates_every_notion_resource(
    tmp_path: Path,
) -> None:
    config_path = _write_complete_config(tmp_path)
    notion_client = _NotionResourceClient()

    resources = asyncio.run(
        resolve_configured_tracker_resources(notion_client, config_path)
    )

    assert resources.config.ticket_prefix == "ALOVYA"
    assert resources.task_database_id == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert resources.task_data_source_id == "cccccccccccccccccccccccccccccccc"
    assert [
        (
            page.local_page_key,
            page.title,
            page.notion_page_id,
        )
        for page in [
            resources.ongoing_tasks_page,
            resources.completed_tasks_page,
            resources.ready_priority_page,
        ]
    ] == [
        (
            "ongoing_landing_page",
            "Alovya's ongoing tasks",
            "11111111111111111111111111111111",
        ),
        (
            "completed_landing_page",
            "Alovya's completed tasks",
            "22222222222222222222222222222222",
        ),
        (
            "ready_priority_page",
            "Alovya's tasks in execution order",
            "33333333333333333333333333333333",
        ),
    ]
    assert notion_client.fetched_database_ids == [
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    ]
    assert notion_client.fetched_data_source_ids == [
        "cccccccccccccccccccccccccccccccc"
    ]


def test_resolve_configured_tracker_resources_requires_every_managed_page_url(
    tmp_path: Path,
) -> None:
    config_path = _write_complete_config(
        tmp_path,
        pages=ManagedPageUrls(
            ongoing_tasks_url=None,
            completed_tasks_url="https://www.notion.so/completed-22222222222222222222222222222222",
            ready_priority_page_url="https://www.notion.so/ready-33333333333333333333333333333333",
        ),
    )

    notion_client = _NotionResourceClient()

    with pytest.raises(
        ValueError,
        match="Configured tracker pages must include ongoing_tasks_url",
    ):
        asyncio.run(
            resolve_configured_tracker_resources(notion_client, config_path)
        )

    assert notion_client.fetched_database_ids == []


def test_resolve_configured_tracker_resources_rejects_multiple_data_sources(
    tmp_path: Path,
) -> None:
    notion_client = _NotionResourceClient(
        data_source_ids=[
            "cccccccccccccccccccccccccccccccc",
            "dddddddddddddddddddddddddddddddd",
        ]
    )

    with pytest.raises(
        ValueError,
        match="task database must contain exactly one data source",
    ):
        asyncio.run(
            resolve_configured_tracker_resources(
                notion_client,
                _write_complete_config(tmp_path),
            )
        )

    assert notion_client.fetched_data_source_ids == []


def _write_complete_config(
    tmp_path: Path,
    pages: ManagedPageUrls | None = None,
) -> Path:
    return write_config(
        TrackerConfig(
            display_name="Alovya",
            ticket_prefix="ALOVYA",
            parent_page_url="https://www.notion.so/tracker-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            pages=pages or ManagedPageUrls(
                ongoing_tasks_url="https://www.notion.so/ongoing-11111111111111111111111111111111",
                completed_tasks_url="https://www.notion.so/completed-22222222222222222222222222222222",
                ready_priority_page_url="https://www.notion.so/ready-33333333333333333333333333333333",
            ),
        ),
        tmp_path / "config.toml",
    )


class _NotionResourceClient:
    def __init__(self, data_source_ids: list[str] | None = None) -> None:
        self.data_source_ids = data_source_ids or [
            "cccccccccccccccccccccccccccccccc"
        ]
        self.fetched_database_ids: list[str] = []
        self.fetched_data_source_ids: list[str] = []

    async def fetch_database(self, database_id: str) -> dict[str, Any]:
        self.fetched_database_ids.append(database_id)
        return {
            "data_sources": [
                {"id": data_source_id}
                for data_source_id in self.data_source_ids
            ]
        }

    async def fetch_data_source(self, data_source_id: str) -> dict[str, Any]:
        self.fetched_data_source_ids.append(data_source_id)
        return {"properties": _fixed_database_properties()}


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
