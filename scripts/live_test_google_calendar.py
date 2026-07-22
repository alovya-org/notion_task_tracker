"""Create, verify, update, and retain one Google Calendar event for inspection."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from notion_task_tracker.config import load_config
from notion_task_tracker.google_calendar import GoogleCalendarClient


async def verify_google_calendar_transport_live() -> None:
    calendar_config = load_config().calendar
    if calendar_config is None:
        raise ValueError("Add [calendar] configuration before running the live Google Calendar test")

    client = GoogleCalendarClient.from_environment(calendar_config.calendar_id)
    inspection_event = _build_inspection_event(calendar_config.timezone_name)
    created_event = await client.create_calendar_event(inspection_event)
    event_id = str(created_event["id"])

    await _verify_created_event_can_be_listed(client, event_id)
    await _replace_and_verify_event(client, event_id, inspection_event)

    print(
        "Google Calendar live transport test passed and retained "
        f"event {event_id}; remove it manually after inspection"
    )


def _build_inspection_event(timezone_name: str) -> dict:
    start_date_time = datetime.now(UTC) + timedelta(days=30)
    end_date_time = start_date_time + timedelta(minutes=30)
    return {
        "summary": "[NTT TEST] Temporary transport verification",
        "description": "Retained by the NTT Google Calendar transport test for manual inspection.",
        "transparency": "transparent",
        "start": {"dateTime": start_date_time.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end_date_time.isoformat(), "timeZone": timezone_name},
        "extendedProperties": {"private": {"ntt_live_test": "true"}},
    }


async def _verify_created_event_can_be_listed(client: GoogleCalendarClient, event_id: str) -> None:
    response = await client.list_calendar_events({"privateExtendedProperty": "ntt_live_test=true"})
    listed_event_ids = {str(event["id"]) for event in response.get("items", [])}
    if event_id not in listed_event_ids:
        raise ValueError(f"Created Google Calendar event {event_id} was not returned by list")


async def _replace_and_verify_event(
    client: GoogleCalendarClient,
    event_id: str,
    original_event: dict,
) -> None:
    replacement_event = {
        **original_event,
        "summary": "[NTT TEST] Updated transport verification",
    }
    replaced_event = await client.replace_calendar_event(event_id, replacement_event)
    if replaced_event.get("summary") != replacement_event["summary"]:
        raise ValueError(f"Google Calendar event {event_id} did not retain its replacement title")


if __name__ == "__main__":
    asyncio.run(verify_google_calendar_transport_live())
