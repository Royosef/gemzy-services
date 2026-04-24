import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from generation_server.settings import Settings


def test_google_provider_requires_api_key_without_vertex_ai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENERATION_APP_URL", "https://example.test")
    monkeypatch.setenv("GENERATION_PROVIDER", "google_gemini")
    monkeypatch.delenv("GOOGLE_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GEMINI_USE_VERTEX_AI", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_GEMINI_API_KEY"):
        Settings.from_env()


def test_google_provider_accepts_vertex_ai_with_default_location(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GENERATION_APP_URL", "https://example.test")
    monkeypatch.setenv("GENERATION_PROVIDER", "google_gemini")
    monkeypatch.setenv("GOOGLE_GEMINI_USE_VERTEX_AI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.delenv("GOOGLE_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    settings = Settings.from_env()

    assert settings.google_gemini_use_vertex_ai is True
    assert settings.google_cloud_project == "demo-project"
    assert settings.google_cloud_location == "global"
    assert settings.google_gemini_model == "gemini-2.5-flash-image"
