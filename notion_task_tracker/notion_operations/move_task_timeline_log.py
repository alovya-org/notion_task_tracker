"""Move one identified task timeline toggle between Notion pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from notion_task_tracker.notion_operations.database_properties import plain_text_from_rich_text_items
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.tasks.task import TASK_PAGE_TIMELINE_LOG_HEADING


LOG_ID_PATTERN = re.compile(
    r"(?P<log_id>[A-Za-z0-9_-]+-LOG-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _MovableTimelineLog:
    entry_date: str
    title: str
    log_id: str
    toggle: dict[str, Any]
    date_heading: dict[str, Any]

    def candidate_summary(self) -> dict[str, str]:
        return {
            "date": self.entry_date,
            "title": self.title,
            "logical_identifier": self.log_id,
        }


async def move_task_timeline_log(
    source_page_id: str,
    destination_page_id: str,
    requested_log_id: str | None,
    notion_client: NotionRestClient,
) -> dict[str, Any]:
    source_blocks = await notion_client.fetch_block_children(source_page_id)
    destination_blocks = await notion_client.fetch_block_children(destination_page_id)
    source_logs = _find_movable_timeline_logs(source_blocks)
    selected_log = _select_timeline_log(source_logs, requested_log_id)
    if selected_log is None:
        return {
            "status": "selection_required",
            "candidates": [log.candidate_summary() for log in source_logs],
        }

    destination_logs = _find_movable_timeline_logs(destination_blocks)
    destination_already_contains_log = any(
        log.log_id == selected_log.log_id
        for log in destination_logs
    )
    if not destination_already_contains_log:
        await _copy_timeline_log_to_destination(selected_log, destination_blocks, destination_page_id, notion_client)
        await _verify_page_contains_log(destination_page_id, selected_log.log_id, notion_client)

    await notion_client.delete_block(selected_log.toggle["id"])
    await _verify_page_does_not_contain_log(source_page_id, selected_log.log_id, notion_client)
    return {
        "status": "moved",
        "date": selected_log.entry_date,
        "title": selected_log.title,
        "logical_identifier": selected_log.log_id,
        "copied_to_destination": not destination_already_contains_log,
        "removed_source_block_identifier": selected_log.toggle["id"],
    }


def _select_timeline_log(
    source_logs: list[_MovableTimelineLog],
    requested_log_id: str | None,
) -> _MovableTimelineLog | None:
    if requested_log_id is None:
        return source_logs[0] if len(source_logs) == 1 else None

    matching_logs = [log for log in source_logs if log.log_id == requested_log_id]
    if len(matching_logs) != 1:
        raise ValueError(f"Source task has no unique movable timeline log {requested_log_id!r}")
    return matching_logs[0]


async def _copy_timeline_log_to_destination(
    selected_log: _MovableTimelineLog,
    destination_blocks: list[dict[str, Any]],
    destination_page_id: str,
    notion_client: NotionRestClient,
) -> None:
    destination_date_heading = _find_date_heading(destination_blocks, selected_log.entry_date)
    if destination_date_heading is not None:
        blocks_to_append = [_copyable_block(selected_log.toggle)]
        insertion_anchor_id = destination_date_heading["id"]
    else:
        timeline_heading = _find_timeline_log_heading(destination_blocks)
        if timeline_heading is None:
            raise ValueError("Destination task has no Timeline log heading")
        blocks_to_append = [
            _copyable_block(selected_log.date_heading),
            _copyable_block(selected_log.toggle),
        ]
        insertion_anchor_id = timeline_heading["id"]

    await notion_client.append_block_children(
        parent_block_id=destination_page_id,
        children=blocks_to_append,
        after_block_id=insertion_anchor_id,
    )


async def _verify_page_contains_log(
    page_id: str,
    log_id: str,
    notion_client: NotionRestClient,
) -> None:
    blocks = await notion_client.fetch_block_children(page_id)
    if not any(log.log_id == log_id for log in _find_movable_timeline_logs(blocks)):
        raise ValueError(f"Destination verification could not find copied timeline log {log_id!r}")


async def _verify_page_does_not_contain_log(
    page_id: str,
    log_id: str,
    notion_client: NotionRestClient,
) -> None:
    blocks = await notion_client.fetch_block_children(page_id)
    if any(log.log_id == log_id for log in _find_movable_timeline_logs(blocks)):
        raise ValueError(f"Source verification still found timeline log {log_id!r}")


def _find_movable_timeline_logs(blocks: list[dict[str, Any]]) -> list[_MovableTimelineLog]:
    logs = []
    current_date = None
    current_date_heading = None
    inside_timeline_log = False
    for block in blocks:
        if _block_plain_text(block) == TASK_PAGE_TIMELINE_LOG_HEADING and block.get("type") == "heading_2":
            inside_timeline_log = True
            current_date = None
            current_date_heading = None
            continue
        if not inside_timeline_log:
            continue

        entry_date = _date_from_heading_block(block)
        if entry_date is not None:
            current_date = entry_date
            current_date_heading = block
            continue
        if block.get("type") != "toggle" or current_date is None or current_date_heading is None:
            continue

        toggle_title = _block_plain_text(block)
        log_id_match = LOG_ID_PATTERN.search(toggle_title)
        if log_id_match is None:
            continue
        log_id = log_id_match.group("log_id")
        logs.append(_MovableTimelineLog(
            entry_date=current_date,
            title=toggle_title[:log_id_match.start()].removesuffix(" · ").strip(),
            log_id=log_id,
            toggle=block,
            date_heading=current_date_heading,
        ))
    return logs


def _find_date_heading(blocks: list[dict[str, Any]], entry_date: str) -> dict[str, Any] | None:
    return next((block for block in blocks if _date_from_heading_block(block) == entry_date), None)


def _find_timeline_log_heading(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((
        block
        for block in blocks
        if block.get("type") == "heading_2" and _block_plain_text(block) == TASK_PAGE_TIMELINE_LOG_HEADING
    ), None)


def _date_from_heading_block(block: dict[str, Any]) -> str | None:
    if block.get("type") not in {"heading_1", "heading_2", "heading_3"}:
        return None
    for rich_text_item in block[block["type"]].get("rich_text", []):
        mention = rich_text_item.get("mention", {})
        if mention.get("type") == "date":
            return mention.get("date", {}).get("start")
    plain_text = _block_plain_text(block)
    return plain_text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", plain_text) else None


def _block_plain_text(block: dict[str, Any]) -> str:
    block_type = block.get("type")
    block_value = block.get(block_type, {})
    return plain_text_from_rich_text_items(block_value.get("rich_text", []))


def _copyable_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = block["type"]
    copied_block = {
        "object": "block",
        "type": block_type,
        block_type: _copyable_block_value(block[block_type]),
    }
    copied_block[block_type].pop("children", None)
    if block.get("children"):
        copied_block[block_type]["children"] = [_copyable_block(child) for child in block["children"]]
    return copied_block


def _copyable_block_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_copyable_block_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    return {
        key: _copyable_block_value(nested_value)
        for key, nested_value in value.items()
        if key not in {"plain_text", "href"} and nested_value is not None
    }
