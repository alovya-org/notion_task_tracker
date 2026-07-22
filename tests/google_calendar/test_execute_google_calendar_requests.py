import asyncio
import json

from httpx import AsyncClient, MockTransport, Request, Response
import pytest

from notion_task_tracker.google_calendar.execute_google_calendar_requests import (
    GoogleCalendarClient,
    GoogleCalendarSyncTokenExpiredError,
)


class FixedAccessTokenProvider:
    async def obtain_valid_access_token(self) -> str:
        return "short-lived-token"


def test_create_calendar_event_uses_bearer_token_and_encoded_calendar_id():
    requests = []

    def respond(request: Request) -> Response:
        requests.append(request)
        return Response(200, json={"id": "created-event"})

    client = GoogleCalendarClient(
        calendar_id="work@example.com",
        access_token_provider=FixedAccessTokenProvider(),
        http_client=AsyncClient(transport=MockTransport(respond)),
    )

    event = asyncio.run(client.create_calendar_event({"summary": "[NTT] Task"}))

    assert requests[0].headers["Authorization"] == "Bearer short-lived-token"
    assert requests[0].url.path == "/calendar/v3/calendars/work@example.com/events"
    assert json.loads(requests[0].content) == {"summary": "[NTT] Task"}
    assert event == {"id": "created-event"}


def test_exposes_list_replace_delete_and_watch_event_operations():
    requests = []

    def respond(request: Request) -> Response:
        requests.append(request)
        if request.method == "DELETE":
            return Response(204)
        return Response(200, json={})

    client = GoogleCalendarClient(
        calendar_id="primary",
        access_token_provider=FixedAccessTokenProvider(),
        http_client=AsyncClient(transport=MockTransport(respond)),
    )

    async def exercise_operations():
        await client.list_calendar_events({"syncToken": "next"})
        await client.replace_calendar_event("event/id", {"summary": "Updated"})
        await client.delete_calendar_event("event/id")
        await client.watch_calendar_events({"id": "channel", "address": "https://example.com/hook"})

    asyncio.run(exercise_operations())

    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/calendar/v3/calendars/primary/events"),
        ("PUT", "/calendar/v3/calendars/primary/events/event/id"),
        ("DELETE", "/calendar/v3/calendars/primary/events/event/id"),
        ("POST", "/calendar/v3/calendars/primary/events/watch"),
    ]


def test_lists_every_calendar_event_page_without_changing_the_original_query():
    requests = []

    def respond(request: Request) -> Response:
        requests.append(request)
        if request.url.params.get("pageToken") == "second-page":
            return Response(200, json={"items": [{"id": "two"}]})
        return Response(200, json={"items": [{"id": "one"}], "nextPageToken": "second-page"})

    client = GoogleCalendarClient(
        calendar_id="primary",
        access_token_provider=FixedAccessTokenProvider(),
        http_client=AsyncClient(transport=MockTransport(respond)),
    )
    query = {"privateExtendedProperty": "ntt_tracker=ALOVYA"}

    events = asyncio.run(client.list_all_calendar_events(query))

    assert events == [{"id": "one"}, {"id": "two"}]
    assert query == {"privateExtendedProperty": "ntt_tracker=ALOVYA"}
    assert requests[1].url.params["pageToken"] == "second-page"


def test_fetches_every_incremental_change_and_returns_the_final_sync_token():
    requests = []

    def respond(request: Request) -> Response:
        requests.append(request)
        if request.url.params.get("pageToken") == "second-page":
            return Response(200, json={
                "items": [{"id": "changed-two"}],
                "nextSyncToken": "next-sync-token",
            })
        return Response(200, json={
            "items": [{"id": "changed-one"}],
            "nextPageToken": "second-page",
        })

    client = GoogleCalendarClient(
        calendar_id="primary",
        access_token_provider=FixedAccessTokenProvider(),
        http_client=AsyncClient(transport=MockTransport(respond)),
    )

    changes = asyncio.run(client.fetch_calendar_event_changes("previous-sync-token"))

    assert changes.events == [{"id": "changed-one"}, {"id": "changed-two"}]
    assert changes.next_sync_token == "next-sync-token"
    assert requests[0].url.params["syncToken"] == "previous-sync-token"
    assert requests[0].url.params["showDeleted"] == "true"
    assert requests[1].url.params["syncToken"] == "previous-sync-token"
    assert requests[1].url.params["pageToken"] == "second-page"


def test_initial_calendar_sync_uses_the_same_unfiltered_query_shape():
    requests = []

    def respond(request: Request) -> Response:
        requests.append(request)
        return Response(200, json={"items": [], "nextSyncToken": "initial-sync-token"})

    client = GoogleCalendarClient(
        calendar_id="primary",
        access_token_provider=FixedAccessTokenProvider(),
        http_client=AsyncClient(transport=MockTransport(respond)),
    )

    changes = asyncio.run(client.fetch_calendar_event_changes())

    assert changes.next_sync_token == "initial-sync-token"
    assert dict(requests[0].url.params) == {"showDeleted": "true"}


def test_identifies_an_expired_incremental_sync_token():
    def reject_expired_token(request: Request) -> Response:
        return Response(410, json={"error": {"message": "Sync token is no longer valid"}})

    client = GoogleCalendarClient(
        calendar_id="primary",
        access_token_provider=FixedAccessTokenProvider(),
        http_client=AsyncClient(transport=MockTransport(reject_expired_token)),
    )

    with pytest.raises(GoogleCalendarSyncTokenExpiredError):
        asyncio.run(client.fetch_calendar_event_changes("expired-sync-token"))
