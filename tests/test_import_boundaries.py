from pathlib import Path


PACKAGE_PATH = Path(__file__).resolve().parents[1] / "notion_task_tracker"


def test_rest_client_does_not_import_removed_transport_symbols():
    source = _source("notion_operations/rest_client.py")

    removed_transport_name = "m" + "cp"
    assert f"notion_task_tracker.{removed_transport_name}" not in source
    assert f"Notion{removed_transport_name.title()}" not in source


def test_package_has_no_removed_transport_runtime_imports():
    removed_transport_name = "m" + "cp"
    removed_transport_title = removed_transport_name.title()
    forbidden_text = [
        f"{removed_transport_name}_client",
        f"Notion{removed_transport_title}",
        f"Notion{removed_transport_title}ToolCall",
        f"Notion{removed_transport_title}CallPlanner",
    ]

    for source_path in PACKAGE_PATH.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert not any(forbidden in source for forbidden in forbidden_text), source_path


def test_workflow_modules_do_not_import_notion_protocol_details():
    forbidden_text = [
        "Notion" + ("m" + "cp").title() + "ToolCall",
        "Notion" + ("m" + "cp").title() + "CallPlanner",
        "NotionRestClient",
        "execute_write_intent",
        "send_call",
    ]
    workflow_files = [
        "run_notion_task_tracker.py",
        "notion_operations/write_executor.py",
    ]

    for workflow_file in workflow_files:
        source = _source(workflow_file)
        assert not any(forbidden in source for forbidden in forbidden_text), workflow_file


def test_tracker_metadata_modules_do_not_import_notion_operations():
    metadata_files = [
        "tasks/task.py",
        "tasks/dependency_graph.py",
        "tasks/database.py",
        "tasks/landing_pages.py",
        "tasks/timeline_log.py",
        "tasks/create_task.py",
        "tasks/derive_task_timeline_log.py",
        "tasks/refresh_task_tracker_state.py",
        "miscellaneous_pages.py",
        "synthesis_pages.py",
    ]

    for metadata_file in metadata_files:
        source = _source(metadata_file).replace(
            "notion_task_tracker.notion_operations.notion_id",
            "",
        )
        assert "notion_task_tracker.notion_operations" not in source, metadata_file


def test_rest_client_uses_notion_sdk_not_raw_http_transport():
    source = _source("notion_operations/rest_client.py")

    assert "from notion_client import AsyncClient" in source
    assert "urlopen" not in source
    assert "urllib.request" not in source


def _source(relative_path: str) -> str:
    return (PACKAGE_PATH / relative_path).read_text(encoding="utf-8")
