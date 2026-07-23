import asyncio
import json
from pathlib import Path

import pytest

import notion_task_tracker.run_notion_task_tracker as run_notion_task_tracker
from notion_task_tracker import COMPLETED_LANDING_PAGE_TITLE, ONGOING_LANDING_PAGE_TITLE
from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.config import ManagedPageUrls, TrackerConfig
from notion_task_tracker.notion_operations.rest_client import NotionWriteExecutionResult
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from tests.notion_operations.helpers import FakeNotionClient
from tests.tasks.build_task_command_fixtures import build_fetched_task_page, build_tracker_state_with_root_task
from notion_task_tracker.tasks import DEFAULT_TASK_PRIORITY
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DEADLINE_PROPERTY,
    TASK_DATABASE_DEPENDENCIES_PROPERTY,
    TASK_DATABASE_DEPENDANTS_PROPERTY,
    TASK_DATABASE_DURATION_PROPERTY,
    TASK_DATABASE_DURATION_UNIT_PROPERTY,
    TASK_DATABASE_END_PROPERTY,
    TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
    TASK_DATABASE_FRICTION_PROPERTY,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_START_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_DATABASE_UNCERTAINTY_PROPERTY,
)
from notion_task_tracker.run_notion_task_tracker import (
    DEFAULT_TRACKER_STATE_PATH,
    _action_name_from_tracker_command,
    _command_changes_task_relations,
    _run_refresh_notion_task_tracker_command,
    _run_write_tracker_command,
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


def test_parse_args_reads_full_page_action():
    args = parse_args(["--read-all", "--ticket-number", "67"])

    assert args.read_all is True
    assert args.ticket_number == [67]


def test_parse_args_reads_install_skill_action():
    args = parse_args(["--install-skill"])

    assert args.install_skill is True


def test_parse_args_reads_sync_tasks_to_google_calendar_action():
    args = parse_args(["--sync-tasks-to-google-calendar"])

    assert args.sync_tasks_to_google_calendar is True


def test_parse_args_reads_notification_channel_maintenance_identity():
    args = parse_args([
        "--maintain-google-calendar-notification-channel",
        "--tracker-user",
        "al0vya",
        "--calendar-notification-url",
        "https://worker.example/google-calendar-notifications",
    ])

    assert args.maintain_google_calendar_notification_channel is True
    assert args.tracker_user == "al0vya"
    assert args.calendar_notification_url.endswith("/google-calendar-notifications")


def test_parse_args_reads_google_calendar_change_tracker_identity():
    args = parse_args([
        "--apply-google-calendar-changes-to-tasks",
        "--tracker-user",
        "al0vya",
    ])

    assert args.apply_google_calendar_changes_to_tasks is True
    assert args.tracker_user == "al0vya"


def test_parse_args_reads_initialise_action_and_configuration():
    args = parse_args([
        "--init",
        "--display-name", "Alovya",
        "--ticket-prefix", "ALOVYA",
        "--parent-page-url", "https://www.notion.so/parent",
        "--task-database-url", "https://www.notion.so/database",
    ])

    assert args.init is True
    assert args.display_name == "Alovya"
    assert args.ticket_prefix == "ALOVYA"


def test_parse_args_collects_repeated_titles():
    args = parse_args(["--child", "--parent-ticket-number", "67", "--title", "One"])

    assert args.title == ["One"]


def test_parse_args_uses_default_task_priority():
    args = parse_args(["--parent", "--title", "Default priority task"])

    assert args.priority == DEFAULT_TASK_PRIORITY.value


def test_parse_args_reads_reparent_action():
    args = parse_args(["--reparent", "--ticket-number", "68", "--parent-ticket-number", "67"])

    assert args.reparent is True
    assert args.ticket_number == [68]
    assert args.parent_ticket_number == 67


def test_parse_args_reads_complete_with_all_children_action():
    args = parse_args(["--complete-with-all-children", "--ticket-number", "67"])

    assert args.complete_with_all_children is True
    assert args.ticket_number == [67]


def test_parse_args_reads_delete_action():
    args = parse_args(["--delete", "--ticket-number", "67"])

    assert args.delete is True
    assert args.ticket_number == [67]


def test_parse_args_reads_move_logs_action_and_selection():
    args = parse_args([
        "--move-logs",
        "--ticket-number", "21",
        "--destination-ticket-number", "25",
        "--log-id", "ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0",
    ])

    assert args.move_logs is True
    assert args.ticket_number == [21]
    assert args.destination_ticket_number == 25


def test_delete_command_reports_delete_action_name():
    assert _action_name_from_tracker_command({"command": "delete_task"}) == "delete"


def test_main_rejects_removed_transport_flag():
    with pytest.raises(SystemExit) as error:
        main(["--notion-" + "transport", "removed"])

    assert error.value.code == 2


def test_main_rejects_removed_token_file_flag():
    with pytest.raises(SystemExit) as error:
        main(["--credentials-" + "path", "credentials.json"])

    assert error.value.code == 2


def test_main_rejects_unknown_flag():
    with pytest.raises(SystemExit) as error:
        main(["--unknown-flag", "result.json"])

    assert error.value.code == 2


def test_main_exits_non_zero_when_refresh_refuses_unsafe_state(monkeypatch, capsys):
    refusal_message = "Notion page changed task identity; refusing to refresh"

    def _refuse_unsafe_refresh(args):
        raise ValueError(refusal_message)

    monkeypatch.setattr(
        run_notion_task_tracker,
        "_run_requested_cli_action",
        _refuse_unsafe_refresh,
    )

    with pytest.raises(SystemExit) as error:
        main(["--refresh-notion-task-tracker"])

    assert error.value.code == 2
    assert capsys.readouterr().err == f"{refusal_message}\n"


def test_relation_command_uses_its_consistent_local_result_for_landing_pages():
    command_result = TrackerCommandResult(
        tracker_state={},
        write_intents=[
            NotionWriteIntent(
                operation_key="update_dependencies:task:ALOVYA-2",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-2",
                arguments={"properties": {}},
            )
        ],
    )

    assert _command_changes_task_relations(command_result) is True


def test_default_tracker_paths_are_constant_app_paths():
    assert resolve_tracker_state_path() == DEFAULT_TRACKER_STATE_PATH
    assert resolve_tracker_state_path() == Path.home() / ".notion-task-tracker" / "notion_tasks_tree.json"


def test_explicit_tracker_paths_override_defaults(tmp_path: Path):
    tracker_state_path = tmp_path / "explicit_state.json"

    assert resolve_tracker_state_path(tracker_state_path) == tracker_state_path


def test_repair_and_write_refreshed_tracker_state_pushes_repairs_for_changed_task(
    tmp_path: Path,
):
    notion_client = _FakeNotionClient(
        ongoing_landing_markdown="\n".join([
            "## P1 (high impact)",
            (
                '- [P1] <mention-page url="https://www.notion.so/'
                '22222222222222222222222222222222"/>: Active {color="orange"}'
            ),
        ])
    )
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
        "action_name": "refresh_notion_task_tracker",
        "backup_path": str(backup_path),
        "completed_operations": [
            "update_properties:task:ALOVYA-1",
            "replace:ongoing_landing_page",
        ],
        "output_path": str(output_path),
        "tracker_state_path": str(tracker_state_path),
        "task_count": 1,
        "repair_operation_count": 2,
        "task_tree_changes": [
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


def test_repair_and_write_refreshed_tracker_state_skips_landing_pages_when_nothing_changed(
    tmp_path: Path,
):
    notion_client = _FakeNotionClient(
        ongoing_landing_markdown="\n".join([
            "## P1 (high impact)",
            (
                '- [P1] <mention-page url="https://www.notion.so/'
                '22222222222222222222222222222222"/>: Active {color="orange"}'
            ),
        ])
    )
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
    assert refresh_summary.to_json_summary()["task_tree_changes"] == []
    assert refresh_summary.to_json_summary()["repair_operation_count"] == 0


def test_write_command_renders_landing_pages_from_fully_refreshed_database_state(tmp_path: Path):
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Task page": "Remote priority task",
                "Task ID": "1",
                "Priority": "P2",
                "Status": "Active",
                "Parent": "[]",
                "Dependencies": "[]",
                "Dependants": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            },
            {
                "Task page": "Touched task",
                "Task ID": "2",
                "Priority": "P1",
                "Status": "Complete",
                "Parent": "[]",
                "Dependencies": "[]",
                "Dependants": "[]",
                "Deadline": "",
                "External coordination": "No",
                "Uncertainty": "Low",
                "Friction": "None",
                "url": "https://www.notion.so/33333333333333333333333333333333",
            },
        ],
        fetched_page_content_by_id={
            "33333333333333333333333333333333": build_fetched_task_page(
                ticket_id="2",
                title="Touched task",
                priority="P1",
                status="Active",
                parent_urls=[],
            )
        },
    )
    tracker_state = _tracker_state_with_stale_task_and_touched_task()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    tracker_state_path.write_text(json.dumps(tracker_state), encoding="utf-8")

    asyncio.run(
        _run_write_tracker_command(
            command={
                "command": "complete_task",
                "task_id": "ALOVYA-2",
                "timeline_entry": {
                    "log_id": "ALOVYA-LOG-00000000-0000-4000-8000-000000000001",
                    "title": "Completed touched task",
                    "entry_date": "2026-07-16",
                    "heading": '<mention-date start="2026-07-16"/>',
                    "lines": ["Completed the touched task."],
                },
            },
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            backup_path=backup_path,
            notion_client=notion_client,
        )
    )

    refreshed_tracker_state = json.loads(tracker_state_path.read_text(encoding="utf-8"))
    ongoing_landing_markdown = _markdown_for_call(notion_client, "replace:ongoing_landing_page")
    completed_landing_markdown = _markdown_for_call(notion_client, "replace:completed_landing_page")
    assert refreshed_tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert refreshed_tracker_state["tasks"]["ALOVYA-2"]["status"] == "Complete"
    assert "[P2]" in ongoing_landing_markdown
    assert "22222222222222222222222222222222" in ongoing_landing_markdown
    assert "[P1]" not in ongoing_landing_markdown
    assert "33333333333333333333333333333333" in completed_landing_markdown
    assert notion_client.execution_order_membership_updates == [
        (
            "22222222222222222222222222222222",
            {"In execution order": {"checkbox": True}},
        ),
        (
            "33333333333333333333333333333333",
            {"In execution order": {"checkbox": False}},
        ),
    ]


def test_refresh_notion_task_tracker_creates_missing_tracker_state_from_configuration(tmp_path: Path):
    notion_client = _ConfiguredTrackerRefreshClient()
    tracker_state_path = tmp_path / "notion_tasks_tree.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"

    refresh_summary = asyncio.run(
        _run_refresh_notion_task_tracker_command(
            config=_configured_tracker(),
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            backup_path=backup_path,
            notion_client=notion_client,
        )
    )

    tracker_state = json.loads(tracker_state_path.read_text(encoding="utf-8"))
    backed_up_tracker_state = json.loads(backup_path.read_text(encoding="utf-8"))
    assert tracker_state["identity"] == {"display_name": "Alovya", "ticket_prefix": "ALOVYA"}
    assert tracker_state["task_database"]["data_source_id"] == "cccccccccccccccccccccccccccccccc"
    assert tracker_state["ongoing_landing_page"]["notion_page_id"] == "dddddddddddddddddddddddddddddddd"
    assert tracker_state["completed_landing_page"]["notion_page_id"] == "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    assert tracker_state["ready_priority_page"]["notion_page_id"] == "77777777777777777777777777777777"
    assert tracker_state["miscellaneous_notes"]["page"]["notion_page_id"] == (
        "ffffffffffffffffffffffffffffffff"
    )
    assert tracker_state["synthesis_notes"]["page"]["notion_page_id"] == (
        "99999999999999999999999999999999"
    )
    assert tracker_state["tasks"] == {}
    assert backed_up_tracker_state == tracker_state
    assert notion_client.created_pages == []
    assert notion_client.write_intents == []
    assert refresh_summary.to_json_summary()["completed_operations"] == [
        "create:task_database_property:in_execution_order",
        "create:ready_priority_page:linked_database_view",
    ]
    assert json.loads(output_path.read_text(encoding="utf-8"))["task_count"] == 0


def test_refresh_notion_task_tracker_rejects_missing_configured_page_url(tmp_path: Path):
    with pytest.raises(ValueError, match="synthesis_notes_url"):
        asyncio.run(
            _run_refresh_notion_task_tracker_command(
                config=_configured_tracker(synthesis_notes_url=None),
                tracker_state_path=tmp_path / "notion_tasks_tree.json",
                output_path=tmp_path / "output.json",
                backup_path=tmp_path / "backup.json",
                notion_client=_ConfiguredTrackerRefreshClient(),
            )
        )


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
                    "Task page": "Read task summaries",
                    "Task ID": "1",
                    "Priority": "P2",
                    "Status": "Active",
                    "Parent": "[]",
                    "Dependencies": "[]",
                    "Deadline": "",
                    "External coordination": "No",
                    "Uncertainty": "Low",
                    "Friction": "None",
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


def test_read_all_task_pages_includes_complete_fetched_page_content(tmp_path: Path):
    tracker_state = build_tracker_state_with_root_task()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "read_all.json"
    tracker_state_path.write_text(json.dumps(tracker_state), encoding="utf-8")
    full_page_content = "\n".join([
        "<page>",
        "<properties>",
        json.dumps({
            "Task page": "Read complete task page",
            "Task ID": "1",
            "Priority": "P2",
            "Status": "Active",
            "Parent": "[]",
            "Dependencies": "[]",
            "Deadline": "",
            "External coordination": "No",
            "Uncertainty": "Low",
            "Friction": "None",
            "url": "https://www.notion.so/Read-complete-task-page-22222222222222222222222222222222",
        }),
        "</properties>",
        "<content>",
        "First line.",
        "Second line.",
        "Third line.",
        "Fourth line.",
        "Fifth line.",
        "Decided to target Google Calendar API directly.",
        "</content>",
        "</page>",
    ])
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": full_page_content,
        }
    )

    read_summary = asyncio.run(
        _run_read_task_pages(
            action_name="read_all",
            task_ids=["ALOVYA-1"],
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            notion_client=notion_client,
            include_full_page_content=True,
        )
    )

    task_summary = read_summary.to_json_summary()["tasks"][0]
    assert task_summary["summary"] == [
        "First line.",
        "Second line.",
        "Third line.",
        "Fourth line.",
        "Fifth line.",
    ]
    assert task_summary["full_page_content"] == full_page_content
    written_task_summary = json.loads(output_path.read_text(encoding="utf-8"))["tasks"][0]
    assert written_task_summary["full_page_content"] == full_page_content
    assert notion_client.calls == []


class _FakeNotionClient:
    def __init__(
        self,
        ongoing_landing_markdown: str,
        completed_landing_markdown: str = "No completed tasks yet.",
    ):
        self.write_intents = []
        self.landing_markdown_by_page_id = {
            "11111111111111111111111111111111": ongoing_landing_markdown,
            "44444444444444444444444444444444": completed_landing_markdown,
        }

    async def execute_command_result(self, command_result: TrackerCommandResult):
        self.write_intents.extend(command_result.write_intents)
        return NotionWriteExecutionResult(
            completed_operation_keys=[
                write_intent.operation_key
                for write_intent in command_result.write_intents
            ],
        )

    async def fetch_block_children(self, parent_block_id: str) -> list[dict]:
        assert parent_block_id == "99999999999999999999999999999999"
        return [{"id": "linked-database", "type": "child_database"}]

    async def ensure_checkbox_property(self, data_source_id: str, property_name: str):
        return ({property_name: {"id": "execution-order-property"}}, False)

    async def query_checkbox_page_ids(self, data_source_id: str, property_name: str):
        return {"22222222222222222222222222222222"}

    async def fetch_page_markdown(self, page_id: str) -> str:
        return self.landing_markdown_by_page_id[page_id]


class _ConfiguredTrackerRefreshClient:
    def __init__(self) -> None:
        self.created_pages: list[dict] = []
        self.write_intents = []

    async def fetch_database(self, database_id: str) -> dict:
        assert database_id == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        return {"data_sources": [{"id": "cccccccccccccccccccccccccccccccc"}]}

    async def fetch_data_source(self, data_source_id: str) -> dict:
        assert data_source_id == "cccccccccccccccccccccccccccccccc"
        return {"properties": _fixed_database_properties()}

    async def query_task_database_rows(self, tracker_state: dict) -> list[dict]:
        assert tracker_state["task_database"]["data_source_id"] == "cccccccccccccccccccccccccccccccc"
        return []

    async def fetch_page_markdown(self, page_id: str) -> str:
        if page_id == "dddddddddddddddddddddddddddddddd":
            return ""
        if page_id == "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            return "No completed tasks yet."
        raise AssertionError(f"Unexpected managed page {page_id}")

    async def execute_command_result(self, command_result: TrackerCommandResult):
        self.write_intents.extend(command_result.write_intents)
        return NotionWriteExecutionResult(
            completed_operation_keys=[
                write_intent.operation_key
                for write_intent in command_result.write_intents
            ],
        )

    async def fetch_block_children(self, parent_block_id: str) -> list[dict]:
        assert parent_block_id == "77777777777777777777777777777777"
        return []

    async def ensure_checkbox_property(self, data_source_id: str, property_name: str):
        properties = {
            **_fixed_database_properties(),
            property_name: {"id": "execution-order-property", "type": "checkbox"},
        }
        for property_name, property_definition in properties.items():
            property_definition.setdefault("id", property_name)
        return properties, True

    async def create_linked_execution_order_view(self, **arguments):
        self.created_linked_view = arguments

    async def query_checkbox_page_ids(self, data_source_id: str, property_name: str):
        return set()

    async def create_page(self, parent: dict, properties: dict, markdown: str) -> dict:
        self.created_pages.append(
            {"parent": parent, "properties": properties, "markdown": markdown}
        )
        raise AssertionError("Refreshing tracker state must not create managed pages")


def _tracker_state(title: str, priority: str) -> dict:
    return {
        "task_database": {"data_source_id": "88888888888888888888888888888888"},
        "ongoing_landing_page": {
            "local_page_key": "ongoing_landing_page",
            "title": ONGOING_LANDING_PAGE_TITLE,
            "notion_page_id": "11111111111111111111111111111111",
            "parent_page_key": None,
        },
        "completed_landing_page": {
            "local_page_key": "completed_landing_page",
            "title": COMPLETED_LANDING_PAGE_TITLE,
            "notion_page_id": "44444444444444444444444444444444",
            "parent_page_key": None,
        },
        "ready_priority_page": {
            "local_page_key": "ready_priority_page",
            "title": "Tasks in execution order",
            "notion_page_id": "99999999999999999999999999999999",
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
                "dependency_task_ids": [],
                "dependant_task_ids": [],
                "deadline": None,
                "start": None,
                "end": None,
                "duration": None,
                "duration_unit": None,
                "external_coordination": "No",
                "uncertainty": "Low",
                "friction": "None",
                "timeline_entries": [],
                "links": [],
                "notion_page_id": "22222222222222222222222222222222",
            }
        },
    }


def _tracker_state_with_stale_task_and_touched_task() -> dict:
    tracker_state = _tracker_state(title="Stale priority task", priority="P1")
    tracker_state["identity"] = {"display_name": "Alovya", "ticket_prefix": "ALOVYA"}
    tracker_state["task_database"] = {"data_source_id": "configured-data-source-id"}
    tracker_state["completed_landing_page"]["notion_page_id"] = "44444444444444444444444444444444"
    tracker_state["tasks"]["ALOVYA-2"] = {
        **tracker_state["tasks"]["ALOVYA-1"],
        "task_id": "ALOVYA-2",
        "title": "Touched task",
        "notion_page_id": "33333333333333333333333333333333",
    }
    return tracker_state


def _markdown_for_call(notion_client: FakeNotionClient, operation_key: str) -> str:
    for notion_call in reversed(notion_client.calls):
        if notion_call.operation_key == operation_key:
            return notion_call.arguments["markdown"]

    raise AssertionError(f"Expected Notion call {operation_key!r}")


def _configured_tracker(
    synthesis_notes_url: str | None = "https://www.notion.so/synthesis-99999999999999999999999999999999",
    ready_priority_page_url: str | None = "https://www.notion.so/priorities-77777777777777777777777777777777",
) -> TrackerConfig:
    return TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/parent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        task_database_url="https://www.notion.so/tasks-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        pages=ManagedPageUrls(
            ongoing_tasks_url="https://www.notion.so/ongoing-dddddddddddddddddddddddddddddddd",
            completed_tasks_url="https://www.notion.so/completed-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            ready_priority_page_url=ready_priority_page_url,
            miscellaneous_notes_url="https://www.notion.so/misc-ffffffffffffffffffffffffffffffff",
            synthesis_notes_url=synthesis_notes_url,
        ),
    )


def _fixed_database_properties() -> dict[str, dict[str, str]]:
    return {
        TASK_DATABASE_TITLE_PROPERTY: {"type": "title"},
        TASK_DATABASE_TICKET_ID_PROPERTY: {"type": "unique_id"},
        TASK_DATABASE_PRIORITY_PROPERTY: {"type": "select"},
        TASK_DATABASE_STATUS_PROPERTY: {"type": "select"},
        TASK_DATABASE_PARENT_PROPERTY: {"type": "relation"},
        TASK_DATABASE_DEPENDENCIES_PROPERTY: {"type": "relation"},
        TASK_DATABASE_DEPENDANTS_PROPERTY: {"type": "relation"},
        TASK_DATABASE_DEADLINE_PROPERTY: {"type": "date"},
        TASK_DATABASE_START_PROPERTY: {"type": "date"},
        TASK_DATABASE_END_PROPERTY: {"type": "date"},
        TASK_DATABASE_DURATION_PROPERTY: {"type": "number"},
        TASK_DATABASE_DURATION_UNIT_PROPERTY: {"type": "select"},
        TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY: {"type": "select"},
        TASK_DATABASE_UNCERTAINTY_PROPERTY: {"type": "select"},
        TASK_DATABASE_FRICTION_PROPERTY: {"type": "select"},
    }
