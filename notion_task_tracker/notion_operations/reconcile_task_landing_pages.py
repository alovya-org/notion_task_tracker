"""Plan managed landing-page writes from current Notion content."""

from __future__ import annotations

import re

from notion_task_tracker.notion_operations.notion_id import (
    canonical_notion_page_id,
    notion_page_id_from_url,
)
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    build_page_registry_for_task_tree,
    render_completed_landing_page_markdown,
    render_ongoing_landing_page_markdown,
)
from notion_task_tracker.notion_operations.rest_client import NotionRestClient
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks import TaskTree
from notion_task_tracker.tasks.task import LANDING_HEADING_BY_PRIORITY
from notion_task_tracker.tracked_pages import TrackedPage


_PAGE_MENTION_URL_PATTERN = re.compile(
    r'(<mention-page url="https://www\.notion\.so/)([^"]+)("/>)'
)
_MANAGED_TASK_LINE_PATTERN = re.compile(
    r'^\t*- \[(?:P0|P1|P2|P3|N/A)\] '
    r'(?:~~)?<mention-page url="https://www\.notion\.so/[a-fA-F0-9-]+"/>(?:~~)?'
    r': (?:Active|Blocked|Complete|Cancelled) \{color="(?:red|orange|yellow|gray|green)"\}$'
)
_MANAGED_LANDING_HEADINGS = {
    *LANDING_HEADING_BY_PRIORITY.values(),
    "Completed",
    "Cancelled",
}


async def plan_task_landing_page_reconciliation(
    task_tree: TaskTree,
    notion_client: NotionRestClient,
) -> list[NotionWriteIntent]:
    page_registry = build_page_registry_for_task_tree(task_tree)
    expected_ongoing_markdown = render_ongoing_landing_page_markdown(
        task_tree.tasks,
        page_registry,
    )
    expected_completed_markdown = render_completed_landing_page_markdown(
        task_tree.tasks,
        page_registry,
    )
    ongoing_page = task_tree.ongoing_tasks_landing_page.page
    completed_page = task_tree.completed_tasks_landing_page.page

    current_ongoing_markdown = await notion_client.fetch_page_markdown(
        _required_page_id(ongoing_page)
    )
    current_completed_markdown = await notion_client.fetch_page_markdown(
        _required_page_id(completed_page)
    )
    return [
        *_plan_landing_page_replacement(
            ongoing_page,
            current_ongoing_markdown,
            expected_ongoing_markdown,
        ),
        *_plan_landing_page_replacement(
            completed_page,
            current_completed_markdown,
            expected_completed_markdown,
        ),
    ]


def _plan_landing_page_replacement(
    page: TrackedPage,
    current_markdown: str,
    expected_markdown: str,
) -> list[NotionWriteIntent]:
    normalised_current_markdown = _normalise_notion_markdown(current_markdown)
    normalised_expected_markdown = _normalise_notion_markdown(expected_markdown)
    if normalised_current_markdown == normalised_expected_markdown:
        return []

    _require_managed_landing_page_content(page, normalised_current_markdown)
    return [
        NotionWriteIntent(
            operation_key=f"replace:{page.local_page_key}",
            operation_name="replace_page_markdown",
            target_page_key=page.local_page_key,
            arguments={"markdown": expected_markdown},
        )
    ]


def _normalise_notion_markdown(markdown: str) -> str:
    normalised_lines = [
        line.rstrip()
        for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    ]
    normalised_markdown = "\n".join(normalised_lines)
    return _PAGE_MENTION_URL_PATTERN.sub(
        _canonical_page_mention_url,
        normalised_markdown,
    )


def _canonical_page_mention_url(match: re.Match[str]) -> str:
    return (
        match.group(1)
        + canonical_notion_page_id(
            notion_page_id_from_url("https://www.notion.so/" + match.group(2))
        )
        + match.group(3)
    )


def _require_managed_landing_page_content(
    page: TrackedPage,
    current_markdown: str,
) -> None:
    if not current_markdown:
        return
    if current_markdown == "No completed tasks yet.":
        return

    for line in current_markdown.splitlines():
        if line.startswith("## "):
            heading = line.removeprefix("## ")
            if heading in _MANAGED_LANDING_HEADINGS:
                continue
        if _MANAGED_TASK_LINE_PATTERN.fullmatch(line):
            continue
        raise ValueError(
            f"Managed page {page.title!r} contains unsupported content: {line!r}"
        )


def _required_page_id(page: TrackedPage) -> str:
    if page.notion_page_id is None:
        raise ValueError(f"Managed page {page.title!r} has no Notion page id")
    return canonical_notion_page_id(page.notion_page_id)
