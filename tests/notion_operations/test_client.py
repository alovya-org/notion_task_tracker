import pytest

from notion_task_tracker.notion_operations.client import notion_client_from_environment
from notion_task_tracker.notion_operations.rest_client import NotionRestClient


def test_notion_client_from_environment_returns_rest_client(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test")

    notion_client = notion_client_from_environment()

    assert isinstance(notion_client, NotionRestClient)


def test_notion_client_from_environment_has_no_argument(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test")

    with pytest.raises(TypeError):
        notion_client_from_environment("removed")
