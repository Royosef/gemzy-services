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

from server import generations
from postgrest.exceptions import APIError


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None

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

    def _matches(self, row: dict[str, Any]) -> bool:
        for op, column, value in self.filters:
            if op == "eq" and row.get(column) != value:
                return False
            if op == "in" and row.get(column) not in set(value):
                return False
        return True

    def execute(self) -> SimpleNamespace:
        data = [copy.deepcopy(row) for row in self.rows if self._matches(row)]
        if self.limit_value is not None:
            data = data[: self.limit_value]
        return SimpleNamespace(data=data)


class _StubClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "prompt_engines": [],
            "prompt_engine_versions": [],
        }

    def table(self, name: str) -> _StubTable:
        return _StubTable(self, name)


def test_generation_ui_config_returns_db_overrides_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    client = TestClient(app)
    stub = _StubClient()

    stub.tables["prompt_engines"] = [
        {
            "id": "engine-1",
            "slug": "on-model-v4-5",
            "published_version_id": "version-1",
        }
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-1",
            "definition": {
                "ui": {
                    "surface": "onModel",
                    "engineId": "v2",
                    "selector": {
                        "id": "v2",
                        "pillLabel": "Gemzy Experimental",
                        "title": "Gemzy Experimental",
                        "description": "DB override",
                        "imageKey": "engine-v2",
                        "sortOrder": 5,
                    },
                    "trialTaskLabel": "On Model - Experimental Presets",
                    "promptVersion": "v9",
                }
            },
        }
    ]

    monkeypatch.setattr(generations, "get_client", lambda: stub)
    monkeypatch.setattr(generations, "ensure_default_prompt_registry", lambda client=None: False)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "generation-ui-v1"
    assert body["onModel"]["defaultEngineId"] == "v2"
    assert body["onModel"]["engines"][0]["selector"]["title"] == "Gemzy Experimental"
    assert body["onModel"]["engines"][0]["trialTaskLabel"] == "On Model - Experimental Presets"
    assert body["onModel"]["engines"][0]["promptVersion"] == "v9"
    assert body["onModel"]["engines"][0]["engineSlug"] == "on-model-v4-5"
    assert body["pureJewelry"]["engines"], "Expected fallback pure-jewelry engines to remain available"
    assert body["fetchedAt"]


def test_generation_ui_config_falls_back_when_registry_seed_hits_rls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    client = TestClient(app)
    stub = _StubClient()

    monkeypatch.setattr(generations, "get_client", lambda: stub)

    def _raise_rls_error(client=None):
        raise APIError(
            {
                "message": 'new row violates row-level security policy for table "prompt_engines"',
                "code": "42501",
                "hint": None,
                "details": None,
            }
        )

    monkeypatch.setattr(generations, "ensure_default_prompt_registry", _raise_rls_error)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "generation-ui-v1"
    assert body["onModel"]["engines"], "Expected fallback on-model engines to remain available"
    assert body["pureJewelry"]["engines"], "Expected fallback pure-jewelry engines to remain available"
    assert body["fetchedAt"]
