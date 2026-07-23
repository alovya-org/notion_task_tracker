from pathlib import Path

from notion_task_tracker.tracker_action_execution_summary import (
    TrackerActionExecutionSummary,
)


def test_summary_reports_observable_notion_and_calendar_work():
    summary = TrackerActionExecutionSummary(
        action_name="refresh_notion_task_tracker",
        output_path=Path("/tmp/result.json"),
        notion_operation_keys=["update_schedule:task:ALOVYA-1"],
        calendar_operation_keys=["replace:calendar_event:ALOVYA-1"],
        task_count=1,
        warnings=[{"kind": "example", "message": "Example warning"}],
        recovered_expired_google_change_cursor=False,
    )

    assert summary.to_json_summary() == {
        "action_name": "refresh_notion_task_tracker",
        "output_path": "/tmp/result.json",
        "notion_operations": ["update_schedule:task:ALOVYA-1"],
        "calendar_operations": ["replace:calendar_event:ALOVYA-1"],
        "task_count": 1,
        "warnings": [{"kind": "example", "message": "Example warning"}],
        "recovered_expired_google_change_cursor": False,
    }
