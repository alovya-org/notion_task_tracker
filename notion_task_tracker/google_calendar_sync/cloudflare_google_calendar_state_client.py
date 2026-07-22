"""Read and change durable Google Calendar state through the Cloudflare Worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient


GOOGLE_CALENDAR_STATE_API_URL_ENVIRONMENT_VARIABLE = "NTT_GOOGLE_CALENDAR_STATE_API_URL"
GOOGLE_CALENDAR_STATE_API_TOKEN_ENVIRONMENT_VARIABLE = "NTT_GOOGLE_CALENDAR_STATE_API_TOKEN"


@dataclass(frozen=True)
class GoogleCalendarNotificationChannelState:
    channel_id: str
    resource_id: str
    expires_at: int
    google_change_cursor: str


@dataclass(frozen=True)
class GoogleCalendarEventLedgerEntry:
    google_event_id: str
    ntt_task_id: str
    lifecycle_state: str


@dataclass(frozen=True)
class GoogleCalendarSynchronisationState:
    google_change_cursor: str
    event_ledger: list[GoogleCalendarEventLedgerEntry]


class CloudflareGoogleCalendarStateClient:
    def __init__(
        self,
        google_calendar_state_api_url: str,
        google_calendar_state_api_token: str,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.google_calendar_state_api_url = google_calendar_state_api_url.rstrip("/")
        self.google_calendar_state_api_token = google_calendar_state_api_token
        self.http_client = http_client or AsyncClient()

    @classmethod
    def from_environment(
        cls,
        http_client: AsyncClient | None = None,
    ) -> "CloudflareGoogleCalendarStateClient":
        return cls(
            google_calendar_state_api_url=_required_environment_value(
                GOOGLE_CALENDAR_STATE_API_URL_ENVIRONMENT_VARIABLE,
            ),
            google_calendar_state_api_token=_required_environment_value(
                GOOGLE_CALENDAR_STATE_API_TOKEN_ENVIRONMENT_VARIABLE,
            ),
            http_client=http_client,
        )

    async def record_google_calendar_notification_channel(
        self,
        channel: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._send_google_calendar_state_request(
            "POST",
            "notification-channels",
            channel,
        )

    async def read_latest_google_calendar_notification_channel(
        self,
        tracker_user: str,
        calendar_id: str,
    ) -> GoogleCalendarNotificationChannelState | None:
        response = await self.http_client.get(
            f"{self.google_calendar_state_api_url}/notification-channels",
            headers=self._authorisation_headers(),
            params={"tracker_user": tracker_user, "calendar_id": calendar_id},
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        channel = response.json()
        return GoogleCalendarNotificationChannelState(
            channel_id=channel["channel_id"],
            resource_id=channel["resource_id"],
            expires_at=channel["expires_at"],
            google_change_cursor=channel["google_change_cursor"],
        )

    async def advance_google_calendar_change_cursor(
        self,
        tracker_user: str,
        calendar_id: str,
        previous_google_change_cursor: str,
        next_google_change_cursor: str,
    ) -> dict[str, Any]:
        return await self._send_google_calendar_state_request(
            "PATCH",
            "change-cursors",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "previous_google_change_cursor": previous_google_change_cursor,
                "next_google_change_cursor": next_google_change_cursor,
            },
        )

    async def read_google_calendar_synchronisation_state(
        self,
        tracker_user: str,
        calendar_id: str,
    ) -> GoogleCalendarSynchronisationState:
        response = await self.http_client.get(
            f"{self.google_calendar_state_api_url}/synchronisation-state",
            headers=self._authorisation_headers(),
            params={"tracker_user": tracker_user, "calendar_id": calendar_id},
        )
        response.raise_for_status()
        state = response.json()
        return GoogleCalendarSynchronisationState(
            google_change_cursor=state["google_change_cursor"],
            event_ledger=[
                GoogleCalendarEventLedgerEntry(
                    google_event_id=entry["google_event_id"],
                    ntt_task_id=entry["ntt_task_id"],
                    lifecycle_state=entry["lifecycle_state"],
                )
                for entry in state["event_ledger"]
            ],
        )

    async def record_active_google_calendar_event(
        self,
        tracker_user: str,
        calendar_id: str,
        google_event_id: str,
        ntt_task_id: str,
    ) -> dict[str, Any]:
        return await self._send_google_calendar_state_request(
            "PUT",
            "event-ledger/active-events",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "google_event_id": google_event_id,
                "ntt_task_id": ntt_task_id,
            },
        )

    async def mark_google_calendar_event_deleted_by_ntt(
        self,
        tracker_user: str,
        calendar_id: str,
        google_event_id: str,
        ntt_task_id: str,
    ) -> dict[str, Any]:
        return await self._send_google_calendar_state_request(
            "PUT",
            "event-ledger/ntt-deletions",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "google_event_id": google_event_id,
                "ntt_task_id": ntt_task_id,
            },
        )

    async def delete_google_calendar_event_mapping(
        self,
        tracker_user: str,
        calendar_id: str,
        google_event_id: str,
        ntt_task_id: str,
    ) -> dict[str, Any]:
        return await self._send_google_calendar_state_request(
            "DELETE",
            "event-ledger/events",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "google_event_id": google_event_id,
                "ntt_task_id": ntt_task_id,
            },
        )

    async def replace_google_calendar_event_ledger_snapshot(
        self,
        tracker_user: str,
        calendar_id: str,
        active_events: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await self._send_google_calendar_state_request(
            "PUT",
            "event-ledger/snapshot",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "active_events": active_events,
            },
        )

    async def _send_google_calendar_state_request(
        self,
        method: str,
        resource_name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self.http_client.request(
            method,
            f"{self.google_calendar_state_api_url}/{resource_name}",
            headers=self._authorisation_headers(),
            json=body,
        )
        response.raise_for_status()
        return response.json()

    def _authorisation_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.google_calendar_state_api_token}",
        }


def _required_environment_value(variable_name: str) -> str:
    value = os.environ.get(variable_name)
    if not value:
        raise ValueError(f"Missing environment variable: {variable_name}")
    return value
