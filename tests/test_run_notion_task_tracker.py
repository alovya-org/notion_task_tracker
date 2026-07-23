import json

import pytest

from notion_task_tracker.run_notion_task_tracker import (
    _action_name_from_tracker_command,
    _write_task_action_summary,
    parse_args,
)
from notion_task_tracker.tasks import DEFAULT_TASK_PRIORITY


def test_parse_args_reads_explicit_read_action():
    arguments = parse_args([
        "--read",
        "--ticket-number",
        "67",
        "--ticket-number",
        "68",
    ])

    assert arguments.read is True
    assert arguments.ticket_number == [67, 68]


def test_parse_args_reads_full_page_action():
    arguments = parse_args(["--read-all", "--ticket-number", "67"])

    assert arguments.read_all is True
    assert arguments.ticket_number == [67]


def test_parse_args_reads_two_way_google_calendar_synchronisation_action():
    arguments = parse_args([
        "--synchronise-notion-task-tracker-with-google-calendar"
    ])

    assert arguments.synchronise_notion_task_tracker_with_google_calendar is True


def test_parse_args_reads_notification_channel_maintenance_identity():
    arguments = parse_args([
        "--maintain-google-calendar-notification-channel",
        "--tracker-user",
        "al0vya",
        "--calendar-notification-url",
        "https://worker.example/google-calendar-notifications",
    ])

    assert arguments.maintain_google_calendar_notification_channel is True
    assert arguments.tracker_user == "al0vya"
    assert arguments.calendar_notification_url.endswith(
        "/google-calendar-notifications"
    )


def test_parse_args_reads_initialise_action_and_configuration():
    arguments = parse_args([
        "--init",
        "--display-name",
        "Alovya",
        "--ticket-prefix",
        "ALOVYA",
        "--parent-page-url",
        "https://www.notion.so/parent",
        "--task-database-url",
        "https://www.notion.so/database",
    ])

    assert arguments.init is True
    assert arguments.display_name == "Alovya"
    assert arguments.ticket_prefix == "ALOVYA"


def test_parse_args_uses_default_task_priority():
    assert parse_args(["--parent", "--title", "One"]).priority == (
        DEFAULT_TASK_PRIORITY.value
    )


def test_parse_args_reads_complete_with_all_children_action():
    arguments = parse_args([
        "--complete-with-all-children",
        "--ticket-number",
        "67",
    ])

    assert arguments.complete_with_all_children is True


def test_delete_command_reports_delete_action_name():
    assert _action_name_from_tracker_command({"command": "delete_task"}) == "delete"


def test_task_mutation_summary_reports_completed_notion_operations(tmp_path):
    output_path = tmp_path / "result.json"

    summary = _write_task_action_summary(
        action_name="set_start",
        output_path=output_path,
        notion_operation_keys=["set_start:task:ALOVYA-102"],
        warnings=[],
    )

    expected_summary = {
        "action_name": "set_start",
        "notion_operations": ["set_start:task:ALOVYA-102"],
        "output_path": str(output_path),
        "warnings": [],
    }
    assert summary.to_json_summary() == expected_summary
    assert json.loads(output_path.read_text(encoding="utf-8")) == expected_summary


@pytest.mark.parametrize(
    "removed_flag",
    [
        "--tracker-state-path",
        "--transport",
        "--token-file",
        "--misc",
        "--synth",
    ],
)
def test_parse_args_rejects_removed_flags(removed_flag):
    with pytest.raises(SystemExit):
        parse_args([removed_flag, "obsolete"])
