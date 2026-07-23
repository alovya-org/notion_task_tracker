from notion_task_tracker.tasks.timeline_log import (
    render_initialised_task_timeline_markdown,
    parse_timeline_entries_from_fetched_task_page_content,
    parse_timeline_log_ids_from_fetched_task_page_content,
)


def test_parse_timeline_entries_from_fetched_task_page_content_reads_unique_date_headings():
    timeline_entries = parse_timeline_entries_from_fetched_task_page_content(
        "\n".join(
            [
                "<page>",
                "<content>",
                "## Timeline log",
                '### <mention-date start="2026-05-26"/>',
                "- First entry",
                '### <mention-date start="2026-05-26"/>',
                "- Duplicate heading",
                '### <mention-date start="2026-05-25"/>',
                "</content>",
                "</page>",
            ]
        )
    )

    assert timeline_entries == [
        {"entry_date": "2026-05-26", "heading": '<mention-date start="2026-05-26"/>'},
        {"entry_date": "2026-05-25", "heading": '<mention-date start="2026-05-25"/>'},
    ]


def test_parse_timeline_log_ids_from_current_page_body():
    fetched_page_content = "\n".join([
        "<page>",
        "<content>",
        "## Timeline log",
        '### <mention-date start="2026-07-23"/>',
        "<details>",
        (
            "<summary>Implemented state-free reads · "
            "ALOVYA-LOG-09c41014-3381-4ae6-b620-cb53ce8ab12e</summary>"
        ),
        "</details>",
        "</content>",
        "</page>",
    ])

    assert parse_timeline_log_ids_from_fetched_task_page_content(
        fetched_page_content
    ) == {"ALOVYA-LOG-09c41014-3381-4ae6-b620-cb53ce8ab12e"}


def test_parse_timeline_entries_from_fetched_task_page_content_reads_manual_date_headings():
    timeline_entries = parse_timeline_entries_from_fetched_task_page_content(
        "\n".join(
            [
                "<page>",
                "## Timeline log",
                '### <mention-date start="2026-05-26"/>',
                "- Human note.",
                "### 2026-05-25",
                "- Older human note.",
                "</page>",
            ]
        )
    )

    assert timeline_entries == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
        },
        {
            "entry_date": "2026-05-25",
            "heading": "2026-05-25",
        },
    ]


def test_render_initialised_task_timeline_markdown_subsumes_existing_body_under_today():
    markdown = render_initialised_task_timeline_markdown(
        entry_date="2026-05-26",
        timeline_section_markdown='### <mention-date start="2026-05-26"/>\n- Started task.',
        fetched_page_content="<content>Loose note from the page body.</content>",
    )

    assert markdown == "\n".join([
        "## Timeline log",
        '### <mention-date start="2026-05-26"/>',
        "- Started task.",
        "Loose note from the page body.",
    ])
