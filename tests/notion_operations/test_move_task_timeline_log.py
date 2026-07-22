import asyncio
from copy import deepcopy

from notion_task_tracker.notion_operations.move_task_timeline_log import move_task_timeline_log


LOG_ID = "ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0"


class _InMemoryNotionClient:
    def __init__(self, source_blocks, destination_blocks):
        self.pages = {
            "source-page": deepcopy(source_blocks),
            "destination-page": deepcopy(destination_blocks),
        }
        self.calls = []

    async def fetch_block_children(self, parent_block_id):
        self.calls.append(("read", parent_block_id))
        return deepcopy(self.pages[parent_block_id])

    async def append_block_children(self, parent_block_id, children, after_block_id):
        self.calls.append(("append", parent_block_id, after_block_id, deepcopy(children)))
        insertion_index = next(
            index
            for index, block in enumerate(self.pages[parent_block_id])
            if block["id"] == after_block_id
        ) + 1
        copied_children = deepcopy(children)
        for index, block in enumerate(copied_children):
            block["id"] = f"copied-{index}"
        self.pages[parent_block_id][insertion_index:insertion_index] = copied_children

    async def delete_block(self, block_id):
        self.calls.append(("delete", block_id))
        self.pages["source-page"] = [
            block for block in self.pages["source-page"] if block["id"] != block_id
        ]


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
        ("read", "destination-page"),
        ("delete", "source-toggle"),
        ("read", "source-page"),
    ]
    copied_toggle = notion_client.calls[2][3][1]
    copied_body_text = copied_toggle["toggle"]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert copied_body_text == "Complete body"
    assert "icon" not in copied_toggle["toggle"]["children"][0]["paragraph"]


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
