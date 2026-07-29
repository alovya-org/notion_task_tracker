import asyncio
from copy import deepcopy

import pytest

from notion_task_tracker.notion_operations.move_task_timeline_log import move_task_timeline_log


LOG_ID = "ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0"


class _InMemoryNotionClient:
    def __init__(self, source_blocks, destination_blocks, fail_on_append_call_number=None):
        self.pages = {
            "source-page": deepcopy(source_blocks),
            "destination-page": deepcopy(destination_blocks),
        }
        self.calls = []
        self._next_created_block_number = 1
        self._append_call_count = 0
        self._fail_on_append_call_number = fail_on_append_call_number

    async def fetch_block_children(self, parent_block_id):
        self.calls.append(("read", parent_block_id))
        return deepcopy(self._children_for(parent_block_id))

    async def append_block_children(self, parent_block_id, children, after_block_id):
        self.calls.append(("append", parent_block_id, after_block_id, deepcopy(children)))
        self._append_call_count += 1
        if self._append_call_count == self._fail_on_append_call_number:
            raise RuntimeError("append failed")

        copied_children = deepcopy(children)
        for block in copied_children:
            self._assign_created_block_ids(block)
            self._normalise_created_block_tree(block)

        destination_children = self._children_for(parent_block_id)
        insertion_index = len(destination_children)
        if after_block_id is not None:
            insertion_index = next(
                index
                for index, block in enumerate(destination_children)
                if block["id"] == after_block_id
            ) + 1
        destination_children[insertion_index:insertion_index] = copied_children
        return deepcopy(copied_children)

    async def delete_block(self, block_id):
        self.calls.append(("delete", block_id))
        parent_children = self._find_parent_children(block_id)
        parent_children[:] = [
            block for block in parent_children if block["id"] != block_id
        ]

    def _children_for(self, parent_block_id):
        if parent_block_id in self.pages:
            return self.pages[parent_block_id]

        parent_block = self._find_block(parent_block_id)
        if parent_block is None:
            raise KeyError(parent_block_id)
        return parent_block.setdefault("children", [])

    def _find_block(self, block_id):
        for blocks in self.pages.values():
            found_block = _find_block(blocks, block_id)
            if found_block is not None:
                return found_block
        return None

    def _find_parent_children(self, block_id):
        for blocks in self.pages.values():
            found_children = _find_parent_children(blocks, block_id)
            if found_children is not None:
                return found_children
        raise KeyError(block_id)

    def _assign_created_block_ids(self, block):
        block["id"] = f"copied-{self._next_created_block_number}"
        self._next_created_block_number += 1
        for child in block.get("children", []):
            self._assign_created_block_ids(child)
        for child in block.get(block["type"], {}).get("children", []):
            self._assign_created_block_ids(child)

    def _normalise_created_block_tree(self, block):
        nested_children = block[block["type"]].pop("children", None)
        if nested_children:
            block["children"] = nested_children
            block["has_children"] = True
            for child in nested_children:
                self._normalise_created_block_tree(child)
            return

        block.pop("children", None)
        block["has_children"] = False


def test_move_task_timeline_log_returns_compact_candidates_when_selection_is_ambiguous():
    notion_client = _InMemoryNotionClient(
        source_blocks=_timeline_blocks(LOG_ID, second_log_id="ALOVYA-LOG-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        destination_blocks=_empty_timeline_blocks(),
    )

    result = asyncio.run(move_task_timeline_log(
        source_page_id="source-page",
        destination_page_id="destination-page",
        requested_log_id=None,
        notion_client=notion_client,
    ))

    assert result == {
        "status": "selection_required",
        "candidates": [
            {
                "date": "2026-07-18",
                "title": "First log",
                "logical_identifier": LOG_ID,
            },
            {
                "date": "2026-07-18",
                "title": "Second log",
                "logical_identifier": "ALOVYA-LOG-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            },
        ],
    }
    assert notion_client.calls == [("read", "source-page"), ("read", "destination-page")]


def test_move_task_timeline_log_copies_verifies_deletes_and_verifies_complete_toggle():
    notion_client = _InMemoryNotionClient(
        source_blocks=_timeline_blocks(LOG_ID),
        destination_blocks=_empty_timeline_blocks(),
    )

    result = asyncio.run(move_task_timeline_log(
        source_page_id="source-page",
        destination_page_id="destination-page",
        requested_log_id=LOG_ID,
        notion_client=notion_client,
    ))

    assert result == {
        "status": "moved",
        "date": "2026-07-18",
        "title": "First log",
        "logical_identifier": LOG_ID,
        "copied_to_destination": True,
        "removed_source_block_identifier": "source-toggle",
    }
    assert [call[:3] for call in notion_client.calls] == [
        ("read", "source-page"),
        ("read", "destination-page"),
        ("append", "destination-page", "destination-timeline-heading"),
        ("append", "copied-2", None),
        ("read", "destination-page"),
        ("delete", "source-toggle"),
        ("read", "source-page"),
    ]
    copied_toggle = _find_block(notion_client.pages["destination-page"], "copied-2")
    copied_body_text = copied_toggle["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert copied_body_text == "Complete body"
    assert "icon" not in copied_toggle["children"][0]["paragraph"]


def test_move_task_timeline_log_drops_list_format_from_nested_numbered_lists():
    source_blocks = _timeline_blocks(LOG_ID)
    outer_list_item = _numbered_list_item_block(
        "outer-numbered-list-item",
        "Outer item",
        list_start_index=3,
    )
    outer_list_item["children"] = [_numbered_list_item_block(
        "nested-numbered-list-item",
        "Nested item",
    )]
    outer_list_item["has_children"] = True
    source_blocks[2]["children"] = [outer_list_item]

    notion_client = _InMemoryNotionClient(
        source_blocks=source_blocks,
        destination_blocks=_empty_timeline_blocks(),
    )

    asyncio.run(move_task_timeline_log(
        source_page_id="source-page",
        destination_page_id="destination-page",
        requested_log_id=LOG_ID,
        notion_client=notion_client,
    ))

    copied_toggle = _find_block(notion_client.pages["destination-page"], "copied-2")
    copied_outer_list_item = copied_toggle["children"][0]
    copied_nested_list_item = copied_outer_list_item["children"][0]
    assert copied_outer_list_item["numbered_list_item"]["list_start_index"] == 3
    assert copied_outer_list_item["numbered_list_item"]["rich_text"][0]["text"]["content"] == "Outer item"
    assert copied_nested_list_item["numbered_list_item"]["rich_text"][0]["text"]["content"] == "Nested item"
    assert "list_format" not in copied_outer_list_item["numbered_list_item"]
    assert "list_format" not in copied_nested_list_item["numbered_list_item"]


def test_move_task_timeline_log_creates_column_lists_under_toggle_in_a_separate_append():
    source_blocks = _timeline_blocks(LOG_ID)
    source_blocks[2]["children"] = [_column_list_block()]

    notion_client = _InMemoryNotionClient(
        source_blocks=source_blocks,
        destination_blocks=_empty_timeline_blocks(),
    )

    asyncio.run(move_task_timeline_log(
        source_page_id="source-page",
        destination_page_id="destination-page",
        requested_log_id=LOG_ID,
        notion_client=notion_client,
    ))

    assert [call[:3] for call in notion_client.calls] == [
        ("read", "source-page"),
        ("read", "destination-page"),
        ("append", "destination-page", "destination-timeline-heading"),
        ("append", "copied-2", None),
        ("read", "copied-3"),
        ("read", "copied-4"),
        ("read", "copied-6"),
        ("read", "destination-page"),
        ("delete", "source-toggle"),
        ("read", "source-page"),
    ]
    column_list_append = notion_client.calls[3][3][0]
    assert column_list_append["type"] == "column_list"
    assert [column["type"] for column in column_list_append["column_list"]["children"]] == ["column", "column"]
    assert [
        child["type"]
        for child in column_list_append["column_list"]["children"][0]["column"]["children"]
    ] == ["image"]
    left_image = column_list_append["column_list"]["children"][0]["column"]["children"][0]["image"]
    assert left_image["type"] == "external"
    assert left_image["external"] == {"url": "https://example.com/left.png"}
    assert "file" not in left_image
    assert [
        child["type"]
        for child in column_list_append["column_list"]["children"][1]["column"]["children"]
    ] == ["image"]


def test_move_task_timeline_log_removes_partial_destination_copy_when_child_append_fails():
    notion_client = _InMemoryNotionClient(
        source_blocks=_timeline_blocks(LOG_ID),
        destination_blocks=_empty_timeline_blocks(),
        fail_on_append_call_number=2,
    )

    with pytest.raises(RuntimeError, match="append failed"):
        asyncio.run(move_task_timeline_log(
            source_page_id="source-page",
            destination_page_id="destination-page",
            requested_log_id=LOG_ID,
            notion_client=notion_client,
        ))

    assert [call[:3] for call in notion_client.calls] == [
        ("read", "source-page"),
        ("read", "destination-page"),
        ("append", "destination-page", "destination-timeline-heading"),
        ("append", "copied-2", None),
        ("delete", "copied-2"),
        ("delete", "copied-1"),
    ]
    assert _find_block(notion_client.pages["source-page"], "source-toggle") is not None
    assert _find_block(notion_client.pages["destination-page"], "copied-1") is None
    assert _find_block(notion_client.pages["destination-page"], "copied-2") is None


def test_move_task_timeline_log_reuses_existing_destination_copy_before_deleting_source():
    notion_client = _InMemoryNotionClient(
        source_blocks=_timeline_blocks(LOG_ID),
        destination_blocks=_timeline_blocks(LOG_ID),
    )

    result = asyncio.run(move_task_timeline_log(
        source_page_id="source-page",
        destination_page_id="destination-page",
        requested_log_id=LOG_ID,
        notion_client=notion_client,
    ))

    assert result["copied_to_destination"] is False
    assert notion_client.calls == [
        ("read", "source-page"),
        ("read", "destination-page"),
        ("delete", "source-toggle"),
        ("read", "source-page"),
    ]


def _empty_timeline_blocks():
    return [
        _rich_text_block("destination-timeline-heading", "heading_2", "Timeline log"),
    ]


def _timeline_blocks(log_id, second_log_id=None):
    blocks = [
        _rich_text_block("source-timeline-heading", "heading_2", "Timeline log"),
        _rich_text_block("source-date-heading", "heading_3", "2026-07-18"),
        _toggle_block("source-toggle", "First log", log_id),
    ]
    if second_log_id is not None:
        blocks.append(_toggle_block("second-toggle", "Second log", second_log_id))
    return blocks


def _toggle_block(block_id, title, log_id):
    block = _rich_text_block(block_id, "toggle", f"{title} · {log_id}")
    block["has_children"] = True
    block["children"] = [_rich_text_block("body-paragraph", "paragraph", "Complete body")]
    block["children"][0]["paragraph"]["icon"] = None
    return block


def _numbered_list_item_block(block_id, text, list_start_index=None):
    block = _rich_text_block(block_id, "numbered_list_item", text)
    block["numbered_list_item"]["list_format"] = "numbers"
    if list_start_index is not None:
        block["numbered_list_item"]["list_start_index"] = list_start_index
    return block


def _column_list_block():
    return {
        "object": "block",
        "id": "source-column-list",
        "type": "column_list",
        "has_children": True,
        "column_list": {},
        "children": [
            _column_block("source-column-left", "https://example.com/left.png", 0.5),
            _column_block("source-column-right", "https://example.com/right.png", 0.5),
        ],
    }


def _column_block(block_id, image_url, width_ratio):
    return {
        "object": "block",
        "id": block_id,
        "type": "column",
        "has_children": True,
        "column": {"width_ratio": width_ratio},
        "children": [_image_block(f"{block_id}-image", image_url)],
    }


def _image_block(block_id, image_url):
    return {
        "object": "block",
        "id": block_id,
        "type": "image",
        "has_children": False,
        "image": {
            "caption": [],
            "type": "file",
            "file": {
                "url": image_url,
                "expiry_time": "2026-07-29T10:15:04.000Z",
            },
        },
    }


def _rich_text_block(block_id, block_type, text):
    return {
        "object": "block",
        "id": block_id,
        "type": block_type,
        "has_children": False,
        block_type: {
            "rich_text": [{"type": "text", "plain_text": text, "text": {"content": text}}],
            "color": "default",
        },
    }


def _find_block(blocks, block_id):
    for block in blocks:
        if block["id"] == block_id:
            return block
        found_block = _find_block(block.get("children", []), block_id)
        if found_block is not None:
            return found_block
    return None


def _find_parent_children(blocks, block_id):
    for block in blocks:
        if any(child["id"] == block_id for child in block.get("children", [])):
            return block["children"]

        found_children = _find_parent_children(block.get("children", []), block_id)
        if found_children is not None:
            return found_children

    if any(block["id"] == block_id for block in blocks):
        return blocks
    return None
