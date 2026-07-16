"""Initialise one user's tracker from a parent page and task database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.config import ManagedPageUrls, TrackerConfig, write_config
from notion_task_tracker.fixed_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
    ONGOING_LANDING_PAGE_LOCAL_KEY,
    SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
)
from notion_task_tracker.notion_operations.notion_id import canonical_notion_page_id, notion_page_id_from_url
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_END_DATE_TIME_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_START_DATE_TIME_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
    build_task_database_tracker_state,
)


@dataclass(frozen=True)
class TrackerInitialisationResult:
    config_path: Path
    tracker_state_path: Path
    data_source_id: str
    created_page_urls: ManagedPageUrls

    def to_json_summary(self) -> dict[str, Any]:
        return {
            "action_name": "init",
            "config_path": str(self.config_path),
            "tracker_state_path": str(self.tracker_state_path),
            "data_source_id": self.data_source_id,
            "created_page_urls": {
                "ongoing_tasks_url": self.created_page_urls.ongoing_tasks_url,
                "completed_tasks_url": self.created_page_urls.completed_tasks_url,
                "miscellaneous_notes_url": self.created_page_urls.miscellaneous_notes_url,
                "synthesis_notes_url": self.created_page_urls.synthesis_notes_url,
            },
        }


async def initialise_tracker(
    display_name: str,
    ticket_prefix: str,
    parent_page_url: str,
    task_database_url: str,
    config_path: Path,
    tracker_state_path: Path,
    notion_client: NotionRestClient,
) -> TrackerInitialisationResult:
    requested_config = TrackerConfig(
        display_name=display_name,
        ticket_prefix=ticket_prefix,
        parent_page_url=parent_page_url,
        task_database_url=task_database_url,
    )
    requested_config.validate()
    _refuse_to_replace_existing_tracker_files(config_path, tracker_state_path)

    data_source_id = await find_fixed_schema_data_source_id(task_database_url, notion_client)
    created_pages = await _create_managed_pages(display_name, parent_page_url, notion_client)
    configured_tracker = TrackerConfig(
        display_name=display_name,
        ticket_prefix=ticket_prefix,
        parent_page_url=parent_page_url,
        task_database_url=task_database_url,
        pages=_managed_page_urls(created_pages),
    )
    written_config_path = write_config(configured_tracker, config_path)
    tracker_state = _tracker_state_from_configured_pages(
        configured_tracker=configured_tracker,
        data_source_id=data_source_id,
    )
    _write_tracker_state(tracker_state_path, tracker_state)
    return TrackerInitialisationResult(
        config_path=written_config_path,
        tracker_state_path=tracker_state_path,
        data_source_id=data_source_id,
        created_page_urls=configured_tracker.pages,
    )


async def create_tracker_state_from_configured_pages(
    configured_tracker: TrackerConfig,
    tracker_state_path: Path,
    notion_client: NotionRestClient,
) -> dict[str, Any]:
    configured_tracker.validate()
    if tracker_state_path.exists():
        raise FileExistsError(f"Tracker state already exists at {tracker_state_path}")

    data_source_id = await find_fixed_schema_data_source_id(
        configured_tracker.task_database_url,
        notion_client,
    )
    tracker_state = _tracker_state_from_configured_pages(
        configured_tracker=configured_tracker,
        data_source_id=data_source_id,
    )
    _write_tracker_state(tracker_state_path, tracker_state)
    return tracker_state


def _refuse_to_replace_existing_tracker_files(config_path: Path, tracker_state_path: Path) -> None:
    existing_paths = [path for path in (config_path, tracker_state_path) if path.exists()]
    if existing_paths:
        joined_paths = ", ".join(str(path) for path in existing_paths)
        raise FileExistsError(f"Tracker is already initialised at {joined_paths}")


async def find_fixed_schema_data_source_id(
    task_database_url: str,
    notion_client: NotionRestClient,
) -> str:
    database_id = canonical_notion_page_id(notion_page_id_from_url(task_database_url))
    database = await notion_client.fetch_database(database_id)
    data_sources = database.get("data_sources", [])
    if len(data_sources) != 1:
        raise ValueError("The task database must contain exactly one data source")

    data_source_id = canonical_notion_page_id(data_sources[0]["id"])
    data_source = await notion_client.fetch_data_source(data_source_id)
    _validate_fixed_database_schema(data_source.get("properties", {}))
    return data_source_id


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
        TASK_DATABASE_START_DATE_TIME_PROPERTY: "date",
        TASK_DATABASE_END_DATE_TIME_PROPERTY: "date",
        TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY: "select",
        TASK_DATABASE_UNCERTAINTY_PROPERTY: "select",
        TASK_DATABASE_FRICTION_PROPERTY: "select",
    }
    missing_property_names = sorted(expected_property_types.keys() - properties.keys())
    if missing_property_names:
        raise ValueError(
            "The task database is missing required properties: " + ", ".join(missing_property_names)
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


async def _create_managed_pages(
    display_name: str,
    parent_page_url: str,
    notion_client: NotionRestClient,
) -> dict[str, dict[str, Any]]:
    parent_page_id = canonical_notion_page_id(notion_page_id_from_url(parent_page_url))
    page_titles = _managed_page_titles(display_name)
    created_pages = {}
    for local_page_key, title in page_titles.items():
        created_pages[local_page_key] = await notion_client.create_page(
            parent={"type": "page_id", "page_id": parent_page_id},
            properties={"title": title},
            markdown="",
        )
    return created_pages


def _managed_page_titles(display_name: str) -> dict[str, str]:
    return {
        ONGOING_LANDING_PAGE_LOCAL_KEY: f"{display_name}'s ongoing tasks",
        COMPLETED_LANDING_PAGE_LOCAL_KEY: f"{display_name}'s completed tasks",
        MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY: f"{display_name}'s miscellaneous notes",
        SYNTHESIS_NOTES_PAGE_LOCAL_KEY: f"{display_name}'s synthesis notes",
    }


def _managed_page_urls(created_pages: dict[str, dict[str, Any]]) -> ManagedPageUrls:
    return ManagedPageUrls(
        ongoing_tasks_url=created_pages[ONGOING_LANDING_PAGE_LOCAL_KEY]["url"],
        completed_tasks_url=created_pages[COMPLETED_LANDING_PAGE_LOCAL_KEY]["url"],
        miscellaneous_notes_url=created_pages[MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY]["url"],
        synthesis_notes_url=created_pages[SYNTHESIS_NOTES_PAGE_LOCAL_KEY]["url"],
    )


def _tracker_state_from_configured_pages(
    configured_tracker: TrackerConfig,
    data_source_id: str,
) -> dict[str, Any]:
    page_titles = _managed_page_titles(configured_tracker.display_name)
    return {
        "identity": {
            "display_name": configured_tracker.display_name,
            "ticket_prefix": configured_tracker.ticket_prefix,
        },
        "task_database": build_task_database_tracker_state(
            data_source_id=data_source_id,
        ),
        "ongoing_landing_page": _created_page_state(
            ONGOING_LANDING_PAGE_LOCAL_KEY,
            page_titles,
            _required_managed_page_url(
                configured_tracker.pages.ongoing_tasks_url,
                "ongoing_tasks_url",
            ),
        ),
        "completed_landing_page": _created_page_state(
            COMPLETED_LANDING_PAGE_LOCAL_KEY,
            page_titles,
            _required_managed_page_url(
                configured_tracker.pages.completed_tasks_url,
                "completed_tasks_url",
            ),
        ),
        "miscellaneous_notes": {
            "page": _created_page_state(
                MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
                page_titles,
                _required_managed_page_url(
                    configured_tracker.pages.miscellaneous_notes_url,
                    "miscellaneous_notes_url",
                ),
            ),
            "dated_pages": {},
        },
        "synthesis_notes": {
            "page": _created_page_state(
                SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
                page_titles,
                _required_managed_page_url(
                    configured_tracker.pages.synthesis_notes_url,
                    "synthesis_notes_url",
                ),
            ),
            "existing_page_mentions": {},
            "pages": {},
        },
        "tasks": {},
    }


def _created_page_state(
    local_page_key: str,
    page_titles: dict[str, str],
    page_url: str,
) -> dict[str, str | None]:
    return {
        "local_page_key": local_page_key,
        "title": page_titles[local_page_key],
        "notion_page_id": canonical_notion_page_id(notion_page_id_from_url(page_url)),
        "parent_page_key": None,
    }


def _required_managed_page_url(page_url: str | None, field_name: str) -> str:
    if not page_url:
        raise ValueError(f"Configured tracker pages must include {field_name}")

    return page_url


def _write_tracker_state(tracker_state_path: Path, tracker_state: dict[str, Any]) -> None:
    tracker_state_path.parent.mkdir(parents=True, exist_ok=True)
    tracker_state_path.write_text(json.dumps(tracker_state, indent=2, sort_keys=True), encoding="utf-8")
