import asyncio

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from notion_task_tracker.google_calendar.authenticate_with_google import (
    GOOGLE_CALENDAR_EVENTS_SCOPE,
    GoogleCalendarCredentials,
    GoogleOAuthAccessTokenProvider,
)


def test_obtain_valid_access_token_refreshes_once_then_reuses_it():
    requests = []

    def respond(request: Request) -> Response:
        requests.append(request)
        return Response(200, json={"access_token": "short-lived-token", "expires_in": 3600})

    provider = GoogleOAuthAccessTokenProvider(
        GoogleCalendarCredentials("client", "secret", "refresh"),
        AsyncClient(transport=MockTransport(respond)),
    )

    first_token = asyncio.run(provider.obtain_valid_access_token())
    second_token = asyncio.run(provider.obtain_valid_access_token())

    assert first_token == "short-lived-token"
    assert second_token == "short-lived-token"
    assert len(requests) == 1
    assert "grant_type=refresh_token" in requests[0].content.decode()
    assert "gmail" not in GOOGLE_CALENDAR_EVENTS_SCOPE


def test_credentials_require_calendar_specific_environment_secrets(monkeypatch):
    for environment_variable in [
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_CALENDAR_REFRESH_TOKEN",
    ]:
        monkeypatch.delenv(environment_variable, raising=False)

    with pytest.raises(PermissionError, match="GOOGLE_CALENDAR_CLIENT_ID"):
        GoogleCalendarCredentials.from_environment()
