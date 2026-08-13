import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generation_server import llm_tasks
from generation_server.settings import Settings


def _settings(*, use_vertex_ai: bool) -> Settings:
    return Settings(
        shared_secret=None,
        provider="google_gemini",
        model_service_url=None,
        gcs_bucket=None,
        gcs_credentials=None,
        worker_concurrency=1,
        job_look_concurrency=1,
        callback_timeout=1,
        callback_max_attempts=1,
        callback_retry_delay=0,
        result_poll_interval=0.5,
        output_dir="./outputs",
        google_gemini_api_key="key" if not use_vertex_ai else None,
        google_gemini_models=("gemini-2.5-flash",),
        google_gemini_timeout=1,
        google_gemini_use_vertex_ai=use_vertex_ai,
        google_cloud_project="demo-project" if use_vertex_ai else None,
        google_cloud_location="global",
        google_gemini_max_retries=4,
        google_gemini_retry_initial_delay=1.0,
        google_gemini_retry_max_delay=16.0,
        google_gemini_retry_jitter=0.25,
    )


def test_get_client_uses_api_key_when_vertex_disabled(monkeypatch):
    calls: list[dict] = []

    class FakeClientFactory:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace()

    monkeypatch.setattr(llm_tasks, "get_settings", lambda: _settings(use_vertex_ai=False))
    monkeypatch.setattr(llm_tasks, "genai", SimpleNamespace(Client=FakeClientFactory()))

    client = llm_tasks._get_client()

    assert client is not None
    assert calls == [{"api_key": "key"}]


def test_get_client_uses_vertex_ai_when_enabled(monkeypatch):
    calls: list[dict] = []

    class FakeClientFactory:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace()

    monkeypatch.setattr(llm_tasks, "get_settings", lambda: _settings(use_vertex_ai=True))
    monkeypatch.setattr(llm_tasks, "genai", SimpleNamespace(Client=FakeClientFactory()))

    client = llm_tasks._get_client()

    assert client is not None
    assert calls == [
        {
            "vertexai": True,
            "project": "demo-project",
            "location": "global",
        }
    ]
