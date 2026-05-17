import os
import sys
import copy
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("GENERATION_APP_URL", "https://app.example")

from prompting import (  # noqa: E402
    PROMPT_TASK_ON_MODEL,
    PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
    PROMPT_TASK_PLANNER_ENRICH,
    ensure_default_prompt_registry,
    resolve_prompt_task,
)


def test_resolve_prompt_task_falls_back_to_default_registry_for_v45() -> None:
    rendered = resolve_prompt_task(
        PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
        {
            "request": {
                "model": {"slug": "model"},
                "style": {
                    "public_version_key": "v4.5",
                    "background": "White Studio",
                    "camera": "Portrait",
                    "image_style": "Natural",
                },
                "looks": 1,
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )

    assert rendered["prompts"]
    prompt = rendered["prompts"][0]
    assert prompt.startswith("HERO\nUltra-realistic editorial jewelry photograph.")
    assert "\nSCENE: White Studio\n" in prompt
    assert "\nJEWELRY TYPE: Ring\n" in prompt
    assert "negative_prompt" in rendered


def test_resolve_prompt_task_builds_planner_enrich_prompt_bundle() -> None:
    rendered = resolve_prompt_task(
        PROMPT_TASK_PLANNER_ENRICH,
        {
            "prompt": "A creative launch day",
            "persona": {"display_name": "Maya", "bio": "Founder"},
            "style_profile": {
                "realism_level": "high",
                "camera_style_tags": ["editorial"],
                "color_palette_tags": ["warm"],
            },
            "preferences": {"stories_per_day": 3, "posts_per_day": 1},
            "world_summary": {
                "location_tags": ["studio", "cafe"],
                "wardrobe_tags": ["linen", "gold"],
            },
        },
    )

    assert rendered["model_name"] == os.getenv("GOOGLE_GEMINI_MODEL", "gemini-2.5-flash")
    assert "expert social media manager" in rendered["system_instruction"]
    assert "Persona Name: Maya" in rendered["user_prompt"]
    assert "Available Locations: studio, cafe" in rendered["user_prompt"]


def test_resolve_prompt_task_supports_task_first_on_model_registry() -> None:
    rendered = resolve_prompt_task(
        PROMPT_TASK_ON_MODEL,
        {
            "request": {
                "model": {"slug": "model"},
                "style": {
                    "task_type": "on-model",
                    "public_version_key": "v4.5",
                    "background": "White Studio",
                    "camera": "Portrait",
                    "image_style": "Natural",
                },
                "looks": 1,
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )

    assert rendered["prompts"]
    assert "White Studio" in rendered["prompts"][0]


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, object]] = []
        self.pending_update: dict[str, object] | None = None
        self.pending_insert: list[dict[str, object]] | None = None

    @property
    def rows(self) -> list[dict[str, object]]:
        return self.client.tables.setdefault(self.name, [])

    def select(self, *_args: object, **_kwargs: object) -> "_StubTable":
        return self

    def eq(self, column: str, value: object) -> "_StubTable":
        self.filters.append(("eq", column, value))
        return self

    def limit(self, _value: int) -> "_StubTable":
        return self

    def update(self, payload: dict[str, object]) -> "_StubTable":
        self.pending_update = copy.deepcopy(payload)
        return self

    def insert(self, payload: dict[str, object] | list[dict[str, object]]) -> "_StubTable":
        rows = payload if isinstance(payload, list) else [payload]
        self.pending_insert = [copy.deepcopy(row) for row in rows]
        return self

    def execute(self) -> SimpleNamespace:
        if self.pending_insert is not None:
            created: list[dict[str, object]] = []
            for row in self.pending_insert:
                if "id" not in row:
                    row["id"] = self.client.next_id(self.name)
                self.rows.append(copy.deepcopy(row))
                created.append(copy.deepcopy(row))
            return SimpleNamespace(data=created)
        filtered = [
            row
            for row in self.rows
            if all(row.get(column) == value for op, column, value in self.filters if op == "eq")
        ]
        if self.pending_update is not None:
            updated: list[dict[str, object]] = []
            for row in filtered:
                row.update(copy.deepcopy(self.pending_update))
                updated.append(copy.deepcopy(row))
            return SimpleNamespace(data=updated)
        return SimpleNamespace(data=[copy.deepcopy(row) for row in filtered])


class _StubClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, object]]] = {
            "prompt_tasks": [],
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


def test_ensure_default_prompt_registry_backfills_edit_prompt_fields() -> None:
    stub = _StubClient()
    stub.tables["prompt_tasks"] = [
        {"id": "task-1", "key": "on-model/edited", "display_defaults": {}},
        {"id": "task-2", "key": "pure-jewelry/edited", "display_defaults": {}},
    ]
    stub.tables["prompt_engines"] = [
        {"id": "engine-1", "slug": "on-model-edit-default"},
        {"id": "engine-2", "slug": "pure-jewelry-edit-default"},
    ]
    stub.tables["prompt_engine_versions"] = [
        {
            "id": "version-1",
            "engine_id": "engine-1",
            "definition": {
                "negative_prompt": "neg",
                "editOptions": [],
            },
        },
        {
            "id": "version-2",
            "engine_id": "engine-2",
            "definition": {
                "negative_prompt": "neg",
                "hero": "Custom hero",
            },
        },
    ]

    changed = ensure_default_prompt_registry(client=stub, force=True)

    assert changed is True
    on_model_definition = stub.tables["prompt_engine_versions"][0]["definition"]
    pure_definition = stub.tables["prompt_engine_versions"][1]["definition"]
    assert on_model_definition["hero"].startswith("Generate this exact same image.")
    assert on_model_definition["pure_jewelry_addendum"].startswith("The source was created as pure jewelry")
    assert on_model_definition["requested_edits_heading"] == "Requested edits:"
    assert pure_definition["hero"] == "Custom hero"
    assert pure_definition["pure_jewelry_addendum"].startswith("The source was created as pure jewelry")
    assert pure_definition["requested_edits_heading"] == "Requested edits:"
