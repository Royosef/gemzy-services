import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("GENERATION_APP_URL", "https://app.example")

from generation_server import tasks
from generation_server.models import (
    GenerationDimensions,
    GenerationJobPayload,
    GenerationModel,
    GenerationRequest,
    GenerationUpload,
    JobMetadata,
    UserState,
)
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
        callback_timeout=1,
        callback_max_attempts=1,
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


def _payload(*, model_image_uri: str | None, model_image_base64: str | None) -> GenerationJobPayload:
    return GenerationJobPayload(
        job=JobMetadata(
            id="job-1",
            userId="user-1",
            callbackUrl="https://app.example/callback",
            looks=1,
        ),
        user=UserState(id="user-1", name="User", plan="Pro", credits=10),
        request=GenerationRequest(
            uploads=[
                GenerationUpload(
                    id="upload-1",
                    uri="https://example.com/source.png",
                    base64="c291cmNlLWltYWdl",
                    mimeType="image/png",
                )
            ],
            model=GenerationModel(
                id="model-1",
                slug="image-edit",
                name="Edited Model",
                planTier="Pro",
                imageUri=model_image_uri,
                imageBase64=model_image_base64,
            ),
            style={"task_type": "on-model/edited"},
            mode="ADVANCED",
            aspect="4:5",
            dims=GenerationDimensions(w=1080, h=1350),
            looks=1,
            quality="2k",
            plan="Pro",
            creditsNeeded=1,
            promptOverrides=[],
        ),
    )


class _Runner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def initialize(self) -> None:
        return None

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images,
        model_image: bytes,
        product_image_mime_types=None,
        model_image_mime_type=None,
        aspect,
        look_index: int,
    ) -> bytes:
        self.calls.append(
            {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "product_images": list(product_images),
                "model_image": model_image,
                "product_image_mime_types": list(product_image_mime_types or []),
                "model_image_mime_type": model_image_mime_type,
                "aspect": aspect,
                "look_index": look_index,
            }
        )
        return b"result-image"

    def encode_base64(self, image_bytes: bytes) -> str:
        return image_bytes.decode("utf-8")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_image_edit_uses_forwarded_model_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()
    events: list[str] = []

    async def _resolve_model_image(request, settings):
        assert request.model.imageUri == "https://example.com/original-model.png"
        assert request.model.imageBase64 == "bW9kZWwtaW1hZ2U="
        return b"resolved-model-image"

    async def _safe_send_event(_settings, _job, event):
        events.append(event.type)

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)
    monkeypatch.setattr(
        tasks,
        "resolve_prompt_task",
        lambda *_args, **_kwargs: {
            "prompts": ["edit prompt"],
            "negative_prompt": "neg",
        },
    )

    await tasks.process_generation_job(
        _payload(
            model_image_uri="https://example.com/original-model.png",
            model_image_base64="bW9kZWwtaW1hZ2U=",
        )
    )

    assert events == ["started", "result", "completed"]
    assert len(runner.calls) == 1
    assert runner.calls[0]["model_image"] == b"resolved-model-image"
    assert runner.calls[0]["model_image_mime_type"] == "image/png"


@pytest.mark.anyio
async def test_image_edit_without_forwarded_model_reference_keeps_blank_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()

    async def _unexpected_resolve_model_image(_request, _settings):
        raise AssertionError("resolve_model_image should not run without a forwarded model reference")

    async def _safe_send_event(_settings, _job, _event):
        return None

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _unexpected_resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)
    monkeypatch.setattr(
        tasks,
        "resolve_prompt_task",
        lambda *_args, **_kwargs: {
            "prompts": ["edit prompt"],
            "negative_prompt": "neg",
        },
    )

    await tasks.process_generation_job(
        _payload(
            model_image_uri=None,
            model_image_base64=None,
        )
    )

    assert len(runner.calls) == 1
    assert runner.calls[0]["model_image"] == b""
    assert runner.calls[0]["model_image_mime_type"] is None


@pytest.mark.anyio
async def test_generation_task_resolution_tries_task_first_then_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()
    resolve_calls: list[tuple[str, bool]] = []

    async def _resolve_model_image(_request, _settings):
        return b"resolved-model-image"

    async def _safe_send_event(_settings, _job, _event):
        return None

    def _resolve_prompt_task(task_type, _payload, allow_defaults_fallback=True):
        resolve_calls.append((task_type, allow_defaults_fallback))
        if task_type == "on-model/edited":
            raise RuntimeError("route missing")
        return {
            "prompts": ["legacy prompt"],
            "negative_prompt": "legacy negative",
        }

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)
    monkeypatch.setattr(tasks, "resolve_prompt_task", _resolve_prompt_task)

    await tasks.process_generation_job(
        _payload(
            model_image_uri="https://example.com/original-model.png",
            model_image_base64="bW9kZWwtaW1hZ2U=",
        )
    )

    assert resolve_calls == [
        ("on-model/edited", False),
        (tasks.PROMPT_TASK_IMAGE_GENERATION_COMPOSE, True),
    ]
    assert runner.calls[0]["prompt"] == "legacy prompt"
