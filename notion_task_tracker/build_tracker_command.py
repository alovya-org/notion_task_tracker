"""Build deterministic tracker commands from explicit CLI actions."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path
from typing import Any


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
    "set_external_coordination",
    "set_uncertainty",
    "set_friction",
    "reparent",
    "parent",
    "child",
    "sibling",
    "misc",
    "synth",
}

READ_ACTIONS = {
    "read",
    "work",
}

MAINTENANCE_ACTIONS = {
    "reconcile_from_notion",
}


def selected_cli_action_from_arguments(arguments: Namespace) -> str | None:
    for action_name in [*sorted(MAINTENANCE_ACTIONS), *sorted(READ_ACTIONS), *sorted(WRITE_ACTIONS)]:
        if getattr(arguments, action_name, False):
            return action_name

    return None


def build_tracker_command_from_cli_action(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    action_name = selected_cli_action_from_arguments(arguments)
    if action_name is None:
        raise ValueError("Choose --reconcile-from-notion or one tracker action")
    if action_name == "reconcile_from_notion":
        return {"command": "reconcile_from_notion"}
    if action_name == "read":
        return _build_read_command(arguments, ticket_prefix)
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

    raise ValueError(f"CLI action {action_name!r} does not produce a tracker command")


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


def _build_work_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "work_task",
        "task_ids": [_single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix)],
    }


def _build_log_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "append_task_timeline_log",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
    }


def _build_complete_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "complete_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
    }


def _build_complete_with_all_children_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "complete_task_with_all_children",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
    }


def _build_cancel_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    return {
        "command": "cancel_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number, ticket_prefix),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
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
        command["timeline_entry"] = _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date)
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
        command["parent_timeline_entry"] = _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date)
    return command


def _build_sibling_command(arguments: Namespace, ticket_prefix: str) -> dict[str, Any]:
    _reject_explicit_split_relations(arguments, "sibling")
    command = {
        "command": "split_task_with_sibling",
        "source_task_id": ticket_id_from_number(arguments.sibling_ticket_number, ticket_prefix),
        "sibling_task": _new_task_command(arguments, parse_one_title_arg(arguments, "sibling"), ticket_prefix),
    }
    if arguments.content_path is not None:
        command["timeline_entry"] = _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date)
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
        "status": "Active",
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
        "external_coordination": arguments.external_coordination or "No",
        "uncertainty": arguments.uncertainty or "Low",
        "friction": arguments.friction or "None",
    }


def _timeline_entry_from_content_path(content_path: str | None, entry_date: str | None) -> dict[str, Any]:
    if content_path is None:
        raise ValueError("This action requires --content-path")

    content = _read_json_object(content_path)
    resolved_entry_date = _entry_date_from_arguments(entry_date)
    timeline_entry = {
        "entry_date": resolved_entry_date,
        "heading": f'<mention-date start="{resolved_entry_date}"/>',
    }
    if content.get("subheading") is not None:
        timeline_entry["subheading"] = content["subheading"]
    if content.get("blocks") is not None:
        timeline_entry["blocks"] = list(content["blocks"])
    if content.get("lines") is not None:
        timeline_entry["lines"] = list(content["lines"])
    if "blocks" not in timeline_entry and "lines" not in timeline_entry:
        raise ValueError("Timeline content must include blocks or lines")
    return timeline_entry


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


def _read_json_object(source_path: str | Path | None) -> dict[str, Any]:
    if source_path is None:
        raise ValueError("This action requires --content-path")

    content = json.loads(Path(source_path).read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("Content path must contain a JSON object")

    return content
