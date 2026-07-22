"""Build deterministic tracker commands from explicit CLI actions."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import date, datetime, time
import re
from pathlib import Path
from typing import Any

from notion_task_tracker.tasks import (
    DEFAULT_TASK_EXTERNAL_COORDINATION,
    DEFAULT_TASK_FRICTION,
    DEFAULT_TASK_STATUS,
    DEFAULT_TASK_UNCERTAINTY,
)
from notion_task_tracker.tasks.task import generate_timeline_log_id


WRITE_ACTIONS = {
    "log",
    "complete",
    "complete_with_all_children",
    "cancel",
    "delete",
    "set_dependencies",
    "set_dependants",
    "set_deadline",
    "clear_deadline",
    "set_start",
    "clear_start",
    "set_duration",
    "clear_duration",
    "set_external_coordination",
    "set_uncertainty",
    "set_friction",
    "reparent",
    "parent",
    "child",
    "sibling",
    "misc",
    "synth",
    "move_logs",
}

READ_ACTIONS = {
    "read",
    "read_all",
    "work",
}

MAINTENANCE_ACTIONS = {
    "maintain_google_calendar_notification_channel",
    "sync_tasks_to_google_calendar",
    "apply_google_calendar_changes_to_tasks",
    "refresh_notion_task_tracker",
}


def selected_cli_action_from_arguments(arguments: Namespace) -> str | None:
    for action_name in [*sorted(MAINTENANCE_ACTIONS), *sorted(READ_ACTIONS), *sorted(WRITE_ACTIONS)]:
        if getattr(arguments, action_name, False):
            return action_name

    return None


def build_tracker_command_from_cli_action(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    action_name = selected_cli_action_from_arguments(arguments)
    if action_name is None:
        raise ValueError("Choose one tracker action")
    if action_name == "sync_tasks_to_google_calendar":
        return {"command": "sync_tasks_to_google_calendar"}
    if action_name == "maintain_google_calendar_notification_channel":
        if not arguments.tracker_user:
            raise ValueError(
                "--maintain-google-calendar-notification-channel requires --tracker-user"
            )
        if not arguments.calendar_notification_url:
            raise ValueError(
                "--maintain-google-calendar-notification-channel requires "
                "--calendar-notification-url"
            )
        return {
            "command": "maintain_google_calendar_notification_channel",
            "tracker_user": arguments.tracker_user,
            "notification_url": arguments.calendar_notification_url,
        }
    if action_name == "apply_google_calendar_changes_to_tasks":
        if not arguments.google_change_cursor:
            raise ValueError(
                "--apply-google-calendar-changes-to-tasks requires --google-change-cursor"
            )
        if not arguments.tracker_user:
            raise ValueError("--apply-google-calendar-changes-to-tasks requires --tracker-user")
        return {
            "command": "apply_google_calendar_changes_to_tasks",
            "google_change_cursor": arguments.google_change_cursor,
            "tracker_user": arguments.tracker_user,
        }
    if action_name == "refresh_notion_task_tracker":
        return {"command": "refresh_notion_task_tracker"}
    if action_name == "read":
        return _build_read_command(arguments, ticket_prefix)
    if action_name == "read_all":
        return _build_read_all_command(arguments, ticket_prefix)
    if action_name == "work":
        return _build_work_command(arguments, ticket_prefix)
    if action_name == "log":
        return _build_log_command(arguments, ticket_prefix)
    if action_name == "complete":
        return _build_complete_command(arguments, ticket_prefix)
    if action_name == "complete_with_all_children":
        return _build_complete_with_all_children_command(arguments, ticket_prefix)
    if action_name == "cancel":
        return _build_cancel_command(arguments, ticket_prefix)
    if action_name == "delete":
        return _build_delete_command(arguments, ticket_prefix)
    if action_name == "set_dependencies":
        return _build_set_dependencies_command(arguments, ticket_prefix)
    if action_name == "set_dependants":
        return _build_set_dependants_command(arguments, ticket_prefix)
    if action_name == "set_deadline":
        return _build_set_deadline_command(arguments, ticket_prefix)
    if action_name == "clear_deadline":
        return _build_clear_deadline_command(arguments, ticket_prefix)
    if action_name == "set_start":
        return _build_set_start_command(arguments, ticket_prefix)
    if action_name == "clear_start":
        return _build_clear_start_command(arguments, ticket_prefix)
    if action_name == "set_duration":
        return _build_set_duration_command(arguments, ticket_prefix)
    if action_name == "clear_duration":
        return _build_clear_duration_command(arguments, ticket_prefix)
    if action_name == "set_external_coordination":
        return _build_set_external_coordination_command(arguments, ticket_prefix)
    if action_name == "set_uncertainty":
        return _build_set_uncertainty_command(arguments, ticket_prefix)
    if action_name == "set_friction":
        return _build_set_friction_command(arguments, ticket_prefix)
    if action_name == "reparent":
        return _build_reparent_command(arguments, ticket_prefix)
    if action_name == "parent":
        return _build_parent_command(arguments, ticket_prefix)
    if action_name == "child":
        return _build_child_command(arguments, ticket_prefix)
    if action_name == "sibling":
        return _build_sibling_command(arguments, ticket_prefix)
    if action_name == "misc":
        return _build_miscellaneous_command(arguments)
    if action_name == "synth":
        return _build_synthesis_command(arguments)
    if action_name == "move_logs":
        return _build_move_logs_command(arguments, ticket_prefix)

    raise ValueError(f"CLI action {action_name!r} does not produce a tracker command")


def _build_move_logs_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.destination_ticket_number is None:
        raise ValueError("--move-logs requires --destination-ticket-number")

    return {
        "command": "move_task_timeline_log",
        "source_task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "destination_task_id": ticket_id_from_number(arguments.destination_ticket_number, ticket_prefix),
        "log_id": arguments.log_id,
    }


def ticket_id_from_number(ticket_number: int, ticket_prefix: str) -> str:
    if ticket_number < 1:
        raise ValueError("Ticket numbers must be positive")

    return f"{ticket_prefix}-{ticket_number}"


def ticket_ids_from_numbers(ticket_numbers: list[int], ticket_prefix: str) -> list[str]:
    return [ticket_id_from_number(ticket_number, ticket_prefix) for ticket_number in ticket_numbers]


def _build_read_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if not arguments.ticket_number:
        raise ValueError("--read requires at least one --ticket-number")

    return {
        "command": "read_tasks",
        "task_ids": ticket_ids_from_numbers(arguments.ticket_number, ticket_prefix),
    }


def _build_read_all_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if not arguments.ticket_number:
        raise ValueError("--read-all requires at least one --ticket-number")

    return {
        "command": "read_all_tasks",
        "task_ids": ticket_ids_from_numbers(arguments.ticket_number, ticket_prefix),
    }


def _build_work_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "work_task",
        "task_ids": [_single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix)],
    }


def _build_log_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "append_task_timeline_log",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        ),
    }


def _build_complete_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "complete_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        ),
    }


def _build_complete_with_all_children_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "complete_task_with_all_children",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        ),
    }


def _build_cancel_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "cancel_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        ),
    }


def _build_delete_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "delete_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
    }


def _build_set_dependencies_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "set_task_dependencies",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "dependency_task_ids": ticket_ids_from_numbers(arguments.dependency_ticket_number, ticket_prefix),
    }


def _build_set_dependants_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "set_task_dependants",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "dependant_task_ids": ticket_ids_from_numbers(arguments.dependant_ticket_number, ticket_prefix),
    }


def _build_set_deadline_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.deadline is None:
        raise ValueError("--set-deadline requires --deadline")

    return {
        "command": "set_task_deadline",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "deadline": arguments.deadline,
    }


def _build_clear_deadline_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "clear_task_deadline",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
    }


def _build_set_start_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.start is None:
        raise ValueError("--set-start requires --start")

    return {
        "command": "set_task_start",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "start": _optional_start_arg(arguments.start),
    }


def _build_clear_start_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "clear_task_start",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
    }


def _build_set_duration_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.duration is None or arguments.duration_unit is None:
        raise ValueError("--set-duration requires --duration and --duration-unit")

    return {
        "command": "set_task_duration",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "duration": arguments.duration,
        "duration_unit": arguments.duration_unit,
    }


def _build_clear_duration_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "clear_task_duration",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
    }


def _build_set_external_coordination_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.external_coordination is None:
        raise ValueError("--set-external-coordination requires --external-coordination")

    return {
        "command": "set_task_external_coordination",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "external_coordination": arguments.external_coordination,
    }


def _build_set_uncertainty_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.uncertainty is None:
        raise ValueError("--set-uncertainty requires --uncertainty")

    return {
        "command": "set_task_uncertainty",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "uncertainty": arguments.uncertainty,
    }


def _build_set_friction_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.friction is None:
        raise ValueError("--set-friction requires --friction")

    return {
        "command": "set_task_friction",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "friction": arguments.friction,
    }


def _build_reparent_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    if arguments.parent_ticket_number is None:
        raise ValueError("--reparent requires --parent-ticket-number")

    return {
        "command": "reparent_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "parent_task_id": ticket_id_from_number(arguments.parent_ticket_number, ticket_prefix),
    }


def _build_parent_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    command = {
        "command": "create_top_level_task",
        "task": _new_task_command(arguments, parse_one_title_arg(arguments, "parent"), ticket_prefix),
    }
    if arguments.content_path is not None:
        command["timeline_entry"] = _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        )
    return command


def _build_child_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    _reject_explicit_split_relations(arguments, "child")
    command = {
        "command": "split_task_into_children",
        "source_task_id": ticket_id_from_number(arguments.parent_ticket_number, ticket_prefix),
        "child_tasks": [
            _new_task_command(arguments, parse_one_title_arg(arguments, "child"), ticket_prefix),
        ],
    }
    if arguments.content_path is not None:
        command["parent_timeline_entry"] = _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        )
    return command


def _build_sibling_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    _reject_explicit_split_relations(arguments, "sibling")
    command = {
        "command": "split_task_with_sibling",
        "source_task_id": ticket_id_from_number(arguments.sibling_ticket_number, ticket_prefix),
        "sibling_task": _new_task_command(arguments, parse_one_title_arg(arguments, "sibling"), ticket_prefix),
    }
    if arguments.content_path is not None:
        command["timeline_entry"] = _timeline_entry_from_content_path(
            arguments.content_path,
            arguments.entry_date,
            ticket_prefix,
        )
    return command


def _build_miscellaneous_command(arguments: Namespace) -> dict[str, Any]:
    content = _read_json_object(arguments.content_path)
    return {
        "command": "append_miscellaneous_note",
        "note_date": _entry_date_from_arguments(arguments.entry_date),
        "lines": _lines_from_content(content),
    }


def _build_synthesis_command(arguments: Namespace) -> dict[str, Any]:
    content = _read_json_object(arguments.content_path)
    return {
        "command": "create_synthesis_page",
        "synthesis_key": arguments.synthesis_key,
        "title": parse_one_title_arg(arguments, "synth"),
        "summary": content.get("summary", ""),
        "sources": list(content.get("sources", [])),
        "lines": _lines_from_content(content),
    }


def _single_task_id_from_ticket_numbers(ticket_numbers: list[int], ticket_prefix: str) -> str:
    if len(ticket_numbers) != 1:
        raise ValueError("This action requires exactly one --ticket-number")

    return ticket_id_from_number(ticket_numbers[0], ticket_prefix)


def _new_task_command(arguments: Namespace, title: str, ticket_prefix: str) -> dict[str, Any]:
    return {
        "title": title,
        "configured_priority": arguments.priority,
        "status": DEFAULT_TASK_STATUS.value,
        **_new_task_database_fields_from_arguments(arguments, ticket_prefix),
    }


def parse_one_title_arg(arguments: Namespace, action_name: str) -> str:
    return parse_title_args(arguments, action_name, expected_count=1)[0]


def parse_title_args(arguments: Namespace, action_name: str, expected_count: int) -> list[str]:
    raw_titles = arguments.title or []
    titles = [raw_titles] if isinstance(raw_titles, str) else list(raw_titles)
    if len(titles) != expected_count:
        raise ValueError(f"--{action_name} requires exactly {expected_count} --title value")

    return titles


def _reject_explicit_split_relations(arguments: Namespace, action_name: str) -> None:
    if arguments.dependency_ticket_number:
        raise ValueError(f"--{action_name} derives dependencies from the source task; do not pass --dependency-ticket-number")
    if arguments.dependant_ticket_number:
        raise ValueError(f"--{action_name} derives dependants from the source task; do not pass --dependant-ticket-number")


def _new_task_database_fields_from_arguments(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    dependency_task_ids = ticket_ids_from_numbers(arguments.dependency_ticket_number, ticket_prefix)
    dependant_task_ids = ticket_ids_from_numbers(arguments.dependant_ticket_number, ticket_prefix)
    if dependency_task_ids and dependant_task_ids:
        raise ValueError("Choose dependencies or dependants, not both")

    return {
        "dependency_task_ids": dependency_task_ids,
        "dependant_task_ids": dependant_task_ids,
        "deadline": arguments.deadline,
        "start": _optional_start_arg(arguments.start),
        "duration": arguments.duration,
        "duration_unit": arguments.duration_unit,
        "external_coordination": arguments.external_coordination or DEFAULT_TASK_EXTERNAL_COORDINATION.value,
        "uncertainty": arguments.uncertainty or DEFAULT_TASK_UNCERTAINTY.value,
        "friction": arguments.friction or DEFAULT_TASK_FRICTION.value,
    }


def _timeline_entry_from_content_path(
    content_path: str | None,
    entry_date: str | None,
    ticket_prefix: str,
) -> dict[str, Any]:
    if content_path is None:
        raise ValueError("This action requires --content-path")

    content = _read_json_object(content_path)
    resolved_entry_date = _entry_date_from_arguments(entry_date)
    timeline_entry = {
        "log_id": generate_timeline_log_id(ticket_prefix),
        "title": _required_timeline_log_title(content),
        "entry_date": resolved_entry_date,
        "heading": f'<mention-date start="{resolved_entry_date}"/>',
    }
    if content.get("blocks") is not None:
        timeline_entry["blocks"] = list(content["blocks"])
    if content.get("lines") is not None:
        timeline_entry["lines"] = list(content["lines"])
    if "blocks" not in timeline_entry and "lines" not in timeline_entry:
        raise ValueError("Timeline content must include blocks or lines")
    return timeline_entry


def _required_timeline_log_title(content: dict[str, Any]) -> str:
    title = content.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Timeline content must include a non-empty title")

    return title


def _lines_from_content(content: dict[str, Any]) -> list[str]:
    if content.get("lines") is not None:
        return list(content["lines"])

    if content.get("blocks") is not None:
        return [_line_from_content_block(block) for block in content["blocks"]]

    raise ValueError("Content must include lines or blocks")


def _line_from_content_block(block: Any) -> str:
    if not isinstance(block, dict):
        raise ValueError("Each content block must be an object")
    if not isinstance(block.get("text"), str):
        raise ValueError("Each content block must include string text")

    return block["text"]


def _entry_date_from_arguments(entry_date: str | None) -> str:
    return entry_date or date.today().isoformat()


def _parse_date_time_arg(raw_date_time: str, argument_name: str) -> str:
    if re.fullmatch(r"\d{1,2}:\d{2}", raw_date_time):
        raise ValueError(f"{argument_name} requires a date; time-only values are not supported")

    local_timezone = datetime.now().astimezone().tzinfo
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date_time):
        parsed_date = date.fromisoformat(raw_date_time)
        return datetime.combine(parsed_date, time.min, tzinfo=local_timezone).isoformat(timespec="seconds")

    normalised_date_time = raw_date_time.replace("T", " ")
    try:
        parsed_date_time = datetime.strptime(normalised_date_time, "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise ValueError(
            f"{argument_name} must be YYYY-MM-DD, YYYY-MM-DD HH:MM, or YYYY-MM-DDTHH:MM"
        ) from error
    return parsed_date_time.replace(tzinfo=local_timezone).isoformat(timespec="seconds")


def _optional_date_time_arg(raw_date_time: str | None, argument_name: str) -> str | None:
    if raw_date_time is None:
        return None

    return _parse_date_time_arg(raw_date_time, argument_name)


def _optional_start_arg(raw_start: str | None) -> str | None:
    if raw_start is None:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_start):
        return date.fromisoformat(raw_start).isoformat()
    return _parse_date_time_arg(raw_start, "--start")


def _read_json_object(source_path: str | Path | None) -> dict[str, Any]:
    if source_path is None:
        raise ValueError("This action requires --content-path")

    content = json.loads(Path(source_path).read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("Content path must contain a JSON object")

    return content
