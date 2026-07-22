"""Authenticate with Google and execute narrow Calendar event requests."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from httpx import AsyncClient
from httpx import HTTPStatusError


GOOGLE_CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class CalendarEventChanges:
    events: list[dict[str, Any]]
    next_sync_token: str


@dataclass(frozen=True)
class GoogleCalendarCredentials:
    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_environment(cls) -> "GoogleCalendarCredentials":
        return cls(
            client_id=_required_secret("GOOGLE_CALENDAR_CLIENT_ID"),
            client_secret=_required_secret("GOOGLE_CALENDAR_CLIENT_SECRET"),
            refresh_token=_required_secret("GOOGLE_CALENDAR_REFRESH_TOKEN"),
        )


class GoogleCalendarSyncTokenExpiredError(Exception):
    pass


class GoogleCalendarClient:
    def __init__(
        self,
        calendar_id: str,
        credentials: GoogleCalendarCredentials,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.calendar_id = calendar_id
        self.http_client = http_client or AsyncClient()
        self._access_tokens = _GoogleOAuthAccessTokenProvider(credentials, self.http_client)

    @classmethod
    def from_environment(
        cls,
        calendar_id: str,
        http_client: AsyncClient | None = None,
    ) -> "GoogleCalendarClient":
        return cls(
            calendar_id=calendar_id,
            credentials=GoogleCalendarCredentials.from_environment(),
            http_client=http_client,
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

    async def fetch_calendar_event_changes(
        self,
        sync_token: str | None = None,
    ) -> CalendarEventChanges:
        query = {"showDeleted": "true"}
        if sync_token is not None:
            query["syncToken"] = sync_token

        events = []
        while True:
            try:
                response = await self.list_calendar_events(query)
            except HTTPStatusError as error:
                if error.response.status_code == 410 and sync_token is not None:
                    raise GoogleCalendarSyncTokenExpiredError from error
                raise
            events.extend(response.get("items", []))
            next_page_token = response.get("nextPageToken")
            if next_page_token is not None:
                query["pageToken"] = next_page_token
                continue

            next_sync_token = response.get("nextSyncToken")
            if not isinstance(next_sync_token, str) or not next_sync_token:
                raise ValueError("Final Google Calendar event page has no nextSyncToken")
            return CalendarEventChanges(events=events, next_sync_token=next_sync_token)

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
        access_token = await self._access_tokens.obtain_valid_access_token()
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


class _GoogleOAuthAccessTokenProvider:
    def __init__(
        self,
        credentials: GoogleCalendarCredentials,
        http_client: AsyncClient,
    ) -> None:
        self.credentials = credentials
        self.http_client = http_client
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    async def obtain_valid_access_token(self) -> str:
        if self._access_token is not None and time.monotonic() < self._access_token_expires_at:
            return self._access_token

        response = await self.http_client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "refresh_token": self.credentials.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        response_body = response.json()
        access_token = response_body.get("access_token")
        if not access_token:
            raise ValueError("Google OAuth refresh response has no access_token")

        expires_in = float(response_body.get("expires_in", 3600))
        self._access_token = str(access_token)
        self._access_token_expires_at = time.monotonic() + max(0, expires_in - 60)
        return self._access_token


def _required_secret(environment_variable: str) -> str:
    value = os.environ.get(environment_variable)
    if not value:
        raise PermissionError(f"Set {environment_variable} before using Google Calendar")
    return value
