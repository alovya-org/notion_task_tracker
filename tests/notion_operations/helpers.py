from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry
from notion_task_tracker.notion_operations.rest_client import CreatedTaskDatabasePage, NotionWriteExecutionResult
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_TITLE_PROPERTY,
    task_database_data_source_id_from_tracker_state,
)


class FakeNotionOperation:
    def __init__(self, operation_key: str, operation_name: str, arguments: dict):
        self.operation_key = operation_key
        self.operation_name = operation_name
        self.arguments = arguments


class FakeNotionClient:
    def __init__(
        self,
        created_page_ids: list[str] | None = None,
        database_rows: list[dict] | None = None,
        fetched_page_content_by_id: dict[str, str] | None = None,
    ):
        self.calls = []
        self.database_rows = list(database_rows or [])
        self.fetched_page_content_by_id = fetched_page_content_by_id or {}
        self.fetched_pages = []
        self.queries = []
        self.view_queries = []
        self.created_page_ids = list(created_page_ids or [])

    async def fetch_task_page_content(self, page_id: str):
        self.fetched_pages.append(page_id)
        return self.fetched_page_content_by_id.get(page_id, "")

    async def query_data_source(self, data_source_url: str, query: str):
        self.queries.append({"data_source_url": data_source_url, "query": query})
        return list(self.database_rows)

    async def query_database_view(self, view_url: str):
        self.view_queries.append(view_url)
        return list(self.database_rows)

    async def query_task_database_rows(self, tracker_state: dict):
        self.queries.append({
            "data_source_id": task_database_data_source_id_from_tracker_state(tracker_state),
        })
        return list(self.database_rows)

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict,
        content: str,
        operation_key: str,
    ):
        page_id = self._next_created_page_id()
        self._record_call(
            operation_key=operation_key,
            operation_name="create_task_database_page",
            arguments={
                "data_source_id": data_source_id,
                "properties": properties,
                "content": content,
                "created_page_id": page_id,
            },
        )
        return CreatedTaskDatabasePage(
            notion_page_id=page_id,
            operation_keys=[operation_key],
        )

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ):
        self._record_call(
            operation_key=operation_key,
            operation_name="update_task_database_page_title",
            arguments={
                "page_id": page_id,
                "properties": {
                    title_property or TASK_DATABASE_TITLE_PROPERTY: title,
                },
            },
        )
        return operation_key

    async def execute_command_result(self, command_result: TrackerCommandResult):
        if command_result.page_registry is None:
            raise ValueError("Fake write execution requires a page registry")

        completed_operation_keys = []
        captured_page_ids = {}
        for write_intent in command_result.write_intents:
            write_result = self._execute_write_intent(write_intent, command_result.page_registry)
            completed_operation_keys.append(write_result["operation_key"])
            if write_result.get("captured_page_key") is not None:
                captured_page_ids[write_result["captured_page_key"]] = write_result["captured_page_id"]

        return NotionWriteExecutionResult(
            completed_operation_keys=completed_operation_keys,
            captured_page_ids=captured_page_ids,
        )

    def _execute_write_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict:
        if write_intent.operation_name == "create_page":
            return self._execute_create_page_intent(write_intent, page_registry)
        if write_intent.operation_name == "replace_page_markdown":
            self._record_call(
                operation_key=write_intent.operation_key,
                operation_name="replace_page_markdown",
                arguments={
                    "page_id": page_registry.page_id(_required_target_page_key(write_intent)),
                    "markdown": write_intent.arguments["markdown"],
                },
            )
            return _write_result(write_intent.operation_key)
        if write_intent.operation_name == "update_page_properties":
            self._record_call(
                operation_key=write_intent.operation_key,
                operation_name="update_page_properties",
                arguments={
                    "page_id": page_registry.page_id(_required_target_page_key(write_intent)),
                    "properties": write_intent.arguments["properties"],
                },
            )
            return _write_result(write_intent.operation_key)
        if write_intent.operation_name == "archive_page":
            self._record_call(
                operation_key=write_intent.operation_key,
                operation_name="archive_page",
                arguments={
                    "page_id": page_registry.page_id(_required_target_page_key(write_intent)),
                },
            )
            return _write_result(write_intent.operation_key)
        if write_intent.operation_name == "update_timeline_log":
            return self._execute_timeline_log_update_intent(write_intent, page_registry)
        if write_intent.operation_name == "append_miscellaneous_context":
            return self._execute_miscellaneous_context_append_intent(write_intent, page_registry)
        if write_intent.operation_name == "create_synthesis_page":
            return self._execute_synthesis_page_creation_intent(write_intent, page_registry)

        raise ValueError(f"Fake Notion client cannot execute write intent {write_intent.operation_name!r}")

    def _execute_create_page_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict:
        page_id = self._next_created_page_id()
        arguments = write_intent.arguments
        parent_page_key = arguments.get("parent_page_key")
        self._record_call(
            operation_key=write_intent.operation_key,
            operation_name="create_page",
            arguments={
                "parent_page_id": None if parent_page_key is None else page_registry.page_id(parent_page_key),
                "properties": {"title": arguments["title"]},
                "markdown": arguments.get("markdown", ""),
                "created_page_id": page_id,
            },
        )
        return _write_result(write_intent.operation_key, arguments["local_page_key"], page_id)

    def _execute_timeline_log_update_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict:
        arguments = write_intent.arguments
        page_id = page_registry.page_id(_required_target_page_key(write_intent))
        if "old_timeline_section_markdown" in arguments:
            operation_name = "replace_markdown_section"
            operation_arguments = {
                "page_id": page_id,
                "old_markdown": arguments["old_timeline_section_markdown"],
                "new_markdown": arguments["new_timeline_section_markdown"],
            }
        else:
            operation_name = "insert_markdown_after_anchor"
            operation_arguments = {
                "page_id": page_id,
                "anchor_markdown": f"## {arguments['timeline_log_heading']}",
                "inserted_markdown": arguments["timeline_section_markdown"],
            }
        self._record_call(write_intent.operation_key, operation_name, operation_arguments)
        return _write_result(write_intent.operation_key)

    def _execute_miscellaneous_context_append_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict:
        dated_page = write_intent.arguments["dated_page"]
        dated_page_key = dated_page["local_page_key"]
        if not _page_has_id(page_registry, dated_page_key):
            return self._execute_create_page_intent(
                NotionWriteIntent(
                    operation_key=f"create:{dated_page_key}",
                    operation_name="create_page",
                    target_page_key=None,
                    arguments={
                        "local_page_key": dated_page_key,
                        "title": dated_page["title"],
                        "parent_page_key": dated_page.get("parent_page_key"),
                        "markdown": write_intent.arguments["dated_page_markdown"],
                    },
                ),
                page_registry,
            )

        self._record_replace_page_content(dated_page_key, write_intent.arguments["dated_page_markdown"], page_registry)
        if write_intent.arguments.get("root_page_markdown") is not None:
            self._record_replace_page_content(
                write_intent.arguments["root_page_key"],
                write_intent.arguments["root_page_markdown"],
                page_registry,
            )
        return _write_result(write_intent.operation_key)

    def _execute_synthesis_page_creation_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict:
        synthesis_page = write_intent.arguments["page"]
        synthesis_page_key = synthesis_page["local_page_key"]
        if not _page_has_id(page_registry, synthesis_page_key):
            return self._execute_create_page_intent(
                NotionWriteIntent(
                    operation_key=f"create:{synthesis_page_key}",
                    operation_name="create_page",
                    target_page_key=None,
                    arguments={
                        "local_page_key": synthesis_page_key,
                        "title": synthesis_page["title"],
                        "parent_page_key": synthesis_page.get("parent_page_key"),
                        "markdown": write_intent.arguments["markdown"],
                    },
                ),
                page_registry,
            )

        self._record_replace_page_content(synthesis_page_key, write_intent.arguments["markdown"], page_registry)
        if write_intent.arguments.get("root_page_markdown") is not None:
            self._record_replace_page_content(
                write_intent.arguments["root_page_key"],
                write_intent.arguments["root_page_markdown"],
                page_registry,
            )
        return _write_result(write_intent.operation_key)

    def _record_replace_page_content(self, page_key: str, markdown: str, page_registry: NotionPageRegistry) -> None:
        self._record_call(
            operation_key=f"replace:{page_key}",
            operation_name="replace_page_markdown",
            arguments={
                "page_id": page_registry.page_id(page_key),
                "markdown": markdown,
            },
        )

    def _record_call(self, operation_key: str, operation_name: str, arguments: dict) -> None:
        self.calls.append(FakeNotionOperation(operation_key, operation_name, arguments))

    def _next_created_page_id(self) -> str:
        if self.created_page_ids:
            return self.created_page_ids.pop(0)
        return f"{len(self.calls) + 1:032x}"


def _required_target_page_key(write_intent: NotionWriteIntent) -> str:
    if write_intent.target_page_key is None:
        raise ValueError(f"Write intent {write_intent.operation_key!r} has no target page key")

    return write_intent.target_page_key


def _page_has_id(page_registry: NotionPageRegistry, page_key: str) -> bool:
    try:
        page_registry.page_id(page_key)
    except ValueError:
        return False

    return True


def _write_result(
    operation_key: str,
    captured_page_key: str | None = None,
    captured_page_id: str | None = None,
) -> dict:
    result = {"operation_key": operation_key}
    if captured_page_key is not None:
        result["captured_page_key"] = captured_page_key
        result["captured_page_id"] = captured_page_id
    return result
