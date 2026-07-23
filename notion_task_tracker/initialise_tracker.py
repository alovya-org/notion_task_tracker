"""Initialise one user's tracker from a parent page and task database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.config import ManagedPageUrls, TrackerConfig, write_config
from notion_task_tracker.fixed_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    ONGOING_LANDING_PAGE_LOCAL_KEY,
    READY_PRIORITY_PAGE_LOCAL_KEY,
    derive_managed_page_titles,
)
from notion_task_tracker.notion_operations.notion_id import canonical_notion_page_id, notion_page_id_from_url
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    resolve_task_database,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks.database import build_task_database_tracker_state


@dataclass(frozen=True)
class TrackerInitialisationResult:
    config_path: Path
    data_source_id: str
    created_page_urls: ManagedPageUrls

    def to_json_summary(self) -> dict[str, Any]:
        return {
            "action_name": "init",
            "config_path": str(self.config_path),
            "data_source_id": self.data_source_id,
            "created_page_urls": {
                "ongoing_tasks_url": self.created_page_urls.ongoing_tasks_url,
                "completed_tasks_url": self.created_page_urls.completed_tasks_url,
                "ready_priority_page_url": self.created_page_urls.ready_priority_page_url,
            },
        }


async def initialise_tracker(
    display_name: str,
    ticket_prefix: str,
    parent_page_url: str,
    task_database_url: str,
    config_path: Path,
    notion_client: NotionRestClient,
) -> TrackerInitialisationResult:
    requested_config = TrackerConfig(
        display_name=display_name,
        ticket_prefix=ticket_prefix,
        parent_page_url=parent_page_url,
        task_database_url=task_database_url,
    )
    requested_config.validate()
    _refuse_to_replace_existing_config(config_path)

    task_database = await resolve_task_database(
        task_database_url,
        notion_client,
    )
    created_pages = await _create_managed_pages(display_name, parent_page_url, notion_client)
    configured_tracker = TrackerConfig(
        display_name=display_name,
        ticket_prefix=ticket_prefix,
        parent_page_url=parent_page_url,
        task_database_url=task_database_url,
        pages=_managed_page_urls(created_pages),
    )
    written_config_path = write_config(configured_tracker, config_path)
    return TrackerInitialisationResult(
        config_path=written_config_path,
        data_source_id=task_database.data_source_id,
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

    task_database = await resolve_task_database(
        configured_tracker.task_database_url,
        notion_client,
    )
    tracker_state = _tracker_state_from_configured_pages(
        configured_tracker=configured_tracker,
        data_source_id=task_database.data_source_id,
    )
    _write_tracker_state(tracker_state_path, tracker_state)
    return tracker_state


def add_configured_ready_priority_page_to_tracker_state(
    tracker_state: dict[str, Any],
    configured_tracker: TrackerConfig,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    page_titles = derive_managed_page_titles(configured_tracker.display_name)
    updated_tracker_state["ready_priority_page"] = _created_page_state(
        READY_PRIORITY_PAGE_LOCAL_KEY,
        page_titles,
        _required_managed_page_url(
            configured_tracker.pages.ready_priority_page_url,
            "ready_priority_page_url",
        ),
    )
    return updated_tracker_state


def _refuse_to_replace_existing_config(config_path: Path) -> None:
    if config_path.exists():
        raise FileExistsError(f"Tracker is already initialised at {config_path}")


async def _create_managed_pages(
    display_name: str,
    parent_page_url: str,
    notion_client: NotionRestClient,
) -> dict[str, dict[str, Any]]:
    parent_page_id = canonical_notion_page_id(notion_page_id_from_url(parent_page_url))
    page_titles = derive_managed_page_titles(display_name)
    created_pages = {}
    for local_page_key, title in page_titles.items():
        created_pages[local_page_key] = await notion_client.create_page(
            parent={"type": "page_id", "page_id": parent_page_id},
            properties={"title": title},
            markdown="",
        )
    return created_pages


def _managed_page_urls(created_pages: dict[str, dict[str, Any]]) -> ManagedPageUrls:
    return ManagedPageUrls(
        ongoing_tasks_url=created_pages[ONGOING_LANDING_PAGE_LOCAL_KEY]["url"],
        completed_tasks_url=created_pages[COMPLETED_LANDING_PAGE_LOCAL_KEY]["url"],
        ready_priority_page_url=created_pages[READY_PRIORITY_PAGE_LOCAL_KEY]["url"],
    )


def _tracker_state_from_configured_pages(
    configured_tracker: TrackerConfig,
    data_source_id: str,
) -> dict[str, Any]:
    page_titles = derive_managed_page_titles(configured_tracker.display_name)
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
        "ready_priority_page": _created_page_state(
            READY_PRIORITY_PAGE_LOCAL_KEY,
            page_titles,
            _required_managed_page_url(
                configured_tracker.pages.ready_priority_page_url,
                "ready_priority_page_url",
            ),
        ),
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
