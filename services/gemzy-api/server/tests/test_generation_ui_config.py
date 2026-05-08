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

from postgrest.exceptions import APIError
from server import generations


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
            "prompt_tasks": [],
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
            "name": "Gemzy Experimental",
            "description": "DB override",
            "task_id": "task-1",
            "public_engine_key": "on-model-v4-5",
            "is_user_selectable": True,
            "sort_order": 5,
            "selector_title": "Gemzy Experimental",
            "selector_pill_label": "Gemzy Experimental",
            "selector_description": "DB override",
            "selector_image_key": "engine-v2",
            "active_version_id": "version-1",
            "published_version_id": "version-1",
        }
    ]
    stub.tables["prompt_tasks"] = [
        {
            "id": "task-1",
            "key": "on-model",
            "name": "On Model",
            "description": "Primary task",
            "surface": "onModel",
            "display_defaults": {"layout": "flat-sections"},
        }
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-1",
            "public_version_key": "v9",
            "definition": {},
        }
    ]

    monkeypatch.setattr(generations, "get_client", lambda: stub)
    monkeypatch.setattr(generations, "ensure_default_prompt_registry", lambda client=None: False)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "generation-ui-v1"
    assert body["onModel"]["defaultEngineId"] == "on-model-v4-5"
    assert body["onModel"]["engines"][0]["selector"]["title"] == "Gemzy Experimental"
    assert body["onModel"]["engines"][0]["publicVersionKey"] == "v9"
    assert body["onModel"]["engines"][0]["engineSlug"] == "on-model-v4-5"
    assert body["tasks"][0]["key"] == "on-model"
    assert body["tasks"][0]["displayDefaults"]["layout"] == "flat-sections"
    assert body["tasks"][0]["engines"][0]["taskKey"] == "on-model"
    assert body["pureJewelry"]["engines"] == []
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
    assert body["tasks"], "Expected fallback task metadata to remain available"
    assert body["fetchedAt"]


def test_generation_ui_config_ignores_runtime_only_tasks_and_normalizes_surface_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    client = TestClient(app)
    stub = _StubClient()

    stub.tables["prompt_tasks"] = [
        {
            "id": "task-on-model",
            "key": "on-model",
            "name": "On Model",
            "description": "Primary task",
            "surface": "onModel",
            "display_defaults": {"layout": "flat-sections"},
        },
        {
            "id": "task-runtime",
            "key": "planner.enrich",
            "name": "Planner Enrich",
            "description": "Runtime-only planner task",
            "surface": None,
            "display_defaults": {},
        },
    ]
    stub.tables["prompt_engines"] = [
        {
            "id": "engine-surface",
            "slug": "on-model-v3",
            "name": "Gemzy Ultra",
            "description": "Published DB engine",
            "task_id": "task-on-model",
            "public_engine_key": "v3",
            "is_user_selectable": True,
            "sort_order": 7,
            "selector_title": "Gemzy Ultra",
            "selector_pill_label": "Gemzy Ultra",
            "selector_description": "Published DB engine",
            "active_version_id": "version-surface",
            "published_version_id": "version-surface",
        },
        {
            "id": "engine-runtime",
            "slug": "planner-enrich-default",
            "name": "Planner Enrich Default",
            "description": "Internal planner engine",
            "task_id": "task-runtime",
            "public_engine_key": "planner-default",
            "is_user_selectable": False,
            "sort_order": 100,
            "selector_title": "Planner Enrich Default",
            "selector_pill_label": "Planner Enrich Default",
            "selector_description": "Internal planner engine",
            "active_version_id": "version-runtime",
            "published_version_id": "version-runtime",
        },
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-surface",
            "public_version_key": "v3",
            "definition": {},
        },
        {
            "id": "version-runtime",
            "public_version_key": "default",
            "definition": {},
        },
    ]

    monkeypatch.setattr(generations, "get_client", lambda: stub)
    monkeypatch.setattr(generations, "ensure_default_prompt_registry", lambda client=None: False)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()

    on_model_engine = next(engine for engine in body["onModel"]["engines"] if engine["engineId"] == "v3")
    assert on_model_engine["surface"] == "onModel"
    assert on_model_engine["engineSlug"] == "on-model-v3"
    assert on_model_engine["selector"]["id"] == "v3"
    assert on_model_engine["selector"]["title"] == "Gemzy Ultra"
    assert on_model_engine["selector"]["pillLabel"] == "Gemzy Ultra"
    assert on_model_engine["selector"]["description"] == "Published DB engine"

    on_model_task = next(task for task in body["tasks"] if task["key"] == "on-model")
    assert any(engine["engineId"] == "v3" for engine in on_model_task["engines"])


def test_generation_ui_config_exposes_db_managed_edit_catalogs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    client = TestClient(app)
    stub = _StubClient()

    stub.tables["prompt_tasks"] = [
        {
            "id": "task-on-model-edit",
            "key": "on-model/edited",
            "name": "On Model Edit",
            "description": "Edit flow",
            "surface": "onModel",
            "display_defaults": {"layout": "flat-sections"},
        }
    ]
    stub.tables["prompt_engines"] = [
        {
            "id": "engine-edit",
            "slug": "on-model-edit-default",
            "name": "On Model Edit",
            "description": "DB-managed image edit engine",
            "task_id": "task-on-model-edit",
            "public_engine_key": "on-model-edit-default",
            "is_user_selectable": False,
            "sort_order": 1,
            "selector_title": "On Model Edit",
            "selector_pill_label": "Edit",
            "selector_description": "DB-managed image edit engine",
            "active_version_id": "version-edit",
            "published_version_id": "version-edit",
        }
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-edit",
            "public_version_key": "default",
            "definition": {
                "editCategories": [
                    {
                        "id": "jewelry",
                        "label": "Jewelry",
                        "options": ["enhance_shine"],
                    }
                ],
                "editOptions": [
                    {
                        "id": "enhance_shine",
                        "label": "Enhance shine & reflections",
                        "description": "More dimension and glow",
                        "category": "jewelry",
                        "prompt": "Enhance the jewelry highlights.",
                    }
                ],
            },
        }
    ]

    monkeypatch.setattr(generations, "get_client", lambda: stub)
    monkeypatch.setattr(generations, "ensure_default_prompt_registry", lambda client=None: False)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()
    edit_task = next(task for task in body["tasks"] if task["key"] == "on-model/edited")
    assert edit_task["defaultEngineId"] == "on-model-edit-default"
    assert edit_task["engines"][0]["engineId"] == "on-model-edit-default"
    assert edit_task["engines"][0]["editConfig"]["categories"][0]["id"] == "jewelry"
    assert edit_task["engines"][0]["editConfig"]["options"][0]["id"] == "enhance_shine"


def test_generation_ui_config_derives_on_model_option_labels_from_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    client = TestClient(app)
    stub = _StubClient()

    stub.tables["prompt_tasks"] = [
        {
            "id": "task-on-model",
            "key": "on-model",
            "name": "On Model",
            "description": "Primary task",
            "surface": "onModel",
            "display_defaults": {
                "layout": "flat-sections",
                "sectionDefaults": {
                    "hair": {
                        "label": "Hair",
                        "description": "Choose the hair direction",
                        "iconKey": "sparkles",
                        "editTier": "Pro",
                        "supportsRandom": True,
                    }
                },
            },
        }
    ]
    stub.tables["prompt_engines"] = [
        {
            "id": "engine-surface",
            "slug": "on-model-v3",
            "name": "Gemzy Ultra",
            "description": "Published DB engine",
            "task_id": "task-on-model",
            "public_engine_key": "v3",
            "is_user_selectable": True,
            "sort_order": 7,
            "selector_title": "Gemzy Ultra",
            "selector_pill_label": "Gemzy Ultra",
            "selector_description": "Published DB engine",
            "active_version_id": "version-surface",
            "published_version_id": "version-surface",
        }
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-surface",
            "public_version_key": "v3",
            "definition": {
                "mapping": {
                    "hair": {
                        "Soft Wind": "soft wind prompt",
                        "Behind Ear\u05d3": "hair tucked behind the ear prompt",
                    }
                }
            },
        }
    ]

    monkeypatch.setattr(generations, "get_client", lambda: stub)
    monkeypatch.setattr(generations, "ensure_default_prompt_registry", lambda client=None: False)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()

    on_model_engine = next(engine for engine in body["onModel"]["engines"] if engine["engineId"] == "v3")
    hair_section = next(section for section in on_model_engine["sections"] if section["id"] == "hair")
    assert hair_section["label"] == "Hair"
    assert hair_section["description"] == "Choose the hair direction"
    assert [option["label"] for option in hair_section["options"]] == ["Soft Wind", "Behind Ear\u05d3"]
    assert [option["id"] for option in hair_section["options"]] == ["soft-wind", "behind-ear"]


def test_generation_ui_config_derives_pure_jewelry_style_options_from_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    client = TestClient(app)
    stub = _StubClient()

    stub.tables["prompt_tasks"] = [
        {
            "id": "task-pure",
            "key": "pure-jewelry",
            "name": "Pure Jewelry",
            "description": "Primary task",
            "surface": "pureJewelry",
            "display_defaults": {
                "layout": "style-cards",
                "sectionDefaults": {
                    "scene": {
                        "label": "Scene",
                        "description": "Studio environment",
                        "iconKey": "mountains",
                        "editTier": "Pro",
                        "supportsRandom": False,
                    }
                },
            },
        }
    ]
    stub.tables["prompt_engines"] = [
        {
            "id": "engine-pure",
            "slug": "pure-jewelry-v3",
            "name": "Pure Ultra",
            "description": "Published DB engine",
            "task_id": "task-pure",
            "public_engine_key": "v3",
            "is_user_selectable": True,
            "sort_order": 7,
            "selector_title": "Pure Ultra",
            "selector_pill_label": "Pure Ultra",
            "selector_description": "Published DB engine",
            "active_version_id": "version-pure",
            "published_version_id": "version-pure",
        }
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-pure",
            "public_version_key": "v3",
            "definition": {
                "styles": {
                    "pure-studio": {
                        "categories": [
                            (
                                "scene",
                                "SCENE",
                                {
                                    "Rose Mist": "rose mist prompt",
                                    "Pure White": "pure white prompt",
                                },
                            )
                        ]
                    }
                }
            },
        }
    ]

    monkeypatch.setattr(generations, "get_client", lambda: stub)
    monkeypatch.setattr(generations, "ensure_default_prompt_registry", lambda client=None: False)

    response = client.get("/generations/ui-config")

    assert response.status_code == 200
    body = response.json()

    pure_engine = next(engine for engine in body["pureJewelry"]["engines"] if engine["engineId"] == "v3")
    pure_style = next(style for style in pure_engine["styles"] if style["id"] == "pure-studio")
    scene_parameter = next(parameter for parameter in pure_style["parameters"] if parameter["id"] == "scene")
    assert pure_style["title"] == "Pure Studio"
    assert scene_parameter["label"] == "Scene"
    assert scene_parameter["description"] == "Studio environment"
    assert [option["label"] for option in scene_parameter["options"]] == ["Rose Mist", "Pure White"]
    assert [option["id"] for option in scene_parameter["options"]] == ["rose-mist", "pure-white"]
