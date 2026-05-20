"""Compatibility wrappers around the shared prompt registry."""

from __future__ import annotations

import re
from typing import Any, Iterable

from prompting import (
    PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
    PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
    render_default_task,
    render_engine_version,
)
from prompting.registry import resolve_prompt_task_row

from .models import GenerationItem, GenerationRequest


def _serialize_items(items: list[GenerationItem] | None) -> list[dict]:
    return [item.model_dump(mode="json") for item in (items or [])]


def _slugify_label(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def _normalize_definition_option_label(option_key: str, option_definition: Any, selected: str) -> str | None:
    candidate = str(selected or "").strip()
    if not candidate:
        return None

    label = option_key.strip()
    option_id = ""
    if isinstance(option_definition, dict):
        label = str(option_definition.get("label") or label).strip() or label
        option_id = str(option_definition.get("id") or "").strip() or _slugify_label(label)
    else:
        option_id = _slugify_label(label)

    if candidate in {label, option_id}:
        return label
    return None


def _normalize_option_map_selection(option_map: dict[str, Any], selected: str | None) -> str | None:
    candidate = str(selected or "").strip()
    if not candidate:
        return None

    if candidate in option_map:
        option_definition = option_map[candidate]
        if isinstance(option_definition, dict):
            return str(option_definition.get("label") or candidate).strip() or candidate
        return candidate

    for option_key, option_definition in option_map.items():
        normalized = _normalize_definition_option_label(
            str(option_key or "").strip(),
            option_definition,
            candidate,
        )
        if normalized:
            return normalized
    return None


def _normalize_on_model_style(
    style: dict[str, Any],
    definition: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(style)
    mapping = definition.get("mapping") or {}
    if not isinstance(mapping, dict):
        return normalized

    for field in ("background", "emotion", "hair", "outfit", "pose", "lighting", "camera", "image_style"):
        option_map = mapping.get(field)
        if field == "background" and not isinstance(option_map, dict):
            option_map = mapping.get("scene")
        if not isinstance(option_map, dict):
            continue
        resolved = _normalize_option_map_selection(option_map, normalized.get(field))
        if resolved:
            normalized[field] = resolved
    return normalized


def _normalize_pure_jewelry_style(
    style: dict[str, Any],
    definition: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(style)
    styles = definition.get("styles") or {}
    if not isinstance(styles, dict):
        return normalized

    style_type = str(normalized.get("style_type") or "").strip()
    config = styles.get(style_type)
    if not isinstance(config, dict):
        return normalized

    for raw_category in config.get("categories") or []:
        if isinstance(raw_category, (list, tuple)) and len(raw_category) >= 3:
            category_id = str(raw_category[0] or "").strip()
            option_map = raw_category[2] or {}
        elif isinstance(raw_category, dict):
            category_id = str(
                raw_category.get("id") or raw_category.get("key") or raw_category.get("parameterId") or ""
            ).strip()
            option_map = raw_category.get("options") or raw_category.get("values") or {}
        else:
            continue

        if not category_id or not isinstance(option_map, dict):
            continue

        resolved = _normalize_option_map_selection(option_map, normalized.get(category_id))
        if resolved:
            normalized[category_id] = resolved
    return normalized


def _normalize_request_payload_for_prompting(
    payload: dict[str, Any],
    *,
    task_type: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    request = payload.get("request") or {}
    style = request.get("style") or {}
    if not isinstance(request, dict) or not isinstance(style, dict) or not isinstance(definition, dict):
        return payload

    normalized_payload = dict(payload)
    normalized_request = dict(request)
    model = normalized_request.get("model") or {}
    model_slug = str(model.get("slug") or "").strip()
    effective_task_type = str(style.get("task_type") or task_type).strip()

    if effective_task_type.startswith("pure-jewelry") or model_slug == "pure-jewelry":
        normalized_request["style"] = _normalize_pure_jewelry_style(style, definition)
    elif effective_task_type.startswith("on-model"):
        normalized_request["style"] = _normalize_on_model_style(style, definition)
    else:
        normalized_request["style"] = style
    normalized_payload["request"] = normalized_request
    return normalized_payload


def render_prompt_request(
    task_type: str,
    request: GenerationRequest,
    *,
    allow_defaults_fallback: bool = True,
) -> dict[str, Any]:
    payload = {"request": request.model_dump(mode="json")}
    row = resolve_prompt_task_row(
        task_type,
        payload,
        allow_defaults_fallback=allow_defaults_fallback,
    )
    normalized_payload = _normalize_request_payload_for_prompting(
        payload,
        task_type=task_type,
        definition=row["version"].get("definition") or {},
    )
    return render_engine_version(row["engine"], row["version"], normalized_payload)


def build_prompts(request: GenerationRequest) -> list[str]:
    """Generate prompts for each look using the default registry snapshot."""

    rendered = render_prompt_request(
        PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
        request,
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
