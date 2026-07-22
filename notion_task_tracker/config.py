"""Per-user configuration for the Notion task tracker."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

from platformdirs import user_config_path


CONFIG_ENVIRONMENT_VARIABLE = "NTT_CONFIG_PATH"
CONFIG_FILE_NAME = "config.toml"
_TICKET_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class ManagedPageUrls:
    ongoing_tasks_url: str | None = None
    completed_tasks_url: str | None = None
    ready_priority_page_url: str | None = None
    miscellaneous_notes_url: str | None = None
    synthesis_notes_url: str | None = None


@dataclass(frozen=True)
class CalendarConfig:
    calendar_id: str
    timezone_name: str
    colour_id: str | None = None

    def validate(self) -> None:
        if not self.calendar_id.strip():
            raise ValueError("calendar_id must not be empty")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"timezone_name must be an IANA timezone: {self.timezone_name}") from error


@dataclass(frozen=True)
class TrackerConfig:
    display_name: str
    ticket_prefix: str
    parent_page_url: str
    task_database_url: str
    pages: ManagedPageUrls = field(default_factory=ManagedPageUrls)
    calendar: CalendarConfig | None = None

    def validate(self) -> None:
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")
        if not _TICKET_PREFIX_PATTERN.fullmatch(self.ticket_prefix):
            raise ValueError("ticket_prefix must start with a letter and contain only A-Z, 0-9, and underscore")
        for field_name, value in {
            "parent_page_url": self.parent_page_url,
            "task_database_url": self.task_database_url,
        }.items():
            if not value.startswith("https://"):
                raise ValueError(f"{field_name} must be an https:// Notion URL")
        if self.calendar is not None:
            self.calendar.validate()


def default_config_path() -> Path:
    configured_path = os.environ.get(CONFIG_ENVIRONMENT_VARIABLE)
    if configured_path:
        return Path(configured_path).expanduser()
    return user_config_path("notion-task-tracker", appauthor=False) / CONFIG_FILE_NAME


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    return Path(config_path).expanduser() if config_path else default_config_path()


def load_config(config_path: str | Path | None = None) -> TrackerConfig:
    source_path = resolve_config_path(config_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Tracker is not configured at {source_path}. Run `ntt --init`.")
    raw_config = tomllib.loads(source_path.read_text(encoding="utf-8"))
    identity = raw_config.get("identity", {})
    notion = raw_config.get("notion", {})
    pages = raw_config.get("pages", {})
    calendar = raw_config.get("calendar")
    config = TrackerConfig(
        display_name=identity.get("display_name", ""),
        ticket_prefix=identity.get("ticket_prefix", ""),
        parent_page_url=notion.get("parent_page_url", ""),
        task_database_url=notion.get("task_database_url", ""),
        pages=ManagedPageUrls(
            ongoing_tasks_url=pages.get("ongoing_tasks_url"),
            completed_tasks_url=pages.get("completed_tasks_url"),
            ready_priority_page_url=pages.get("ready_priority_page_url"),
            miscellaneous_notes_url=pages.get("miscellaneous_notes_url"),
            synthesis_notes_url=pages.get("synthesis_notes_url"),
        ),
        calendar=(
            CalendarConfig(
                calendar_id=calendar.get("calendar_id", ""),
                timezone_name=calendar.get("timezone_name", ""),
                colour_id=calendar.get("colour_id"),
            )
            if calendar is not None
            else None
        ),
    )
    config.validate()
    return config


def write_config(config: TrackerConfig, config_path: str | Path | None = None) -> Path:
    config.validate()
    destination_path = resolve_config_path(config_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[identity]",
        f'display_name = {_toml_string(config.display_name)}',
        f'ticket_prefix = {_toml_string(config.ticket_prefix)}',
        "",
        "[notion]",
        f'parent_page_url = {_toml_string(config.parent_page_url)}',
        f'task_database_url = {_toml_string(config.task_database_url)}',
        "",
        "[pages]",
    ]
    for key, value in {
        "ongoing_tasks_url": config.pages.ongoing_tasks_url,
        "completed_tasks_url": config.pages.completed_tasks_url,
        "ready_priority_page_url": config.pages.ready_priority_page_url,
        "miscellaneous_notes_url": config.pages.miscellaneous_notes_url,
        "synthesis_notes_url": config.pages.synthesis_notes_url,
    }.items():
        if value is not None:
            lines.append(f"{key} = {_toml_string(value)}")
    if config.calendar is not None:
        lines.extend([
            "",
            "[calendar]",
            f"calendar_id = {_toml_string(config.calendar.calendar_id)}",
            f"timezone_name = {_toml_string(config.calendar.timezone_name)}",
        ])
        if config.calendar.colour_id is not None:
            lines.append(f"colour_id = {_toml_string(config.calendar.colour_id)}")
    destination_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination_path


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
