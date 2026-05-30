"""Install the Notion task tracker skill for local agent tools."""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TextIO


PROJECT_DISTRIBUTION_NAME = "notion-task-tracker"
SKILL_DIRECTORY_NAME = "notion_task_tracker"
SKILL_FILE_NAME = "SKILL.md"


@dataclass(frozen=True)
class SkillInstallTarget:
    tool_name: str
    skill_path: Path


@dataclass(frozen=True)
class SkillInstallResult:
    tool_name: str
    skill_path: Path
    status: str

    def to_json_summary(self) -> dict[str, str]:
        return {
            "tool_name": self.tool_name,
            "skill_path": str(self.skill_path),
            "status": self.status,
        }


def install_skill(
    codex_home_path: str | Path | None = None,
    home_path: str | Path | None = None,
    output_stream: TextIO = sys.stdout,
) -> list[SkillInstallResult]:
    source_skill_path = find_source_skill_path()
    targets = skill_install_targets(
        codex_home_path=codex_home_path,
        home_path=home_path,
    )
    results = [
        install_skill_for_target(source_skill_path, target)
        for target in targets
    ]
    print(json.dumps([result.to_json_summary() for result in results], indent=2), file=output_stream)
    return results


def find_source_skill_path() -> Path:
    repository_skill_path = Path(__file__).resolve().parents[1] / SKILL_FILE_NAME
    if repository_skill_path.exists():
        return repository_skill_path

    distribution_files = metadata.files(PROJECT_DISTRIBUTION_NAME) or []
    for distribution_file in distribution_files:
        if Path(str(distribution_file)).name == SKILL_FILE_NAME:
            installed_skill_path = Path(str(distribution_file.locate()))
            if installed_skill_path.exists():
                return installed_skill_path

    raise FileNotFoundError(
        f"Could not find {SKILL_FILE_NAME}. Reinstall {PROJECT_DISTRIBUTION_NAME} and retry."
    )


def skill_install_targets(
    codex_home_path: str | Path | None = None,
    home_path: str | Path | None = None,
) -> list[SkillInstallTarget]:
    resolved_home_path = Path(home_path).expanduser() if home_path else Path.home()
    resolved_codex_home_path = _codex_home_path(codex_home_path)

    return [
        SkillInstallTarget(
            tool_name="codex",
            skill_path=resolved_codex_home_path / "skills" / SKILL_DIRECTORY_NAME / SKILL_FILE_NAME,
        ),
        SkillInstallTarget(
            tool_name="claude",
            skill_path=resolved_home_path / ".claude" / "skills" / SKILL_DIRECTORY_NAME / SKILL_FILE_NAME,
        ),
    ]


def install_skill_for_target(
    source_skill_path: Path,
    target: SkillInstallTarget,
) -> SkillInstallResult:
    if target.skill_path.exists():
        if filecmp.cmp(source_skill_path, target.skill_path, shallow=False):
            return SkillInstallResult(
                tool_name=target.tool_name,
                skill_path=target.skill_path,
                status="already_installed",
            )

        raise FileExistsError(
            f"{target.skill_path} already exists and differs from {source_skill_path}. "
            "Move it aside before reinstalling."
        )

    target.skill_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_skill_path, target.skill_path)
    return SkillInstallResult(
        tool_name=target.tool_name,
        skill_path=target.skill_path,
        status="installed",
    )


def _codex_home_path(codex_home_path: str | Path | None) -> Path:
    if codex_home_path:
        return Path(codex_home_path).expanduser()

    configured_codex_home_path = os.environ.get("CODEX_HOME")
    if configured_codex_home_path:
        return Path(configured_codex_home_path).expanduser()

    return Path.home() / ".codex"
