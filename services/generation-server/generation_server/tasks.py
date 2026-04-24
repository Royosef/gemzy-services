"""Processing orchestration for generation jobs."""

from __future__ import annotations

from typing import Iterable, List, Literal, Protocol

from prompting import PROMPT_TASK_IMAGE_GENERATION_COMPOSE, resolve_prompt_task

from .callbacks import CallbackEvent, safe_send_event
from .comfy_runner import ComfyWorkflowRunner
from .google_runner import GoogleGeminiError, GoogleGeminiRunner
from .models import GenerationJobPayload, GenerationResult
from .settings import get_settings
from .storage import ModelImageUnavailable, decode_upload_image, resolve_model_image

class GenerationRunner(Protocol):
    async def initialize(self) -> None:
        ...

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Iterable[bytes],
        model_image: bytes,
        product_image_mime_types: Iterable[str] | None = None,
        model_image_mime_type: str | None = None,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        ...

    def encode_base64(self, image_bytes: bytes) -> str:
        ...


_runner: GenerationRunner | None = None


def _get_runner() -> GenerationRunner:
    global _runner
    if _runner is None:
        settings = get_settings()
        if settings.provider == "google_gemini":
            _runner = GoogleGeminiRunner(
                api_key=settings.google_gemini_api_key,
                model=settings.google_gemini_model or "gemini-2.5-flash-image",
                use_vertex_ai=settings.google_gemini_use_vertex_ai,
                vertex_project=settings.google_cloud_project,
                vertex_location=settings.google_cloud_location,
                timeout=settings.google_gemini_timeout,
            )
        else:
            _runner = ComfyWorkflowRunner(settings.output_dir)
    return _runner


async def initialize_generation_backend():
    runner = _get_runner()
    await runner.initialize()


async def process_generation_job(payload: GenerationJobPayload) -> None:
    """Execute the full generation workflow for a single job."""

    settings = get_settings()
    job = payload.job
    request = payload.request

    await safe_send_event(settings, job, CallbackEvent(type="started"))

    try:
        product_images: List[bytes] = [decode_upload_image(upload.base64) for upload in request.uploads]
        product_image_mime_types = [upload.mimeType or "image/png" for upload in request.uploads]
        
        # Pure Jewelry uses the product itself as the reference, skipping external model fetch
        if request.model.slug == "pure-jewelry":
            model_image = product_images[0] if product_images else b""
            model_image_mime_type = product_image_mime_types[0] if product_image_mime_types else "image/png"
        else:
            model_image = await resolve_model_image(request, settings)
            model_image_mime_type = "image/png"
            
        rendered_prompt = resolve_prompt_task(
            PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
            {"request": request.model_dump(mode="json")},
        )
        prompts = list(rendered_prompt.get("prompts") or [])
        negative_prompt = str(rendered_prompt.get("negative_prompt") or "")

        runner = _get_runner()

        for index, prompt in enumerate(prompts):
            image_bytes = await runner.generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                product_images=product_images,
                model_image=model_image,
                product_image_mime_types=product_image_mime_types,
                model_image_mime_type=model_image_mime_type,
                aspect=request.aspect,
                look_index=index,
            )
            encoded = runner.encode_base64(image_bytes)
            await safe_send_event(
                settings,
                job,
                CallbackEvent(
                    type="result",
                    result=GenerationResult(base64=encoded),
                    progress=(index + 1) / max(1, len(prompts)),
                    completedLooks=index + 1,
                ),
            )

        await safe_send_event(
            settings,
            job,
            CallbackEvent(
                type="completed",
                progress=1.0,
                completedLooks=len(prompts),
            ),
        )
    except (ModelImageUnavailable, GoogleGeminiError) as exc:
        await safe_send_event(
            settings,
            job,
            CallbackEvent(type="failed", error=str(exc)),
        )
        raise
    except Exception as exc:  # pragma: no cover - best effort logging
        await safe_send_event(
            settings,
            job,
            CallbackEvent(type="failed", error=str(exc)),
        )
        raise
