"""Register durable Google Calendar watch channels for push-driven synchronisation."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Any
from uuid import uuid4

from notion_task_tracker.calendar_sync_state import CalendarChannelStatus, CalendarSyncStateClient
from notion_task_tracker.config import TrackerConfig
from notion_task_tracker.google_calendar import GoogleCalendarClient


@dataclass(frozen=True)
class CalendarWatchRegistration:
    channel_id: str
    resource_id: str
    expires_at: int


@dataclass(frozen=True)
class CalendarWatchMaintenance:
    channel_id: str
    expires_at: int
    registered_replacement: bool
    catch_up_sync_token: str | None


async def ensure_google_calendar_watch_is_active(
    tracker_user: str,
    notification_url: str,
    current_time_milliseconds: int,
    renew_within_milliseconds: int,
    config: TrackerConfig,
    google_calendar_client: GoogleCalendarClient,
    calendar_sync_state_client: CalendarSyncStateClient,
) -> CalendarWatchMaintenance:
    calendar_id = _configured_calendar_id(config)
    current_channel = await calendar_sync_state_client.find_latest_calendar_channel(
        tracker_user,
        calendar_id,
    )
    if _channel_remains_active_beyond_renewal_window(
        current_channel,
        current_time_milliseconds,
        renew_within_milliseconds,
    ):
        assert current_channel is not None
        return CalendarWatchMaintenance(
            channel_id=current_channel.channel_id,
            expires_at=current_channel.expires_at,
            registered_replacement=False,
            catch_up_sync_token=None,
        )

    replacement = await register_google_calendar_watch(
        tracker_user=tracker_user,
        notification_url=notification_url,
        channel_id=str(uuid4()),
        channel_token=secrets.token_urlsafe(32),
        config=config,
        google_calendar_client=google_calendar_client,
        calendar_sync_state_client=calendar_sync_state_client,
        initial_sync_token=current_channel.sync_token if current_channel is not None else None,
    )
    catch_up_sync_token = (
        current_channel.sync_token
        if current_channel is not None and current_channel.expires_at <= current_time_milliseconds
        else None
    )
    return CalendarWatchMaintenance(
        channel_id=replacement.channel_id,
        expires_at=replacement.expires_at,
        registered_replacement=True,
        catch_up_sync_token=catch_up_sync_token,
    )


async def register_google_calendar_watch(
    tracker_user: str,
    notification_url: str,
    channel_id: str,
    channel_token: str,
    config: TrackerConfig,
    google_calendar_client: GoogleCalendarClient,
    calendar_sync_state_client: CalendarSyncStateClient,
    initial_sync_token: str | None = None,
) -> CalendarWatchRegistration:
    calendar_id = _configured_calendar_id(config)
    sync_token = initial_sync_token
    if sync_token is None:
        initial_changes = await google_calendar_client.fetch_calendar_event_changes()
        sync_token = initial_changes.next_sync_token
    google_channel = await google_calendar_client.watch_calendar_events({
        "id": channel_id,
        "type": "web_hook",
        "address": notification_url,
        "token": channel_token,
    })
    registered_channel = _read_registered_google_channel(google_channel, channel_id)
    await calendar_sync_state_client.register_calendar_channel({
        "channel_id": registered_channel.channel_id,
        "tracker_user": tracker_user,
        "calendar_id": calendar_id,
        "resource_id": registered_channel.resource_id,
        "channel_token": channel_token,
        "sync_token": sync_token,
        "expires_at": registered_channel.expires_at,
    })
    return registered_channel


def _configured_calendar_id(config: TrackerConfig) -> str:
    if config.calendar is None:
        raise ValueError("Configure [calendar] before registering a Google Calendar watch")
    return config.calendar.calendar_id


def _channel_remains_active_beyond_renewal_window(
    channel: CalendarChannelStatus | None,
    current_time_milliseconds: int,
    renew_within_milliseconds: int,
) -> bool:
    return (
        channel is not None
        and channel.expires_at > current_time_milliseconds + renew_within_milliseconds
    )


def _read_registered_google_channel(
    google_channel: dict[str, Any],
    requested_channel_id: str,
) -> CalendarWatchRegistration:
    returned_channel_id = google_channel.get("id")
    if returned_channel_id != requested_channel_id:
        raise ValueError("Google Calendar watch response did not preserve the requested channel id")
    resource_id = google_channel.get("resourceId")
    if not isinstance(resource_id, str) or not resource_id:
        raise ValueError("Google Calendar watch response has no resourceId")
    expiration = google_channel.get("expiration")
    if not isinstance(expiration, str) or not expiration.isdigit():
        raise ValueError("Google Calendar watch response has no millisecond expiration")
    return CalendarWatchRegistration(
        channel_id=returned_channel_id,
        resource_id=resource_id,
        expires_at=int(expiration),
    )
