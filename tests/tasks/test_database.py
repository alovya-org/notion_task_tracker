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
    build_task_database_tracker_state,
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    build_task_tree_from_database_query_results,
    task_id_from_fetched_task_database_page,
)


class TestTaskTreeFromDatabaseQueryResults:
    def test_builds_tree_from_ticket_ids_and_parent_relations(self):
        previous_task_tree = TaskTree()
        previous_task_tree.add_task(
            Task(
                task_id="ALOVYA-68",
                title="Old root title",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                status_update="Keep local status detail.",
                notion_page_id="11111111111111111111111111111111",
            )
        )

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
            previous_task_tree=previous_task_tree,
        )

        assert task_tree.tasks["ALOVYA-68"].title == "Root task"
        assert task_tree.tasks["ALOVYA-68"].status_update == "Keep local status detail."
        assert task_tree.tasks["ALOVYA-68"].child_task_ids == ["ALOVYA-69"]
        assert task_tree.tasks["ALOVYA-69"].parent_task_id == "ALOVYA-68"
        assert task_tree.tasks["ALOVYA-69"].configured_priority == Priority.P2
        assert task_tree.tasks["ALOVYA-69"].status == TaskStatus.BLOCKED

    def test_rejects_a_different_ticket_id_for_a_known_notion_page(self):
        previous_task_tree = TaskTree()
        previous_task_tree.add_task(
            Task(
                task_id="ALOVYA-118",
                title="Stage 1",
                configured_priority=Priority.P2,
                status=TaskStatus.ACTIVE,
                notion_page_id="11111111111111111111111111111111",
            )
        )

        with pytest.raises(
            ValueError,
            match=(
                "Notion page 11111111111111111111111111111111 changed task identity "
                "from ALOVYA-118 to ALOVYA-127; refusing to reconcile"
            ),
        ):
            _build_task_tree(
                query_results=[
                    _build_task_database_row(
                        ticket_page="Stage 1",
                        ticket_id="127",
                        page_id="11111111111111111111111111111111",
                    ),
                ],
                landing_page=TrackedPage(
                    local_page_key="ongoing_landing_page",
                    title=ONGOING_LANDING_PAGE_TITLE,
                    notion_page_id="landing-page-id",
                ),
                previous_task_tree=previous_task_tree,
            )

    def test_preserves_completed_landing_page_from_previous_tree(self):
        previous_task_tree = TaskTree()
        previous_task_tree.completed_tasks_landing_page.page.notion_page_id = "completed-landing-page-id"

        task_tree = _build_task_tree(
            query_results=[],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
            previous_task_tree=previous_task_tree,
        )

        assert task_tree.completed_tasks_landing_page.page.title == COMPLETED_LANDING_PAGE_TITLE
        assert task_tree.completed_tasks_landing_page.page.notion_page_id == "completed-landing-page-id"

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

    def test_skips_rows_that_point_to_unknown_parent_rows(self):
        task_tree = _build_task_tree(
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
            )
        )

        assert task_tree.tasks == {}

    def test_skips_orphan_subtrees(self):
        task_tree = _build_task_tree(
            query_results=[
                _build_task_database_row(
                    ticket_page="Parent prototype",
                    ticket_id="15",
                    parent_page_ids=["11111111111111111111111111111111"],
                    page_id="22222222222222222222222222222222",
                ),
                _build_task_database_row(
                    ticket_page="Child prototype",
                    ticket_id="16",
                    parent_page_ids=["22222222222222222222222222222222"],
                    page_id="33333333333333333333333333333333",
                ),
            ],
            landing_page=TrackedPage(
                local_page_key="ongoing_landing_page",
                title=ONGOING_LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            )
        )

        assert task_tree.tasks == {}

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


class TestTaskDatabaseTrackerState:
    def test_builds_task_property_filtered_query_for_configured_data_source(self):
        tracker_state = build_task_database_tracker_state(
            data_source_id="configured-data-source-id",
        )

        assert task_database_data_source_url_from_tracker_state(tracker_state={"task_database": tracker_state}) == (
            "collection://configured-data-source-id"
        )
        assert task_database_query_for_tracker_state({"task_database": tracker_state}) == (
            'SELECT * FROM "collection://configured-data-source-id"'
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
