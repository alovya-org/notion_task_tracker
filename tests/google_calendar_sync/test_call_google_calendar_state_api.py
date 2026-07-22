from __future__ import annotations

import asyncio

import httpx
import pytest

from notion_task_tracker.google_calendar_sync.call_google_calendar_state_api import (
    GoogleCalendarStateClient,
)


def test_registers_a_google_notification_channel_without_exposing_the_state_api_token():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"registered": True, "channel_id": "channel-one"})

    state_client = _state_client(
        record_request,
        state_api_url="https://worker.example/google-calendar/",
    )
    channel = {
        "channel_id": "channel-one",
        "tracker_user": "al0vya",
        "calendar_id": "calendar@example.com",
        "resource_id": "resource-one",
        "channel_token": "channel-secret",
        "google_change_cursor": "initial-sync-token",
        "expires_at": 1786000000000,
    }

    result = asyncio.run(state_client.register_google_notification_channel(channel))

    assert result == {"registered": True, "channel_id": "channel-one"}
    assert requests[0].url == "https://worker.example/google-calendar/notification-channels"
    assert requests[0].headers["Authorization"] == "Bearer state-api-secret"
    assert requests[0].url.query == b""


def test_advances_the_google_change_cursor_with_its_consumed_predecessor():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"advanced": True})

    state_client = _state_client(record_request)

    result = asyncio.run(state_client.advance_google_change_cursor(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
        previous_google_change_cursor="previous-sync-token",
        next_google_change_cursor="next-sync-token",
    ))

    assert result == {"advanced": True}
    assert requests[0].method == "PATCH"
    assert requests[0].url == "https://worker.example/google-calendar/change-cursors"
    assert requests[0].read().decode() == (
        '{"tracker_user":"al0vya","calendar_id":"calendar@example.com",'
        '"previous_google_change_cursor":"previous-sync-token",'
        '"next_google_change_cursor":"next-sync-token"}'
    )


def test_reads_the_latest_notification_channel_and_google_change_cursor():
    async def return_channel(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "channel_id": "channel-one",
            "resource_id": "resource-one",
            "expires_at": 1786000000000,
            "google_change_cursor": "current-sync-token",
        })

    state_client = _state_client(return_channel)

    channel = asyncio.run(state_client.find_latest_google_notification_channel(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
    ))

    assert channel is not None
    assert channel.channel_id == "channel-one"
    assert channel.google_change_cursor == "current-sync-token"


def test_requires_google_calendar_state_api_environment(monkeypatch):
    monkeypatch.delenv("NTT_GOOGLE_CALENDAR_STATE_API_URL", raising=False)
    monkeypatch.delenv("NTT_GOOGLE_CALENDAR_STATE_API_TOKEN", raising=False)

    with pytest.raises(ValueError) as error:
        GoogleCalendarStateClient.from_environment()

    assert str(error.value) == (
        "Missing environment variable: NTT_GOOGLE_CALENDAR_STATE_API_URL"
    )


def _state_client(record_request, state_api_url="https://worker.example/google-calendar"):
    return GoogleCalendarStateClient(
        state_api_url=state_api_url,
        state_api_token="state-api-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(record_request)),
    )
