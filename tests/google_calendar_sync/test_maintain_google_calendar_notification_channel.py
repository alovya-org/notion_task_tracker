from __future__ import annotations

import asyncio

import pytest

from notion_task_tracker.config import CalendarConfig, ManagedPageUrls, TrackerConfig
from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    GoogleCalendarNotificationChannelState,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import CalendarEventChanges
from notion_task_tracker.google_calendar_sync.maintain_google_calendar_notification_channel import (
    _create_google_calendar_notification_channel,
    _maintain_google_calendar_notification_channel,
    maintain_google_calendar_notification_channel,
)


def test_creates_google_notification_channel_with_initial_change_cursor_in_durable_state():
    google_calendar_client = _RecordingGoogleCalendarClient()
    google_calendar_state_client = _RecordingGoogleCalendarStateClient()

    channel = asyncio.run(_create_google_calendar_notification_channel(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        channel_id="channel-one",
        channel_token="channel-secret",
        config=_configured_tracker(),
        google_calendar_client=google_calendar_client,
        google_calendar_state_client=google_calendar_state_client,
    ))

    assert channel.channel_id == "channel-one"
    assert channel.resource_id == "resource-one"
    assert channel.expires_at == 1786000000000
    assert google_calendar_client.requested_channel == {
        "id": "channel-one",
        "type": "web_hook",
        "address": "https://worker.example/google-calendar-notifications",
        "token": "channel-secret",
    }
    assert google_calendar_state_client.registered_channel == {
        "channel_id": "channel-one",
        "tracker_user": "al0vya",
        "calendar_id": "calendar@example.com",
        "resource_id": "resource-one",
        "channel_token": "channel-secret",
        "google_change_cursor": "initial-sync-token",
        "expires_at": 1786000000000,
    }


def test_refuses_google_response_for_another_notification_channel():
    google_calendar_client = _RecordingGoogleCalendarClient(returned_channel_id="wrong-channel")

    with pytest.raises(ValueError) as error:
            asyncio.run(_create_google_calendar_notification_channel(
            tracker_user="al0vya",
            notification_url="https://worker.example/google-calendar-notifications",
            channel_id="channel-one",
            channel_token="channel-secret",
            config=_configured_tracker(),
            google_calendar_client=google_calendar_client,
            google_calendar_state_client=_RecordingGoogleCalendarStateClient(),
        ))

    assert str(error.value) == (
        "Google Calendar notification channel response did not preserve the requested channel id"
    )


def test_keeps_a_channel_that_remains_active_beyond_the_replacement_window():
    google_calendar_client = _RecordingGoogleCalendarClient()
    google_calendar_state_client = _RecordingGoogleCalendarStateClient(
        current_channel=GoogleCalendarNotificationChannelState(
            channel_id="current-channel",
            resource_id="current-resource",
            expires_at=1_800_000,
            google_change_cursor="current-sync-token",
        ),
    )

    maintenance = asyncio.run(_maintain_google_calendar_notification_channel(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        replace_within_milliseconds=500_000,
        config=_configured_tracker(),
        google_calendar_client=google_calendar_client,
        google_calendar_state_client=google_calendar_state_client,
    ))

    assert maintenance.registered_replacement is False
    assert maintenance.channel_id == "current-channel"
    assert google_calendar_client.requested_channel is None


def test_replaces_an_expired_channel_and_requests_incremental_catch_up():
    google_calendar_state_client = _RecordingGoogleCalendarStateClient(
        current_channel=GoogleCalendarNotificationChannelState(
            channel_id="expired-channel",
            resource_id="expired-resource",
            expires_at=900_000,
            google_change_cursor="last-delivered-sync-token",
        ),
    )

    maintenance = asyncio.run(_maintain_google_calendar_notification_channel(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        replace_within_milliseconds=500_000,
        config=_configured_tracker(),
        google_calendar_client=_RecordingGoogleCalendarClient(returned_channel_id=None),
        google_calendar_state_client=google_calendar_state_client,
    ))

    assert maintenance.registered_replacement is True
    assert maintenance.requires_synchronisation is True


def test_replaces_a_nearly_expired_channel_without_fetching_calendar_events():
    google_calendar_client = _RecordingGoogleCalendarClient(returned_channel_id=None)
    google_calendar_state_client = _RecordingGoogleCalendarStateClient(
        current_channel=GoogleCalendarNotificationChannelState(
            channel_id="current-channel",
            resource_id="current-resource",
            expires_at=1_400_000,
            google_change_cursor="current-sync-token",
        ),
    )

    maintenance = asyncio.run(_maintain_google_calendar_notification_channel(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        replace_within_milliseconds=500_000,
        config=_configured_tracker(),
        google_calendar_client=google_calendar_client,
        google_calendar_state_client=google_calendar_state_client,
    ))

    assert maintenance.registered_replacement is True
    assert maintenance.requires_synchronisation is False
    assert google_calendar_client.change_fetch_count == 0
    assert google_calendar_state_client.registered_channel["google_change_cursor"] == (
        "current-sync-token"
    )


def test_expired_channel_renews_then_dispatches_synchronisation_and_prunes(tmp_path):
    google_calendar_state_client = _RecordingGoogleCalendarStateClient(
        current_channel=GoogleCalendarNotificationChannelState(
            channel_id="expired-channel",
            resource_id="expired-resource",
            expires_at=900_000,
            google_change_cursor="last-delivered-sync-token",
        ),
    )

    summary = asyncio.run(maintain_google_calendar_notification_channel(
        tracker_user="al0vya",
        notification_url="https://worker.example/google-calendar-notifications",
        current_time_milliseconds=1_000_000,
        replace_within_milliseconds=500_000,
        config=_configured_tracker(),
        output_path=tmp_path / "output.json",
        google_calendar_client=_RecordingGoogleCalendarClient(returned_channel_id=None),
        google_calendar_state_client=google_calendar_state_client,
    ))

    assert google_calendar_state_client.operations == [
        "record_channel",
        "dispatch_synchronisation:al0vya",
        "prune_before:400000",
    ]
    assert summary.google_calendar_notification_channel == {
        "channel_id": google_calendar_state_client.registered_channel["channel_id"],
        "expires_at": 1786000000000,
        "registered_replacement": True,
        "dispatched_synchronisation_after_expiration": True,
        "pruned_expired_channel_count": 1,
    }


class _RecordingGoogleCalendarClient:
    def __init__(self, returned_channel_id: str | None = "channel-one") -> None:
        self.returned_channel_id = returned_channel_id
        self.requested_channel = None
        self.change_fetch_count = 0

    async def fetch_calendar_event_changes(self):
        self.change_fetch_count += 1
        return CalendarEventChanges(events=[], next_sync_token="initial-sync-token")

    async def watch_calendar_events(self, channel):
        self.requested_channel = channel
        return {
            "id": self.returned_channel_id or channel["id"],
            "resourceId": "resource-one",
            "expiration": "1786000000000",
        }


class _RecordingGoogleCalendarStateClient:
    def __init__(self, current_channel=None) -> None:
        self.registered_channel = None
        self.current_channel = current_channel
        self.operations = []

    async def read_latest_google_calendar_notification_channel(
        self,
        tracker_user,
        calendar_id,
    ):
        return self.current_channel

    async def record_google_calendar_notification_channel(self, channel):
        self.registered_channel = channel
        self.operations.append("record_channel")
        return {"registered": True, "channel_id": channel["channel_id"]}

    async def dispatch_google_calendar_synchronisation(self, tracker_user):
        self.operations.append(f"dispatch_synchronisation:{tracker_user}")
        return {"dispatched": True}

    async def prune_expired_google_calendar_notification_channels(self, expired_before):
        self.operations.append(f"prune_before:{expired_before}")
        return {"deleted_channel_count": 1}


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
