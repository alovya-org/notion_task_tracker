from __future__ import annotations

import asyncio

import httpx
import pytest

from notion_task_tracker.google_calendar_sync.call_calendar_sync_cloudflare_worker import (
    CalendarSyncCloudflareWorker,
)


def test_registers_a_google_notification_channel_without_exposing_the_administration_token():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"registered": True, "channel_id": "channel-one"})

    worker = _cloudflare_worker(record_request, worker_url="https://worker.example/calendar-sync/")
    channel = {
        "channel_id": "channel-one",
        "tracker_user": "al0vya",
        "calendar_id": "calendar@example.com",
        "resource_id": "resource-one",
        "channel_token": "channel-secret",
        "sync_token": "initial-sync-token",
        "expires_at": 1786000000000,
    }

    result = asyncio.run(worker.register_google_notification_channel(channel))

    assert result == {"registered": True, "channel_id": "channel-one"}
    assert requests[0].url == "https://worker.example/calendar-sync/channels"
    assert requests[0].headers["Authorization"] == "Bearer admin-secret"
    assert requests[0].url.query == b""


def test_advances_the_google_change_cursor_with_its_consumed_predecessor():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"advanced": True})

    worker = _cloudflare_worker(record_request)

    result = asyncio.run(worker.advance_google_change_cursor(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
        previous_google_change_cursor="previous-sync-token",
        next_google_change_cursor="next-sync-token",
    ))

    assert result == {"advanced": True}
    assert requests[0].method == "PATCH"
    assert requests[0].url == "https://worker.example/calendar-sync/cursors"
    assert requests[0].read().decode() == (
        '{"tracker_user":"al0vya","calendar_id":"calendar@example.com",'
        '"previous_sync_token":"previous-sync-token","next_sync_token":"next-sync-token"}'
    )


def test_reads_the_latest_notification_channel_and_google_change_cursor():
    async def return_channel(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "channel_id": "channel-one",
            "resource_id": "resource-one",
            "expires_at": 1786000000000,
            "sync_token": "current-sync-token",
        })

    worker = _cloudflare_worker(return_channel)

    channel = asyncio.run(worker.find_latest_google_notification_channel(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
    ))

    assert channel is not None
    assert channel.channel_id == "channel-one"
    assert channel.google_change_cursor == "current-sync-token"


def test_requires_calendar_sync_cloudflare_worker_environment(monkeypatch):
    monkeypatch.delenv("NTT_CALENDAR_SYNC_CLOUDFLARE_WORKER_URL", raising=False)
    monkeypatch.delenv("NTT_CALENDAR_SYNC_CLOUDFLARE_WORKER_ADMIN_TOKEN", raising=False)

    with pytest.raises(ValueError) as error:
        CalendarSyncCloudflareWorker.from_environment()

    assert str(error.value) == (
        "Missing environment variable: NTT_CALENDAR_SYNC_CLOUDFLARE_WORKER_URL"
    )


def _cloudflare_worker(record_request, worker_url="https://worker.example/calendar-sync"):
    return CalendarSyncCloudflareWorker(
        worker_url=worker_url,
        administration_token="admin-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(record_request)),
    )
