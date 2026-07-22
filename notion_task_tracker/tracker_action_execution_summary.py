"""Describe the observable outcome of a tracker action."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrackerActionExecutionSummary:
    action_name: str
    output_path: Path
    tracker_state_path: Path
    warnings: list[dict[str, str]]
    backup_path: Path | None = None
    completed_operation_keys: list[str] | None = None
    tasks: list[dict[str, Any]] | None = None
    task_tree_changes: list[dict[str, Any]] | None = None
    task_count: int | None = None
    repair_operation_count: int | None = None
    movement: dict[str, Any] | None = None
    calendar_operation_keys: list[str] | None = None
    desired_calendar_event_count: int | None = None
    calendar_watch: dict[str, Any] | None = None
    recovered_expired_google_change_cursor: bool | None = None

    def to_json_summary(self) -> dict[str, Any]:
        summary = {
            "action_name": self.action_name,
            "output_path": str(self.output_path),
            "tracker_state_path": str(self.tracker_state_path),
            "warnings": list(self.warnings),
        }
        if self.backup_path is not None:
            summary["backup_path"] = str(self.backup_path)
        if self.completed_operation_keys is not None:
            summary["completed_operations"] = list(self.completed_operation_keys)
        if self.tasks is not None:
            summary["tasks"] = self.tasks
        if self.task_tree_changes is not None:
            summary["task_tree_changes"] = self.task_tree_changes
        if self.task_count is not None:
            summary["task_count"] = self.task_count
        if self.repair_operation_count is not None:
            summary["repair_operation_count"] = self.repair_operation_count
        if self.movement is not None:
            summary["movement"] = self.movement
        if self.calendar_operation_keys is not None:
            summary["calendar_operations"] = list(self.calendar_operation_keys)
        if self.desired_calendar_event_count is not None:
            summary["desired_calendar_event_count"] = self.desired_calendar_event_count
        if self.calendar_watch is not None:
            summary["calendar_watch"] = dict(self.calendar_watch)
        if self.recovered_expired_google_change_cursor is not None:
            summary["recovered_expired_google_change_cursor"] = (
                self.recovered_expired_google_change_cursor
            )
        return summary
