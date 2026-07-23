from pathlib import Path


REPOSITORY_ROOT_PATH = Path(__file__).parent.parent
SYNCHRONISATION_WORKFLOW_PATH = (
    REPOSITORY_ROOT_PATH / ".github/workflows/refresh-notion-task-tracker.yml"
)
def test_every_wake_up_invokes_one_universal_tracker_lifecycle():
    workflow = SYNCHRONISATION_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count("ntt --refresh-notion-task-tracker") == 1
    assert "--synchronise-notion-task-tracker" not in workflow
    assert "--synchronise-notion-task-tracker-with-google-calendar" not in workflow
    assert "ntt --apply-google-calendar-changes-to-tasks" not in workflow
    assert "ntt --sync-tasks-to-google-calendar" not in workflow
    assert "--tracker-state-path" not in workflow


def test_every_ordinary_wake_up_runs_one_serialised_universal_synchronisation():
    workflow = SYNCHRONISATION_WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow_paths = list((REPOSITORY_ROOT_PATH / ".github/workflows").glob("*.yml"))

    assert "- refresh-notion-task-tracker" in workflow
    assert "- apply-google-calendar-changes-to-notion-task-tracker" in workflow
    assert "group: refresh-notion-task-tracker-" in workflow
    assert workflow.count("ntt --refresh-notion-task-tracker") == 1
    assert [
        workflow_path
        for workflow_path in workflow_paths
        if "ntt --refresh-notion-task-tracker"
        in workflow_path.read_text(encoding="utf-8")
    ] == [SYNCHRONISATION_WORKFLOW_PATH]


def test_universal_workflow_exposes_calendar_credentials_as_optional_inputs():
    workflow = SYNCHRONISATION_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}" in workflow
    assert "NTT_CONFIG_TOML: ${{ secrets.NTT_CONFIG_TOML }}" in workflow
    assert "GOOGLE_CALENDAR_CLIENT_ID: ${{ secrets.GOOGLE_CALENDAR_CLIENT_ID }}" in workflow
    assert "NTT_GOOGLE_CALENDAR_STATE_API_TOKEN: ${{ secrets.NTT_GOOGLE_CALENDAR_STATE_API_TOKEN }}" in workflow


def test_google_change_cursor_never_crosses_the_github_dispatch_boundary():
    workflow = SYNCHRONISATION_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "google-change-cursor" not in workflow
    assert "GOOGLE_CHANGE_CURSOR" not in workflow


def test_workflows_use_current_actions_and_report_background_failures():
    workflow_dir = REPOSITORY_ROOT_PATH / ".github/workflows"
    calendar_workflow_paths = [
        SYNCHRONISATION_WORKFLOW_PATH,
        workflow_dir / "maintain-google-calendar-notification-channel.yml",
    ]

    for workflow_path in calendar_workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "actions/checkout@v6" in workflow
        assert "actions/setup-python@v6" in workflow
        assert "contents: read" in workflow
        assert "issues: write" in workflow
        assert "gh issue create" in workflow
        assert "actions/runs/$GITHUB_RUN_ID" in workflow
