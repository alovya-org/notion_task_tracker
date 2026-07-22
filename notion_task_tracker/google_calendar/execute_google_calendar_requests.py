"""Execute narrow Google Calendar event requests without task-domain decisions."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from httpx import AsyncClient

from notion_task_tracker.google_calendar.authenticate_with_google import (
    GoogleOAuthAccessTokenProvider,
)


GOOGLE_CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarClient:
    def __init__(
        self,
        calendar_id: str,
        access_token_provider: GoogleOAuthAccessTokenProvider,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.calendar_id = calendar_id
        self.access_token_provider = access_token_provider
        self.http_client = http_client or AsyncClient()

    @classmethod
    def from_environment(
        cls,
        calendar_id: str,
        http_client: AsyncClient | None = None,
    ) -> "GoogleCalendarClient":
        shared_http_client = http_client or AsyncClient()
        return cls(
            calendar_id=calendar_id,
            access_token_provider=GoogleOAuthAccessTokenProvider.from_environment(shared_http_client),
            http_client=shared_http_client,
        )

    async def list_calendar_events(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._send_calendar_request("GET", self._events_path(), query=query)

    async def list_all_calendar_events(self, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        events = []
        next_query = dict(query or {})
        while True:
            response = await self.list_calendar_events(next_query)
            events.extend(response.get("items", []))
            next_page_token = response.get("nextPageToken")
            if next_page_token is None:
                return events
            next_query["pageToken"] = next_page_token

    async def create_calendar_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return await self._send_calendar_request("POST", self._events_path(), body=event)

    async def replace_calendar_event(self, event_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return await self._send_calendar_request("PUT", self._event_path(event_id), body=event)

    async def delete_calendar_event(self, event_id: str) -> None:
        await self._send_calendar_request("DELETE", self._event_path(event_id))

    async def watch_calendar_events(self, channel: dict[str, Any]) -> dict[str, Any]:
        return await self._send_calendar_request("POST", f"{self._events_path()}/watch", body=channel)

    async def _send_calendar_request(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        access_token = await self.access_token_provider.obtain_valid_access_token()
        response = await self.http_client.request(
            method,
            f"{GOOGLE_CALENDAR_API_URL}{path}",
            params=query,
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    def _events_path(self) -> str:
        return f"/calendars/{quote(self.calendar_id, safe='')}/events"

    def _event_path(self, event_id: str) -> str:
        return f"{self._events_path()}/{quote(event_id, safe='')}"
