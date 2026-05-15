"""Processing orchestration for generation jobs."""

from __future__ import annotations

import asyncio
from typing import Iterable, List, Literal, Protocol

from prompting import PROMPT_TASK_IMAGE_GENERATION_COMPOSE, resolve_prompt_task

from .callbacks import CallbackEvent, safe_send_event
from .prompt_builder import build_negative_prompt, build_prompts
from .comfy_runner import ComfyWorkflowRunner
from .google_runner import GoogleGeminiError, GoogleGeminiRunner
from .models import GenerationJobPayload, GenerationResult
from .settings import Settings, get_settings
from .storage import ModelImageUnavailable, decode_upload_image, resolve_model_image

class GenerationRunner(Protocol):
    supports_parallel_look_generation: bool

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


def _resolve_job_look_concurrency(
    settings: Settings,
    runner: GenerationRunner,
    look_count: int,
) -> int:
    configured = max(1, settings.job_look_concurrency)
    if look_count <= 1 or configured <= 1:
        return 1
    if not getattr(runner, "supports_parallel_look_generation", False):
        return 1
    return min(configured, look_count)


async def _generate_single_look(
    *,
    runner: GenerationRunner,
    prompt: str,
    negative_prompt: str,
    product_images: list[bytes],
    model_image: bytes,
    product_image_mime_types: list[str],
    model_image_mime_type: str | None,
    aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
    look_index: int,
) -> bytes:
    return await runner.generate(
        prompt=prompt,
        negative_prompt=negative_prompt,
        product_images=product_images,
        model_image=model_image,
        product_image_mime_types=product_image_mime_types,
        model_image_mime_type=model_image_mime_type,
        aspect=aspect,
        look_index=look_index,
    )


async def generate_looks(
    *,
    settings: Settings,
    runner: GenerationRunner,
    prompts: list[str],
    negative_prompt: str,
    product_images: list[bytes],
    model_image: bytes,
    product_image_mime_types: list[str],
    model_image_mime_type: str | None,
    aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
) -> list[bytes]:
    if not prompts:
        return []

    concurrency = _resolve_job_look_concurrency(settings, runner, len(prompts))
    if concurrency == 1:
        results: list[bytes] = []
        for index, prompt in enumerate(prompts):
            results.append(
                await _generate_single_look(
                    runner=runner,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    product_images=product_images,
                    model_image=model_image,
                    product_image_mime_types=product_image_mime_types,
                    model_image_mime_type=model_image_mime_type,
                    aspect=aspect,
                    look_index=index,
                )
            )
        return results

    semaphore = asyncio.Semaphore(concurrency)

    async def _run(index: int, prompt: str) -> bytes:
        async with semaphore:
            return await _generate_single_look(
                runner=runner,
                prompt=prompt,
                negative_prompt=negative_prompt,
                product_images=product_images,
                model_image=model_image,
                product_image_mime_types=product_image_mime_types,
                model_image_mime_type=model_image_mime_type,
                aspect=aspect,
                look_index=index,
            )

    tasks = [asyncio.create_task(_run(index, prompt)) for index, prompt in enumerate(prompts)]
    try:
        ordered_results: list[bytes] = []
        for task in tasks:
            ordered_results.append(await task)
        return ordered_results
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def process_generation_job(payload: GenerationJobPayload) -> None:
    """Execute the full generation workflow for a single job."""

    settings = get_settings()
    job = payload.job
    request = payload.request

    await safe_send_event(settings, job, CallbackEvent(type="started"))

    try:
        product_images: List[bytes] = [decode_upload_image(upload.base64) for upload in request.uploads]
        product_image_mime_types = [upload.mimeType or "image/png" for upload in request.uploads]
        
        task_type = request.style.get("task_type", request.model.slug) 
        is_image_edit = (
            request.model.slug == "image-edit"
            or task_type == "image_edit"
            or task_type.endswith("/edited")
        )
        has_model_reference = bool(
            request.model.imageBase64 or request.model.imageUri
        )

        # Pure-jewelry generations already receive the uploaded jewelry as
        # product_images. Forwarding the same upload as model_image makes the
        # backend behave like an on-model/reference-image request.
        if request.model.slug == "pure-jewelry":
            model_image = b""
            model_image_mime_type = None
        # Edited on-model jobs can optionally carry forward the original model
        # reference. If it is absent, keep the previous edit behavior.
        elif is_image_edit and has_model_reference:
            model_image = await resolve_model_image(request, settings)
            model_image_mime_type = "image/png"
        elif is_image_edit:
            model_image = b""
            model_image_mime_type = None
        else:
            model_image = await resolve_model_image(request, settings)
            model_image_mime_type = "image/png"
            
        prompt_payload = {"request": request.model_dump(mode="json")}
        requested_task_type = str(request.style.get("task_type", "")).strip()
        resolved_task_type = requested_task_type or PROMPT_TASK_IMAGE_GENERATION_COMPOSE

        try:
            rendered_prompt = resolve_prompt_task(
                resolved_task_type,
                prompt_payload,
                allow_defaults_fallback=False,
            )
        except Exception:
            rendered_prompt = resolve_prompt_task(
                PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                prompt_payload,
            )


        if request.style.get("task_type", "") == "":
            prompts = build_prompts(request)
            negative_prompt = build_negative_prompt(items=request.items)
        else:
            prompts = list(rendered_prompt.get("prompts") or [])
            negative_prompt = str(rendered_prompt.get("negative_prompt") or "")

        runner = _get_runner()

        generated_images = await generate_looks(
            settings=settings,
            runner=runner,
            prompts=prompts,
            negative_prompt=negative_prompt,
            product_images=product_images,
            model_image=model_image,
            product_image_mime_types=product_image_mime_types,
            model_image_mime_type=model_image_mime_type,
            aspect=request.aspect,
        )

        for index, image_bytes in enumerate(generated_images):
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
