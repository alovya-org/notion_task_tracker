import json

from notion_task_tracker.apply_tracker_command import apply_command_to_tracker_state
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskTree


class TestApplyCommandToTrackerState:
    def test_append_task_timeline_log_updates_tracker_state_and_produces_write_intent(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000001",
                    "title": "Remaining blocker",
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["Found the remaining blocker."],
                },
            },
            tracker_state=_combined_tracker_state(),
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": [],
            }
        ]
        assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
            "update_timeline_log:task:ALOVYA-1:2026-05-24:ALOVYA-LOG-00000000-0000-4000-8000-000000000001"
        ]
        assert command_result.write_intents[0].operation_name == "update_timeline_log"
        assert command_result.write_intents[0].arguments["timeline_section_markdown"] == "\n".join([
            '### <mention-date start="2026-05-24"/>',
            "<details>",
            "<summary>Remaining blocker · ALOVYA-LOG-00000000-0000-4000-8000-000000000001</summary>",
            "\t- Found the remaining blocker.",
            "</details>",
        ])

    def test_append_task_timeline_log_inserts_after_existing_date_heading(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] = [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": ["Existing handwritten or reconciled line."],
            }
        ]

        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000002",
                    "title": "Agent investigation",
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["New agent line."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.write_intents[0].arguments["existing_timeline_heading"] == (
            '<mention-date start="2026-05-24"/>'
        )
        assert command_result.write_intents[0].arguments["appended_markdown"] == "\n".join([
            "<details>",
            "<summary>Agent investigation · ALOVYA-LOG-00000000-0000-4000-8000-000000000002</summary>",
            "\t- New agent line.",
            "</details>",
        ])

    def test_append_task_timeline_log_preserves_manual_existing_date_heading(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] = [
            {
                "entry_date": "2026-05-24",
                "heading": "2026-05-24",
                "lines": [],
            }
        ]

        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000003",
                    "title": "Agent investigation",
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["New agent line."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"][0]["heading"] == "2026-05-24"
        assert command_result.write_intents[0].arguments["existing_timeline_heading"] == "2026-05-24"

    def test_append_task_timeline_log_uses_title_and_identifier_for_toggle(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] = [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": [],
            }
        ]

        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000004",
                    "title": "Design notes",
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["Moved task metadata into the database."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.write_intents[0].arguments["appended_markdown"] == "\n".join([
            "<details>",
            "<summary>Design notes · ALOVYA-LOG-00000000-0000-4000-8000-000000000004</summary>",
            "\t- Moved task metadata into the database.",
            "</details>",
        ])

    def test_append_task_timeline_log_with_blocks_renders_paragraphs_and_code_without_bullets(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000005",
                    "title": "Target write investigation",
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "blocks": [
                        {
                            "type": "paragraph",
                            "text": "Investigated the target-side file creation failure.",
                        },
                        {
                            "type": "code",
                            "language": "bash",
                            "text": "ssh root@target '/mnt/bin/touch /var/cache/qnn_sdk/test_write'",
                        },
                    ],
                },
            },
            tracker_state=_combined_tracker_state(),
        )

        assert command_result.write_intents[0].arguments["timeline_section_markdown"] == "\n".join([
            '### <mention-date start="2026-05-24"/>',
            "<details>",
            "<summary>Target write investigation · ALOVYA-LOG-00000000-0000-4000-8000-000000000005</summary>",
            "\tInvestigated the target-side file creation failure.",
            "\t```bash",
            "\tssh root@target '/mnt/bin/touch /var/cache/qnn_sdk/test_write'",
            "\t```",
            "</details>",
        ])

    def test_complete_task_updates_status_and_produces_write_intents(self):
        tracker_state = _combined_tracker_state()
        tracker_state["completed_landing_page"]["notion_page_id"] = "33333333333333333333333333333333"
        command_result = apply_command_to_tracker_state(
            command={
                "command": "complete_task",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000006",
                    "title": "Completed task",
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["Completed the task."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Complete"
        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": [],
            }
        ]
        assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
            "update_properties:task:ALOVYA-1",
            "replace:ongoing_landing_page",
            "replace:completed_landing_page",
            "update_timeline_log:task:ALOVYA-1:2026-05-24:ALOVYA-LOG-00000000-0000-4000-8000-000000000006",
        ]
        write_intents_by_key = {
            write_intent.operation_key: write_intent
            for write_intent in command_result.write_intents
        }
        assert write_intents_by_key["update_properties:task:ALOVYA-1"].target_page_key == "task:ALOVYA-1"
        assert write_intents_by_key["update_properties:task:ALOVYA-1"].arguments["properties"]["Status"] == "Complete"
        assert write_intents_by_key["replace:ongoing_landing_page"].operation_name == "replace_page_markdown"
        assert write_intents_by_key["replace:completed_landing_page"].arguments["markdown"].startswith("## Completed")
        timeline_write_intent = next(
            write_intent
            for write_intent in command_result.write_intents
            if write_intent.operation_name == "update_timeline_log"
        )
        assert timeline_write_intent.operation_name == "update_timeline_log"

    def test_append_miscellaneous_note_command_updates_combined_tracker_state(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_miscellaneous_note",
                "note_date": "2026-05-24",
                "lines": ["Recent context."],
            },
            tracker_state=_combined_tracker_state(),
        )

        assert "tasks" in command_result.tracker_state
        assert command_result.tracker_state["miscellaneous_notes"]["dated_pages"]["2026-05-24"]["entries"][0]["lines"] == [
            "Recent context."
        ]
        assert command_result.write_intents[0].operation_name == "append_miscellaneous_context"
        assert command_result.write_intents[0].target_page_key == "miscellaneous:2026-05-24"

    def test_create_synthesis_page_command_updates_combined_tracker_state(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "create_synthesis_page",
                "synthesis_key": "onnx_qdq",
                "title": "ONNX QDQ",
                "summary": "Reusable explanation.",
                "sources": [
                    {
                        "source_type": "Notion page",
                        "label": "ALOVYA-1",
                        "page_key": "task:ALOVYA-1",
                    }
                ],
                "lines": ["QDQ nodes preserve quantisation boundaries."],
            },
            tracker_state=_combined_tracker_state(),
        )

        assert "tasks" in command_result.tracker_state
        assert command_result.tracker_state["synthesis_notes"]["pages"]["onnx_qdq"]["sources"][0]["page_key"] == (
            "task:ALOVYA-1"
        )
        assert command_result.write_intents[0].operation_name == "create_synthesis_page"
        assert command_result.write_intents[0].arguments["page"]["local_page_key"] == "synthesis:onnx_qdq"
        assert command_result.write_intents[0].arguments["markdown"].startswith("## Sources")

    def test_reconcile_synthesis_root_page_mentions_updates_tracker_state_without_rest_writes(self):
        tracker_state = _combined_tracker_state()
        tracker_state["synthesis_notes"]["existing_page_mentions"] = {
            "stale": {
                "mention_key": "stale",
                "title": "Stale page",
                "notion_page_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
        }

        command_result = apply_command_to_tracker_state(
            command={
                "command": "reconcile_synthesis_root_page_mentions",
                "root_page_content": (
                    '<mention-page url="https://www.notion.so/wayve/Useful-guide-'
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">Useful guide</mention-page>'
                ),
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["synthesis_notes"]["existing_page_mentions"] == {
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": {
                "mention_key": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "title": "Useful guide",
                "notion_page_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "display_order": 0,
                "root_block_type": "page_mention",
            },
        }
        assert command_result.write_intents == []

    def test_record_page_id_command_updates_combined_synthesis_tracker_state(self):
        tracker_state = _combined_tracker_state()
        tracker_state["synthesis_notes"]["pages"]["onnx_qdq"] = {
            "synthesis_key": "onnx_qdq",
            "title": "ONNX QDQ",
            "summary": "",
            "lines": [],
            "sources": [],
            "notion_page_id": None,
        }

        command_result = apply_command_to_tracker_state(
            command={
                "command": "record_page_id",
                "local_page_key": "synthesis:onnx_qdq",
                "notion_page_id": "66666666666666666666666666666666",
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"] == tracker_state["tasks"]
        assert command_result.tracker_state["synthesis_notes"]["pages"]["onnx_qdq"]["notion_page_id"] == (
            "66666666666666666666666666666666"
        )

    def test_set_task_dependencies_updates_dependency_relation(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "set_task_dependencies",
                "task_id": "ALOVYA-1",
                "dependency_task_ids": ["ALOVYA-2"],
            },
            tracker_state=_combined_tracker_state_with_two_tasks(),
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["dependency_task_ids"] == ["ALOVYA-2"]
        assert command_result.tracker_state["tasks"]["ALOVYA-2"]["dependant_task_ids"] == ["ALOVYA-1"]
        assert command_result.write_intents[0].operation_key == "update_dependencies:task:ALOVYA-1"
        assert command_result.write_intents[0].arguments["properties"] == {
            "Dependencies": ["task:ALOVYA-2"],
        }

    def test_set_task_dependants_updates_dependants_relation(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "set_task_dependants",
                "task_id": "ALOVYA-1",
                "dependant_task_ids": ["ALOVYA-2"],
            },
            tracker_state=_combined_tracker_state_with_two_tasks(),
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["dependant_task_ids"] == ["ALOVYA-2"]
        assert command_result.tracker_state["tasks"]["ALOVYA-2"]["dependency_task_ids"] == ["ALOVYA-1"]
        assert command_result.write_intents[0].operation_key == "update_dependants:task:ALOVYA-1"
        assert command_result.write_intents[0].arguments["properties"] == {
            "Dependants": ["task:ALOVYA-2"],
        }

    def test_reparent_task_moves_task_and_refreshes_landing_page(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "reparent_task",
                "task_id": "ALOVYA-2",
                "parent_task_id": "ALOVYA-1",
            },
            tracker_state=_combined_tracker_state_with_two_tasks(),
        )

        write_intents_by_key = {
            write_intent.operation_key: write_intent
            for write_intent in command_result.write_intents
        }

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["child_task_ids"] == ["ALOVYA-2"]
        assert command_result.tracker_state["tasks"]["ALOVYA-2"]["parent_task_id"] == "ALOVYA-1"
        assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
            "update_parent:task:ALOVYA-2",
            "replace:ongoing_landing_page",
        ]
        assert write_intents_by_key["update_parent:task:ALOVYA-2"].arguments["properties"] == {
            "Parent": ["task:ALOVYA-1"],
        }
        assert "22222222222222222222222222222222" in (
            write_intents_by_key["replace:ongoing_landing_page"].arguments["markdown"]
        )
        assert "33333333333333333333333333333333" in (
            write_intents_by_key["replace:ongoing_landing_page"].arguments["markdown"]
        )

    def test_complete_task_with_all_children_completes_descendants_before_parent_and_refreshes_landing_pages_once(self):
        tracker_state = _combined_tracker_state_with_two_tasks()
        task_tree = TaskTree.from_tracker_state(tracker_state)
        task_tree.link_parent_to_child(parent_task_id="ALOVYA-1", child_task_id="ALOVYA-2")
        tracker_state = task_tree.replace_task_tree_in_tracker_state(tracker_state)

        command_result = apply_command_to_tracker_state(
            command={
                "command": "complete_task_with_all_children",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000007",
                    "title": "Completed task tree",
                    "entry_date": "2026-06-23",
                    "heading": '<mention-date start="2026-06-23"/>',
                    "lines": ["Finished the task and all children."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Complete"
        assert command_result.tracker_state["tasks"]["ALOVYA-2"]["status"] == "Complete"
        operation_keys = [write_intent.operation_key for write_intent in command_result.write_intents]
        assert operation_keys[0] == "update_properties:task:ALOVYA-2"
        assert operation_keys[1].startswith(
            "update_timeline_log:task:ALOVYA-2:2026-06-23:ALOVYA-LOG-"
        )
        assert operation_keys[2:] == [
            "update_properties:task:ALOVYA-1",
            "update_timeline_log:task:ALOVYA-1:2026-06-23:ALOVYA-LOG-00000000-0000-4000-8000-000000000007",
            "replace:ongoing_landing_page",
        ]

    def test_set_task_deadline_updates_deadline_field(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "set_task_deadline",
                "task_id": "ALOVYA-1",
                "deadline": "2026-06-15",
            },
            tracker_state=_combined_tracker_state(),
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["deadline"] == "2026-06-15"
        assert command_result.write_intents[0].operation_key == "update_deadline:task:ALOVYA-1"
        assert command_result.write_intents[0].arguments["properties"] == {
            "Deadline": "2026-06-15",
        }

    def test_set_task_duration_without_start_preserves_an_unscheduled_estimate(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "set_task_duration",
                "task_id": "ALOVYA-1",
                "duration": 2.5,
                "duration_unit": "Hours",
            },
            tracker_state=_combined_tracker_state(),
        )

        task = command_result.tracker_state["tasks"]["ALOVYA-1"]
        assert task["start"] is None
        assert task["end"] is None
        assert task["duration"] == 2.5
        assert task["duration_unit"] == "Hours"
        assert command_result.write_intents[0].arguments["properties"] == {
            "End": None,
            "Duration": 2.5,
            "Duration unit": "Hours",
        }

    def test_setting_and_clearing_start_derives_end_without_clearing_duration(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["duration"] = 2.5
        tracker_state["tasks"]["ALOVYA-1"]["duration_unit"] = "Hours"

        scheduled_result = apply_command_to_tracker_state(
            command={
                "command": "set_task_start",
                "task_id": "ALOVYA-1",
                "start": "2026-06-15T09:30:00+01:00",
            },
            tracker_state=tracker_state,
        )
        cleared_result = apply_command_to_tracker_state(
            command={"command": "clear_task_start", "task_id": "ALOVYA-1"},
            tracker_state=scheduled_result.tracker_state,
        )

        assert scheduled_result.tracker_state["tasks"]["ALOVYA-1"]["end"] == "2026-06-15T12:00:00+01:00"
        cleared_task = cleared_result.tracker_state["tasks"]["ALOVYA-1"]
        assert cleared_task["start"] is None
        assert cleared_task["end"] is None
        assert cleared_task["duration"] == 2.5
        assert cleared_task["duration_unit"] == "Hours"

def test_cancel_task_updates_status_and_produces_write_intents():
    tracker_state = _combined_tracker_state()
    tracker_state["completed_landing_page"]["notion_page_id"] = "33333333333333333333333333333333"

    command_result = apply_command_to_tracker_state(
        command={
            "command": "cancel_task",
            "task_id": "ALOVYA-1",
            "timeline_entry": {
                "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000008",
                "title": "Cancelled task",
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Cancelled because the task is no longer needed.",
                    }
                ],
            },
        },
        tracker_state=tracker_state,
    )

    write_intents_by_key = {
        write_intent.operation_key: write_intent
        for write_intent in command_result.write_intents
    }

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Cancelled"
    assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
        "update_properties:task:ALOVYA-1",
        "replace:ongoing_landing_page",
        "replace:completed_landing_page",
        "update_timeline_log:task:ALOVYA-1:2026-05-24:ALOVYA-LOG-00000000-0000-4000-8000-000000000008",
    ]
    assert write_intents_by_key["update_properties:task:ALOVYA-1"].arguments["properties"]["Status"] == "Cancelled"
    assert "## Cancelled" in write_intents_by_key["replace:completed_landing_page"].arguments["markdown"]
    assert "[N/A]" in write_intents_by_key["replace:completed_landing_page"].arguments["markdown"]
    timeline_write_intent = next(
        write_intent
        for write_intent in command_result.write_intents
        if write_intent.operation_name == "update_timeline_log"
    )
    assert timeline_write_intent.arguments["timeline_section_markdown"] == "\n".join([
        '### <mention-date start="2026-05-24"/>',
        "<details>",
        "<summary>Cancelled task · ALOVYA-LOG-00000000-0000-4000-8000-000000000008</summary>",
        "\tCancelled because the task is no longer needed.",
        "</details>",
    ])


def test_delete_task_promotes_children_removes_dependencies_and_refreshes_views():
    tracker_state = _combined_tracker_state()
    tracker_state["completed_landing_page"]["notion_page_id"] = "66666666666666666666666666666666"
    task_tree = TaskTree.from_tracker_state(tracker_state)
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Deleted task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="33333333333333333333333333333333",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-3",
            title="Promoted child",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="77777777777777777777777777777777",
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-4",
            title="Former dependant",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependency_task_ids=["ALOVYA-2"],
            notion_page_id="88888888888888888888888888888888",
        )
    )
    task_tree.link_parent_to_child("ALOVYA-1", "ALOVYA-2")
    task_tree.link_parent_to_child("ALOVYA-2", "ALOVYA-3")
    task_tree.derive_dependant_task_ids_from_dependencies()

    command_result = apply_command_to_tracker_state(
        command={"command": "delete_task", "task_id": "ALOVYA-2"},
        tracker_state=task_tree.replace_task_tree_in_tracker_state(tracker_state),
    )

    tasks = command_result.tracker_state["tasks"]
    assert "ALOVYA-2" not in tasks
    assert tasks["ALOVYA-1"]["child_task_ids"] == ["ALOVYA-3"]
    assert tasks["ALOVYA-3"]["parent_task_id"] == "ALOVYA-1"
    assert tasks["ALOVYA-4"]["dependency_task_ids"] == []
    assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
        "update_parent:task:ALOVYA-3",
        "update_dependencies:task:ALOVYA-4",
        "trash:task:ALOVYA-2",
        "replace:ongoing_landing_page",
        "replace:completed_landing_page",
    ]
    assert "Deleted task" not in command_result.write_intents[-2].arguments["markdown"]
    assert command_result.page_registry.page_id("task:ALOVYA-2") == "33333333333333333333333333333333"


def _combined_tracker_state():
    tracker_state = _task_tracker_state()
    tracker_state["identity"] = {
        "display_name": "Alovya",
        "ticket_prefix": "ALOVYA",
    }
    tracker_state["miscellaneous_notes"] = {
        "page": {
            "local_page_key": "miscellaneous_notes",
            "title": "Alovya's miscellanous notes",
            "notion_page_id": "44444444444444444444444444444444",
            "parent_page_key": None,
        },
        "dated_pages": {},
    }
    tracker_state["synthesis_notes"] = {
        "page": {
            "local_page_key": "synthesis_notes",
            "title": "Alovya's synthesis notes",
            "notion_page_id": "55555555555555555555555555555555",
            "parent_page_key": None,
        },
        "pages": {},
    }
    return tracker_state


def _combined_tracker_state_with_two_tasks():
    tracker_state = _combined_tracker_state()
    task_tree = TaskTree.from_tracker_state(tracker_state)
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Second task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="33333333333333333333333333333333",
        )
    )
    return task_tree.replace_task_tree_in_tracker_state(tracker_state)


def _task_tracker_state():
    task_tree = TaskTree()
    task_tree.ongoing_tasks_landing_page.page.notion_page_id = "11111111111111111111111111111111"
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    return task_tree.to_tracker_state()
