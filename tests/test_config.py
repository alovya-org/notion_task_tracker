from pathlib import Path

import pytest

from notion_task_tracker.config import (
    ManagedPageUrls,
    TrackerConfig,
    default_config_path,
    load_config,
    write_config,
)


def test_write_config_then_load_config_preserves_user_and_notion_configuration(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    expected_config = TrackerConfig(
        display_name="Alovya",
        ticket_prefix="ALOVYA",
        parent_page_url="https://www.notion.so/tracker-parent-11111111111111111111111111111111",
        task_database_url="https://www.notion.so/tasks-22222222222222222222222222222222",
        pages=ManagedPageUrls(
            ongoing_tasks_url="https://www.notion.so/ongoing-33333333333333333333333333333333",
            completed_tasks_url="https://www.notion.so/completed-44444444444444444444444444444444",
            miscellaneous_notes_url="https://www.notion.so/miscellaneous-55555555555555555555555555555555",
            synthesis_notes_url="https://www.notion.so/synthesis-66666666666666666666666666666666",
        ),
    )

    write_config(expected_config, config_path)

    assert load_config(config_path) == expected_config


def test_load_config_explains_how_to_initialise_an_unconfigured_tracker(tmp_path: Path) -> None:
    missing_config_path = tmp_path / "missing.toml"

    with pytest.raises(FileNotFoundError, match=r"Run `ntt --init`"):
        load_config(missing_config_path)


@pytest.mark.parametrize("ticket_prefix", ["", "alovya", "1ALOVYA", "ALOVYA-TEAM"])
def test_tracker_config_rejects_ticket_prefixes_that_cannot_form_stable_task_ids(
    ticket_prefix: str,
) -> None:
    config = TrackerConfig(
        display_name="Alovya",
        ticket_prefix=ticket_prefix,
        parent_page_url="https://www.notion.so/11111111111111111111111111111111",
        task_database_url="https://www.notion.so/22222222222222222222222222222222",
    )

    with pytest.raises(ValueError, match="ticket_prefix"):
        config.validate()


def test_default_config_path_honours_explicit_environment_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_path = tmp_path / "personal-tracker.toml"
    monkeypatch.setenv("NTT_CONFIG_PATH", str(configured_path))

    assert default_config_path() == configured_path
