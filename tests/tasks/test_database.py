from __future__ import annotations

import json

import pytest

from notion_task_tracker import COMPLETED_LANDING_PAGE_TITLE, ONGOING_LANDING_PAGE_TITLE, TrackedPage
from notion_task_tracker.tasks import (
    ExternalCoordination,
    Friction,
    Priority,
    TaskTree,
    Task,
    TaskStatus,
    Uncertainty,
)
from notion_task_tracker.tasks.database import (
    build_task_tree_from_database_query_results,
    task_id_from_fetched_task_database_page,
)


class TestTaskTreeFromDatabaseQueryResults:
    def test_builds_tree_from_ticket_ids_and_parent_relations(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page="ALOVYA-1: Root task",
                    ticket_id="68",
                    page_id="11111111111111111111111111111111",
                ),
                _build_task_database_row(
                    ticket_page="ALOVYA-2: Child task",
                    ticket_id="69",
                    priority="P2",
                    status="Blocked",
                    parent_page_ids=["11111111111111111111111111111111"],
                    page_id="22222222222222222222222222222222",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert task_tree.tasks["ALOVYA-68"].title == "Root task"
        assert task_tree.tasks["ALOVYA-68"].child_task_ids == ["ALOVYA-69"]
        assert task_tree.tasks["ALOVYA-69"].parent_task_id == "ALOVYA-68"
        assert task_tree.tasks["ALOVYA-69"].configured_priority == Priority.P2
        assert task_tree.tasks["ALOVYA-69"].status == TaskStatus.BLOCKED

    def test_uses_notion_ticket_id_for_task_id(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page="New database-native task",
                    ticket_id="70",
                    page_id="33333333333333333333333333333333",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert list(task_tree.tasks) == ["ALOVYA-70"]
        assert task_tree.tasks["ALOVYA-70"].title == "New database-native task"

    def test_accepts_slugged_notion_urls(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page="Root task",
                    ticket_id="1",
                    page_url="https://www.notion.so/Root-task-22222222222222222222222222222222",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert task_tree.tasks["ALOVYA-1"].notion_page_id == "22222222222222222222222222222222"

    def test_reads_completed_struckthrough_title_as_plain_task_title(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page=(
                        "A\u0336L\u0336O\u0336V\u0336Y\u0336A\u0336-\u03362\u0336:\u0336 \u0336"
                        "A\u0336L\u0336O\u0336V\u0336Y\u0336A\u0336-\u03362\u0336:\u0336 \u0336Finished task"
                    ),
                    ticket_id="68",
                    priority="P3",
                    status="Complete",
                    page_id="11111111111111111111111111111111",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert task_tree.tasks["ALOVYA-68"].title == "Finished task"

    def test_sorts_child_relations_by_task_number(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page="ALOVYA-1: Root task",
                    ticket_id="68",
                    page_id="11111111111111111111111111111111",
                ),
                _build_task_database_row(
                    ticket_page="ALOVYA-10: Later child",
                    ticket_id="70",
                    parent_page_ids=["11111111111111111111111111111111"],
                    page_id="33333333333333333333333333333333",
                ),
                _build_task_database_row(
                    ticket_page="ALOVYA-2: Earlier child",
                    ticket_id="69",
                    parent_page_ids=["11111111111111111111111111111111"],
                    page_id="22222222222222222222222222222222",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert task_tree.tasks["ALOVYA-68"].child_task_ids == ["ALOVYA-69", "ALOVYA-70"]

    def test_reads_dependency_relations_and_task_metadata(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page="Dependency task",
                    ticket_id="1",
                    dependant_page_ids=["22222222222222222222222222222222"],
                    page_id="11111111111111111111111111111111",
                ),
                _build_task_database_row(
                    ticket_page="Dependant task",
                    ticket_id="2",
                    dependency_page_ids=["11111111111111111111111111111111"],
                    deadline="2026-06-15",
                    external_coordination="Yes",
                    uncertainty="High",
                    friction="Charged",
                    page_id="22222222222222222222222222222222",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert task_tree.tasks["ALOVYA-2"].dependency_task_ids == ["ALOVYA-1"]
        assert task_tree.tasks["ALOVYA-1"].dependant_task_ids == ["ALOVYA-2"]
        assert task_tree.tasks["ALOVYA-2"].deadline == "2026-06-15"
        assert task_tree.tasks["ALOVYA-2"].external_coordination == ExternalCoordination.YES
        assert task_tree.tasks["ALOVYA-2"].uncertainty == Uncertainty.HIGH
        assert task_tree.tasks["ALOVYA-2"].friction == Friction.CHARGED

    def test_rejects_dependency_and_dependant_relation_mismatch(self):
        with pytest.raises(ValueError, match="Dependants for task ALOVYA-1 do not match"):
            _build_task_tree(
                query_results=[
                    _build_task_database_row(
                        ticket_page="Dependency task",
                        ticket_id="1",
                        page_id="11111111111111111111111111111111",
                    ),
                    _build_task_database_row(
                        ticket_page="Dependant task",
                        ticket_id="2",
                        dependency_page_ids=["11111111111111111111111111111111"],
                        page_id="22222222222222222222222222222222",
                    ),
                ],
                landing_page=TrackedPage(
                    local_page_key="ongoing_landing_page",
                    title=ONGOING_LANDING_PAGE_TITLE,
                    notion_page_id="landing-page-id",
                ),
            )

    def test_rejects_dependency_relation_to_unknown_task(self):
        with pytest.raises(
            ValueError,
            match=(
                "Dependency page 99999999999999999999999999999999 "
                "for task ALOVYA-1 is not in the local task tree"
            ),
        ):
            _build_task_tree(
                query_results=[
                    _build_task_database_row(
                        ticket_page="Task with missing dependency",
                        ticket_id="1",
                        dependency_page_ids=["99999999999999999999999999999999"],
                        page_id="11111111111111111111111111111111",
                    ),
                ],
                landing_page=TrackedPage(
                    local_page_key="ongoing_landing_page",
                    title=ONGOING_LANDING_PAGE_TITLE,
                    notion_page_id="landing-page-id",
                ),
            )

    def test_defaults_blank_task_metadata_to_the_least_alarming_values(self):
        row = _build_task_database_row(
            ticket_page="Incomplete task metadata",
            ticket_id="1",
            page_id="11111111111111111111111111111111",
            priority="",
            status="",
        )
        del row["Priority"]
        del row["Status"]
        del row["External coordination"]
        del row["Uncertainty"]
        del row["Friction"]

        task_tree = _build_task_tree(
            query_results=[row],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        task = task_tree.tasks["ALOVYA-1"]
        assert task.configured_priority == Priority.P3
        assert task.status == TaskStatus.ACTIVE
        assert task.deadline is None
        assert task.start is None
        assert task.duration is None
        assert task.duration_unit is None
        assert task.external_coordination == ExternalCoordination.NO
        assert task.uncertainty == Uncertainty.LOW
        assert task.friction == Friction.NONE

    def test_rejects_rows_that_point_to_unknown_parent_rows(self):
        with pytest.raises(
            ValueError,
            match=(
                "Parent page 11111111111111111111111111111111 "
                "for task ALOVYA-69 is not in the current task database"
            ),
        ):
            _build_task_tree(
                query_results=[
                    _build_task_database_row(
                        ticket_page="ALOVYA-2: Child task",
                        ticket_id="69",
                        priority="P2",
                        status="Blocked",
                        parent_page_ids=["11111111111111111111111111111111"],
                        page_id="22222222222222222222222222222222",
                    ),
                ],
                landing_page=TrackedPage(
                    local_page_key="ongoing_landing_page",
                    title=ONGOING_LANDING_PAGE_TITLE,
                    notion_page_id="landing-page-id",
                ),
            )

    def test_rejects_duplicate_task_ids(self):
        with pytest.raises(ValueError, match="Duplicate task id ALOVYA-68"):
            _build_task_tree(
                query_results=[
                    _build_task_database_row(
                        ticket_page="ALOVYA-1: First task",
                        ticket_id="68",
                        page_id="11111111111111111111111111111111",
                    ),
                    _build_task_database_row(
                        ticket_page="ALOVYA-1: Duplicate task",
                        ticket_id="68",
                        priority="P2",
                        page_id="22222222222222222222222222222222",
                    ),
                ],
                landing_page=TrackedPage(
                    local_page_key="ongoing_landing_page",
                    title=ONGOING_LANDING_PAGE_TITLE,
                    notion_page_id="landing-page-id",
                ),
            )


class TestTaskIdFromFetchedTaskDatabasePage:
    def test_reads_notion_assigned_ticket_id_from_properties(self):
        task_id = task_id_from_fetched_task_database_page(
            "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Task ID":"72","Task page":"Fresh task"}',
                    "</properties>",
                    "</page>",
                ]
            ),
            ticket_prefix="PERSONAL",
        )

        assert task_id == "PERSONAL-72"


def _build_task_tree(*args, **kwargs) -> TaskTree:
    return build_task_tree_from_database_query_results(*args, ticket_prefix="ALOVYA", **kwargs)


def _build_task_database_row(
    ticket_page: str,
    ticket_id: str,
    page_id: str | None = None,
    page_url: str | None = None,
    priority: str = "P1",
    status: str = "Active",
    parent_page_ids: list[str] | None = None,
    dependency_page_ids: list[str] | None = None,
    dependant_page_ids: list[str] | None = None,
    deadline: str | None = None,
    start: str | None = None,
    duration: float | None = None,
    duration_unit: str | None = None,
    external_coordination: str = "No",
    uncertainty: str = "Low",
    friction: str = "None",
) -> dict:
    return {
        "Task page": ticket_page,
        "Task ID": ticket_id,
        "Priority": priority,
        "Status": status,
        "Parent": _render_relation_urls(parent_page_ids or []),
        "Dependencies": _render_relation_urls(dependency_page_ids or []),
        "Dependants": _render_relation_urls(dependant_page_ids or []),
        "Deadline": deadline or "",
        "Start": start or "",
        "End": "",
        "Duration": duration if duration is not None else "",
        "Duration unit": duration_unit or "",
        "External coordination": external_coordination,
        "Uncertainty": uncertainty,
        "Friction": friction,
        "url": page_url or f"https://www.notion.so/{page_id}",
    }


def _render_relation_urls(page_ids: list[str]) -> str:
    return json.dumps([
        f"https://www.notion.so/{page_id}"
        for page_id in page_ids
    ])
