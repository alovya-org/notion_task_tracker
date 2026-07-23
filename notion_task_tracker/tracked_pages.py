"""Tracker-owned references to pages that may exist in Notion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrackedPage:
    """One page identity used during the current command."""

    local_page_key: str
    title: str
    notion_page_id: str | None = None
    parent_page_key: str | None = None
def validate_fixed_tracked_page(
    page: TrackedPage,
    expected_local_page_key: str,
) -> None:
    if page.local_page_key != expected_local_page_key:
        raise ValueError(
            f"Fixed page key {page.local_page_key!r} should be {expected_local_page_key!r}"
        )

    if not page.title.strip():
        raise ValueError(f"Fixed page {page.local_page_key!r} must have a title")
