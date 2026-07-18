import json
from argparse import Namespace
from uuid import UUID

import pytest

from notion_task_tracker.build_tracker_command import (
    _parse_date_time_arg,
    build_tracker_command_from_cli_action,
    ticket_ids_from_numbers,
)
from notion_task_tracker.tasks import DEFAULT_TASK_PRIORITY


def test_reconcile_action_builds_refresh_command():
    command = _build_tracker_command(_arguments(reconcile_from_notion=True))

    assert command == {"command": "reconcile_from_notion"}


def test_read_action_builds_read_command_for_all_ticket_numbers():
    command = _build_tracker_command(_arguments(read=True, ticket_number=[67, 68]))

    assert command == {
        "command": "read_tasks",
        "task_ids": ["ALOVYA-67", "ALOVYA-68"],
    }


def test_read_action_uses_configured_ticket_prefix():
    command = _build_tracker_command(
        _arguments(read=True, ticket_number=[67]),
        ticket_prefix="PERSONAL",
    )

    assert command["task_ids"] == ["PERSONAL-67"]


def test_work_action_builds_work_command_for_one_ticket_number():
    command = _build_tracker_command(_arguments(work=True, ticket_number=[67]))

    assert command == {
        "command": "work_task",
        "task_ids": ["ALOVYA-67"],
    }


def test_delete_action_builds_delete_command_for_one_ticket_number():
    command = _build_tracker_command(_arguments(delete=True, ticket_number=[67]))

    assert command == {
        "command": "delete_task",
        "task_id": "ALOVYA-67",
    }


def test_log_action_builds_timeline_command_from_content_path(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "title": "Implementation notes",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Added explicit CLI actions.",
                }
            ],
        }),
        encoding="utf-8",
    )

    command = _build_tracker_command(
        _arguments(
            log=True,
            ticket_number=[67],
            content_path=str(content_path),
            entry_date="2026-05-30",
        )
    )

    generated_log_id = command["timeline_entry"].pop("log_id")
    _assert_uuid4_log_id(generated_log_id)
    assert command == {
        "command": "append_task_timeline_log",
        "task_id": "ALOVYA-67",
        "timeline_entry": {
            "title": "Implementation notes",
            "entry_date": "2026-05-30",
            "heading": '<mention-date start="2026-05-30"/>',
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Added explicit CLI actions.",
                }
            ],
        },
    }


def test_log_action_uses_configured_ticket_prefix_in_generated_log_id(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "title": "Personal tracker log",
            "lines": ["Verified configured identifier namespace."],
        }),
        encoding="utf-8",
    )

    command = _build_tracker_command(
        _arguments(log=True, ticket_number=[67], content_path=str(content_path)),
        ticket_prefix="PERSONAL",
    )

    assert command["task_id"] == "PERSONAL-67"
    _assert_uuid4_log_id(command["timeline_entry"]["log_id"], ticket_prefix="PERSONAL")


def test_child_action_builds_split_command_from_one_title(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "title": "Child task creation",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Spawned a child task for the CLI parser.",
                }
            ],
        }),
        encoding="utf-8",
    )

    command = _build_tracker_command(
        _arguments(
            child=True,
            parent_ticket_number=67,
            title=["Add explicit CLI actions"],
            priority="P2",
            content_path=str(content_path),
            entry_date="2026-05-30",
        )
    )

    generated_log_id = command["parent_timeline_entry"].pop("log_id")
    _assert_uuid4_log_id(generated_log_id)
    assert command == {
        "command": "split_task_into_children",
        "source_task_id": "ALOVYA-67",
        "child_tasks": [
            {
                "title": "Add explicit CLI actions",
                "configured_priority": "P2",
                "status": "Active",
                "dependency_task_ids": [],
                "dependant_task_ids": [],
                "deadline": None,
                "start_date_time": None,
                "end_date_time": None,
                "external_coordination": "No",
                "uncertainty": "Low",
                "friction": "None",
            },
        ],
        "parent_timeline_entry": {
            "title": "Child task creation",
            "entry_date": "2026-05-30",
            "heading": '<mention-date start="2026-05-30"/>',
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Spawned a child task for the CLI parser.",
                }
            ],
        },
    }


def test_child_action_rejects_wrong_title_counts():
    for titles in [[], ["One", "Two"]]:
        with pytest.raises(ValueError, match="--child requires exactly 1 --title value"):
            _build_tracker_command(
                _arguments(child=True, parent_ticket_number=67, title=titles)
            )


def test_sibling_action_requires_one_title():
    command = _build_tracker_command(
        _arguments(sibling=True, sibling_ticket_number=67, title=["Sibling task"])
    )

    assert command["command"] == "split_task_with_sibling"
    assert command["source_task_id"] == "ALOVYA-67"
    assert command["sibling_task"]["title"] == "Sibling task"

    with pytest.raises(ValueError, match="--sibling requires exactly 1 --title value"):
        _build_tracker_command(
            _arguments(sibling=True, sibling_ticket_number=67, title=["One", "Two"])
        )


def test_parent_action_requires_one_title():
    command = _build_tracker_command(_arguments(parent=True, title=["Parent task"]))

    assert command["task"]["title"] == "Parent task"

    with pytest.raises(ValueError, match="--parent requires exactly 1 --title value"):
        _build_tracker_command(_arguments(parent=True, title=["One", "Two"]))


def test_split_actions_reject_explicit_relation_flags():
    with pytest.raises(ValueError, match="--child derives dependencies"):
        _build_tracker_command(
            _arguments(child=True, parent_ticket_number=67, title=["One", "Two"], dependency_ticket_number=[1])
        )

    with pytest.raises(ValueError, match="--sibling derives dependants"):
        _build_tracker_command(
            _arguments(sibling=True, sibling_ticket_number=67, title=["One"], dependant_ticket_number=[1])
        )


def test_parent_action_builds_task_creation_command_with_dependencies():
    command = _build_tracker_command(
        _arguments(
            parent=True,
            title="Create dependent task",
            dependency_ticket_number=[10, 12],
            deadline="2026-06-15",
            start_date_time="2026-06-15",
            end_date_time="2026-06-15 09:30",
            external_coordination="Yes",
            uncertainty="High",
            friction="Charged",
        )
    )

    assert command["task"] == {
        "title": "Create dependent task",
        "configured_priority": DEFAULT_TASK_PRIORITY.value,
        "status": "Active",
        "dependency_task_ids": ["ALOVYA-10", "ALOVYA-12"],
        "dependant_task_ids": [],
        "deadline": "2026-06-15",
        "start_date_time": "2026-06-15T00:00:00+06:00",
        "end_date_time": "2026-06-15T09:30:00+06:00",
        "external_coordination": "Yes",
        "uncertainty": "High",
        "friction": "Charged",
    }


def test_parent_action_rejects_dependencies_and_dependants_together():
    with pytest.raises(ValueError, match="Choose dependencies or dependants"):
        _build_tracker_command(
            _arguments(
                parent=True,
                title="Ambiguous relation task",
                dependency_ticket_number=[10],
                dependant_ticket_number=[12],
            )
        )


def test_set_dependencies_action_builds_field_specific_command():
    command = _build_tracker_command(
        _arguments(
            set_dependencies=True,
            ticket_number=[67],
            dependency_ticket_number=[10, 12],
        )
    )

    assert command == {
        "command": "set_task_dependencies",
        "task_id": "ALOVYA-67",
        "dependency_task_ids": ["ALOVYA-10", "ALOVYA-12"],
    }


def test_set_dependants_action_builds_field_specific_command():
    command = _build_tracker_command(
        _arguments(
            set_dependants=True,
            ticket_number=[67],
            dependant_ticket_number=[10, 12],
        )
    )

    assert command == {
        "command": "set_task_dependants",
        "task_id": "ALOVYA-67",
        "dependant_task_ids": ["ALOVYA-10", "ALOVYA-12"],
    }


def test_reparent_action_builds_parent_relation_command():
    command = _build_tracker_command(
        _arguments(
            reparent=True,
            ticket_number=[68],
            parent_ticket_number=67,
        )
    )

    assert command == {
        "command": "reparent_task",
        "task_id": "ALOVYA-68",
        "parent_task_id": "ALOVYA-67",
    }


def test_reparent_action_requires_parent_ticket_number():
    with pytest.raises(ValueError, match="--reparent requires --parent-ticket-number"):
        _build_tracker_command(_arguments(reparent=True, ticket_number=[68]))


def test_complete_with_all_children_action_builds_completion_with_all_children_command(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "title": "Completed task tree",
            "lines": ["Finished the task and all children."],
        }),
        encoding="utf-8",
    )

    command = _build_tracker_command(
        _arguments(
            complete_with_all_children=True,
            ticket_number=[67],
            content_path=str(content_path),
            entry_date="2026-06-23",
        )
    )

    generated_log_id = command["timeline_entry"].pop("log_id")
    _assert_uuid4_log_id(generated_log_id)
    assert command == {
        "command": "complete_task_with_all_children",
        "task_id": "ALOVYA-67",
        "timeline_entry": {
            "title": "Completed task tree",
            "entry_date": "2026-06-23",
            "heading": '<mention-date start="2026-06-23"/>',
            "lines": ["Finished the task and all children."],
        },
    }


def test_log_action_requires_a_non_empty_timeline_log_title(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({"lines": ["Untitled log content."]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Timeline content must include a non-empty title"):
        _build_tracker_command(
            _arguments(log=True, ticket_number=[67], content_path=str(content_path))
        )


def test_set_deadline_actions_build_field_specific_commands():
    assert _build_tracker_command(
        _arguments(set_deadline=True, ticket_number=[67], deadline="2026-06-15")
    ) == {
        "command": "set_task_deadline",
        "task_id": "ALOVYA-67",
        "deadline": "2026-06-15",
    }
    assert _build_tracker_command(
        _arguments(clear_deadline=True, ticket_number=[67])
    ) == {
        "command": "clear_task_deadline",
        "task_id": "ALOVYA-67",
    }


def test_set_date_time_actions_build_field_specific_commands():
    assert _build_tracker_command(
        _arguments(set_start_date_time=True, ticket_number=[67], start_date_time="2026-06-15T09:30")
    ) == {
        "command": "set_task_start_date_time",
        "task_id": "ALOVYA-67",
        "start_date_time": "2026-06-15T09:30:00+06:00",
    }
    assert _build_tracker_command(
        _arguments(clear_start_date_time=True, ticket_number=[67])
    ) == {
        "command": "clear_task_start_date_time",
        "task_id": "ALOVYA-67",
    }
    assert _build_tracker_command(
        _arguments(set_end_date_time=True, ticket_number=[67], end_date_time="2026-06-16")
    ) == {
        "command": "set_task_end_date_time",
        "task_id": "ALOVYA-67",
        "end_date_time": "2026-06-16T00:00:00+06:00",
    }
    assert _build_tracker_command(
        _arguments(clear_end_date_time=True, ticket_number=[67])
    ) == {
        "command": "clear_task_end_date_time",
        "task_id": "ALOVYA-67",
    }


def test_parse_date_time_arg_rejects_time_only_values():
    with pytest.raises(ValueError, match="requires a date"):
        _parse_date_time_arg("09:30", "--start-date-time")
    with pytest.raises(ValueError, match="requires a date"):
        _parse_date_time_arg("9:30", "--start-date-time")


def test_parse_date_time_arg_rejects_unsupported_formats():
    with pytest.raises(ValueError, match="must be YYYY-MM-DD"):
        _parse_date_time_arg("15/06/2026 09:30", "--start-date-time")


def test_set_enum_field_actions_build_field_specific_commands():
    assert _build_tracker_command(
        _arguments(set_external_coordination=True, ticket_number=[67], external_coordination="Yes")
    ) == {
        "command": "set_task_external_coordination",
        "task_id": "ALOVYA-67",
        "external_coordination": "Yes",
    }
    assert _build_tracker_command(
        _arguments(set_uncertainty=True, ticket_number=[67], uncertainty="High")
    ) == {
        "command": "set_task_uncertainty",
        "task_id": "ALOVYA-67",
        "uncertainty": "High",
    }
    assert _build_tracker_command(
        _arguments(set_friction=True, ticket_number=[67], friction="Stale")
    ) == {
        "command": "set_task_friction",
        "task_id": "ALOVYA-67",
        "friction": "Stale",
    }


def test_synthesis_action_keeps_rich_sources_inside_content_payload(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "summary": "Reusable tracker CLI design.",
            "sources": [
                {
                    "source_type": "Notion page",
                    "label": "ALOVYA-67",
                    "page_key": "task:ALOVYA-67",
                }
            ],
            "lines": ["Actions freeze schemas; content remains free-form."],
        }),
        encoding="utf-8",
    )

    command = _build_tracker_command(
        _arguments(
            synth=True,
            synthesis_key="explicit_tracker_cli",
            title=["Explicit tracker CLI"],
            content_path=str(content_path),
        )
    )

    assert command == {
        "command": "create_synthesis_page",
        "synthesis_key": "explicit_tracker_cli",
        "title": "Explicit tracker CLI",
        "summary": "Reusable tracker CLI design.",
        "sources": [
            {
                "source_type": "Notion page",
                "label": "ALOVYA-67",
                "page_key": "task:ALOVYA-67",
            }
        ],
        "lines": ["Actions freeze schemas; content remains free-form."],
    }


def test_ticket_ids_from_numbers_rejects_invalid_ticket_numbers():
    with pytest.raises(ValueError) as error:
        ticket_ids_from_numbers([0], "ALOVYA")

    assert str(error.value) == "Ticket numbers must be positive"


def test_build_move_logs_command_keeps_log_selection_optional():
    command = _build_tracker_command(_arguments(
        move_logs=True,
        ticket_number=[21],
        destination_ticket_number=25,
        log_id="ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0",
    ))

    assert command == {
        "command": "move_task_timeline_log",
        "source_task_id": "ALOVYA-21",
        "destination_task_id": "ALOVYA-25",
        "log_id": "ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0",
    }


def _build_tracker_command(arguments: Namespace, ticket_prefix: str = "ALOVYA") -> dict:
    return build_tracker_command_from_cli_action(arguments, ticket_prefix=ticket_prefix)


def _assert_uuid4_log_id(log_id: str, ticket_prefix: str = "ALOVYA") -> None:
    expected_log_id_prefix = f"{ticket_prefix}-LOG-"
    assert log_id.startswith(expected_log_id_prefix)
    uuid_value = UUID(log_id.removeprefix(expected_log_id_prefix))
    assert uuid_value.version == 4


def _arguments(**overrides):
    values = {
        "reconcile_from_notion": False,
        "read": False,
        "work": False,
        "log": False,
        "complete": False,
        "complete_with_all_children": False,
        "cancel": False,
        "delete": False,
        "set_dependencies": False,
        "set_dependants": False,
        "set_deadline": False,
        "clear_deadline": False,
        "set_start_date_time": False,
        "clear_start_date_time": False,
        "set_end_date_time": False,
        "clear_end_date_time": False,
        "set_external_coordination": False,
        "set_uncertainty": False,
        "set_friction": False,
        "reparent": False,
        "parent": False,
        "child": False,
        "sibling": False,
        "misc": False,
        "synth": False,
        "move_logs": False,
        "ticket_number": [],
        "parent_ticket_number": None,
        "sibling_ticket_number": None,
        "title": None,
        "priority": DEFAULT_TASK_PRIORITY.value,
        "dependency_ticket_number": [],
        "dependant_ticket_number": [],
        "deadline": None,
        "start_date_time": None,
        "end_date_time": None,
        "external_coordination": None,
        "uncertainty": None,
        "friction": None,
        "content_path": None,
        "synthesis_key": None,
        "entry_date": "2026-05-30",
        "destination_ticket_number": None,
        "log_id": None,
    }
    values.update(overrides)
    return Namespace(**values)
