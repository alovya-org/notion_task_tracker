import asyncio
import json

from notion_task_tracker.config import CalendarConfig, ManagedPageUrls, TrackerConfig
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
)
from notion_task_tracker.refresh_notion_task_tracker import (
    refresh_notion_task_tracker,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_TITLE_STRIKETHROUGH_VALUE,
)
from notion_task_tracker.tracked_pages import TrackedPage
from tests.notion_operations.helpers import FakeNotionClient


def test_notion_only_refresh_completes_one_current_notion_lifecycle(
    tmp_path,
    monkeypatch,
):
    notion_client = _CurrentTaskNotionClient([_task_row_with_stale_derived_end()])
    reconciled_task_trees = []

    async def resolve_test_resources(config, notion_client):
        return _resolved_test_resources(config)

    async def record_stale_managed_page_reconciliation(
        task_tree,
        resources,
        notion_client,
    ):
        reconciled_task_trees.append(task_tree)
        return ["replace:ongoing_landing_page"]

    def reject_google_client_construction(*args, **kwargs):
        raise AssertionError("Notion-only refresh must not construct Google clients")

    monkeypatch.setattr(
        "notion_task_tracker.refresh_notion_task_tracker."
        "resolve_tracker_resources",
        resolve_test_resources,
    )
    monkeypatch.setattr(
        "notion_task_tracker.refresh_notion_task_tracker."
        "reconcile_managed_pages_from_current_tree",
        record_stale_managed_page_reconciliation,
    )
    monkeypatch.setattr(
        "notion_task_tracker.refresh_notion_task_tracker."
        "GoogleCalendarClient.from_environment",
        reject_google_client_construction,
    )
    monkeypatch.setattr(
        "notion_task_tracker.refresh_notion_task_tracker."
        "CloudflareGoogleCalendarStateClient.from_environment",
        reject_google_client_construction,
    )

    output_path = tmp_path / "summary.json"
    summary = asyncio.run(refresh_notion_task_tracker(
        tracker_user="notion-only",
        output_path=output_path,
        config=_notion_only_tracker_config(),
        notion_client=notion_client,
    ))

    assert notion_client.queried_data_source_ids == ["data-source-id"]
    assert len(reconciled_task_trees) == 1
    assert summary.notion_operation_keys == [
        "repair:end:task:ALOVYA-1",
        "replace:ongoing_landing_page",
    ]
    assert summary.calendar_operation_keys == []
    assert summary.desired_calendar_event_count == 0
    assert summary.task_count == 1
    assert summary.repair_operation_count == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == (
        summary.to_json_summary()
    )


def test_calendar_configuration_continues_from_the_same_current_notion_tree(
    tmp_path,
    monkeypatch,
):
    notion_client = _CurrentTaskNotionClient([_task_row_with_stale_derived_end()])
    continued_lifecycles = []

    async def resolve_test_resources(config, notion_client):
        return _resolved_test_resources(config)

    async def record_calendar_continuation(**arguments):
        continued_lifecycles.append(arguments)
        return "calendar-summary"

    monkeypatch.setattr(
        "notion_task_tracker.refresh_notion_task_tracker."
        "resolve_tracker_resources",
        resolve_test_resources,
    )
    monkeypatch.setattr(
        "notion_task_tracker.refresh_notion_task_tracker."
        "continue_synchronisation_with_google_calendar",
        record_calendar_continuation,
    )

    result = asyncio.run(refresh_notion_task_tracker(
        tracker_user="calendar-enabled",
        output_path=tmp_path / "summary.json",
        config=_calendar_enabled_tracker_config(),
        notion_client=notion_client,
    ))

    continuation = continued_lifecycles[0]
    assert result == "calendar-summary"
    assert notion_client.queried_data_source_ids == ["data-source-id"]
    assert continuation["current_tasks"].task_tree.tasks["ALOVYA-1"].title == (
        "Scheduled task"
    )
    assert continuation["completed_notion_operations"] == [
        "repair:end:task:ALOVYA-1"
    ]
    assert continuation["resources"].task_data_source_id == "data-source-id"


class _CurrentTaskNotionClient(FakeNotionClient):
    def __init__(self, database_rows):
        super().__init__(database_rows=database_rows)
        self.queried_data_source_ids = []

    async def query_data_source_id(self, data_source_id):
        self.queried_data_source_ids.append(data_source_id)
        return list(self.database_rows)


def _notion_only_tracker_config():
    return TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/parent",
        task_database_url="https://www.notion.so/database",
        pages=ManagedPageUrls(),
        calendar=None,
    )


def _calendar_enabled_tracker_config():
    return TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/parent",
        task_database_url="https://www.notion.so/database",
        pages=ManagedPageUrls(),
        calendar=CalendarConfig(
            calendar_id="calendar-id",
            timezone_name="Europe/London",
        ),
    )


def _resolved_test_resources(config):
    return ResolvedTrackerResources(
        config=config,
        task_database_id="database-id",
        task_data_source_id="data-source-id",
        ongoing_tasks_page=TrackedPage(
            "ongoing_landing_page",
            "Alovya's ongoing tasks",
            "22222222222222222222222222222222",
        ),
        completed_tasks_page=TrackedPage(
            "completed_landing_page",
            "Alovya's completed tasks",
            "33333333333333333333333333333333",
        ),
        ready_priority_page=TrackedPage(
            "ready_priority_page",
            "Alovya's tasks in execution order",
            "44444444444444444444444444444444",
        ),
    )


def _task_row_with_stale_derived_end():
    return {
        "Task page": "[1] Scheduled task",
        TASK_DATABASE_TITLE_STRIKETHROUGH_VALUE: False,
        "Task ID": "1",
        "Priority": "P2",
        "Status": "Active",
        "Parent": [],
        "Dependencies": [],
        "Dependants": [],
        "Deadline": "",
        "Start": "2026-08-03T09:00:00+01:00",
        "End": "",
        "Duration": 1,
        "Duration unit": "Hours",
        "External coordination": "No",
        "Uncertainty": "Low",
        "Friction": "None",
        "url": "https://www.notion.so/11111111111111111111111111111111",
    }
