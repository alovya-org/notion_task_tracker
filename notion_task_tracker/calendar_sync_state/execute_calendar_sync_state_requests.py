"""Execute authenticated calendar synchronisation state requests without workflow decisions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient


CALENDAR_SYNC_STATE_URL_ENVIRONMENT_VARIABLE = "NTT_CALENDAR_SYNC_STATE_URL"
CALENDAR_SYNC_ADMIN_TOKEN_ENVIRONMENT_VARIABLE = "NTT_CALENDAR_SYNC_ADMIN_TOKEN"


@dataclass(frozen=True)
class CalendarChannelStatus:
    channel_id: str
    resource_id: str
    expires_at: int
    sync_token: str


class CalendarSyncStateClient:
    def __init__(
        self,
        state_url: str,
        administration_token: str,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.state_url = state_url.rstrip("/")
        self.administration_token = administration_token
        self.http_client = http_client or AsyncClient()

    @classmethod
    def from_environment(
        cls,
        http_client: AsyncClient | None = None,
    ) -> "CalendarSyncStateClient":
        return cls(
            state_url=_required_environment_value(CALENDAR_SYNC_STATE_URL_ENVIRONMENT_VARIABLE),
            administration_token=_required_environment_value(
                CALENDAR_SYNC_ADMIN_TOKEN_ENVIRONMENT_VARIABLE,
            ),
            http_client=http_client,
        )

    async def register_calendar_channel(
        self,
        channel: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._send_state_request("POST", "channels", channel)

    async def find_latest_calendar_channel(
        self,
        tracker_user: str,
        calendar_id: str,
    ) -> CalendarChannelStatus | None:
        response = await self.http_client.get(
            f"{self.state_url}/channels",
            headers=self._authorisation_headers(),
            params={"tracker_user": tracker_user, "calendar_id": calendar_id},
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        channel = response.json()
        return CalendarChannelStatus(
            channel_id=channel["channel_id"],
            resource_id=channel["resource_id"],
            expires_at=channel["expires_at"],
            sync_token=channel["sync_token"],
        )

    async def advance_calendar_sync_token(
        self,
        tracker_user: str,
        calendar_id: str,
        previous_sync_token: str,
        next_sync_token: str,
    ) -> dict[str, Any]:
        return await self._send_state_request(
            "PATCH",
            "cursors",
            {
                "tracker_user": tracker_user,
                "calendar_id": calendar_id,
                "previous_sync_token": previous_sync_token,
                "next_sync_token": next_sync_token,
            },
        )

    async def _send_state_request(
        self,
        method: str,
        resource_name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self.http_client.request(
            method,
            f"{self.state_url}/{resource_name}",
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
