"""Compatibility wrappers around the shared prompt registry."""

from __future__ import annotations

from typing import Iterable

from prompting import (
    PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
    PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
    render_default_task,
)

from .models import GenerationItem, GenerationRequest


def _serialize_items(items: list[GenerationItem] | None) -> list[dict]:
    return [item.model_dump(mode="json") for item in (items or [])]


def build_prompts(request: GenerationRequest) -> list[str]:
    """Generate prompts for each look using the default registry snapshot."""

    rendered = render_default_task(
        PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
        {"request": request.model_dump(mode="json")},
    )
    return list(rendered.get("prompts") or [])


def build_negative_prompt(
    extras: Iterable[str] | None = None,
    items: list[GenerationItem] | None = None,
) -> str:
    """Compose a negative prompt string using the registry-backed defaults."""

    rendered = render_default_task(
        PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
        {
            "extras": list(extras or []),
            "items": _serialize_items(items),
        },
    )
    return str(rendered.get("negative_prompt") or "")
