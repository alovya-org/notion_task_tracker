"""Resolve one command's configured Notion resources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.config import TrackerConfig, load_config
from notion_task_tracker.fixed_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
    ONGOING_LANDING_PAGE_LOCAL_KEY,
    READY_PRIORITY_PAGE_LOCAL_KEY,
    SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
    derive_managed_page_titles,
)
from notion_task_tracker.notion_operations.notion_id import (
    canonical_notion_page_id,
    notion_page_id_from_url,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
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
from notion_task_tracker.tracked_pages import TrackedPage


@dataclass(frozen=True)
class ResolvedTrackerResources:
    config: TrackerConfig
    task_database_id: str
    task_data_source_id: str
    ongoing_tasks_page: TrackedPage
    completed_tasks_page: TrackedPage
    ready_priority_page: TrackedPage
    miscellaneous_notes_page: TrackedPage
    synthesis_notes_page: TrackedPage


@dataclass(frozen=True)
class ResolvedTaskDatabase:
    database_id: str
    data_source_id: str


async def resolve_configured_tracker_resources(
    notion_client: NotionRestClient,
    config_path: str | Path | None = None,
) -> ResolvedTrackerResources:
    config = load_config(config_path)
    page_titles = derive_managed_page_titles(config.display_name)
    ongoing_tasks_page = _resolve_managed_page(
        ONGOING_LANDING_PAGE_LOCAL_KEY,
        page_titles,
        config.pages.ongoing_tasks_url,
        "ongoing_tasks_url",
    )
    completed_tasks_page = _resolve_managed_page(
        COMPLETED_LANDING_PAGE_LOCAL_KEY,
        page_titles,
        config.pages.completed_tasks_url,
        "completed_tasks_url",
    )
    ready_priority_page = _resolve_managed_page(
        READY_PRIORITY_PAGE_LOCAL_KEY,
        page_titles,
        config.pages.ready_priority_page_url,
        "ready_priority_page_url",
    )
    miscellaneous_notes_page = _resolve_managed_page(
        MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
        page_titles,
        config.pages.miscellaneous_notes_url,
        "miscellaneous_notes_url",
    )
    synthesis_notes_page = _resolve_managed_page(
        SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
        page_titles,
        config.pages.synthesis_notes_url,
        "synthesis_notes_url",
    )
    task_database = await resolve_task_database(
        config.task_database_url,
        notion_client,
    )
    return ResolvedTrackerResources(
        config=config,
        task_database_id=task_database.database_id,
        task_data_source_id=task_database.data_source_id,
        ongoing_tasks_page=ongoing_tasks_page,
        completed_tasks_page=completed_tasks_page,
        ready_priority_page=ready_priority_page,
        miscellaneous_notes_page=miscellaneous_notes_page,
        synthesis_notes_page=synthesis_notes_page,
    )


async def resolve_task_database(
    task_database_url: str,
    notion_client: NotionRestClient,
) -> ResolvedTaskDatabase:
    task_database_id = canonical_notion_page_id(
        notion_page_id_from_url(task_database_url)
    )
    database = await notion_client.fetch_database(task_database_id)
    data_sources = database.get("data_sources", [])
    if len(data_sources) != 1:
        raise ValueError("The task database must contain exactly one data source")

    task_data_source_id = canonical_notion_page_id(data_sources[0]["id"])
    data_source = await notion_client.fetch_data_source(task_data_source_id)
    _validate_fixed_database_schema(data_source.get("properties", {}))
    return ResolvedTaskDatabase(
        database_id=task_database_id,
        data_source_id=task_data_source_id,
    )


def _resolve_managed_page(
    local_page_key: str,
    page_titles: dict[str, str],
    page_url: str | None,
    config_field_name: str,
) -> TrackedPage:
    if not page_url:
        raise ValueError(f"Configured tracker pages must include {config_field_name}")

    return TrackedPage(
        local_page_key=local_page_key,
        title=page_titles[local_page_key],
        notion_page_id=canonical_notion_page_id(notion_page_id_from_url(page_url)),
    )


def _validate_fixed_database_schema(properties: dict[str, Any]) -> None:
    expected_property_types = {
        TASK_DATABASE_TITLE_PROPERTY: "title",
        TASK_DATABASE_TICKET_ID_PROPERTY: "unique_id",
        TASK_DATABASE_PRIORITY_PROPERTY: "select",
        TASK_DATABASE_STATUS_PROPERTY: "select",
        TASK_DATABASE_PARENT_PROPERTY: "relation",
        TASK_DATABASE_DEPENDENCIES_PROPERTY: "relation",
        TASK_DATABASE_DEPENDANTS_PROPERTY: "relation",
        TASK_DATABASE_DEADLINE_PROPERTY: "date",
        TASK_DATABASE_START_PROPERTY: "date",
        TASK_DATABASE_END_PROPERTY: "date",
        TASK_DATABASE_DURATION_PROPERTY: "number",
        TASK_DATABASE_DURATION_UNIT_PROPERTY: "select",
        TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY: "select",
        TASK_DATABASE_UNCERTAINTY_PROPERTY: "select",
        TASK_DATABASE_FRICTION_PROPERTY: "select",
    }
    missing_property_names = sorted(expected_property_types.keys() - properties.keys())
    if missing_property_names:
        raise ValueError(
            "The task database is missing required properties: "
            + ", ".join(missing_property_names)
        )

    incorrectly_typed_properties = [
        f"{property_name} must be {expected_type}, found {properties[property_name].get('type') or 'unknown'}"
        for property_name, expected_type in expected_property_types.items()
        if properties[property_name].get("type") != expected_type
    ]
    if incorrectly_typed_properties:
        raise ValueError(
            "The task database has incompatible property types: "
            + "; ".join(incorrectly_typed_properties)
        )
