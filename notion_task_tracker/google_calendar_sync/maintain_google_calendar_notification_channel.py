"""Maintain the Google Calendar notification channel and catch up after expiration."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from notion_task_tracker.config import TrackerConfig, load_config
from notion_task_tracker.google_calendar_sync.apply_google_calendar_changes_to_tasks import (
    apply_google_calendar_changes_to_tasks,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_state_api import (
    GoogleCalendarStateClient,
    GoogleNotificationChannelStatus,
)
from notion_task_tracker.google_calendar_sync.call_google_calendar_api import GoogleCalendarClient
from notion_task_tracker.json_file import write_json_file
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tracker_action_execution_summary import TrackerActionExecutionSummary


@dataclass(frozen=True)
class GoogleCalendarNotificationChannel:
    channel_id: str
    resource_id: str
    expires_at: int


@dataclass(frozen=True)
class GoogleCalendarNotificationChannelMaintenance:
    channel_id: str
    expires_at: int
    registered_replacement: bool
    catch_up_google_change_cursor: str | None


class _RefreshTasksFromNotion(Protocol):
    async def __call__(
        self,
        config: TrackerConfig | None,
        tracker_state_path: str | Path,
        output_path: str | Path,
        backup_path: str | Path | None,
        notion_client: NotionRestClient | None,
    ) -> TrackerActionExecutionSummary: ...


async def maintain_google_calendar_notification_channel(
    tracker_user: str,
    notification_url: str,
    current_time_milliseconds: int,
    replace_within_milliseconds: int,
    config: TrackerConfig | None,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: NotionRestClient | None,
    google_calendar_client: GoogleCalendarClient | None,
    google_calendar_state_client: GoogleCalendarStateClient | None,
    refresh_tasks_from_notion: _RefreshTasksFromNotion,
) -> TrackerActionExecutionSummary:
    configured_tracker = config or load_config()
    if configured_tracker.calendar is None:
        raise ValueError(
            "Configure [calendar] before maintaining a Google Calendar notification channel"
        )

    calendar_client = google_calendar_client or GoogleCalendarClient.from_environment(
        configured_tracker.calendar.calendar_id,
    )
    state_client = (
        google_calendar_state_client or GoogleCalendarStateClient.from_environment()
    )
    maintenance = await _maintain_google_calendar_notification_channel(
        tracker_user=tracker_user,
        notification_url=notification_url,
        current_time_milliseconds=current_time_milliseconds,
        replace_within_milliseconds=replace_within_milliseconds,
        config=configured_tracker,
        google_calendar_client=calendar_client,
        google_calendar_state_client=state_client,
    )
    if maintenance.catch_up_google_change_cursor is not None:
        await refresh_tasks_from_notion(
            config=configured_tracker,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            backup_path=backup_path,
            notion_client=notion_client,
        )
        await apply_google_calendar_changes_to_tasks(
            tracker_user=tracker_user,
            google_change_cursor=maintenance.catch_up_google_change_cursor,
            config=configured_tracker,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            notion_client=notion_client,
            google_calendar_client=calendar_client,
            google_calendar_state_client=state_client,
        )

    execution_summary = TrackerActionExecutionSummary(
        action_name="maintain_google_calendar_notification_channel",
        output_path=Path(output_path),
        tracker_state_path=Path(tracker_state_path),
        warnings=[],
        google_calendar_notification_channel={
            "channel_id": maintenance.channel_id,
            "expires_at": maintenance.expires_at,
            "registered_replacement": maintenance.registered_replacement,
            "caught_up_after_expiration": (
                maintenance.catch_up_google_change_cursor is not None
            ),
        },
    )
    write_json_file(execution_summary.to_json_summary(), output_path)
    return execution_summary


async def _maintain_google_calendar_notification_channel(
    tracker_user: str,
    notification_url: str,
    current_time_milliseconds: int,
    replace_within_milliseconds: int,
    config: TrackerConfig,
    google_calendar_client: GoogleCalendarClient,
    google_calendar_state_client: GoogleCalendarStateClient,
) -> GoogleCalendarNotificationChannelMaintenance:
    calendar_id = _configured_calendar_id(config)
    current_channel = await google_calendar_state_client.find_latest_google_notification_channel(
        tracker_user,
        calendar_id,
    )
    if _channel_remains_active_beyond_replacement_window(
        current_channel,
        current_time_milliseconds,
        replace_within_milliseconds,
    ):
        assert current_channel is not None
        return GoogleCalendarNotificationChannelMaintenance(
            channel_id=current_channel.channel_id,
            expires_at=current_channel.expires_at,
            registered_replacement=False,
            catch_up_google_change_cursor=None,
        )

    replacement = await _create_google_calendar_notification_channel(
        tracker_user=tracker_user,
        notification_url=notification_url,
        channel_id=str(uuid4()),
        channel_token=secrets.token_urlsafe(32),
        config=config,
        google_calendar_client=google_calendar_client,
        google_calendar_state_client=google_calendar_state_client,
        initial_google_change_cursor=(
            current_channel.google_change_cursor if current_channel is not None else None
        ),
    )
    catch_up_google_change_cursor = (
        current_channel.google_change_cursor
        if current_channel is not None and current_channel.expires_at <= current_time_milliseconds
        else None
    )
    return GoogleCalendarNotificationChannelMaintenance(
        channel_id=replacement.channel_id,
        expires_at=replacement.expires_at,
        registered_replacement=True,
        catch_up_google_change_cursor=catch_up_google_change_cursor,
    )


async def _create_google_calendar_notification_channel(
    tracker_user: str,
    notification_url: str,
    channel_id: str,
    channel_token: str,
    config: TrackerConfig,
    google_calendar_client: GoogleCalendarClient,
    google_calendar_state_client: GoogleCalendarStateClient,
    initial_google_change_cursor: str | None = None,
) -> GoogleCalendarNotificationChannel:
    calendar_id = _configured_calendar_id(config)
    google_change_cursor = initial_google_change_cursor
    if google_change_cursor is None:
        initial_changes = await google_calendar_client.fetch_calendar_event_changes()
        google_change_cursor = initial_changes.next_sync_token
    google_channel = await google_calendar_client.watch_calendar_events({
        "id": channel_id,
        "type": "web_hook",
        "address": notification_url,
        "token": channel_token,
    })
    registered_channel = _read_registered_google_channel(google_channel, channel_id)
    await google_calendar_state_client.register_google_notification_channel({
        "channel_id": registered_channel.channel_id,
        "tracker_user": tracker_user,
        "calendar_id": calendar_id,
        "resource_id": registered_channel.resource_id,
        "channel_token": channel_token,
        "google_change_cursor": google_change_cursor,
        "expires_at": registered_channel.expires_at,
    })
    return registered_channel


def _configured_calendar_id(config: TrackerConfig) -> str:
    if config.calendar is None:
        raise ValueError(
            "Configure [calendar] before creating a Google Calendar notification channel"
        )
    return config.calendar.calendar_id


def _channel_remains_active_beyond_replacement_window(
    channel: GoogleNotificationChannelStatus | None,
    current_time_milliseconds: int,
    replace_within_milliseconds: int,
) -> bool:
    return (
        channel is not None
        and channel.expires_at > current_time_milliseconds + replace_within_milliseconds
    )


def _read_registered_google_channel(
    google_channel: dict[str, Any],
    requested_channel_id: str,
) -> GoogleCalendarNotificationChannel:
    returned_channel_id = google_channel.get("id")
    if returned_channel_id != requested_channel_id:
        raise ValueError(
            "Google Calendar notification channel response did not preserve the requested channel id"
        )
    resource_id = google_channel.get("resourceId")
    if not isinstance(resource_id, str) or not resource_id:
        raise ValueError("Google Calendar notification channel response has no resourceId")
    expiration = google_channel.get("expiration")
    if not isinstance(expiration, str) or not expiration.isdigit():
        raise ValueError(
            "Google Calendar notification channel response has no millisecond expiration"
        )
    return GoogleCalendarNotificationChannel(
        channel_id=returned_channel_id,
        resource_id=resource_id,
        expires_at=int(expiration),
    )
