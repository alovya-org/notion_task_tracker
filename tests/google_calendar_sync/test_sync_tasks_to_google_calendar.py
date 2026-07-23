import asyncio
from datetime import date, datetime
from notion_task_tracker.google_calendar_sync.sync_tasks_to_google_calendar import (
    DesiredCalendarEvent,
    derive_desired_calendar_events,
    plan_google_calendar_updates,
    project_current_tasks_into_google_calendar,
)
from notion_task_tracker.tasks import DurationUnit, Priority, Task, TaskStatus, TaskTree


def test_derives_timed_and_all_day_events_for_active_scheduled_leaves():
    task_tree = TaskTree()
    task_tree.add_task(_scheduled_task("ALOVYA-1", "Timed work", "2026-07-30T23:30:00+01:00", 2.5, DurationUnit.HOURS))
    task_tree.add_task(_scheduled_task("ALOVYA-2", "Calendar week", "2026-08-03", 1, DurationUnit.WEEKS))

    events = derive_desired_calendar_events(task_tree, "Europe/London")

    assert events[0].start_date_time == datetime.fromisoformat("2026-07-30T23:30:00+01:00")
    assert events[0].end_date_time == datetime.fromisoformat("2026-07-31T02:00:00+01:00")
    assert events[0].title == "[NTT] Timed work"
    assert events[0].transparency == "transparent"
    assert events[1].start_date == date(2026, 8, 3)
    assert events[1].end_date == date(2026, 8, 10)


def test_excludes_parents_incomplete_schedules_and_finished_tasks():
    task_tree = TaskTree()
    parent = _scheduled_task("ALOVYA-1", "Parent", "2026-08-03", 1, DurationUnit.DAYS)
    child = _scheduled_task("ALOVYA-2", "Child", "2026-08-04", 1, DurationUnit.DAYS)
    incomplete = Task("ALOVYA-3", "Estimate only", Priority.P2, TaskStatus.ACTIVE, duration=2, duration_unit=DurationUnit.HOURS)
    complete = _scheduled_task("ALOVYA-4", "Finished", "2026-08-05", 1, DurationUnit.DAYS, TaskStatus.COMPLETE)
    for task in [parent, child, incomplete, complete]:
        task_tree.add_task(task)
    task_tree.link_parent_to_child("ALOVYA-1", "ALOVYA-2")

    events = derive_desired_calendar_events(task_tree, "Europe/London")

    assert [event.task_id for event in events] == ["ALOVYA-2"]


def test_hour_duration_keeps_elapsed_time_across_daylight_saving_change():
    task_tree = TaskTree()
    task_tree.add_task(
        _scheduled_task(
            "ALOVYA-1",
            "Cross the spring clock change",
            "2026-03-29T00:30:00+00:00",
            2,
            DurationUnit.HOURS,
        )
    )

    event = derive_desired_calendar_events(task_tree, "Europe/London")[0]

    assert event.start_date_time == datetime.fromisoformat("2026-03-29T00:30:00+00:00")
    assert event.end_date_time == datetime.fromisoformat("2026-03-29T03:30:00+01:00")


def test_projects_the_supplied_current_task_tree_to_google_calendar():
    task_tree = TaskTree()
    task_tree.add_task(_scheduled_task(
        "ALOVYA-1",
        "Write Stage 5",
        "2026-08-03T09:00:00+01:00",
        1.5,
        DurationUnit.HOURS,
    ))
    google_calendar_client = _RecordingGoogleCalendarClient()
    google_calendar_state_client = _RecordingGoogleCalendarStateClient()

    calendar_operations, warnings, desired_event_count = asyncio.run(
        project_current_tasks_into_google_calendar(
        task_tree=task_tree,
        tracker_user="al0vya",
        tracker_id="ALOVYA",
        calendar_id="test-calendar",
        timezone_name="Europe/London",
        colour_id="8",
        google_calendar_client=google_calendar_client,
        google_calendar_state_client=google_calendar_state_client,
        )
    )

    assert google_calendar_client.list_queries == [{
        "privateExtendedProperty": "ntt_tracker=ALOVYA",
        "showDeleted": "false",
    }]
    assert len(google_calendar_client.created_events) == 1
    created_event = google_calendar_client.created_events[0]
    assert created_event["summary"] == "[NTT] Write Stage 5"
    assert created_event["colorId"] == "8"
    assert created_event["extendedProperties"]["private"] == {
        "ntt_tracker": "ALOVYA",
        "ntt_task_id": "ALOVYA-1",
    }
    assert calendar_operations == ["create:calendar_event:ALOVYA-1"]
    assert warnings == []
    assert desired_event_count == 1
    assert google_calendar_state_client.active_events == [
        ("al0vya", "test-calendar", "created-event", "ALOVYA-1")
    ]


def test_marks_an_orphaned_event_as_ntt_deleted_before_removing_it_from_google():
    operations = []
    google_calendar_state_client = _RecordingGoogleCalendarStateClient(operations)

    class CalendarWithOrphanedEvent:
        async def list_all_calendar_events(self, query):
            return [{"id": "event-one", **_timed_resource("ALOVYA-42", "Removed task")}]

        async def create_calendar_event(self, event):
            raise AssertionError("No event should be created")

        async def replace_calendar_event(self, event_id, event):
            raise AssertionError("No event should be replaced")

        async def delete_calendar_event(self, event_id):
            operations.append(("delete_from_google", event_id))

    asyncio.run(project_current_tasks_into_google_calendar(
        task_tree=TaskTree(),
        tracker_user="al0vya",
        tracker_id="ALOVYA",
        calendar_id="test-calendar",
        timezone_name="Europe/London",
        colour_id=None,
        google_calendar_client=CalendarWithOrphanedEvent(),
        google_calendar_state_client=google_calendar_state_client,
    ))

    assert operations == [
        ("record_active", "event-one", "ALOVYA-42"),
        ("mark_deleted_by_ntt", "event-one", "ALOVYA-42"),
        ("delete_from_google", "event-one"),
    ]


class _RecordingGoogleCalendarClient:
    def __init__(self):
        self.list_queries = []
        self.created_events = []

    async def list_all_calendar_events(self, query):
        self.list_queries.append(query)
        return []

    async def create_calendar_event(self, event):
        self.created_events.append(event)
        return {"id": "created-event"}

    async def replace_calendar_event(self, event_id, event):
        raise AssertionError("No event should be replaced")

    async def delete_calendar_event(self, event_id):
        raise AssertionError("No event should be deleted")


class _RecordingGoogleCalendarStateClient:
    def __init__(self, operations=None):
        self.active_events = []
        self.ntt_deletions = []
        self.operations = operations

    async def record_active_google_calendar_event(
        self,
        tracker_user,
        calendar_id,
        google_event_id,
        ntt_task_id,
    ):
        identity = (tracker_user, calendar_id, google_event_id, ntt_task_id)
        self.active_events.append(identity)
        if self.operations is not None:
            self.operations.append(("record_active", google_event_id, ntt_task_id))

    async def mark_google_calendar_event_deleted_by_ntt(
        self,
        tracker_user,
        calendar_id,
        google_event_id,
        ntt_task_id,
    ):
        identity = (tracker_user, calendar_id, google_event_id, ntt_task_id)
        self.ntt_deletions.append(identity)
        if self.operations is not None:
            self.operations.append(("mark_deleted_by_ntt", google_event_id, ntt_task_id))


def _scheduled_task(
    task_id: str,
    title: str,
    start: str,
    duration: float,
    duration_unit: DurationUnit,
    status: TaskStatus = TaskStatus.ACTIVE,
) -> Task:
    from notion_task_tracker.tasks.task import derive_task_end

    return Task(
        task_id=task_id,
        title=title,
        configured_priority=Priority.P2,
        status=status,
        start=start,
        end=derive_task_end(task_id, start, duration, duration_unit),
        duration=duration,
        duration_unit=duration_unit,
    )


def test_plans_create_replace_and_unambiguously_orphaned_delete_changes():
    desired_events = [
        _timed_event("ALOVYA-1", "Keep unchanged"),
        _timed_event("ALOVYA-2", "Replace changed"),
        _all_day_event("ALOVYA-3", "Create missing"),
    ]
    existing_events = [
        {
            "id": "keep",
            **_timed_resource("ALOVYA-1", "Keep unchanged"),
            "extendedProperties": {
                "private": {"ntt_tracker": "ALOVYA", "ntt_task_id": "ALOVYA-1"},
                "shared": {"calendar_owner_metadata": "preserved"},
            },
        },
        {"id": "replace", **_timed_resource("ALOVYA-2", "Old title")},
        {"id": "delete", **_timed_resource("ALOVYA-4", "Orphan")},
        {"id": "foreign", **_timed_resource("OTHER-1", "Foreign", tracker_id="OTHER")},
    ]

    plan = plan_google_calendar_updates(
        desired_events,
        existing_events,
        tracker_id="ALOVYA",
        timezone_name="Europe/London",
        colour_id="8",
    )

    assert [event["extendedProperties"]["private"]["ntt_task_id"] for event in plan.events_to_create] == [
        "ALOVYA-3"
    ]
    assert [(replacement.event_id, replacement.event["summary"]) for replacement in plan.events_to_replace] == [
        ("replace", "[NTT] Replace changed")
    ]
    assert [(deletion.event_id, deletion.task_id) for deletion in plan.events_to_delete] == [
        ("delete", "ALOVYA-4")
    ]
    assert [(identity.event_id, identity.task_id) for identity in plan.existing_event_identities] == [
        ("keep", "ALOVYA-1"),
        ("replace", "ALOVYA-2"),
    ]
    assert plan.warnings == []
    assert plan.events_to_create[0]["start"] == {"date": "2026-08-03"}
    assert plan.events_to_create[0]["end"] == {"date": "2026-08-04"}


def test_preserves_owned_events_when_task_identity_is_missing_or_duplicated():
    existing_events = [
        {"id": "missing-task", "extendedProperties": {"private": {"ntt_tracker": "ALOVYA"}}},
        {"id": "duplicate-one", **_timed_resource("ALOVYA-8", "Duplicate")},
        {"id": "duplicate-two", **_timed_resource("ALOVYA-8", "Duplicate")},
    ]

    plan = plan_google_calendar_updates(
        [_timed_event("ALOVYA-8", "Duplicate")],
        existing_events,
        tracker_id="ALOVYA",
        timezone_name="Europe/London",
    )

    assert plan.events_to_create == []
    assert plan.events_to_replace == []
    assert plan.events_to_delete == []
    assert [warning["kind"] for warning in plan.warnings] == [
        "ambiguous_calendar_event",
        "ambiguous_calendar_event",
    ]


def _timed_event(task_id: str, title: str) -> DesiredCalendarEvent:
    return DesiredCalendarEvent(
        task_id=task_id,
        title=f"[NTT] {title}",
        description="This is a personal task. Feel free to schedule a meeting over this slot.",
        transparency="transparent",
        start_date_time=datetime.fromisoformat("2026-08-03T09:00:00+01:00"),
        end_date_time=datetime.fromisoformat("2026-08-03T10:00:00+01:00"),
    )


def _all_day_event(task_id: str, title: str) -> DesiredCalendarEvent:
    return DesiredCalendarEvent(
        task_id=task_id,
        title=f"[NTT] {title}",
        description="This is a personal task. Feel free to schedule a meeting over this slot.",
        transparency="transparent",
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 4),
    )


def _timed_resource(task_id: str, title: str, tracker_id: str = "ALOVYA") -> dict:
    return {
        "summary": f"[NTT] {title}",
        "description": "This is a personal task. Feel free to schedule a meeting over this slot.",
        "transparency": "transparent",
        "start": {"dateTime": "2026-08-03T09:00:00+01:00", "timeZone": "Europe/London"},
        "end": {"dateTime": "2026-08-03T10:00:00+01:00", "timeZone": "Europe/London"},
        "colorId": "8",
        "extendedProperties": {
            "private": {
                "ntt_tracker": tracker_id,
                "ntt_task_id": task_id,
            }
        },
    }
