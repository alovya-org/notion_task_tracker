from notion_task_tracker.notion_operations.database_properties import rich_text_items, strikethrough_rich_text_items


def test_rich_text_items_preserves_date_mentions_as_notion_mentions():
    rich_text = rich_text_items('Logged <mention-date start="2026-05-27"/>')

    assert rich_text == [
        {"type": "text", "text": {"content": "Logged "}},
        {
            "type": "mention",
            "mention": {
                "type": "date",
                "date": {"start": "2026-05-27"},
            },
        },
    ]


def test_strikethrough_rich_text_items_keeps_plain_text_content_and_adds_annotations():
    rich_text = strikethrough_rich_text_items("[165] Split plan and prompt tests by module")

    assert rich_text == [
        {
            "type": "text",
            "text": {"content": "[165] Split plan and prompt tests by module"},
            "annotations": {
                "bold": False,
                "italic": False,
                "strikethrough": True,
                "underline": False,
                "code": False,
                "color": "default",
            },
        }
    ]
