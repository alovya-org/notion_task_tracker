import asyncio
import json
from pathlib import Path

import pytest

from notion_task_tracker import COMPLETED_LANDING_PAGE_TITLE, ONGOING_LANDING_PAGE_TITLE
from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_operations.client import NotionWriteExecutionResult
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import build_tracker_state_with_root_task
from notion_task_tracker.run_notion_task_tracker import (
    DEFAULT_TRACKER_STATE_PATH,
    _run_read_task_pages,
    main,
    parse_args,
    resolve_tracker_state_path,
    repair_and_write_refreshed_tracker_state,
)


def test_parse_args_reads_explicit_read_action():
    args = parse_args(["--read", "--ticket-number", "67", "--ticket-number", "68"])

    assert args.read is True
    assert args.ticket_number == [67, 68]


def test_parse_args_reads_install_skill_action():
    args = parse_args(["--install-skill"])

    assert args.install_skill is True


def test_main_rejects_removed_notion_transport_flag():
    with pytest.raises(SystemExit) as error:
        main(["--notion-transport", "mcp"])

    assert error.value.code == 2


def test_main_rejects_removed_credentials_path_flag():
    with pytest.raises(SystemExit) as error:
        main(["--credentials-path", "credentials.json"])

    assert error.value.code == 2


def test_main_rejects_unknown_flag():
    with pytest.raises(SystemExit) as error:
        main(["--unknown-flag", "result.json"])

    assert error.value.code == 2


def test_default_tracker_paths_are_constant_app_paths():
    assert resolve_tracker_state_path() == DEFAULT_TRACKER_STATE_PATH
    assert resolve_tracker_state_path() == Path.home() / ".notion-task-tracker" / "notion_tasks_graph.json"


def test_explicit_tracker_paths_override_defaults(tmp_path: Path):
    tracker_state_path = tmp_path / "explicit_state.json"

    assert resolve_tracker_state_path(tracker_state_path) == tracker_state_path


def test_repair_and_write_refreshed_tracker_state_pushes_repairs_for_changed_task(
    tmp_path: Path,
):
    notion_client = _FakeNotionClient()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    before_tracker_state = _tracker_state(title="Investigate baseline behaviour", priority="P1")
    after_tracker_state = _tracker_state(title="Investigate edited behaviour", priority="P2")
    tracker_state_path.write_text(json.dumps(before_tracker_state), encoding="utf-8")
    backup_path.write_text(json.dumps(before_tracker_state), encoding="utf-8")

    refresh_summary = asyncio.run(
        repair_and_write_refreshed_tracker_state(
            source_tracker_state_path=tracker_state_path,
            destination_output_path=output_path,
            destination_backup_path=backup_path,
            before_tracker_state=before_tracker_state,
            refreshed_result=TrackerCommandResult(
                tracker_state=after_tracker_state,
                warnings=[{"kind": "manual_repair", "message": "Derived Notion views need repair"}],
            ),
            notion_client=notion_client,
        ),
    )

    assert json.loads(backup_path.read_text(encoding="utf-8")) == before_tracker_state
    assert json.loads(tracker_state_path.read_text(encoding="utf-8")) == after_tracker_state
    assert [write_intent.operation_key for write_intent in notion_client.write_intents] == [
        "update_properties:task:ALOVYA-1",
        "replace:ongoing_landing_page",
    ]
    assert json.loads(output_path.read_text(encoding="utf-8"))["completed_operations"] == [
        "update_properties:task:ALOVYA-1",
        "replace:ongoing_landing_page",
    ]
    assert refresh_summary.to_json_summary() == {
        "action_name": "reconcile_from_notion",
        "backup_path": str(backup_path),
        "completed_operations": [
            "update_properties:task:ALOVYA-1",
            "replace:ongoing_landing_page",
        ],
        "output_path": str(output_path),
        "tracker_state_path": str(tracker_state_path),
        "task_count": 1,
        "repair_operation_count": 2,
        "task_graph_changes": [
            {
                "task_id": "ALOVYA-1",
                "fields": {
                    "configured_priority": {"before": "P1", "after": "P2"},
                    "title": {
                        "before": "Investigate baseline behaviour",
                        "after": "Investigate edited behaviour",
                    },
                },
            }
        ],
        "warnings": [{"kind": "manual_repair", "message": "Derived Notion views need repair"}],
    }


def test_repair_and_write_refreshed_tracker_state_skips_repairs_when_nothing_changed(
    tmp_path: Path,
):
    notion_client = _FakeNotionClient()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    tracker_state = _tracker_state(title="Stable task", priority="P1")
    tracker_state_path.write_text(json.dumps(tracker_state), encoding="utf-8")
    backup_path.write_text(json.dumps(tracker_state), encoding="utf-8")

    refresh_summary = asyncio.run(
        repair_and_write_refreshed_tracker_state(
            source_tracker_state_path=tracker_state_path,
            destination_output_path=output_path,
            destination_backup_path=backup_path,
            before_tracker_state=tracker_state,
            refreshed_result=TrackerCommandResult(
                tracker_state=tracker_state,
                warnings=[],
            ),
            notion_client=notion_client,
        ),
    )

    assert json.loads(output_path.read_text(encoding="utf-8"))["completed_operations"] == []
    assert notion_client.write_intents == []
    assert refresh_summary.to_json_summary()["task_graph_changes"] == []
    assert refresh_summary.to_json_summary()["repair_operation_count"] == 0


def test_read_task_pages_fetches_live_pages_and_writes_summary_without_notion_writes(tmp_path: Path):
    tracker_state = build_tracker_state_with_root_task()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "read_summary.json"
    tracker_state_path.write_text(json.dumps(tracker_state), encoding="utf-8")

    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join([
                "<page>",
                "<properties>",
                json.dumps({
                    "Ticket page": "Read task summaries",
                    "Ticket ID": "1",
                    "Priority": "P2",
                    "Status": "Active",
                    "Parent": "[]",
                    "url": "https://www.notion.so/Read-task-summaries-22222222222222222222222222222222",
                }),
                "</properties>",
                "<content>",
                "## Timeline log",
                '### <mention-date start="2026-05-30"/>',
                "- Added read-only summary behaviour.",
                "</content>",
                "</page>",
            ]),
        }
    )

    read_summary = asyncio.run(
        _run_read_task_pages(
            action_name="read",
            task_ids=["ALOVYA-1"],
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            notion_client=notion_client,
        )
    )

    summary = read_summary.to_json_summary()
    assert summary["tasks"][0]["task_id"] == "ALOVYA-1"
    assert summary["tasks"][0]["title"] == "Read task summaries"
    assert summary["tasks"][0]["configured_priority"] == "P2"
    assert summary["tasks"][0]["recent_timeline_headings"] == ['<mention-date start="2026-05-30"/>']
    assert summary["tasks"][0]["summary"] == ["Added read-only summary behaviour."]
    assert json.loads(output_path.read_text(encoding="utf-8")) == summary
    assert notion_client.calls == []


class _FakeNotionClient:
    def __init__(self):
        self.write_intents = []

    async def execute_command_result(self, command_result: TrackerCommandResult):
        self.write_intents.extend(command_result.write_intents)
        return NotionWriteExecutionResult(
            completed_operation_keys=[
                write_intent.operation_key
                for write_intent in command_result.write_intents
            ],
        )


def _tracker_state(title: str, priority: str) -> dict:
    return {
        "ongoing_landing_page": {
            "local_page_key": "ongoing_landing_page",
            "title": ONGOING_LANDING_PAGE_TITLE,
            "notion_page_id": "11111111111111111111111111111111",
            "parent_page_key": None,
        },
        "completed_landing_page": {
            "local_page_key": "completed_landing_page",
            "title": COMPLETED_LANDING_PAGE_TITLE,
            "notion_page_id": None,
            "parent_page_key": None,
        },
        "tasks": {
            "ALOVYA-1": {
                "task_id": "ALOVYA-1",
                "title": title,
                "configured_priority": priority,
                "displayed_priority": priority,
                "status": "Active",
                "status_update": "",
                "parent_task_id": None,
                "child_task_ids": [],
                "timeline_entries": [],
                "links": [],
                "notion_page_id": "22222222222222222222222222222222",
            }
        },
    }
