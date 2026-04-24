from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from server import prompt_engines
from server.schemas import UserState


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None
        self.ordering: list[tuple[str, bool]] = []
        self.pending_insert: list[dict[str, Any]] | None = None
        self.pending_update: dict[str, Any] | None = None

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.client.tables.setdefault(self.name, [])

    def select(self, *_args: Any, **_kwargs: Any) -> "_StubTable":
        return self

    def eq(self, column: str, value: Any) -> "_StubTable":
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "_StubTable":
        self.filters.append(("in", column, list(values)))
        return self

    def limit(self, value: int) -> "_StubTable":
        self.limit_value = value
        return self

    def order(self, column: str, desc: bool = False) -> "_StubTable":
        self.ordering.append((column, desc))
        return self

    def insert(self, payload: dict[str, Any] | list[dict[str, Any]]) -> "_StubTable":
        rows = payload if isinstance(payload, list) else [payload]
        self.pending_insert = [copy.deepcopy(row) for row in rows]
        return self

    def update(self, payload: dict[str, Any]) -> "_StubTable":
        self.pending_update = copy.deepcopy(payload)
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for op, column, value in self.filters:
            if op == "eq" and row.get(column) != value:
                return False
            if op == "in" and row.get(column) not in set(value):
                return False
        return True

    def execute(self) -> SimpleNamespace:
        if self.pending_insert is not None:
            created: list[dict[str, Any]] = []
            for row in self.pending_insert:
                if "id" not in row:
                    row["id"] = self.client.next_id(self.name)
                created.append(copy.deepcopy(row))
                self.rows.append(copy.deepcopy(row))
            return SimpleNamespace(data=created)

        filtered = [row for row in self.rows if self._matches(row)]

        if self.pending_update is not None:
            updated_rows: list[dict[str, Any]] = []
            for row in filtered:
                row.update(copy.deepcopy(self.pending_update))
                updated_rows.append(copy.deepcopy(row))
            return SimpleNamespace(data=updated_rows)

        data = [copy.deepcopy(row) for row in filtered]
        for column, desc in reversed(self.ordering):
            data.sort(key=lambda row: row.get(column), reverse=desc)
        if self.limit_value is not None:
            data = data[: self.limit_value]
        return SimpleNamespace(data=data)


class _StubClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "prompt_engines": [],
            "prompt_engine_versions": [],
            "prompt_task_routes": [],
        }
        self.counters: dict[str, int] = {}

    def next_id(self, table: str) -> str:
        value = self.counters.get(table, 0) + 1
        self.counters[table] = value
        return f"{table}-{value}"

    def table(self, name: str) -> _StubTable:
        return _StubTable(self, name)


def _build_app(
    monkeypatch: pytest.MonkeyPatch,
    current_user: UserState,
) -> tuple[TestClient, _StubClient]:
    app = FastAPI()
    app.include_router(prompt_engines.router)
    app.dependency_overrides[prompt_engines.get_current_user] = lambda: current_user
    stub = _StubClient()
    monkeypatch.setattr(prompt_engines, "get_client", lambda: stub)
    monkeypatch.setattr(prompt_engines, "ensure_default_prompt_registry", lambda client=None: False)
    return TestClient(app), stub


def test_prompt_engine_routes_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_app(
        monkeypatch,
        UserState(id="user-1", credits=10, isAdmin=False),
    )

    response = client.get("/prompt-engines")

    assert response.status_code == 403


def test_create_prompt_engine_creates_initial_draft_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )

    response = client.post(
        "/prompt-engines",
        json={
            "slug": "custom-defaults",
            "name": "Custom Defaults",
            "taskType": "image_generation.defaults",
            "rendererKey": "image_defaults_v1",
            "initialVersion": {
                "changeNote": "First draft",
                "definition": {"negative_prompt": "soft blur"},
                "sampleInput": {},
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "custom-defaults"
    assert body["versions"][0]["status"] == "draft"
    assert stub.tables["prompt_engines"][0]["slug"] == "custom-defaults"
    assert stub.tables["prompt_engine_versions"][0]["definition"]["negative_prompt"] == "soft blur"


def test_publish_prompt_engine_version_marks_engine_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )

    create_response = client.post(
        "/prompt-engines",
        json={
            "slug": "publish-me",
            "name": "Publish Me",
            "taskType": "image_generation.defaults",
            "rendererKey": "image_defaults_v1",
            "initialVersion": {
                "definition": {"negative_prompt": "grain"},
                "sampleInput": {},
            },
        },
    )
    version_id = create_response.json()["versions"][0]["id"]

    publish_response = client.post(f"/prompt-engines/publish-me/versions/{version_id}/publish")

    assert publish_response.status_code == 200
    body = publish_response.json()
    assert body["publishedVersionId"] == version_id
    assert body["publishedVersionNumber"] == 1
    assert body["versions"][0]["status"] == "published"


def test_preview_prompt_engine_version_renders_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )

    create_response = client.post(
        "/prompt-engines",
        json={
            "slug": "preview-me",
            "name": "Preview Me",
            "taskType": "image_generation.defaults",
            "rendererKey": "image_defaults_v1",
            "initialVersion": {
                "definition": {"negative_prompt": "blur"},
                "sampleInput": {},
            },
        },
    )
    version_id = create_response.json()["versions"][0]["id"]

    preview_response = client.post(
        f"/prompt-engines/preview-me/versions/{version_id}/preview",
        json={
            "input": {
                "extras": ["grainy"],
                "items": [{"type": "Ring", "size": "Medium"}],
            }
        },
    )

    assert preview_response.status_code == 200
    output = preview_response.json()["output"]
    assert "blur" in output["negative_prompt"]
    assert "grainy" in output["negative_prompt"]
