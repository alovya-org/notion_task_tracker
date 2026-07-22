"""Call the deployed Cloudflare Worker that stores Calendar sync state in D1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient


CALENDAR_SYNC_CLOUDFLARE_WORKER_URL_ENVIRONMENT_VARIABLE = "NTT_CALENDAR_SYNC_CLOUDFLARE_WORKER_URL"
CALENDAR_SYNC_CLOUDFLARE_WORKER_ADMIN_TOKEN_ENVIRONMENT_VARIABLE = (
    "NTT_CALENDAR_SYNC_CLOUDFLARE_WORKER_ADMIN_TOKEN"
)


@dataclass(frozen=True)
class GoogleNotificationChannelStatus:
    channel_id: str
    resource_id: str
    expires_at: int
    google_change_cursor: str


class CalendarSyncCloudflareWorker:
    def __init__(
        self,
        worker_url: str,
        administration_token: str,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.worker_url = worker_url.rstrip("/")
        self.administration_token = administration_token
        self.http_client = http_client or AsyncClient()

    @classmethod
    def from_environment(
        cls,
        http_client: AsyncClient | None = None,
    ) -> "CalendarSyncCloudflareWorker":
        return cls(
            worker_url=_required_environment_value(
                CALENDAR_SYNC_CLOUDFLARE_WORKER_URL_ENVIRONMENT_VARIABLE,
            ),
            administration_token=_required_environment_value(
                CALENDAR_SYNC_CLOUDFLARE_WORKER_ADMIN_TOKEN_ENVIRONMENT_VARIABLE,
            ),
            http_client=http_client,
        )

    async def register_google_notification_channel(
        self,
        channel: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._send_worker_request("POST", "channels", channel)

    async def find_latest_google_notification_channel(
        self,
        tracker_user: str,
        calendar_id: str,
    ) -> GoogleNotificationChannelStatus | None:
        response = await self.http_client.get(
            f"{self.worker_url}/channels",
            headers=self._authorisation_headers(),
            params={"tracker_user": tracker_user, "calendar_id": calendar_id},
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        channel = response.json()
        return GoogleNotificationChannelStatus(
            channel_id=channel["channel_id"],
            resource_id=channel["resource_id"],
            expires_at=channel["expires_at"],
            google_change_cursor=channel["sync_token"],
        )

    async def advance_google_change_cursor(
        self,
        tracker_user: str,
        calendar_id: str,
        previous_google_change_cursor: str,
        next_google_change_cursor: str,
    ) -> dict[str, Any]:
        return await self._send_worker_request(
            "PATCH",
            "cursors",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "previous_sync_token": previous_google_change_cursor,
                "next_sync_token": next_google_change_cursor,
            },
        )

    async def _send_worker_request(
        self,
        method: str,
        resource_name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self.http_client.request(
            method,
            f"{self.worker_url}/{resource_name}",
            headers=self._authorisation_headers(),
            json=body,
        )
        response.raise_for_status()
        return response.json()

    def _authorisation_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.administration_token}"}


def _required_environment_value(variable_name: str) -> str:
    value = os.environ.get(variable_name)
    if not value:
        raise ValueError(f"Missing environment variable: {variable_name}")
    return value
