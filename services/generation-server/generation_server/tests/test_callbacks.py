from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generation_server import callbacks
from generation_server.models import CallbackEvent, JobMetadata
from generation_server.settings import Settings


def _settings() -> Settings:
    return Settings(
        shared_secret=None,
        app_callback_base="https://app.example",
        provider="google_gemini",
        model_service_url=None,
        gcs_bucket=None,
        gcs_credentials=None,
        worker_concurrency=1,
        job_look_concurrency=1,
        callback_timeout=1,
        callback_max_attempts=3,
        callback_retry_delay=0,
        result_poll_interval=0.5,
        output_dir="./outputs",
        google_gemini_api_key="key",
        google_gemini_model="model",
        google_gemini_timeout=1,
        google_gemini_use_vertex_ai=False,
        google_cloud_project=None,
        google_cloud_location="global",
    )


@pytest.mark.anyio
async def test_safe_send_event_retries_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _send_event(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary callback failure")

    monkeypatch.setattr(callbacks, "send_event", _send_event)

    await callbacks.safe_send_event(
        _settings(),
        JobMetadata(
            id="job-1",
            userId="user-1",
            callbackUrl="https://app.example/callback",
            looks=1,
        ),
        CallbackEvent(type="completed"),
    )

    assert calls == 3


@pytest.mark.anyio
async def test_safe_send_event_stops_after_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0

    async def _send_event(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("permanent callback failure")

    monkeypatch.setattr(callbacks, "send_event", _send_event)

    await callbacks.safe_send_event(
        replace(_settings(), callback_max_attempts=2),
        JobMetadata(
            id="job-1",
            userId="user-1",
            callbackUrl="https://app.example/callback",
            looks=1,
        ),
        CallbackEvent(type="completed"),
    )

    assert calls == 2
    assert "Failed to send generation event for job job-1" in capsys.readouterr().out
