from pathlib import Path


REPOSITORY_ROOT_PATH = Path(__file__).parent.parent
SYNCHRONISATION_WORKFLOW_PATH = (
    REPOSITORY_ROOT_PATH / ".github/workflows/refresh-notion-task-tracker.yml"
)


def test_every_ordinary_wake_up_runs_one_serialised_two_way_synchronisation():
    workflow = SYNCHRONISATION_WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow_paths = list((REPOSITORY_ROOT_PATH / ".github/workflows").glob("*.yml"))

    assert "- refresh-notion-task-tracker" in workflow
    assert "- apply-google-calendar-changes-to-notion-task-tracker" in workflow
    assert "group: synchronise-notion-and-google-calendar-" in workflow
    assert workflow.index("ntt --refresh-notion-task-tracker") < workflow.index(
        "ntt --apply-google-calendar-changes-to-tasks"
    )
    assert workflow.index("ntt --apply-google-calendar-changes-to-tasks") < workflow.index(
        "ntt --sync-tasks-to-google-calendar"
    )
    assert [
        workflow_path
        for workflow_path in workflow_paths
        if "ntt --apply-google-calendar-changes-to-tasks"
        in workflow_path.read_text(encoding="utf-8")
    ] == [SYNCHRONISATION_WORKFLOW_PATH]


def test_google_change_cursor_never_crosses_the_github_dispatch_boundary():
    workflow = SYNCHRONISATION_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "google-change-cursor" not in workflow
    assert "GOOGLE_CHANGE_CURSOR" not in workflow
