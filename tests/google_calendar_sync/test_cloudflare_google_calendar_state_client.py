from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from notion_task_tracker.google_calendar_sync.cloudflare_google_calendar_state_client import (
    CloudflareGoogleCalendarStateClient,
)


def test_records_a_google_calendar_notification_channel_without_exposing_the_api_token():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"registered": True, "channel_id": "channel-one"})

    state_client = _state_client(
        record_request,
        google_calendar_state_api_url="https://worker.example/google-calendar/",
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

    result = asyncio.run(state_client.record_google_calendar_notification_channel(channel))

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

    result = asyncio.run(state_client.advance_google_calendar_change_cursor(
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


def test_records_active_event_identity_and_ntt_deletion_provenance():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"recorded": True})

    state_client = _state_client(record_request)

    asyncio.run(state_client.record_active_google_calendar_event(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
        google_event_id="event-one",
        ntt_task_id="ALOVYA-42",
    ))
    asyncio.run(state_client.mark_google_calendar_event_deleted_by_ntt(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
        google_event_id="event-one",
        ntt_task_id="ALOVYA-42",
    ))

    assert [request.url for request in requests] == [
        "https://worker.example/google-calendar/event-ledger/active-events",
        "https://worker.example/google-calendar/event-ledger/ntt-deletions",
    ]
    assert all(request.method == "PUT" for request in requests)
    assert json.loads(requests[0].read()) == {
        "tracker_user": "al0vya",
        "calendar_id": "calendar@example.com",
        "google_event_id": "event-one",
        "ntt_task_id": "ALOVYA-42",
    }


def test_reads_the_latest_notification_channel_and_google_change_cursor():
    async def return_channel(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "channel_id": "channel-one",
            "resource_id": "resource-one",
            "expires_at": 1786000000000,
            "google_change_cursor": "current-sync-token",
        })

    state_client = _state_client(return_channel)

    channel = asyncio.run(state_client.read_latest_google_calendar_notification_channel(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
    ))

    assert channel is not None
    assert channel.channel_id == "channel-one"
    assert channel.google_change_cursor == "current-sync-token"


def test_reads_the_cursor_and_event_ledger_as_synchronisation_state():
    async def return_state(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "google_change_cursor": "current-sync-token",
            "event_ledger": [{
                "google_event_id": "event-one",
                "ntt_task_id": "ALOVYA-42",
                "lifecycle_state": "active",
            }],
        })

    state_client = _state_client(return_state)

    state = asyncio.run(state_client.read_google_calendar_synchronisation_state(
        tracker_user="al0vya",
        calendar_id="calendar@example.com",
    ))

    assert state.google_change_cursor == "current-sync-token"
    assert state.event_ledger[0].google_event_id == "event-one"
    assert state.event_ledger[0].ntt_task_id == "ALOVYA-42"
    assert state.event_ledger[0].lifecycle_state == "active"


def test_removes_acknowledged_event_identity_and_replaces_a_recovered_snapshot():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"updated": True})

    state_client = _state_client(record_request)

    asyncio.run(state_client.delete_google_calendar_event_mapping(
        "al0vya",
        "calendar@example.com",
        "deleted-event",
        "ALOVYA-42",
    ))
    asyncio.run(state_client.replace_google_calendar_event_ledger_snapshot(
        "al0vya",
        "calendar@example.com",
        [{"google_event_id": "current-event", "ntt_task_id": "ALOVYA-43"}],
    ))

    assert [(request.method, str(request.url)) for request in requests] == [
        ("DELETE", "https://worker.example/google-calendar/event-ledger/events"),
        ("PUT", "https://worker.example/google-calendar/event-ledger/snapshot"),
    ]
    assert json.loads(requests[1].read())["active_events"] == [
        {"google_event_id": "current-event", "ntt_task_id": "ALOVYA-43"}
    ]


def test_requests_synchronisation_without_sending_the_google_change_cursor():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"dispatched": True})

    state_client = _state_client(record_request)

    asyncio.run(state_client.dispatch_google_calendar_synchronisation("al0vya"))

    assert requests[0].method == "POST"
    assert requests[0].url == (
        "https://worker.example/google-calendar/synchronisation-dispatches"
    )
    assert json.loads(requests[0].read()) == {"tracker_user": "al0vya"}


def test_prunes_notification_channels_before_an_explicit_expiry_boundary():
    requests = []

    async def record_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"deleted_channel_count": 2})

    state_client = _state_client(record_request)

    result = asyncio.run(
        state_client.prune_expired_google_calendar_notification_channels(1785000000000)
    )

    assert result == {"deleted_channel_count": 2}
    assert requests[0].method == "DELETE"
    assert requests[0].url == (
        "https://worker.example/google-calendar/notification-channels/expired"
    )
    assert json.loads(requests[0].read()) == {"expired_before": 1785000000000}


def test_requires_google_calendar_state_api_environment(monkeypatch):
    monkeypatch.delenv("NTT_GOOGLE_CALENDAR_STATE_API_URL", raising=False)
    monkeypatch.delenv("NTT_GOOGLE_CALENDAR_STATE_API_TOKEN", raising=False)

    with pytest.raises(ValueError) as error:
        CloudflareGoogleCalendarStateClient.from_environment()

    assert str(error.value) == (
        "Missing environment variable: NTT_GOOGLE_CALENDAR_STATE_API_URL"
    )


def _state_client(
    record_request,
    google_calendar_state_api_url="https://worker.example/google-calendar",
):
    return CloudflareGoogleCalendarStateClient(
        google_calendar_state_api_url=google_calendar_state_api_url,
        google_calendar_state_api_token="state-api-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(record_request)),
    )
