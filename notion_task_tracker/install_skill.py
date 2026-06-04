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
    claude_config_dir_path: str | Path | None = None,
    output_stream: TextIO = sys.stdout,
    force: bool = False,
) -> list[SkillInstallResult]:
    source_skill_path = find_source_skill_path()
    targets = skill_install_targets(
        codex_home_path=codex_home_path,
        claude_config_dir_path=claude_config_dir_path,
    )
    results = [
        install_skill_for_target(source_skill_path, target, force=force)
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
    claude_config_dir_path: str | Path | None = None,
) -> list[SkillInstallTarget]:
    resolved_codex_home_path = _codex_home_path(codex_home_path)
    resolved_claude_config_dir_path = _claude_config_dir_path(claude_config_dir_path)

    return [
        SkillInstallTarget(
            tool_name="codex",
            skill_path=resolved_codex_home_path / "skills" / SKILL_DIRECTORY_NAME / SKILL_FILE_NAME,
        ),
        SkillInstallTarget(
            tool_name="claude",
            skill_path=resolved_claude_config_dir_path / "skills" / SKILL_DIRECTORY_NAME / SKILL_FILE_NAME,
        ),
    ]


def install_skill_for_target(
    source_skill_path: Path,
    target: SkillInstallTarget,
    force: bool = False,
) -> SkillInstallResult:
    if target.skill_path.exists():
        if filecmp.cmp(source_skill_path, target.skill_path, shallow=False):
            return SkillInstallResult(
                tool_name=target.tool_name,
                skill_path=target.skill_path,
                status="already_installed",
            )

        if not force:
            raise FileExistsError(
                f"{target.skill_path} already exists and differs from {source_skill_path}. "
                "Use --force to overwrite."
            )

        shutil.copy2(source_skill_path, target.skill_path)
        return SkillInstallResult(
            tool_name=target.tool_name,
            skill_path=target.skill_path,
            status="overwritten",
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

    raise RuntimeError("CODEX_HOME must be set or codex_home_path must be provided.")


def _claude_config_dir_path(claude_config_dir_path: str | Path | None) -> Path:
    if claude_config_dir_path:
        return Path(claude_config_dir_path).expanduser()

    configured_claude_config_dir_path = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured_claude_config_dir_path:
        return Path(configured_claude_config_dir_path).expanduser()

    raise RuntimeError("CLAUDE_CONFIG_DIR must be set or claude_config_dir_path must be provided.")
