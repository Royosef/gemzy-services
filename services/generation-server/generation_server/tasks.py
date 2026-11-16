"""Processing orchestration for generation jobs."""

from __future__ import annotations

import asyncio
from typing import Iterable, List, Literal, Protocol

from prompting import PROMPT_TASK_IMAGE_GENERATION_COMPOSE

from .callbacks import CallbackEvent, safe_send_event
from .prompt_builder import build_negative_prompt, build_prompts, render_prompt_request
from .comfy_runner import ComfyWorkflowRunner
from .google_runner import GoogleGeminiError, GoogleGeminiRunner
from .models import GenerationJobPayload, GenerationRequest, GenerationResult
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
        product_image_labels: Iterable[str] | None = None,
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
                models=settings.google_gemini_models,
                use_vertex_ai=settings.google_gemini_use_vertex_ai,
                vertex_project=settings.google_cloud_project,
                vertex_location=settings.google_cloud_location,
                timeout=settings.google_gemini_timeout,
                max_retries=settings.google_gemini_max_retries,
                retry_initial_delay=settings.google_gemini_retry_initial_delay,
                retry_max_delay=settings.google_gemini_retry_max_delay,
                retry_jitter=settings.google_gemini_retry_jitter,
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
    product_image_labels: list[str],
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
        product_image_labels=product_image_labels,
        model_image_mime_type=model_image_mime_type,
        aspect=aspect,
        look_index=look_index,
    )


def _resolve_prompts(
    request: GenerationRequest,
    rendered_prompt: dict[str, object],
) -> list[str]:
    """Resolve the effective prompts for a request.

    Explicit prompt overrides are request-level input and should win over
    renderer output when present. This keeps worker behavior aligned with the
    registry's override semantics even for task routes that only return shared
    defaults such as a negative prompt.
    """

    count = max(1, int(request.looks or 1))
    overrides = [
        str(value).strip()
        for value in request.promptOverrides
        if str(value).strip()
    ]
    if overrides:
        prompts = overrides[:count]
        if len(prompts) < count:
            prompts.extend([prompts[-1]] * (count - len(prompts)))
        return prompts

    return [str(value) for value in (rendered_prompt.get("prompts") or [])]


def _append_mismatched_earring_pair_fidelity(
    request: GenerationRequest,
    prompts: list[str],
) -> list[str]:
    """Keep a two-design earring image intact across every engine/provider."""

    item_types = {
        str(item.type or "").strip().casefold()
        for item in request.items
    }
    style_product = str(request.style.get("product") or "").strip().casefold()
    if not item_types.intersection({"earring", "earrings"}) and style_product not in {
        "earring",
        "earrings",
    }:
        return prompts

    task_type = str(request.style.get("task_type") or request.model.slug).strip().casefold()
    is_pure_jewelry = task_type.startswith("pure-jewelry") or request.model.slug == "pure-jewelry"
    placement_rule = (
        "Show both distinct pieces in the final product composition."
        if is_pure_jewelry
        else (
            "EAR PLACEMENT GRID — LEFT EAR: exactly one uploaded earring attached at the left "
            "earlobe. RIGHT EAR: exactly one uploaded earring attached at the right earlobe. "
            "TOTAL: exactly two visible earrings with a strict [1 left, 1 right] distribution, "
            "never [2, 0] or [0, 2]. If the reference contains two non-identical designs, assign "
            "one distinct design to each ear. No ear may carry both uploaded designs or more than "
            "one product earring. Use a frontal or near-frontal head angle, expose both ears, and "
            "keep hair behind both ears. This placement grid overrides any conflicting pose, hair, "
            "camera, crop, or creative-direction instruction."
        )
    )
    directive = (
        "MISMATCHED EARRING PAIR FIDELITY — Inspect the complete jewelry reference before "
        "deciding whether it contains a single earring, a matching pair, or two non-identical "
        "earrings. A single reference image can contain multiple separate pieces. If it contains "
        "two non-identical earrings, treat them as one intentional mismatched pair and preserve "
        "both designs independently. Never duplicate one earring, merge their details, mirror "
        "them into a matching pair, invent a mate, or omit either piece. "
        f"{placement_rule}"
    )
    return [f"{prompt}\n\n{directive}" for prompt in prompts]


def _append_earring_placement_negatives(
    request: GenerationRequest,
    negative_prompt: str,
) -> str:
    """Reject the common [2, 0] placement failure for on-model earrings."""

    task_type = str(request.style.get("task_type") or request.model.slug).strip().casefold()
    is_pure_jewelry = task_type.startswith("pure-jewelry") or request.model.slug == "pure-jewelry"
    has_earrings = any(
        str(item.type or "").strip().casefold() in {"earring", "earrings"}
        for item in request.items
    ) or str(request.style.get("product") or "").strip().casefold() in {
        "earring",
        "earrings",
    }
    if is_pure_jewelry or not has_earrings:
        return negative_prompt

    placement_negatives = (
        "two product earrings on the same ear, both uploaded earring designs on one ear, "
        "stacked product earrings, clustered product earrings, multiple product piercings on one ear, "
        "[2, 0] earring distribution, [0, 2] earring distribution, empty opposite ear, bare opposite ear, "
        "only one visible ear, profile pose hiding one ear, hair covering either ear"
    )
    return ", ".join(part for part in (negative_prompt.strip(), placement_negatives) if part)


_JEWELRY_SCALE_RULES = {
    "very small": (
        "Use the smallest plausible physical scale. The product must occupy only a minimal "
        "fraction of the relevant anatomy or scene-scale cues and must read as delicate, not statement-sized."
    ),
    "small": (
        "Use a small, understated physical scale. The product must remain clearly subordinate "
        "to the relevant anatomy or scene-scale cues."
    ),
    "medium": (
        "Use a moderate physical scale. The product may be noticeable but must not dominate "
        "the relevant anatomy or scene-scale cues."
    ),
    "big": "Use a large, statement physical scale while keeping it physically plausible.",
    "very big": "Use a very large, dominant physical scale while keeping it physically plausible.",
}


def _append_jewelry_scale_fidelity(
    request: GenerationRequest,
    prompts: list[str],
) -> list[str]:
    """Make selected physical size authoritative over an isolated product crop."""

    sized_items = [
        (index, item, _JEWELRY_SCALE_RULES.get(str(item.size or "").strip().casefold()))
        for index, item in enumerate(request.items, start=1)
    ]
    sized_items = [entry for entry in sized_items if entry[2]]
    if not sized_items:
        return prompts

    item_rules = " ".join(
        f"Item {index} ({item.type}, selected size {item.size}): {rule}"
        for index, item, rule in sized_items
    )
    task_type = str(request.style.get("task_type") or request.model.slug).strip().casefold()
    is_pure_jewelry = task_type.startswith("pure-jewelry") or request.model.slug == "pure-jewelry"
    scale_context = (
        "For this jewelry-only image, communicate physical scale through surface texture, contact "
        "shadows, permitted props, and negative space. A close or macro camera may reveal detail, "
        "but it must not make the product read as physically large relative to the scene."
        if is_pure_jewelry
        else (
            "For this on-model image, judge physical scale against the ear, face, neck, hand, wrist, "
            "or other wearing zone. A close camera may reveal detail, but it must not increase the "
            "product-to-anatomy size ratio."
        )
    )
    directive = (
        "JEWELRY PHYSICAL SCALE OVERRIDE — The selected size describes each distinct jewelry "
        "piece's physical scale relative to the model or scene, not how large the set appears in the source "
        "photo or final crop. An isolated catalog image provides no body- or scene-relative scale. "
        "A source image is only a container and may hold multiple separate pieces. Uniformly scale each "
        "distinct piece independently to the selected size while preserving all "
        "geometry, component proportions, counts, spacing, and materials. This required whole-piece "
        "scaling is not a redesign and overrides any generic instruction not to resize the product. "
        "Never fuse, group, or co-locate separate pieces merely because they share one source image. "
        "For an earring set, size each earring independently; this scale instruction never overrides "
        "the ear placement grid. "
        f"{scale_context} {item_rules}"
    )
    return [f"{prompt}\n\n{directive}" for prompt in prompts]


async def generate_looks(
    *,
    settings: Settings,
    runner: GenerationRunner,
    prompts: list[str],
    negative_prompt: str,
    product_images: list[bytes],
    model_image: bytes,
    product_image_mime_types: list[str],
    product_image_labels: list[str] | None = None,
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
                    product_image_labels=product_image_labels or [],
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
                product_image_labels=product_image_labels or [],
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
        items_by_upload_id = {item.uploadId: item for item in request.items}
        product_image_labels: list[str] = []
        for index, upload in enumerate(request.uploads):
            item = items_by_upload_id.get(upload.id)
            if item is None:
                product_image_labels.append("")
                continue
            details = " ".join(
                value.strip()
                for value in (item.size, item.type)
                if value and value.strip()
            )
            label = f"Jewelry reference {index + 1}"
            product_image_labels.append(f"{label}: {details}" if details else label)
        
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
            
        requested_task_type = str(request.style.get("task_type", "")).strip()
        resolved_task_type = requested_task_type or PROMPT_TASK_IMAGE_GENERATION_COMPOSE

        try:
            rendered_prompt = render_prompt_request(
                resolved_task_type,
                request,
                allow_defaults_fallback=False,
            )
        except Exception:
            rendered_prompt = render_prompt_request(
                PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                request,
            )


        if request.style.get("task_type", "") == "":
            prompts = build_prompts(request)
            negative_prompt = build_negative_prompt(items=request.items)
        else:
            prompts = _resolve_prompts(request, rendered_prompt)
            negative_prompt = str(rendered_prompt.get("negative_prompt") or "")

        prompts = _append_jewelry_scale_fidelity(request, prompts)
        # Placement intentionally comes last: a multi-piece set must never be
        # treated as one combined object by the physical-scale instruction.
        prompts = _append_mismatched_earring_pair_fidelity(request, prompts)
        negative_prompt = _append_earring_placement_negatives(request, negative_prompt)

        runner = _get_runner()

        generated_images = await generate_looks(
            settings=settings,
            runner=runner,
            prompts=prompts,
            negative_prompt=negative_prompt,
            product_images=product_images,
            model_image=model_image,
            product_image_mime_types=product_image_mime_types,
            product_image_labels=product_image_labels,
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
