"""Build task tree metadata from Notion task database rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from notion_task_tracker.errors import NotionPlanningError
from notion_task_tracker.notion_operations.notion_id import canonical_notion_page_id, notion_page_id_from_url
from notion_task_tracker.tasks.task_tree import TaskTree
from notion_task_tracker.tasks.landing_pages import CompletedTasksLandingPage, OngoingTasksLandingPage
from notion_task_tracker.tasks.task import (
    DEFAULT_TASK_EXTERNAL_COORDINATION,
    DEFAULT_TASK_FRICTION,
    DEFAULT_TASK_PRIORITY,
    DEFAULT_TASK_STATUS,
    DEFAULT_TASK_UNCERTAINTY,
    ExternalCoordination,
    Friction,
    PROPERTIES_BLOCK_PATTERN,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    Priority,
    Task,
    TaskStatus,
    Uncertainty,
    task_id_sort_key,
)
from notion_task_tracker.tracked_pages import TrackedPage


TASK_DATABASE_TICKET_ID_PROPERTY = "Task ID"
TASK_DATABASE_PARENT_PROPERTY = "Parent"
TASK_DATABASE_DEPENDENCIES_PROPERTY = "Dependencies"
TASK_DATABASE_DEPENDANTS_PROPERTY = "Dependants"
TASK_DATABASE_DEADLINE_PROPERTY = "Deadline"
TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY = "External coordination"
TASK_DATABASE_UNCERTAINTY_PROPERTY = "Uncertainty"
TASK_DATABASE_FRICTION_PROPERTY = "Friction"
_TASK_TITLE_PREFIX_PATTERN = re.compile(r"^(?:[A-Z][A-Z0-9_]*-\d+:|\[\d+\])\s+")


def build_task_tree_from_database_query_results(
    query_results: list[dict[str, Any]],
    ticket_prefix: str,
    landing_page: TrackedPage,
    completed_landing_page: TrackedPage | None = None,
    previous_task_tree: TaskTree | None = None,
) -> TaskTree:
    previous_tasks_by_task_id = _previous_tasks_by_task_id(previous_task_tree)
    previous_tasks_by_page_id = _previous_tasks_by_page_id(previous_task_tree)
    database_rows = _database_rows_from_query_results(query_results, ticket_prefix)
    database_rows = _database_rows_that_belong_to_task_tree(database_rows)
    task_tree = TaskTree(
        ongoing_tasks_landing_page=OngoingTasksLandingPage(page=landing_page),
        completed_tasks_landing_page=CompletedTasksLandingPage(
            page=completed_landing_page or _previous_completed_landing_page(previous_task_tree)
        ),
    )

    for database_row in database_rows:
        previous_task = previous_tasks_by_task_id.get(database_row.task_id)
        if previous_task is None:
            previous_task = previous_tasks_by_page_id.get(database_row.notion_page_id)
        task_tree.add_task(_task_from_database_row(database_row, previous_task))

    _link_database_parent_rows(task_tree, database_rows)
    _sort_child_task_ids(task_tree)
    task_tree.validate()
    task_tree.recalculate_display_priorities()
    return task_tree


@dataclass(frozen=True)
class TaskDatabaseRow:
    """One task row returned by the Notion task database."""

    task_id: str
    title: str
    configured_priority: Priority
    status: TaskStatus
    notion_page_id: str
    notion_page_url: str
    parent_notion_page_ids: list[str]
    dependency_notion_page_ids: list[str]
    dependant_notion_page_ids: list[str]
    deadline: str | None
    external_coordination: ExternalCoordination
    uncertainty: Uncertainty
    friction: Friction
    ticket_number: int


def task_database_query_for_tracker_state(tracker_state: dict[str, Any]) -> str:
    return (
        f'SELECT * FROM "{task_database_data_source_url_from_tracker_state(tracker_state)}"'
    )


def task_database_data_source_url_from_tracker_state(tracker_state: dict[str, Any]) -> str:
    return str(tracker_state["task_database"]["data_source_url"])


def task_database_data_source_id_from_tracker_state(tracker_state: dict[str, Any]) -> str:
    return str(tracker_state["task_database"]["data_source_id"])


def task_id_from_fetched_task_database_page(fetched_page_content: str, ticket_prefix: str) -> str:
    return f"{ticket_prefix}-{_ticket_number_from_fetched_task_database_page(fetched_page_content)}"


def task_database_row_from_fetched_task_database_page(
    fetched_page_content: str,
    notion_page_id: str,
    ticket_prefix: str,
) -> TaskDatabaseRow:
    properties = _properties_from_fetched_task_database_page(fetched_page_content)
    properties.setdefault("url", f"https://www.notion.so/{canonical_notion_page_id(notion_page_id)}")
    return _database_row_from_query_result(properties, ticket_prefix)


def build_task_database_tracker_state(data_source_id: str) -> dict[str, str]:
    return {
        "data_source_id": data_source_id,
        "data_source_url": f"collection://{data_source_id}",
    }


def _database_rows_from_query_results(
    query_results: list[dict[str, Any]],
    ticket_prefix: str,
) -> list[TaskDatabaseRow]:
    database_rows_by_task_id = {}

    for query_result in query_results:
        if not _query_result_has_task_identity(query_result):
            continue
        database_row = _database_row_from_query_result(query_result, ticket_prefix)
        _record_database_row_by_task_id(database_rows_by_task_id, database_row)

    return list(database_rows_by_task_id.values())


def _database_rows_that_belong_to_task_tree(database_rows: list[TaskDatabaseRow]) -> list[TaskDatabaseRow]:
    retained_database_rows = list(database_rows)

    while True:
        task_page_ids = {
            database_row.notion_page_id
            for database_row in retained_database_rows
        }
        filtered_database_rows = [
            database_row
            for database_row in retained_database_rows
            if _database_row_has_no_parent_or_known_parent(database_row, task_page_ids)
        ]
        if len(filtered_database_rows) == len(retained_database_rows):
            return filtered_database_rows
        retained_database_rows = filtered_database_rows


def _database_row_has_no_parent_or_known_parent(
    database_row: TaskDatabaseRow,
    task_page_ids: set[str],
) -> bool:
    if len(database_row.parent_notion_page_ids) > 1:
        raise NotionPlanningError(f"Task {database_row.task_id} has more than one parent")

    return not database_row.parent_notion_page_ids or database_row.parent_notion_page_ids[0] in task_page_ids


def _ticket_number_from_fetched_task_database_page(fetched_page_content: str) -> int:
    return _required_ticket_number(_properties_from_fetched_task_database_page(fetched_page_content))


def _properties_from_fetched_task_database_page(fetched_page_content: str) -> dict[str, Any]:
    properties_match = PROPERTIES_BLOCK_PATTERN.search(fetched_page_content)
    if properties_match is None:
        raise NotionPlanningError("Fetched task database page has no properties block")

    return json.loads(properties_match.group(1))


def _database_row_from_query_result(query_result: dict[str, Any], ticket_prefix: str) -> TaskDatabaseRow:
    ticket_number = _required_ticket_number(query_result)
    notion_page_url = _required_text_property(query_result, "url")
    notion_page_id = notion_page_id_from_url(notion_page_url)
    task_id = f"{ticket_prefix}-{ticket_number}"
    title = _task_title_from_database_title(
        database_title=_required_text_property(query_result, TASK_DATABASE_TITLE_PROPERTY),
    )
    return TaskDatabaseRow(
        task_id=task_id,
        title=title,
        configured_priority=_priority_from_database_property(query_result),
        status=_status_from_database_property(query_result),
        notion_page_id=notion_page_id,
        notion_page_url=notion_page_url,
        parent_notion_page_ids=[
            notion_page_id_from_url(parent_page_url)
            for parent_page_url in _relation_page_urls(query_result.get(TASK_DATABASE_PARENT_PROPERTY))
        ],
        dependency_notion_page_ids=[
            notion_page_id_from_url(dependency_page_url)
            for dependency_page_url in _relation_page_urls(query_result.get(TASK_DATABASE_DEPENDENCIES_PROPERTY))
        ],
        dependant_notion_page_ids=[
            notion_page_id_from_url(dependant_page_url)
            for dependant_page_url in _relation_page_urls(query_result.get(TASK_DATABASE_DEPENDANTS_PROPERTY))
        ],
        deadline=_optional_text_property(query_result, TASK_DATABASE_DEADLINE_PROPERTY),
        external_coordination=_enum_property_or_default(
            query_result,
            TASK_DATABASE_EXTERNAL_COORDINATION_PROPERTY,
            ExternalCoordination,
            DEFAULT_TASK_EXTERNAL_COORDINATION,
        ),
        uncertainty=_enum_property_or_default(
            query_result,
            TASK_DATABASE_UNCERTAINTY_PROPERTY,
            Uncertainty,
            DEFAULT_TASK_UNCERTAINTY,
        ),
        friction=_enum_property_or_default(
            query_result,
            TASK_DATABASE_FRICTION_PROPERTY,
            Friction,
            DEFAULT_TASK_FRICTION,
        ),
        ticket_number=ticket_number,
    )


def _task_from_database_row(
    database_row: TaskDatabaseRow,
    previous_task: Task | None,
) -> Task:
    return Task(
        task_id=database_row.task_id,
        title=database_row.title,
        configured_priority=database_row.configured_priority,
        status=database_row.status,
        status_update=previous_task.status_update if previous_task else "",
        timeline_entries=list(previous_task.timeline_entries) if previous_task else [],
        links=list(previous_task.links) if previous_task else [],
        notion_page_id=database_row.notion_page_id,
        deadline=database_row.deadline,
        external_coordination=database_row.external_coordination,
        uncertainty=database_row.uncertainty,
        friction=database_row.friction,
    )


def _link_database_parent_rows(
    task_tree: TaskTree,
    database_rows: list[TaskDatabaseRow],
) -> None:
    task_id_by_page_id = {
        database_row.notion_page_id: database_row.task_id
        for database_row in database_rows
    }

    for database_row in database_rows:
        if not database_row.parent_notion_page_ids:
            continue

        parent_page_id = database_row.parent_notion_page_ids[0]
        parent_task_id = task_id_by_page_id.get(parent_page_id)
        task_tree.link_parent_to_child(parent_task_id=parent_task_id, child_task_id=database_row.task_id)

    for database_row in database_rows:
        task = task_tree.tasks[database_row.task_id]
        task.dependency_task_ids = _require_dependency_task_ids_referenced_by_database_row(
            database_row,
            task_id_by_page_id,
        )
    task_tree.derive_dependant_task_ids_from_dependencies()
    _validate_dependants_match_database_rows(task_tree, database_rows, task_id_by_page_id)


def _sort_child_task_ids(task_tree: TaskTree) -> None:
    for task in task_tree.tasks.values():
        task.child_task_ids.sort(key=task_id_sort_key)


def _validate_dependants_match_database_rows(
    task_tree: TaskTree,
    database_rows: list[TaskDatabaseRow],
    task_id_by_page_id: dict[str, str],
) -> None:
    for database_row in database_rows:
        task = task_tree.tasks[database_row.task_id]
        dependant_task_ids = _require_dependant_task_ids_referenced_by_database_row(
            database_row,
            task_id_by_page_id,
        )
        if sorted(dependant_task_ids, key=task_id_sort_key) != task.dependant_task_ids:
            raise NotionPlanningError(
                f"Dependants for task {database_row.task_id} do not match the inverse Dependencies relation"
            )


def _require_dependant_task_ids_referenced_by_database_row(
    database_row: TaskDatabaseRow,
    task_id_by_page_id: dict[str, str],
) -> list[str]:
    return [
        _require_dependant_task_id_for_page_id(database_row, dependant_page_id, task_id_by_page_id)
        for dependant_page_id in database_row.dependant_notion_page_ids
    ]


def _require_dependant_task_id_for_page_id(
    database_row: TaskDatabaseRow,
    dependant_page_id: str,
    task_id_by_page_id: dict[str, str],
) -> str:
    dependant_task_id = task_id_by_page_id.get(dependant_page_id)
    if dependant_task_id is None:
        raise NotionPlanningError(
            f"Dependant page {dependant_page_id} for task {database_row.task_id} is not in the local task tree"
        )

    return dependant_task_id


def _require_dependency_task_ids_referenced_by_database_row(
    database_row: TaskDatabaseRow,
    task_id_by_page_id: dict[str, str],
) -> list[str]:
    return [
        _require_dependency_task_id_for_page_id(database_row, dependency_page_id, task_id_by_page_id)
        for dependency_page_id in database_row.dependency_notion_page_ids
    ]


def _require_dependency_task_id_for_page_id(
    database_row: TaskDatabaseRow,
    dependency_page_id: str,
    task_id_by_page_id: dict[str, str],
) -> str:
    dependency_task_id = task_id_by_page_id.get(dependency_page_id)
    if dependency_task_id is None:
        raise NotionPlanningError(
            f"Dependency page {dependency_page_id} for task {database_row.task_id} is not in the local task tree"
        )

    return dependency_task_id


def _query_result_has_task_identity(query_result: dict[str, Any]) -> bool:
    return bool(
        query_result.get(TASK_DATABASE_TITLE_PROPERTY)
        and query_result.get(TASK_DATABASE_TICKET_ID_PROPERTY)
    )


def _record_database_row_by_task_id(
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
    database_row: TaskDatabaseRow,
) -> None:
    existing_database_row = database_rows_by_task_id.get(database_row.task_id)
    if existing_database_row is None:
        database_rows_by_task_id[database_row.task_id] = database_row
        return

    raise NotionPlanningError(f"Duplicate task id {database_row.task_id} in task database")


def _task_title_from_database_title(database_title: str) -> str:
    database_title = _plain_database_title(database_title)
    while True:
        task_title_match = _TASK_TITLE_PREFIX_PATTERN.match(database_title)
        if task_title_match is None:
            return database_title
        database_title = database_title.removeprefix(task_title_match.group(0))



def _plain_database_title(database_title: str) -> str:
    return database_title.replace("\u0336", "")


def _relation_page_urls(raw_relation: Any) -> list[str]:
    if raw_relation is None or raw_relation == "":
        return []
    if isinstance(raw_relation, list):
        return [str(page_url) for page_url in raw_relation]
    if isinstance(raw_relation, str):
        return [str(page_url) for page_url in json.loads(raw_relation)]

    raise NotionPlanningError(f"Unsupported relation value {raw_relation!r}")


def _required_ticket_number(query_result: dict[str, Any]) -> int:
    raw_ticket_number = query_result.get(TASK_DATABASE_TICKET_ID_PROPERTY)
    if raw_ticket_number in {None, ""}:
        raise NotionPlanningError("Task database row has no Task ID")

    return int(raw_ticket_number)


def _required_text_property(query_result: dict[str, Any], property_name: str) -> str:
    value = _optional_text_property(query_result, property_name)
    if value is None:
        raise NotionPlanningError(f"Task database row has no {property_name}")

    return value


def _optional_text_property(query_result: dict[str, Any], property_name: str) -> str | None:
    value = query_result.get(property_name)
    if value in {None, ""}:
        return None

    if property_name == "url":
        return f"https://www.notion.so/{notion_page_id_from_url(str(value))}"

    return str(value)


def _priority_from_database_property(query_result: dict[str, Any]) -> Priority:
    return Priority(
        _optional_text_property(query_result, TASK_DATABASE_PRIORITY_PROPERTY)
        or DEFAULT_TASK_PRIORITY.value
    )


def _status_from_database_property(query_result: dict[str, Any]) -> TaskStatus:
    return TaskStatus(
        _optional_text_property(query_result, TASK_DATABASE_STATUS_PROPERTY)
        or DEFAULT_TASK_STATUS.value
    )


def _enum_property_or_default(
    query_result: dict[str, Any],
    property_name: str,
    enum_type: type[ExternalCoordination] | type[Uncertainty] | type[Friction],
    default_value: ExternalCoordination | Uncertainty | Friction,
) -> ExternalCoordination | Uncertainty | Friction:
    return enum_type(_optional_text_property(query_result, property_name) or default_value.value)


def _previous_tasks_by_task_id(previous_task_tree: TaskTree | None) -> dict[str, Task]:
    if previous_task_tree is None:
        return {}

    return dict(previous_task_tree.tasks)


def _previous_completed_landing_page(previous_task_tree: TaskTree | None) -> TrackedPage:
    if previous_task_tree is None:
        return TaskTree().completed_tasks_landing_page.page

    return previous_task_tree.completed_tasks_landing_page.page


def _previous_tasks_by_page_id(previous_task_tree: TaskTree | None) -> dict[str, Task]:
    if previous_task_tree is None:
        return {}

    return {
        canonical_notion_page_id(task.notion_page_id): task
        for task in previous_task_tree.tasks.values()
        if task.notion_page_id is not None
    }
