import os
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generation_server import tasks
from generation_server.models import (
    GenerationDimensions,
    GenerationItem,
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
        google_gemini_api_key="key",
        google_gemini_models=("model",),
        google_gemini_timeout=1,
        google_gemini_use_vertex_ai=False,
        google_cloud_project=None,
        google_cloud_location="global",
    )


def _payload(
    *,
    model_image_uri: str | None,
    model_image_base64: str | None,
    prompt_overrides: list[str] | None = None,
) -> GenerationJobPayload:
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
            promptOverrides=list(prompt_overrides or []),
        ),
    )


def _pure_jewelry_payload(style: dict[str, str] | None = None) -> GenerationJobPayload:
    return GenerationJobPayload(
        job=JobMetadata(
            id="job-pure-jewelry",
            userId="user-1",
            callbackUrl="https://app.example/callback",
            looks=1,
        ),
        user=UserState(id="user-1", name="User", plan="Pro", credits=10),
        request=GenerationRequest(
            uploads=[
                GenerationUpload(
                    id="upload-1",
                    uri="https://example.com/jewelry.png",
                    base64="c291cmNlLWltYWdl",
                    mimeType="image/png",
                )
            ],
            model=GenerationModel(
                id="pure-jewelry-model",
                slug="pure-jewelry",
                name="Pure Jewelry",
                planTier="Free",
                imageUri=None,
                imageBase64=None,
            ),
            style=style or {"task_type": "pure-jewelry", "public_version_key": "v5.2"},
            mode="ADVANCED",
            aspect="1:1",
            dims=GenerationDimensions(w=1080, h=1080),
            looks=1,
            quality="2k",
            plan="Pro",
            creditsNeeded=1,
            promptOverrides=[],
        ),
    )


@pytest.mark.parametrize(
    ("payload", "expected_placement"),
    [
        (
            _payload(
                model_image_uri="https://example.com/original-model.png",
                model_image_base64="bW9kZWwtaW1hZ2U=",
            ),
            "strict [1 left, 1 right] distribution",
        ),
        (
            _pure_jewelry_payload(),
            "Show both distinct pieces in the final product composition",
        ),
    ],
)
def test_mismatched_earring_pair_fidelity_is_engine_independent(
    payload: GenerationJobPayload,
    expected_placement: str,
) -> None:
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Earrings",
            size="Medium",
            uploadId="upload-1",
        )
    ]

    prompts = tasks._append_mismatched_earring_pair_fidelity(
        payload.request,
        ["engine-owned prompt"],
    )

    assert prompts[0].startswith("engine-owned prompt")
    assert "MISMATCHED EARRING PAIR FIDELITY" in prompts[0]
    assert "two non-identical earrings" in prompts[0]
    assert expected_placement in prompts[0]


def test_on_model_earrings_reject_same_ear_placement() -> None:
    payload = _payload(
        model_image_uri="https://example.com/original-model.png",
        model_image_base64="bW9kZWwtaW1hZ2U=",
    )
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Earrings",
            size="Very Small",
            uploadId="upload-1",
        )
    ]

    negative_prompt = tasks._append_earring_placement_negatives(
        payload.request,
        "existing negative",
    )

    assert negative_prompt.startswith("existing negative")
    assert "two product earrings on the same ear" in negative_prompt
    assert "[2, 0] earring distribution" in negative_prompt
    assert "empty opposite ear" in negative_prompt
    assert "profile pose hiding one ear" in negative_prompt


def test_pure_jewelry_does_not_apply_on_model_ear_negatives() -> None:
    payload = _pure_jewelry_payload()
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Earrings",
            size="Very Small",
            uploadId="upload-1",
        )
    ]

    negative_prompt = tasks._append_earring_placement_negatives(
        payload.request,
        "existing negative",
    )

    assert negative_prompt == "existing negative"


def test_mismatched_earring_pair_fidelity_leaves_other_jewelry_unchanged() -> None:
    payload = _pure_jewelry_payload()
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Ring",
            size="Medium",
            uploadId="upload-1",
        )
    ]

    prompts = tasks._append_mismatched_earring_pair_fidelity(
        payload.request,
        ["engine-owned prompt"],
    )

    assert prompts == ["engine-owned prompt"]


def test_very_small_scale_overrides_source_crop_without_changing_design() -> None:
    payload = _payload(
        model_image_uri="https://example.com/original-model.png",
        model_image_base64="bW9kZWwtaW1hZ2U=",
    )
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Earrings",
            size="Very Small",
            uploadId="upload-1",
        )
    ]

    prompts = tasks._append_jewelry_scale_fidelity(
        payload.request,
        ["engine-owned prompt"],
    )

    assert "JEWELRY PHYSICAL SCALE OVERRIDE" in prompts[0]
    assert "selected size Very Small" in prompts[0]
    assert "smallest plausible physical scale" in prompts[0]
    assert "isolated catalog image provides no body- or scene-relative scale" in prompts[0]
    assert "overrides any generic instruction not to resize" in prompts[0]
    assert "preserving all geometry, component proportions" in prompts[0]
    assert "scale each distinct piece independently" in prompts[0]
    assert "Never fuse, group, or co-locate separate pieces" in prompts[0]
    assert "scale instruction never overrides the ear placement grid" in prompts[0]


def test_ear_placement_is_final_after_size_for_a_two_piece_set() -> None:
    payload = _payload(
        model_image_uri="https://example.com/original-model.png",
        model_image_base64="bW9kZWwtaW1hZ2U=",
    )
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Earrings",
            size="Very Small",
            uploadId="upload-1",
        )
    ]

    prompts = tasks._append_jewelry_scale_fidelity(
        payload.request,
        ["engine-owned prompt"],
    )
    prompts = tasks._append_mismatched_earring_pair_fidelity(
        payload.request,
        prompts,
    )

    prompt = prompts[0]
    assert prompt.index("JEWELRY PHYSICAL SCALE OVERRIDE") < prompt.rindex("EAR PLACEMENT GRID")
    assert prompt.rstrip().endswith(
        "This placement grid overrides any conflicting pose, hair, camera, crop, or creative-direction instruction."
    )


def test_pure_jewelry_scale_uses_scene_cues_instead_of_anatomy() -> None:
    payload = _pure_jewelry_payload()
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Ring",
            size="Very Small",
            uploadId="upload-1",
        )
    ]

    prompts = tasks._append_jewelry_scale_fidelity(
        payload.request,
        ["engine-owned prompt"],
    )

    assert "For this jewelry-only image" in prompts[0]
    assert "surface texture, contact shadows, permitted props, and negative space" in prompts[0]
    assert "must not make the product read as physically large relative to the scene" in prompts[0]
    assert "product-to-anatomy size ratio" not in prompts[0]


class _Runner:
    supports_parallel_look_generation = True

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
        product_image_labels=None,
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
                "product_image_labels": list(product_image_labels or []),
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
        "render_prompt_request",
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
        "render_prompt_request",
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
async def test_image_edit_uses_prompt_overrides_when_edit_renderer_returns_defaults_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()

    async def _resolve_model_image(_request, _settings):
        return b"resolved-model-image"

    async def _safe_send_event(_settings, _job, _event):
        return None

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)
    monkeypatch.setattr(
        tasks,
        "render_prompt_request",
        lambda *_args, **_kwargs: {
            "negative_prompt": "neg",
        },
    )

    await tasks.process_generation_job(
        _payload(
            model_image_uri="https://example.com/original-model.png",
            model_image_base64="bW9kZWwtaW1hZ2U=",
            prompt_overrides=["edit prompt from override"],
        )
    )

    assert len(runner.calls) == 1
    assert runner.calls[0]["prompt"] == "edit prompt from override"
    assert runner.calls[0]["negative_prompt"] == "neg"


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

    def _render_prompt_request(task_type, _request, allow_defaults_fallback=True):
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
    monkeypatch.setattr(tasks, "render_prompt_request", _render_prompt_request)

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


@pytest.mark.anyio
async def test_pure_jewelry_generation_does_not_forward_model_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()

    async def _unexpected_resolve_model_image(_request, _settings):
        raise AssertionError("resolve_model_image should not run for pure-jewelry generations")

    async def _safe_send_event(_settings, _job, _event):
        return None

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _unexpected_resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)
    monkeypatch.setattr(
        tasks,
        "render_prompt_request",
        lambda *_args, **_kwargs: {
            "prompts": ["pure jewelry prompt"],
            "negative_prompt": "neg",
        },
    )

    await tasks.process_generation_job(_pure_jewelry_payload())

    assert len(runner.calls) == 1
    assert runner.calls[0]["product_images"] == [b"source-image"]
    assert runner.calls[0]["model_image"] == b""


@pytest.mark.anyio
async def test_generation_labels_each_upload_with_its_matching_item_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()

    async def _safe_send_event(_settings, _job, _event):
        return None

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)

    payload = _pure_jewelry_payload()
    payload.request.uploads.append(
        GenerationUpload(
            id="upload-2",
            uri="https://example.com/ring.png",
            base64="cmluZy1pbWFnZQ==",
            mimeType="image/png",
        )
    )
    payload.request.items = [
        GenerationItem(
            id="item-1",
            type="Necklace",
            size="Small",
            uploadId="upload-1",
        ),
        GenerationItem(
            id="item-2",
            type="Ring",
            size="Medium",
            uploadId="upload-2",
        ),
    ]

    await tasks.process_generation_job(payload)

    assert runner.calls[0]["product_image_labels"] == [
        "Jewelry reference 1: Small Necklace",
        "Jewelry reference 2: Medium Ring",
    ]
    assert runner.calls[0]["model_image_mime_type"] is None


@pytest.mark.anyio
async def test_pure_jewelry_task_normalizes_option_ids_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _Runner()

    async def _unexpected_resolve_model_image(_request, _settings):
        raise AssertionError("resolve_model_image should not run for pure-jewelry generations")

    async def _safe_send_event(_settings, _job, _event):
        return None

    monkeypatch.setattr(tasks, "get_settings", _settings)
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _unexpected_resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)

    await tasks.process_generation_job(
        _pure_jewelry_payload(
            style={
                "task_type": "pure-jewelry",
                "public_version_key": "v5.2",
                "style_type": "pure-studio",
                "scene": "studio-color",
                "surface": "silk",
                "lighting": "soft-diffused",
                "shadow": "soft",
                "composition": "close-up",
                "studioColorHex": "#C0FFEE",
            }
        )
    )

    assert len(runner.calls) == 1
    assert "SCENE: Studio Color" in str(runner.calls[0]["prompt"])
    assert "SURFACE: Silk" in str(runner.calls[0]["prompt"])
    assert "COMPOSITION: Close Up" in str(runner.calls[0]["prompt"])


@pytest.mark.anyio
async def test_multi_look_generation_can_run_in_parallel_while_preserving_result_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str | None, int | None]] = []

    class _BlockingRunner(_Runner):
        def __init__(self) -> None:
            super().__init__()
            self.started: list[int] = []
            self.second_started = tasks.asyncio.Event()

        async def generate(
            self,
            *,
            prompt: str,
            negative_prompt: str,
            product_images,
            model_image: bytes,
            product_image_mime_types=None,
            product_image_labels=None,
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
                    "product_image_labels": list(product_image_labels or []),
                    "model_image_mime_type": model_image_mime_type,
                    "aspect": aspect,
                    "look_index": look_index,
                }
            )
            self.started.append(look_index)
            if look_index == 0:
                await tasks.asyncio.wait_for(self.second_started.wait(), timeout=0.2)
            else:
                self.second_started.set()
            return f"result-{look_index}".encode("utf-8")

    runner = _BlockingRunner()

    async def _resolve_model_image(_request, _settings):
        return b"resolved-model-image"

    async def _safe_send_event(_settings, _job, event):
        encoded = event.result.base64 if event.result is not None else None
        events.append((event.type, encoded, event.completedLooks))

    base_payload = _payload(
        model_image_uri="https://example.com/original-model.png",
        model_image_base64="bW9kZWwtaW1hZ2U=",
    )
    payload = base_payload.model_copy(
        update={
            "job": base_payload.job.model_copy(update={"id": "job-2", "looks": 2}),
            "request": base_payload.request.model_copy(update={"looks": 2}),
        }
    )

    monkeypatch.setattr(tasks, "get_settings", lambda: replace(_settings(), job_look_concurrency=2))
    monkeypatch.setattr(tasks, "_get_runner", lambda: runner)
    monkeypatch.setattr(tasks, "resolve_model_image", _resolve_model_image)
    monkeypatch.setattr(tasks, "safe_send_event", _safe_send_event)
    monkeypatch.setattr(
        tasks,
        "render_prompt_request",
        lambda *_args, **_kwargs: {
            "prompts": ["first prompt", "second prompt"],
            "negative_prompt": "neg",
        },
    )

    await tasks.process_generation_job(payload)

    assert runner.started == [0, 1]
    assert events == [
        ("started", None, None),
        ("result", "result-0", 1),
        ("result", "result-1", 2),
        ("completed", None, 2),
    ]
