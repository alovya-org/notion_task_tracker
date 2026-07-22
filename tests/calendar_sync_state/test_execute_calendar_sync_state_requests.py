from __future__ import annotations

import asyncio

import httpx
import pytest

from notion_task_tracker.calendar_sync_state.execute_calendar_sync_state_requests import (
    CalendarSyncStateClient,
)


def test_registers_a_google_calendar_channel_without_exposing_the_administration_token():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"registered": True, "channel_id": "channel-one"})

    client = CalendarSyncStateClient(
        state_url="https://worker.example/calendar-sync-state/",
        administration_token="admin-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(record_request)),
    )
    channel = {
        "channel_id": "channel-one",
        "tracker_user": "al0vya",
        "calendar_id": "calendar@example.com",
        "resource_id": "resource-one",
        "channel_token": "channel-secret",
        "sync_token": "initial-sync-token",
        "expires_at": 1786000000000,
    }

    result = asyncio.run(client.register_calendar_channel(channel))

    assert result == {"registered": True, "channel_id": "channel-one"}
    assert requests[0].url == "https://worker.example/calendar-sync-state/channels"
    assert requests[0].headers["Authorization"] == "Bearer admin-secret"
    assert requests[0].url.query == b""


def test_advances_the_google_calendar_sync_token_with_its_consumed_predecessor():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"advanced": True})

    client = CalendarSyncStateClient(
        state_url="https://worker.example/calendar-sync-state",
        administration_token="admin-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(record_request)),
    )

    result = asyncio.run(client.advance_calendar_sync_token(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
        previous_sync_token="previous-sync-token",
        next_sync_token="next-sync-token",
    ))

    assert result == {"advanced": True}
    assert requests[0].method == "PATCH"
    assert requests[0].url == "https://worker.example/calendar-sync-state/cursors"
    assert requests[0].read().decode() == (
        '{"tracker_user":"al0vya","calendar_id":"calendar@example.com",'
        '"previous_sync_token":"previous-sync-token","next_sync_token":"next-sync-token"}'
    )


def test_reads_the_latest_channel_and_current_sync_token():
    async def return_channel(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "channel_id": "channel-one",
            "resource_id": "resource-one",
            "expires_at": 1786000000000,
            "sync_token": "current-sync-token",
        })

    client = CalendarSyncStateClient(
        state_url="https://worker.example/calendar-sync-state",
        administration_token="admin-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(return_channel)),
    )

    channel = asyncio.run(client.find_latest_calendar_channel(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
    ))

    assert channel is not None
    assert channel.channel_id == "channel-one"
    assert channel.sync_token == "current-sync-token"


def test_requires_calendar_sync_state_environment(monkeypatch):
    monkeypatch.delenv("NTT_CALENDAR_SYNC_STATE_URL", raising=False)
    monkeypatch.delenv("NTT_CALENDAR_SYNC_ADMIN_TOKEN", raising=False)

    with pytest.raises(ValueError) as error:
        CalendarSyncStateClient.from_environment()

    assert str(error.value) == "Missing environment variable: NTT_CALENDAR_SYNC_STATE_URL"
