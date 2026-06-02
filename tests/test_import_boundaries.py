import ast
from pathlib import Path


PACKAGE_PATH = Path(__file__).resolve().parents[1] / "notion_task_tracker"


def test_rest_client_does_not_import_removed_integration_symbols():
    source = _source("notion_operations/rest_client.py")

    removed_integration_name = "m" + "cp"
    assert f"notion_task_tracker.{removed_integration_name}" not in source
    assert f"Notion{removed_integration_name.title()}" not in source


def test_package_has_no_removed_integration_runtime_imports():
    removed_integration_name = "m" + "cp"
    removed_integration_title = removed_integration_name.title()
    forbidden_text = [
        f"{removed_integration_name}_client",
        f"Notion{removed_integration_title}",
        f"Notion{removed_integration_title}ToolCall",
        f"Notion{removed_integration_title}CallPlanner",
    ]

    for source_path in PACKAGE_PATH.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert not any(forbidden in source for forbidden in forbidden_text), source_path


def test_workflow_modules_do_not_import_notion_protocol_details():
    forbidden_text = [
        "Notion" + ("m" + "cp").title() + "ToolCall",
        "Notion" + ("m" + "cp").title() + "CallPlanner",
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


def test_redundant_client_wrapper_boundary_is_removed():
    removed_wrapper_path = PACKAGE_PATH / "notion_operations" / ("client" + ".py")
    assert not removed_wrapper_path.exists()

    forbidden_text = [
        "notion_operations." + "client",
        "NotionClient",
        "notion_client_from_" + "environment",
    ]
    for source_path in PACKAGE_PATH.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert not any(forbidden in source for forbidden in forbidden_text), source_path


def test_removed_cli_and_auth_shapes_are_absent():
    source = _source("run_notion_task_tracker.py")
    forbidden_text = [
        "--notion-" + "trans" + "port",
        "notion_client_from_" + "credentials" + "_path",
        "credentials" + "_path",
    ]

    assert not any(forbidden in source for forbidden in forbidden_text)


def test_workflow_client_surface_is_rest_client_oriented():
    source = _source("run_notion_task_tracker.py")
    module = ast.parse(source)

    removed_helper_name = "_notion_" + "client_from_instance"
    assert removed_helper_name not in source
    assert "NotionRestClient.from_environment()" in source

    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for argument in node.args.args + node.args.kwonlyargs:
            if argument.arg != "notion_client":
                continue
            assert argument.annotation is not None, node.name
            annotation = ast.unparse(argument.annotation)
            assert annotation != "Any", node.name
            assert not annotation.startswith("Any |"), node.name
            assert not annotation.endswith("| Any"), node.name


def test_tracker_metadata_modules_do_not_import_notion_operations():
    metadata_files = [
        "tasks/task.py",
        "tasks/task_tree.py",
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


def test_rest_client_uses_notion_sdk_not_raw_http_layer():
    source = _source("notion_operations/rest_client.py")

    assert "from notion_client import AsyncClient" in source
    assert "urlopen" not in source
    assert "urllib.request" not in source


def _source(relative_path: str) -> str:
    return (PACKAGE_PATH / relative_path).read_text(encoding="utf-8")
