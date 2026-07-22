from __future__ import annotations

import asyncio

import pytest

from notion_task_tracker.config import CalendarConfig, ManagedPageUrls, TrackerConfig
from notion_task_tracker.google_calendar import CalendarEventChanges
from notion_task_tracker.calendar_sync_state import CalendarChannelStatus
from notion_task_tracker.register_google_calendar_watch import (
    ensure_google_calendar_watch_is_active,
    register_google_calendar_watch,
)


def test_registers_google_watch_identity_and_initial_sync_token_in_durable_state():
    google_calendar_client = _RecordingGoogleCalendarClient()
    calendar_sync_state_client = _RecordingCalendarSyncStateClient()

    registration = asyncio.run(register_google_calendar_watch(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        channel_id="channel-one",
        channel_token="channel-secret",
        config=_configured_tracker(),
        google_calendar_client=google_calendar_client,
        calendar_sync_state_client=calendar_sync_state_client,
    ))

    assert registration.channel_id == "channel-one"
    assert registration.resource_id == "resource-one"
    assert registration.expires_at == 1786000000000
    assert google_calendar_client.watched_channel == {
        "id": "channel-one",
        "type": "web_hook",
        "address": "https://worker.example/google-calendar-notifications",
        "token": "channel-secret",
    }
    assert calendar_sync_state_client.registered_channel == {
        "channel_id": "channel-one",
        "tracker_user": "al0vya",
        "calendar_id": "calendar@example.com",
        "resource_id": "resource-one",
        "channel_token": "channel-secret",
        "sync_token": "initial-sync-token",
        "expires_at": 1786000000000,
    }


def test_refuses_a_google_watch_response_for_another_channel():
    google_calendar_client = _RecordingGoogleCalendarClient(returned_channel_id="wrong-channel")

    with pytest.raises(ValueError) as error:
        asyncio.run(register_google_calendar_watch(
            tracker_user="al0vya",
            notification_url="https://worker.example/google-calendar-notifications",
            channel_id="channel-one",
            channel_token="channel-secret",
            config=_configured_tracker(),
            google_calendar_client=google_calendar_client,
            calendar_sync_state_client=_RecordingCalendarSyncStateClient(),
        ))

    assert str(error.value) == (
        "Google Calendar watch response did not preserve the requested channel id"
    )


def test_keeps_a_watch_that_remains_active_beyond_the_renewal_window():
    google_calendar_client = _RecordingGoogleCalendarClient()
    calendar_sync_state_client = _RecordingCalendarSyncStateClient(
        current_channel=CalendarChannelStatus(
            channel_id="current-channel",
            resource_id="current-resource",
            expires_at=1_800_000,
            sync_token="current-sync-token",
        ),
    )

    maintenance = asyncio.run(ensure_google_calendar_watch_is_active(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        renew_within_milliseconds=500_000,
        config=_configured_tracker(),
        google_calendar_client=google_calendar_client,
        calendar_sync_state_client=calendar_sync_state_client,
    ))

    assert maintenance.registered_replacement is False
    assert maintenance.channel_id == "current-channel"
    assert google_calendar_client.watched_channel is None


def test_replaces_an_expired_watch_and_requests_incremental_catch_up():
    calendar_sync_state_client = _RecordingCalendarSyncStateClient(
        current_channel=CalendarChannelStatus(
            channel_id="expired-channel",
            resource_id="expired-resource",
            expires_at=900_000,
            sync_token="last-delivered-sync-token",
        ),
    )

    maintenance = asyncio.run(ensure_google_calendar_watch_is_active(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        renew_within_milliseconds=500_000,
        config=_configured_tracker(),
        google_calendar_client=_RecordingGoogleCalendarClient(returned_channel_id=None),
        calendar_sync_state_client=calendar_sync_state_client,
    ))

    assert maintenance.registered_replacement is True
    assert maintenance.catch_up_sync_token == "last-delivered-sync-token"


def test_renews_a_nearly_expired_watch_without_fetching_calendar_events():
    google_calendar_client = _RecordingGoogleCalendarClient(returned_channel_id=None)
    calendar_sync_state_client = _RecordingCalendarSyncStateClient(
        current_channel=CalendarChannelStatus(
            channel_id="current-channel",
            resource_id="current-resource",
            expires_at=1_400_000,
            sync_token="current-sync-token",
        ),
    )

    maintenance = asyncio.run(ensure_google_calendar_watch_is_active(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        renew_within_milliseconds=500_000,
        config=_configured_tracker(),
        google_calendar_client=google_calendar_client,
        calendar_sync_state_client=calendar_sync_state_client,
    ))

    assert maintenance.registered_replacement is True
    assert maintenance.catch_up_sync_token is None
    assert google_calendar_client.change_fetch_count == 0
    assert calendar_sync_state_client.registered_channel["sync_token"] == "current-sync-token"


class _RecordingGoogleCalendarClient:
    def __init__(self, returned_channel_id: str | None = "channel-one") -> None:
        self.returned_channel_id = returned_channel_id
        self.watched_channel = None
        self.change_fetch_count = 0

    async def fetch_calendar_event_changes(self):
        self.change_fetch_count += 1
        return CalendarEventChanges(events=[], next_sync_token="initial-sync-token")

    async def watch_calendar_events(self, channel):
        self.watched_channel = channel
        return {
            "id": self.returned_channel_id or channel["id"],
            "resourceId": "resource-one",
            "expiration": "1786000000000",
        }


class _RecordingCalendarSyncStateClient:
    def __init__(self, current_channel=None) -> None:
        self.registered_channel = None
        self.current_channel = current_channel

    async def find_latest_calendar_channel(self, tracker_user, calendar_id):
        return self.current_channel

    async def register_calendar_channel(self, channel):
        self.registered_channel = channel
        return {"registered": True, "channel_id": channel["channel_id"]}


def _configured_tracker() -> TrackerConfig:
    return TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://notion.so/parent",
        task_database_url="https://notion.so/tasks",
        pages=ManagedPageUrls(),
        calendar=CalendarConfig(
            calendar_id="calendar@example.com",
            timezone_name="Europe/London",
        ),
    )
