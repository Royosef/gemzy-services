"""Route compatibility tests for creation look presets."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import looks


class _EmptyPresetQuery:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _EmptyPresetClient:
    def table(self, name: str) -> _EmptyPresetQuery:
        assert name == "creation_look_presets"
        return _EmptyPresetQuery()


def test_creation_look_presets_accepts_both_trailing_slash_forms(
    monkeypatch,
) -> None:
    monkeypatch.setattr(looks, "get_client", lambda: _EmptyPresetClient())

    app = FastAPI()
    app.include_router(looks.creation_look_presets_router)

    with TestClient(app, follow_redirects=False) as client:
        without_slash = client.get("/creation-look-presets")
        with_slash = client.get("/creation-look-presets/")

    assert without_slash.status_code == 200
    assert with_slash.status_code == 200
