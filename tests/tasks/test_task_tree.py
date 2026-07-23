from __future__ import annotations

import pytest

from notion_task_tracker import COMPLETED_LANDING_PAGE_TITLE, ONGOING_LANDING_PAGE_TITLE
from notion_task_tracker.errors import NotionPlanningError
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    plan_completion_write_intents,
    plan_notion_writes_for_task_tree,
    build_timeline_log_write_intent,
)
from notion_task_tracker.tasks import (
    DurationUnit,
    Priority,
    TaskTree,
    Task,
    TaskStatus,
    TimelineEntry,
    TimelineLog,
)
from tests.tasks.helpers import (
    _build_recursive_task_tree,
)


class TestTaskTreeRecalculateDisplayPriorities:
    def test_active_deep_child_priority_rolls_up_to_ancestors(self):
        task_tree = _build_recursive_task_tree()

        task_tree.recalculate_display_priorities()

        assert task_tree.tasks["ALOVYA-5"].displayed_priority == Priority.P0
        assert task_tree.tasks["ALOVYA-3"].displayed_priority == Priority.P0
        assert task_tree.tasks["ALOVYA-2"].displayed_priority == Priority.P0
        assert task_tree.tasks["ALOVYA-4"].displayed_priority == Priority.P3

    def test_intermediate_task_priority_comes_from_children_not_its_configured_priority(self):
        task_tree = TaskTree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-1",
                title="Parent with urgent stored priority",
                configured_priority=Priority.P0,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.add_task(
            Task(
                task_id="ALOVYA-2",
                title="Only active leaf",
                configured_priority=Priority.P3,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.link_parent_to_child(parent_task_id="ALOVYA-1", child_task_id="ALOVYA-2")

        task_tree.recalculate_display_priorities()

        assert task_tree.tasks["ALOVYA-1"].displayed_priority == Priority.P3
        assert task_tree.tasks["ALOVYA-2"].displayed_priority == Priority.P3

    def test_completed_deep_child_priority_stops_rolling_up(self):
        task_tree = _build_recursive_task_tree()
        task_tree.tasks["ALOVYA-5"].status = TaskStatus.COMPLETE

        task_tree.recalculate_display_priorities()

        assert task_tree.tasks["ALOVYA-5"].displayed_priority == Priority.P0
        assert task_tree.tasks["ALOVYA-3"].displayed_priority == Priority.P1
        assert task_tree.tasks["ALOVYA-2"].displayed_priority == Priority.P1


class TestTaskTreeValidate:
    def test_rejects_parent_child_link_mismatch(self):
        task_tree = _build_recursive_task_tree()
        task_tree.tasks["ALOVYA-5"].parent_task_id = "ALOVYA-2"

        with pytest.raises(ValueError, match="should have parent ALOVYA-3"):
            task_tree.validate()

    def test_rejects_task_hierarchy_cycle(self):
        task_tree = TaskTree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-1",
                title="Root",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                parent_task_id="ALOVYA-2",
                child_task_ids=["ALOVYA-2"],
            )
        )
        task_tree.add_task(
            Task(
                task_id="ALOVYA-2",
                title="Child",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                parent_task_id="ALOVYA-1",
                child_task_ids=["ALOVYA-1"],
            )
        )

        with pytest.raises(ValueError, match="Task hierarchy has a cycle"):
            task_tree.validate()

    def test_rejects_dependency_without_matching_dependant(self):
        task_tree = _build_dependency_task_tree()
        task_tree.tasks["ALOVYA-1"].dependant_task_ids = []

        with pytest.raises(ValueError, match="Task ALOVYA-1 should list ALOVYA-2 as a dependant"):
            task_tree.validate()

    def test_rejects_dependant_without_matching_dependency(self):
        task_tree = _build_dependency_task_tree()
        task_tree.tasks["ALOVYA-2"].dependency_task_ids = []

        with pytest.raises(ValueError, match="Task ALOVYA-2 should depend on ALOVYA-1"):
            task_tree.validate()

    def test_rejects_dependency_that_does_not_exist(self):
        task_tree = TaskTree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-1",
                title="Needs missing dependency",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                dependency_task_ids=["ALOVYA-404"],
            )
        )

        with pytest.raises(ValueError, match="Task ALOVYA-404 does not exist"):
            task_tree.validate()

    def test_rejects_task_that_depends_on_itself(self):
        task_tree = TaskTree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-1",
                title="Self dependency",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                dependency_task_ids=["ALOVYA-1"],
            )
        )

        with pytest.raises(ValueError, match="Task ALOVYA-1 cannot depend on itself"):
            task_tree.validate()

    def test_normalises_duplicate_dependencies_and_dependants(self):
        task_tree = TaskTree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-1",
                title="First dependency",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.add_task(
            Task(
                task_id="ALOVYA-2",
                title="Second dependency",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.add_task(
            Task(
                task_id="ALOVYA-3",
                title="Depends on both",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                dependency_task_ids=["ALOVYA-2", "ALOVYA-1", "ALOVYA-2"],
            )
        )

        task_tree.derive_dependant_task_ids_from_dependencies()

        assert task_tree.tasks["ALOVYA-3"].dependency_task_ids == ["ALOVYA-1", "ALOVYA-2"]
        assert task_tree.tasks["ALOVYA-1"].dependant_task_ids == ["ALOVYA-3"]
        assert task_tree.tasks["ALOVYA-2"].dependant_task_ids == ["ALOVYA-3"]


class TestTaskTreeFromSnapshot:
    def test_rejects_state_without_configured_completed_landing_page(self):
        with pytest.raises(ValueError, match="completed_landing_page.*configured title"):
            TaskTree.from_tracker_state(
                {
                    "ongoing_landing_page": {
                        "local_page_key": "ongoing_landing_page",
                        "title": ONGOING_LANDING_PAGE_TITLE,
                        "notion_page_id": "11111111111111111111111111111111",
                        "parent_page_key": None,
                    },
                    "completed_landing_page": None,
                    "tasks": {},
                }
            )


class TestTaskTreeTaskIdsGroupedForLandingPage:
    def test_groups_live_top_level_tasks_by_displayed_priority(self):
        task_tree = _build_recursive_task_tree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-9",
                title="Parked cleanup",
                configured_priority=Priority.P3,
                status=TaskStatus.PARKED,
                notion_page_id="99999999999999999999999999999999",
            )
        )

        grouped_task_ids = task_tree.task_ids_grouped_for_landing_page()

        assert grouped_task_ids[Priority.P0] == ["ALOVYA-2"]
        assert grouped_task_ids[Priority.P3] == ["ALOVYA-9"]

    def test_keeps_completed_tasks_in_completed_section_when_their_parent_is_not_completed(self):
        task_tree = _build_recursive_task_tree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-9",
                title="Completed optimisation",
                configured_priority=Priority.P0,
                status=TaskStatus.COMPLETE,
                notion_page_id="99999999999999999999999999999999",
            )
        )

        grouped_task_ids = task_tree.task_ids_grouped_for_landing_page()

        assert grouped_task_ids[Priority.P0] == ["ALOVYA-2"]
        assert task_tree.completed_task_ids_for_landing_page() == ["ALOVYA-4", "ALOVYA-9"]

    def test_orders_top_level_tasks_by_ticket_number_not_title(self):
        task_tree = _build_recursive_task_tree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-10",
                title="A title that would sort before the existing task",
                configured_priority=Priority.P0,
                status=TaskStatus.ACTIVE,
                notion_page_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )

        grouped_task_ids = task_tree.task_ids_grouped_for_landing_page()

        assert grouped_task_ids[Priority.P0] == ["ALOVYA-2", "ALOVYA-10"]


class TestTaskTreeBuildNotionWritePlan:
    def test_refreshes_fixed_pages_and_database_task_properties_without_creating_task_pages(self):
        task_tree = _build_recursive_task_tree()

        write_intents = plan_notion_writes_for_task_tree(task_tree)

        assert not any(
            write_intent.operation_key.startswith("create:task:")
            for write_intent in write_intents
        )
        assert not any(
            write_intent.operation_key.startswith("replace:task:")
            for write_intent in write_intents
        )
        assert {
            write_intent.operation_key
            for write_intent in write_intents
        } >= {
            "create:ongoing_landing_page",
            "create:completed_landing_page",
            "replace:ongoing_landing_page",
            "update_properties:task:ALOVYA-2",
            "update_properties:task:ALOVYA-4",
        }

    def test_renders_landing_page_trees_from_database_tree(self):
        task_tree = _build_recursive_task_tree()

        landing_refresh_intent = next(
            write_intent
            for write_intent in plan_notion_writes_for_task_tree(task_tree)
            if write_intent.operation_key == "replace:ongoing_landing_page"
        )

        landing_markdown = landing_refresh_intent.arguments["markdown"]

        assert "## P0 (high impact and urgent)" in landing_markdown
        assert '- [P0] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>: Active {color="red"}' in landing_markdown
        assert '\t- [P0] <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>: Active {color="red"}' in landing_markdown
        assert '\t\t- [P0] <mention-page url="https://www.notion.so/55555555555555555555555555555555"/>: Blocked {color="red"}' in landing_markdown
        assert '\t- [N/A] ~~<mention-page url="https://www.notion.so/44444444444444444444444444444444"/>~~: Complete {color="green"}' in landing_markdown

    def test_renders_completed_page_from_completed_tasks_without_completed_parents(self):
        task_tree = _build_recursive_task_tree()
        task_tree.completed_tasks_landing_page.page.notion_page_id = "completed-landing-page-id"

        completed_landing_refresh_intent = next(
            write_intent
            for write_intent in plan_notion_writes_for_task_tree(task_tree)
            if write_intent.operation_key == "replace:completed_landing_page"
        )

        assert completed_landing_refresh_intent.arguments["markdown"] == "\n".join([
            "## Completed",
            '- [N/A] ~~<mention-page url="https://www.notion.so/44444444444444444444444444444444"/>~~: Complete {color="green"}',
        ])

    def test_completed_task_page_title_strikes_through_and_properties_include_database_metadata(self):
        task_tree = _build_recursive_task_tree()

        title_refresh_intent = next(
            write_intent
            for write_intent in plan_notion_writes_for_task_tree(task_tree)
            if write_intent.operation_key == "update_properties:task:ALOVYA-4"
        )

        assert title_refresh_intent.arguments["properties"] == {
            "Deadline": None,
            "Start": None,
            "End": None,
            "Duration": None,
            "Duration unit": None,
            "External coordination": "No",
            "Friction": "None",
            "Priority": "P3",
            "Status": "Complete",
            "Task page": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": "[4] Complete calibration branch"},
                        "annotations": {
                            "bold": False,
                            "italic": False,
                            "strikethrough": True,
                            "underline": False,
                            "code": False,
                            "color": "default",
                        },
                    }
                ],
            },
            "Uncertainty": "Low",
        }


class TestTaskTreeRepairOperationKeysForChanges:
    def test_includes_changed_tasks_ancestors_and_landing_pages(self):
        task_tree = TaskTree()
        task_tree.add_task(
            Task(
                task_id="ALOVYA-1",
                title="Root",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.add_task(
            Task(
                task_id="ALOVYA-2",
                title="Child",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.add_task(
            Task(
                task_id="ALOVYA-3",
                title="Grandchild",
                configured_priority=Priority.P2,
                status=TaskStatus.ACTIVE,
            )
        )
        task_tree.link_parent_to_child("ALOVYA-1", "ALOVYA-2")
        task_tree.link_parent_to_child("ALOVYA-2", "ALOVYA-3")

        operation_keys = task_tree.repair_operation_keys_for_changes(
            [
                {
                    "task_id": "ALOVYA-3",
                    "fields": {
                        "configured_priority": {
                            "before": "P2",
                            "after": "P1",
                        }
                    },
                }
            ]
        )

        assert operation_keys == [
            "update_properties:task:ALOVYA-1",
            "update_properties:task:ALOVYA-2",
            "update_properties:task:ALOVYA-3",
        ]


class TestTaskTreeAppendTaskTimelineLog:
    def test_returns_single_timeline_update_intent(self):
        task_tree = _build_recursive_task_tree()
        timeline_log = TimelineLog(
            log_id="ALOVYA-LOG-00000000-0000-4000-8000-000000000001",
            title="Mismatch test result",
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
            lines=["Tested the mismatch fix and found one remaining failing node."],
        )

        timeline_log_change = task_tree.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_log=timeline_log,
        )
        write_intent = build_timeline_log_write_intent(timeline_log_change)

        assert task_tree.tasks["ALOVYA-5"].timeline_entries[-1] == TimelineEntry(
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
        )
        assert write_intent.operation_name == "update_timeline_log"
        assert write_intent.target_page_key == "task:ALOVYA-5"
        assert write_intent.arguments["task_id"] == "ALOVYA-5"
        assert write_intent.arguments["timeline_log_heading"] == "Timeline log"
        assert write_intent.arguments["timeline_entry"]["entry_date"] == "2026-05-25"
        assert '### <mention-date start="2026-05-25"/>' in write_intent.arguments["timeline_section_markdown"]
        assert "old_timeline_section_markdown" not in write_intent.arguments

    def test_appends_identified_toggle_after_legacy_content_for_same_date(self):
        task_tree = _build_recursive_task_tree()
        task_tree.tasks["ALOVYA-5"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Started debugging the repair path."],
            )
        )

        timeline_log_change = task_tree.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_log=TimelineLog(
                log_id="ALOVYA-LOG-00000000-0000-4000-8000-000000000002",
                title="REST investigation",
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Found the stale REST request."],
            ),
        )
        write_intent = build_timeline_log_write_intent(timeline_log_change)

        assert task_tree.tasks["ALOVYA-5"].timeline_entries == [
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Started debugging the repair path."],
            )
        ]
        assert write_intent.arguments["timeline_entry"]["lines"] == []
        assert write_intent.arguments["appended_markdown"] == "\n".join([
            "<details>",
            "<summary>REST investigation · ALOVYA-LOG-00000000-0000-4000-8000-000000000002</summary>",
            "\t- Found the stale REST request.",
            "</details>",
        ])
        assert write_intent.arguments["new_timeline_section_markdown"] == "\n".join([
            '### <mention-date start="2026-05-25"/>',
            "- Started debugging the repair path.",
            "<details>",
            "<summary>REST investigation · ALOVYA-LOG-00000000-0000-4000-8000-000000000002</summary>",
            "\t- Found the stale REST request.",
            "</details>",
        ])

    def test_appends_log_title_and_identifier_as_toggle_title(self):
        task_tree = _build_recursive_task_tree()
        task_tree.tasks["ALOVYA-5"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
            )
        )

        timeline_log_change = task_tree.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_log=TimelineLog(
                log_id="ALOVYA-LOG-00000000-0000-4000-8000-000000000003",
                title="Design notes",
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Moved task metadata into the database."],
            ),
        )
        write_intent = build_timeline_log_write_intent(timeline_log_change)

        assert write_intent.arguments["appended_markdown"] == "\n".join([
            "<details>",
            "<summary>Design notes · ALOVYA-LOG-00000000-0000-4000-8000-000000000003</summary>",
            "\t- Moved task metadata into the database.",
            "</details>",
        ])

    def test_collapses_existing_duplicate_date_headings_before_appending_lines(self):
        task_tree = _build_recursive_task_tree()
        task_tree.tasks["ALOVYA-5"].timeline_entries.extend(
            [
                TimelineEntry(
                    entry_date="2026-05-25",
                    heading='<mention-date start="2026-05-25"/>',
                    lines=["Started debugging the repair path."],
                ),
                TimelineEntry(
                    entry_date="2026-05-25",
                    heading='<mention-date start="2026-05-25"/>',
                    lines=["Found the stale REST request."],
                ),
            ]
        )

        task_tree.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_log=TimelineLog(
                log_id="ALOVYA-LOG-00000000-0000-4000-8000-000000000004",
                title="Call generator patch",
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Patched the call generator."],
            ),
        )

        assert task_tree.tasks["ALOVYA-5"].timeline_entries == [
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=[
                    "Started debugging the repair path.",
                    "Found the stale REST request.",
                ],
            )
        ]


class TestTaskTreeCompleteTask:
    def test_marks_task_complete_and_updates_database_properties_plus_derived_views(self):
        task_tree = _build_recursive_task_tree()
        timeline_log = TimelineLog(
            log_id="ALOVYA-LOG-00000000-0000-4000-8000-000000000005",
            title="Completed investigation",
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
            lines=["Completed the mismatch investigation."],
        )

        completion_change = task_tree.complete_task(
            task_id="ALOVYA-5",
            timeline_log=timeline_log,
        )
        write_intents = plan_completion_write_intents(task_tree, completion_change)

        assert task_tree.tasks["ALOVYA-5"].status == TaskStatus.COMPLETE
        assert task_tree.tasks["ALOVYA-5"].timeline_entries[-1] == TimelineEntry(
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
        )
        assert [write_intent.operation_key for write_intent in write_intents] == [
            "update_properties:task:ALOVYA-5",
            "replace:ongoing_landing_page",
            "update_timeline_log:task:ALOVYA-5:2026-05-25:ALOVYA-LOG-00000000-0000-4000-8000-000000000005",
        ]


class TestTaskTreeFromTrackerState:
    def test_preserves_configured_fixed_page_titles(self):
        tracker_state = TaskTree().to_tracker_state()
        tracker_state["ongoing_landing_page"]["title"] = "User-edited landing title"
        tracker_state["ongoing_landing_page"]["notion_page_id"] = "landing-page-id"

        loaded_task_tree = TaskTree.from_tracker_state(tracker_state)

        assert loaded_task_tree.ongoing_tasks_landing_page.page.title == "User-edited landing title"
        assert loaded_task_tree.ongoing_tasks_landing_page.page.notion_page_id == "landing-page-id"

    def test_round_trips_dependency_source_and_dependant_inverse(self):
        task_tree = _build_dependency_task_tree()

        loaded_task_tree = TaskTree.from_tracker_state(task_tree.to_tracker_state())

        assert loaded_task_tree.tasks["ALOVYA-2"].dependency_task_ids == ["ALOVYA-1"]
        assert loaded_task_tree.tasks["ALOVYA-1"].dependant_task_ids == ["ALOVYA-2"]

    def test_requires_new_task_database_fields_in_tracker_state(self):
        tracker_state = TaskTree().to_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"] = {
            "task_id": "ALOVYA-1",
            "title": "Incomplete persisted task",
            "configured_priority": "P1",
            "displayed_priority": "P1",
            "status": "Active",
            "status_update": "",
            "parent_task_id": None,
            "child_task_ids": [],
            "timeline_entries": [],
            "links": [],
            "notion_page_id": "11111111111111111111111111111111",
        }

        with pytest.raises(KeyError, match="dependency_task_ids"):
            TaskTree.from_tracker_state(tracker_state)


class TestTaskTreeValidateSchedulingFields:
    def test_allows_duration_estimate_without_start(self):
        task_tree = _task_tree_with_schedule(
            start=None,
            duration=2.5,
            duration_unit=DurationUnit.HOURS,
        )

        task_tree.validate()

    def test_requires_duration_and_unit_together(self):
        task_tree = _task_tree_with_schedule(
            start=None,
            duration=2,
            duration_unit=None,
        )

        with pytest.raises(NotionPlanningError, match="Duration and Duration unit together"):
            task_tree.validate()

    def test_timed_start_requires_hours(self):
        task_tree = _task_tree_with_schedule(
            start="2026-07-22T09:30:00+01:00",
            duration=2,
            duration_unit=DurationUnit.DAYS,
        )

        with pytest.raises(NotionPlanningError, match="timed Start requires Duration unit Hours"):
            task_tree.validate()

    def test_date_only_start_accepts_whole_weeks(self):
        task_tree = _task_tree_with_schedule(
            start="2026-07-22",
            duration=2,
            duration_unit=DurationUnit.WEEKS,
            end="2026-08-05",
        )

        task_tree.validate()

    def test_date_only_start_rejects_hours(self):
        task_tree = _task_tree_with_schedule(
            start="2026-07-22",
            duration=2,
            duration_unit=DurationUnit.HOURS,
        )

        with pytest.raises(NotionPlanningError, match="date-only Start requires"):
            task_tree.validate()

    def test_days_and_weeks_require_whole_numbers(self):
        task_tree = _task_tree_with_schedule(
            start=None,
            duration=1.5,
            duration_unit=DurationUnit.WEEKS,
        )

        with pytest.raises(NotionPlanningError, match="Weeks duration must be a whole number"):
            task_tree.validate()


def _build_dependency_task_tree() -> TaskTree:
    task_tree = TaskTree()
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Dependency",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
        )
    )
    task_tree.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Dependant",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            dependency_task_ids=["ALOVYA-1"],
        )
    )
    task_tree.derive_dependant_task_ids_from_dependencies()
    return task_tree


def _task_tree_with_schedule(
    start: str | None,
    duration: float | None,
    duration_unit: DurationUnit | None,
    end: str | None = None,
) -> TaskTree:
    task_tree = TaskTree()
    task_tree.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Estimated or scheduled task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            start=start,
            end=end,
            duration=duration,
            duration_unit=duration_unit,
        )
    )
    return task_tree
