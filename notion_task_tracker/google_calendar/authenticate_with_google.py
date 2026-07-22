"""Renew short-lived Google access tokens from secret OAuth credentials."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from httpx import AsyncClient


GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


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


class GoogleOAuthAccessTokenProvider:
    def __init__(
        self,
        credentials: GoogleCalendarCredentials,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.credentials = credentials
        self.http_client = http_client or AsyncClient()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    @classmethod
    def from_environment(
        cls,
        http_client: AsyncClient | None = None,
    ) -> "GoogleOAuthAccessTokenProvider":
        return cls(GoogleCalendarCredentials.from_environment(), http_client)

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
