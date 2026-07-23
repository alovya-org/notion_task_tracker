import asyncio

import pytest

from notion_task_tracker.config import CalendarConfig, ManagedPageUrls, TrackerConfig
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import CalendarEventChanges
from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    GoogleCalendarEventLedgerEntry,
    GoogleCalendarSynchronisationState,
)
from notion_task_tracker.google_calendar_sync.synchronise_notion_task_tracker_with_google_calendar import (
    synchronise_notion_task_tracker_with_google_calendar,
)
from notion_task_tracker.notion_operations.resolve_tracker_resources import (
    ResolvedTrackerResources,
)
from notion_task_tracker.tasks.database import TASK_DATABASE_TITLE_STRIKETHROUGH_VALUE
from notion_task_tracker.tracked_pages import TrackedPage
from tests.notion_operations.helpers import FakeNotionClient


def test_google_changes_mutate_the_one_current_tree_before_reconciliation_and_projection(
    tmp_path,
    monkeypatch,
):
    notion_client = _CurrentTaskNotionClient([_scheduled_task_row()])
    calendar_client = _RecordingCalendarClient([_moved_owned_event()])
    state_client = _RecordingCalendarStateClient()
    reconciled_starts = []

    async def record_managed_page_reconciliation(
        task_tree,
        task_data_source_id,
        ready_priority_page,
        notion_client,
    ):
        reconciled_starts.append(task_tree.tasks["ALOVYA-1"].start)
        return ["reconcile:managed_pages"]

    _use_resolved_test_resources(monkeypatch)
    monkeypatch.setattr(
        "notion_task_tracker.google_calendar_sync."
        "synchronise_notion_task_tracker_with_google_calendar."
        "_reconcile_managed_pages_from_current_tree",
        record_managed_page_reconciliation,
    )

    summary = asyncio.run(synchronise_notion_task_tracker_with_google_calendar(
        tracker_user="al0vya",
        output_path=tmp_path / "summary.json",
        config=_tracker_config(),
        notion_client=notion_client,
        google_calendar_client=calendar_client,
        google_calendar_state_client=state_client,
    ))

    assert notion_client.queried_data_source_ids == ["data-source-id"]
    assert reconciled_starts == ["2026-08-04T13:00:00+01:00"]
    assert calendar_client.created_events[0]["start"]["dateTime"] == (
        "2026-08-04T13:00:00+01:00"
    )
    assert calendar_client.created_events[0]["end"]["dateTime"] == (
        "2026-08-04T15:30:00+01:00"
    )
    assert state_client.operations[-1] == (
        "advance_cursor",
        "current-cursor",
        "next-cursor",
    )
    assert summary.notion_operation_keys == [
        "update_schedule:task:ALOVYA-1",
        "reconcile:managed_pages",
    ]
    assert summary.calendar_operation_keys == ["create:calendar_event:ALOVYA-1"]
    assert summary.warnings == []
    assert summary.recovered_expired_google_change_cursor is False


@pytest.mark.parametrize("failed_boundary", ["notion", "calendar"])
def test_failed_remote_operation_leaves_the_google_cursor_unadvanced(
    failed_boundary,
    tmp_path,
    monkeypatch,
):
    notion_client = _CurrentTaskNotionClient(
        [_scheduled_task_row()],
        fail_writes=failed_boundary == "notion",
    )
    calendar_client = _RecordingCalendarClient(
        [_moved_owned_event()],
        fail_creates=failed_boundary == "calendar",
    )
    state_client = _RecordingCalendarStateClient()

    _use_resolved_test_resources(monkeypatch)
    monkeypatch.setattr(
        "notion_task_tracker.google_calendar_sync."
        "synchronise_notion_task_tracker_with_google_calendar."
        "_reconcile_managed_pages_from_current_tree",
        _complete_no_managed_page_operations,
    )

    with pytest.raises(RuntimeError, match=f"{failed_boundary} operation failed"):
        asyncio.run(synchronise_notion_task_tracker_with_google_calendar(
            tracker_user="al0vya",
            output_path=tmp_path / "summary.json",
            config=_tracker_config(),
            notion_client=notion_client,
            google_calendar_client=calendar_client,
            google_calendar_state_client=state_client,
        ))

    assert not [
        operation
        for operation in state_client.operations
        if operation[0] == "advance_cursor"
    ]


def test_expired_cursor_rebuilds_the_ledger_and_reports_recovery(
    tmp_path,
    monkeypatch,
):
    notion_client = _CurrentTaskNotionClient([_scheduled_task_row()])
    calendar_client = _RecordingCalendarClient([], expire_current_cursor=True)
    state_client = _RecordingCalendarStateClient(
        event_ledger=[
            GoogleCalendarEventLedgerEntry(
                google_event_id="deleted-by-ntt",
                ntt_task_id="ALOVYA-1",
                lifecycle_state="deleted_by_ntt",
            )
        ]
    )

    _use_resolved_test_resources(monkeypatch)
    monkeypatch.setattr(
        "notion_task_tracker.google_calendar_sync."
        "synchronise_notion_task_tracker_with_google_calendar."
        "_reconcile_managed_pages_from_current_tree",
        _complete_no_managed_page_operations,
    )

    summary = asyncio.run(synchronise_notion_task_tracker_with_google_calendar(
        tracker_user="al0vya",
        output_path=tmp_path / "summary.json",
        config=_tracker_config(),
        notion_client=notion_client,
        google_calendar_client=calendar_client,
        google_calendar_state_client=state_client,
    ))

    assert calendar_client.fetched_cursors == ["current-cursor", None]
    assert ("replace_ledger", []) in state_client.operations
    assert not [
        call
        for call in notion_client.calls
        if call.operation_key == "update_schedule:task:ALOVYA-1"
    ]
    assert summary.recovered_expired_google_change_cursor is True


async def _complete_no_managed_page_operations(
    task_tree,
    task_data_source_id,
    ready_priority_page,
    notion_client,
):
    return []


def _use_resolved_test_resources(monkeypatch):
    async def resolve_test_resources(config, notion_client):
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

    monkeypatch.setattr(
        "notion_task_tracker.google_calendar_sync."
        "synchronise_notion_task_tracker_with_google_calendar.resolve_tracker_resources",
        resolve_test_resources,
    )


class _CurrentTaskNotionClient(FakeNotionClient):
    def __init__(self, database_rows, fail_writes=False):
        super().__init__(database_rows=database_rows)
        self.queried_data_source_ids = []
        self.fail_writes = fail_writes

    async def query_data_source_id(self, data_source_id):
        self.queried_data_source_ids.append(data_source_id)
        return list(self.database_rows)

    async def execute_command_result(self, command_result):
        if self.fail_writes:
            raise RuntimeError("notion operation failed")
        return await super().execute_command_result(command_result)


class _RecordingCalendarClient:
    def __init__(self, changed_events, fail_creates=False, expire_current_cursor=False):
        self.changed_events = changed_events
        self.fail_creates = fail_creates
        self.expire_current_cursor = expire_current_cursor
        self.fetched_cursors = []
        self.created_events = []

    async def fetch_calendar_event_changes(self, sync_token=None):
        from notion_task_tracker.google_calendar_sync.call_google_calendar_api import (
            GoogleCalendarSyncTokenExpiredError,
        )

        self.fetched_cursors.append(sync_token)
        if self.expire_current_cursor and sync_token is not None:
            raise GoogleCalendarSyncTokenExpiredError
        return CalendarEventChanges(
            events=list(self.changed_events),
            next_sync_token="next-cursor",
        )

    async def list_all_calendar_events(self, query):
        return []

    async def create_calendar_event(self, event):
        if self.fail_creates:
            raise RuntimeError("calendar operation failed")
        self.created_events.append(event)
        return {"id": "created-event"}

    async def replace_calendar_event(self, event_id, event):
        raise AssertionError("No event should be replaced")

    async def delete_calendar_event(self, event_id):
        raise AssertionError("No event should be deleted")


class _RecordingCalendarStateClient:
    def __init__(self, event_ledger=None):
        self.event_ledger = list(event_ledger or [])
        self.operations = []

    async def read_google_calendar_synchronisation_state(self, tracker_user, calendar_id):
        return GoogleCalendarSynchronisationState(
            google_change_cursor="current-cursor",
            event_ledger=self.event_ledger,
        )

    async def record_active_google_calendar_event(
        self,
        tracker_user,
        calendar_id,
        google_event_id,
        ntt_task_id,
    ):
        self.operations.append(("record_active", google_event_id, ntt_task_id))

    async def delete_google_calendar_event_mapping(
        self,
        tracker_user,
        calendar_id,
        google_event_id,
        ntt_task_id,
    ):
        self.operations.append(("delete_mapping", google_event_id, ntt_task_id))

    async def replace_google_calendar_event_ledger_snapshot(
        self,
        tracker_user,
        calendar_id,
        active_events,
    ):
        self.operations.append(("replace_ledger", active_events))

    async def mark_google_calendar_event_deleted_by_ntt(
        self,
        tracker_user,
        calendar_id,
        google_event_id,
        ntt_task_id,
    ):
        self.operations.append(("mark_deleted_by_ntt", google_event_id, ntt_task_id))

    async def advance_google_calendar_change_cursor(
        self,
        tracker_user,
        calendar_id,
        previous_google_change_cursor,
        next_google_change_cursor,
    ):
        self.operations.append((
            "advance_cursor",
            previous_google_change_cursor,
            next_google_change_cursor,
        ))


def _tracker_config():
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


def _scheduled_task_row():
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
        "End": "2026-08-03T10:00:00+01:00",
        "Duration": 1,
        "Duration unit": "Hours",
        "External coordination": "No",
        "Uncertainty": "Low",
        "Friction": "None",
        "url": "https://www.notion.so/11111111111111111111111111111111",
    }


def _moved_owned_event():
    return {
        "id": "owned-event",
        "start": {"dateTime": "2026-08-04T13:00:00+01:00"},
        "end": {"dateTime": "2026-08-04T15:30:00+01:00"},
        "extendedProperties": {
            "private": {
                "ntt_tracker": "ALOVYA",
                "ntt_task_id": "ALOVYA-1",
            }
        },
    }
