import io
import json
from pathlib import Path

import pytest

from notion_task_tracker.install_skill import (
    SkillInstallTarget,
    install_skill,
    install_skill_for_target,
    skill_install_targets,
)


def test_skill_install_targets_use_codex_home_and_claude_user_scope(tmp_path: Path):
    codex_home_path = tmp_path / "codex"
    home_path = tmp_path / "home"

    targets = skill_install_targets(
        codex_home_path=codex_home_path,
        home_path=home_path,
    )

    assert targets == [
        SkillInstallTarget(
            tool_name="codex",
            skill_path=codex_home_path / "skills" / "notion_task_tracker" / "SKILL.md",
        ),
        SkillInstallTarget(
            tool_name="claude",
            skill_path=home_path / ".claude" / "skills" / "notion_task_tracker" / "SKILL.md",
        ),
    ]


def test_install_skill_copies_root_skill_to_agent_tool_paths(tmp_path: Path):
    codex_home_path = tmp_path / "codex"
    home_path = tmp_path / "home"
    output_stream = io.StringIO()

    results = install_skill(
        codex_home_path=codex_home_path,
        home_path=home_path,
        output_stream=output_stream,
    )

    codex_skill_path = codex_home_path / "skills" / "notion_task_tracker" / "SKILL.md"
    claude_skill_path = home_path / ".claude" / "skills" / "notion_task_tracker" / "SKILL.md"
    assert [result.status for result in results] == ["installed", "installed"]
    assert codex_skill_path.read_text(encoding="utf-8").startswith("---")
    assert claude_skill_path.read_text(encoding="utf-8") == codex_skill_path.read_text(encoding="utf-8")
    assert json.loads(output_stream.getvalue()) == [
        {
            "tool_name": "codex",
            "skill_path": str(codex_skill_path),
            "status": "installed",
        },
        {
            "tool_name": "claude",
            "skill_path": str(claude_skill_path),
            "status": "installed",
        },
    ]


def test_install_skill_is_noop_when_existing_file_is_identical(tmp_path: Path):
    source_skill_path = tmp_path / "source" / "SKILL.md"
    target_skill_path = tmp_path / "target" / "SKILL.md"
    source_skill_path.parent.mkdir()
    target_skill_path.parent.mkdir()
    source_skill_path.write_text("same\n", encoding="utf-8")
    target_skill_path.write_text("same\n", encoding="utf-8")

    result = install_skill_for_target(
        source_skill_path,
        SkillInstallTarget(tool_name="codex", skill_path=target_skill_path),
    )

    assert result.status == "already_installed"
    assert target_skill_path.read_text(encoding="utf-8") == "same\n"


def test_install_skill_refuses_to_overwrite_different_existing_file(tmp_path: Path):
    source_skill_path = tmp_path / "source" / "SKILL.md"
    target_skill_path = tmp_path / "target" / "SKILL.md"
    source_skill_path.parent.mkdir()
    target_skill_path.parent.mkdir()
    source_skill_path.write_text("source\n", encoding="utf-8")
    target_skill_path.write_text("target\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        install_skill_for_target(
            source_skill_path,
            SkillInstallTarget(tool_name="codex", skill_path=target_skill_path),
        )

    assert target_skill_path.read_text(encoding="utf-8") == "target\n"
