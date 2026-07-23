"""Fixed Notion pages owned by the tracker."""

ONGOING_LANDING_PAGE_LOCAL_KEY = "ongoing_landing_page"
COMPLETED_LANDING_PAGE_LOCAL_KEY = "completed_landing_page"
READY_PRIORITY_PAGE_LOCAL_KEY = "ready_priority_page"

ONGOING_LANDING_PAGE_TITLE = "Ongoing tasks"
COMPLETED_LANDING_PAGE_TITLE = "Completed tasks"
READY_PRIORITY_PAGE_TITLE = "Tasks in execution order"


def derive_managed_page_titles(display_name: str) -> dict[str, str]:
    return {
        ONGOING_LANDING_PAGE_LOCAL_KEY: f"{display_name}'s ongoing tasks",
        COMPLETED_LANDING_PAGE_LOCAL_KEY: f"{display_name}'s completed tasks",
        READY_PRIORITY_PAGE_LOCAL_KEY: f"{display_name}'s tasks in execution order",
    }
