"""DB-backed prompt registry resolution and rendering helpers."""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from typing import Any, Iterable

from .defaults import (
    PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
    PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
    PROMPT_TASK_PLANNER_ENRICH,
    PROMPT_TASK_PLANNER_RANK,
    get_default_registry,
)


class PromptRegistryError(RuntimeError):
    """Raised when prompt-registry data is invalid or unavailable."""


class PromptRouteNotFound(PromptRegistryError):
    """Raised when no prompt route matches a given task payload."""


_DEFAULTS_SYNCED = False
_STORE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value))


@lru_cache(maxsize=1)
def _get_store_client():
    try:
        from supabase import create_client
    except Exception:
        return None

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        return None
    return create_client(url, key)


def _cache_ttl_seconds() -> float:
    raw = os.getenv("PROMPT_REGISTRY_CACHE_TTL_SECONDS", "30").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 30.0


def _engine_active_version_id(engine: dict[str, Any]) -> str | None:
    active_version_id = engine.get("active_version_id") or engine.get("published_version_id")
    if not active_version_id:
        return None
    return str(active_version_id)


def _normalize_string(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return _normalize_string(left) == _normalize_string(right)
    return left == right


def _lookup_path(payload: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = payload
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        return False, None
    return True, current


def _matches_rule(actual_exists: bool, actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if "exists" in expected and bool(actual_exists) != bool(expected["exists"]):
            return False
        if not actual_exists:
            return "exists" in expected and bool(expected["exists"]) is False
        if "eq" in expected and not _values_equal(actual, expected["eq"]):
            return False
        if "neq" in expected and _values_equal(actual, expected["neq"]):
            return False
        if "in" in expected:
            allowed = expected["in"] or []
            if not any(_values_equal(actual, candidate) for candidate in allowed):
                return False
        if "not_in" in expected:
            blocked = expected["not_in"] or []
            if any(_values_equal(actual, candidate) for candidate in blocked):
                return False
        return True

    if isinstance(expected, list):
        if not actual_exists:
            return False
        return any(_values_equal(actual, candidate) for candidate in expected)

    if not actual_exists:
        return False
    return _values_equal(actual, expected)


def _match_rules(payload: dict[str, Any], rules: dict[str, Any] | None) -> bool:
    if not rules:
        return True
    for path, expected in rules.items():
        exists, actual = _lookup_path(payload, path)
        if not _matches_rule(exists, actual, expected):
            return False
    return True


def _iter_option_entries(option_map: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for raw_label, option_entry in option_map.items():
        label = str(raw_label or "").strip()
        if not label:
            continue
        if isinstance(option_entry, dict):
            yield {
                "label": str(option_entry.get("label") or label).strip() or label,
                "id": str(option_entry.get("id") or "").strip(),
                "prompt": str(option_entry.get("prompt", "")),
                "raw": option_entry,
            }
        else:
            yield {
                "label": label,
                "id": "",
                "prompt": str(option_entry or ""),
                "raw": option_entry,
            }


def _resolve_option_selection(option_map: dict[str, Any], selected: str | None) -> dict[str, Any] | None:
    candidate = str(selected or "").strip()
    if not candidate:
        return None
    if candidate in option_map:
        option_entry = option_map[candidate]
        if isinstance(option_entry, dict):
            return {
                "label": str(option_entry.get("label") or candidate).strip() or candidate,
                "id": str(option_entry.get("id") or "").strip(),
                "prompt": str(option_entry.get("prompt", "")),
                "raw": option_entry,
            }
        return {
            "label": candidate,
            "id": "",
            "prompt": str(option_entry or ""),
            "raw": option_entry,
        }
    for option in _iter_option_entries(option_map):
        if candidate == option["label"] or (option["id"] and candidate == option["id"]):
            return option
    return None


def _normalize_jewelry_type_label(
    value: str | None,
    aliases: dict[str, str] | None = None,
    mapping: dict[str, Any] | None = None,
) -> str:
    if not value:
        return ""
    normalized = value.strip()
    aliases = aliases or {}
    if mapping is None:
        return normalized
    resolved = _resolve_option_selection(mapping.get("jewelry") or {}, normalized)
    if resolved is not None:
        return resolved["label"]
    alias = aliases.get(normalized)
    if alias and (mapping is None or _resolve_option_selection(mapping.get("jewelry") or {}, alias) is not None):
        return alias
    if mapping is not None:
        for source, target in aliases.items():
            if target == normalized:
                resolved_source = _resolve_option_selection(mapping.get("jewelry") or {}, source)
                if resolved_source is not None:
                    return resolved_source["label"]
    return normalized


def _normalize_background_label(
    value: str | None,
    aliases: dict[str, str] | None,
    mapping: dict[str, Any],
) -> str:
    if not value:
        return ""
    normalized = value.strip()
    aliases = aliases or {}
    resolved = _resolve_option_selection(mapping.get("background") or {}, normalized)
    if resolved is not None:
        return resolved["label"]
    alias = aliases.get(normalized)
    if alias:
        resolved_alias = _resolve_option_selection(mapping.get("background") or {}, alias)
        if resolved_alias is not None:
            return resolved_alias["label"]
    for source, target in aliases.items():
        if target == normalized:
            resolved_source = _resolve_option_selection(mapping.get("background") or {}, source)
            if resolved_source is not None:
                return resolved_source["label"]
    return normalized


def _normalize_size_label(value: str | None) -> str:
    return (value or "").strip()


def _style_segment(key: str, value: str) -> str:
    pretty_key = key.replace("_", " ")
    return f"{pretty_key}: {value}".strip()


def _build_item_descriptions(
    items: list[dict[str, Any]] | None,
    aliases: dict[str, str] | None = None,
) -> str:
    if not items:
        return ""

    descriptions: list[str] = []
    for item in items:
        parts: list[str] = []
        size = _normalize_size_label(item.get("size"))
        item_type = _normalize_jewelry_type_label(item.get("type"), aliases)
        if size:
            parts.append(size)
        if item_type:
            parts.append(item_type)
        if parts:
            descriptions.append(f"a {' '.join(parts)}")

    return ", ".join(descriptions)


def _build_size_negative_segments(items: list[dict[str, Any]] | None) -> list[str]:
    sizes = {
        _normalize_string(item.get("size"))
        for item in (items or [])
        if _normalize_size_label(item.get("size"))
    }

    negatives: list[str] = []
    if not sizes.intersection({"big", "very big"}):
        negatives.append("oversized jewelry")
    if not sizes.intersection({"small", "very small"}):
        negatives.append("tiny jewelry")
    return negatives


def compose_negative_prompt(
    base_prompt: str,
    *,
    extras: Iterable[str] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> str:
    parts = [base_prompt]
    parts.extend(_build_size_negative_segments(items))
    if extras:
        parts.extend(str(part).strip() for part in extras if str(part).strip())
    return ", ".join(part.strip() for part in parts if part)


def _finalize_image_prompts(
    request: dict[str, Any],
    *,
    prompt: str,
    negative_prompt: str,
) -> dict[str, Any]:
    count = max(1, int(request.get("looks") or 1))
    overrides = [
        str(value).strip()
        for value in request.get("promptOverrides", []) or []
        if str(value).strip()
    ]

    if overrides:
        prompts = overrides[:count]
        if len(prompts) < count:
            prompts.extend([prompts[-1]] * (count - len(prompts)))
    else:
        prompts = [prompt for _ in range(count)]

    return {
        "prompts": prompts,
        "negative_prompt": negative_prompt,
    }


def _render_image_defaults(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "negative_prompt": compose_negative_prompt(
            str(definition.get("negative_prompt", "")),
            extras=payload.get("extras") or [],
            items=payload.get("items") or [],
        )
    }


def _render_on_model_legacy(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request") or {}
    style = request.get("style") or {}
    items = request.get("items") or []
    aliases = definition.get("jewelry_type_aliases") or {}

    item_descriptions = _build_item_descriptions(items, aliases)
    if not item_descriptions:
        item_descriptions = _normalize_jewelry_type_label(style.get("product"), aliases) or "jewelry"

    defaults = definition.get("defaults") or {}
    camera = style.get("camera") or style.get("camera_style") or defaults.get("camera") or "85mm Portrait"
    pose = style.get("pose") or defaults.get("pose") or "Portrait (Product Touch)"
    background = style.get("background") or defaults.get("background") or "Studio (Pure White)"
    emotion = style.get("emotion") or defaults.get("emotion") or "Sophisticated Calm"
    lighting = style.get("lighting") or defaults.get("lighting") or "Studio Beauty Dish"
    outfit = style.get("outfit")

    segments: list[str] = [
        f"Generate an image of the model wearing the following jewelry pieces: {item_descriptions}.\n",
        f"High-end jewelry campaign, {camera}.",
        f"Pose: {pose}.",
        f"Background: {background}.",
        f"Emotion: {emotion}.",
        f"Lighting: {lighting}.",
    ]
    if outfit:
        segments.append(f"Outfit: {outfit}.")

    segments.extend(
        [
            "Jewelry details stay crisp, true-to-life, and realistically scaled—never oversized or miniature.",
            "No text overlays, captions, or numbers anywhere in the frame.",
        ]
    )

    if (request.get("mode") or "").upper() == "ADVANCED":
        ignored = set(definition.get("advanced_exclude_keys") or [])
        advanced_segments = [
            _style_segment(str(key), str(value))
            for key, value in style.items()
            if key not in ignored
        ]
        segments.extend(segment for segment in advanced_segments if segment)

    return _finalize_image_prompts(
        request,
        prompt=" ".join(filter(None, segments)),
        negative_prompt=compose_negative_prompt(
            str(definition.get("negative_prompt", "")),
            items=items,
        ),
    )


def _resolve_first_item_type(
    items: list[dict[str, Any]] | None,
    style: dict[str, Any],
    aliases: dict[str, str],
    mapping: dict[str, Any],
) -> str:
    for item in items or []:
        resolved = _normalize_jewelry_type_label(item.get("type"), aliases, mapping)
        if resolved:
            return resolved
    return _normalize_jewelry_type_label(style.get("product"), aliases, mapping)


def _resolve_first_item_size(items: list[dict[str, Any]] | None) -> str:
    for item in items or []:
        size = _normalize_size_label(item.get("size"))
        if size:
            return size
    return ""


def _render_on_model_sections(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request") or {}
    style = request.get("style") or {}
    items = request.get("items") or []
    mapping = definition.get("mapping") or {}
    aliases = definition.get("jewelry_type_aliases") or {}
    background_aliases = definition.get("background_aliases") or {}
    texts = definition.get("texts") or {}
    variant = str(definition.get("variant") or "").strip().lower()

    if variant == "v4.5":
        parts: list[str] = [
            f"HERO\n{texts.get('hero', '')}",
            f"\nMODEL\n{texts.get('model_base', '')}",
        ]

        background = _normalize_background_label(style.get("background"), background_aliases, mapping)
        background_color = str(style.get("studioColorHex") or "").upper()
        background_text = (_resolve_option_selection(mapping.get("background", {}), background) or {}).get("prompt", "")
        if background and background_text:
            if "{color}" in background_text and background_color:
                background_text = background_text.replace("{color}", background_color)
            parts.append(f"\nSCENE: {background}\n{background_text}")

        for field, title in (
            ("emotion", "EMOTION"),
            ("hair", "HAIR"),
            ("outfit", "OUTFIT"),
            ("pose", "POSE"),
            ("lighting", "LIGHTING"),
        ):
            selected = style.get(field)
            resolved_option = _resolve_option_selection(mapping.get(field, {}), str(selected or ""))
            description = (resolved_option or {}).get("prompt", "")
            selected = resolved_option["label"] if resolved_option else selected
            selected = resolved_option["label"] if resolved_option else selected
            if selected and description:
                parts.append(f"\n{title}: {resolved_option['label'] if resolved_option else selected}\n{description}")

        jewelry_type = _resolve_first_item_type(items, style, aliases, mapping)
        if jewelry_type:
            jewelry_text = (_resolve_option_selection(mapping.get("jewelry", {}), jewelry_type) or {}).get("prompt", "")
            if jewelry_text:
                parts.append(f"\nJEWELRY TYPE: {jewelry_type}\n{jewelry_text}")

        size_label = _resolve_first_item_size(items)
        if size_label:
            size_text = (_resolve_option_selection(mapping.get("jewelry_size", {}), size_label) or {}).get("prompt", "")
            if size_text:
                parts.append(f"\nJEWELRY SIZE: {size_label}\n{size_text}")

        camera = style.get("camera") or style.get("camera_style")
        resolved_camera = _resolve_option_selection(mapping.get("camera", {}), str(camera or ""))
        camera_text = (resolved_camera or {}).get("prompt", "")
        if camera and camera_text:
            parts.append(f"\nCAMERA STYLE: {resolved_camera['label'] if resolved_camera else camera}\n{camera_text}")

        image_style = style.get("image_style")
        resolved_image_style = _resolve_option_selection(mapping.get("image_style", {}), str(image_style or ""))
        image_style_text = (resolved_image_style or {}).get("prompt", "")
        if image_style and image_style_text:
            parts.append(f"\nSTYLE: {resolved_image_style['label'] if resolved_image_style else image_style}\n{image_style_text}")

        parts.append(f"\n{texts.get('quality', '')}")
        prompt = "\n".join(parts)
    else:
        item_description = _resolve_first_item_type(items, style, aliases, mapping) or "jewelry"
        parts = [
            "HERO PROMPT – Prompt Start",
            texts.get("hero", ""),
            f"[{item_description}]",
        ]

        background = _normalize_background_label(style.get("background"), background_aliases, mapping)
        background_color = str(style.get("studioColorHex") or "")
        background_text = (_resolve_option_selection(mapping.get("background", {}), background) or {}).get("prompt", "")
        if background and background_text:
            if "{color}" in background_text and background_color:
                background_text = background_text.replace("{color}", background_color)
            parts.append(f"SCENE\n{background} — {background_text}")

        parts.append(f"MODEL\nBase prompt — {texts.get('model_base', '')}")

        for field, title in (
            ("emotion", "EMOTION"),
            ("hair", "HAIR"),
            ("outfit", "FASHION (Clothing)"),
            ("pose", "POSE"),
            ("lighting", "LIGHTING"),
        ):
            selected = style.get(field)
            resolved_option = _resolve_option_selection(mapping.get(field, {}), str(selected or ""))
            description = (resolved_option or {}).get("prompt", "")
            if selected and description:
                parts.append(f"{title}\n{selected} — {description}")

        jewelry_text = f"Base prompt — {texts.get('jewelry_base', '')}"
        jewelry_type = _resolve_first_item_type(items, style, aliases, mapping)
        if jewelry_type:
            description = (_resolve_option_selection(mapping.get("jewelry", {}), jewelry_type) or {}).get("prompt", "")
            if description:
                jewelry_text += f"\n{description}"
        parts.append(f"JEWELRY\n{jewelry_text}")

        size_label = _resolve_first_item_size(items)
        if size_label:
            size_text = (_resolve_option_selection(mapping.get("jewelry_size", {}), size_label) or {}).get("prompt", "")
            if size_text:
                parts.append(f"SCALE & PROPORTION\n{size_text}")

        camera = style.get("camera") or style.get("camera_style")
        resolved_camera = _resolve_option_selection(mapping.get("camera", {}), str(camera or ""))
        camera = resolved_camera["label"] if resolved_camera else camera
        camera_text = (resolved_camera or {}).get("prompt", "")
        if camera and camera_text:
            parts.append(f"CAMERA\n{camera} — {camera_text}")

        style_text = f"Base prompt — {texts.get('style_base', '')}"
        image_style = style.get("image_style")
        if image_style:
            resolved_image_style = _resolve_option_selection(mapping.get("image_style", {}), str(image_style or ""))
            image_style = resolved_image_style["label"] if resolved_image_style else image_style
            image_style_text = (resolved_image_style or {}).get("prompt", "")
            if image_style_text:
                style_text += f"\n{image_style} — {image_style_text}"
        parts.append(f"STYLE\n{style_text}")
        parts.append(f"QUALITY CONTROL & RULES\n{texts.get('rules', '')}")

        prompt = "\n\n".join(filter(None, parts))

    return _finalize_image_prompts(
        request,
        prompt=prompt,
        negative_prompt=compose_negative_prompt(
            str(definition.get("negative_prompt", "")),
            items=items,
        ),
    )


def _resolve_pure_jewelry_background(style: dict[str, Any], fallback: str) -> str:
    background = style.get("background", fallback)
    studio_color_hex = style.get("studioColorHex")
    if background in {"Studio Color (Dynamic)", "Studio Color"} and studio_color_hex:
        return f"Studio color backdrop in {studio_color_hex}"
    return str(background)


def _render_pure_jewelry_legacy(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request") or {}
    style = request.get("style") or {}
    templates = definition.get("templates") or {}
    style_type = style.get("style_type")

    if style_type == "studio-shot":
        prompt = str(templates.get("studio-shot", "")).format(
            background=_resolve_pure_jewelry_background(style, "Pure white"),
            surface=style.get("surface", "Floating"),
            lighting=style.get("lighting", "Soft diffused"),
            addons=style.get("add-ons", "None"),
        )
    elif style_type == "lifestyle":
        prompt = str(templates.get("lifestyle", "")).format(
            base=style.get("base", "Fabric"),
            color_palette=style.get("color-palette", "Neutral"),
            lighting=style.get("lighting", "Natural daylight"),
            composition=style.get("composition", "Centered"),
            addons=style.get("add-ons", "None"),
        )
    elif style_type == "collection":
        prompt = str(templates.get("collection", "")).format(
            quantity=style.get("quantity", "3 items"),
            arrangement=style.get("arrangement", "Clean grid"),
            emphasis=style.get("emphasis", "Balanced focus"),
            background=_resolve_pure_jewelry_background(style, "Studio neutral"),
            lighting=style.get("lighting", "Catalog lighting"),
        )
    elif style_type == "on-dummy":
        prompt = str(templates.get("on-dummy", "")).format(
            dummy_type=style.get("dummy-type", "Ceramic bust"),
            dummy_color=style.get("dummy-color", "White"),
            pose_angle=style.get("pose-angle", "Front-facing"),
            lighting=style.get("lighting", "Soft studio"),
            background=_resolve_pure_jewelry_background(style, "Studio clean"),
        )
    else:
        fallback_definition = definition.get("fallback_definition") or {}
        return _render_on_model_legacy(fallback_definition, payload)

    return _finalize_image_prompts(
        request,
        prompt=prompt,
        negative_prompt=compose_negative_prompt(
            str(definition.get("negative_prompt", "")),
            items=request.get("items") or [],
        ),
    )


def _normalize_pure_jewelry_type(value: str, aliases: dict[str, str]) -> str:
    return aliases.get(value, value)


def _resolve_pure_jewelry_type(
    items: list[dict[str, Any]] | None,
    style: dict[str, Any],
    aliases: dict[str, str],
) -> str:
    for item in items or []:
        label = str(item.get("type") or "").strip()
        if label:
            return _normalize_pure_jewelry_type(label, aliases)
    return _normalize_pure_jewelry_type(str(style.get("product") or "").strip(), aliases)


def _resolve_pure_jewelry_size(items: list[dict[str, Any]] | None) -> str:
    for item in items or []:
        label = _normalize_size_label(item.get("size"))
        if label:
            return label
    return ""


def _option_prompt(option_entry: object, color_hex: str) -> str:
    if isinstance(option_entry, str):
        return option_entry
    if isinstance(option_entry, dict):
        return str(option_entry.get("prompt", "")).replace("[HEX]", color_hex)
    return ""


def _render_pure_jewelry_sections(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request") or {}
    style = request.get("style") or {}
    items = request.get("items") or []
    styles = definition.get("styles") or {}
    style_type = str(style.get("style_type") or "").strip()
    config = styles.get(style_type)
    color_hex = str(style.get("studioColorHex") or definition.get("default_color_hex") or "").upper()

    parts = [f"HERO\n{definition.get('hero', '')}"]

    if config:
        parts.append(f"\nATMOSPHERE\n{config.get('atmosphere', '')}")

    item_type = _resolve_pure_jewelry_type(items, style, definition.get("type_aliases") or {})
    type_prompts = definition.get("type_prompts") or {}
    if item_type in type_prompts:
        parts.append(f"\nJEWELRY TYPE: {item_type}\n{type_prompts[item_type]}")

    size = _resolve_pure_jewelry_size(items)
    size_prompts = definition.get("size_prompts") or {}
    if size in size_prompts:
        parts.append(f"\nJEWELRY SIZE: {size}\n{size_prompts[size]}")

    if config:
        for category_id, category_name, options in config.get("categories", []):
            selected = str(style.get(category_id) or "").strip()
            if not selected or selected == "None":
                continue
            resolved_option = _resolve_option_selection(options or {}, selected)
            if resolved_option is None:
                continue
            prompt = _option_prompt(resolved_option["raw"], color_hex)
            if prompt:
                parts.append(f"\n{category_name}: {resolved_option['label']}\n{prompt}")

    parts.append(f"\n{definition.get('quality', '')}")
    prompt = "\n".join(parts)

    return _finalize_image_prompts(
        request,
        prompt=prompt,
        negative_prompt=compose_negative_prompt(
            str(definition.get("negative_prompt", "")),
            items=items,
        ),
    )


def _render_planner_enrich(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    style_profile = payload.get("style_profile") or {}
    preferences = payload.get("preferences") or {}
    world_summary = payload.get("world_summary") or {}
    persona = payload.get("persona") or {}
    style_tags = (style_profile.get("camera_style_tags") or []) + (
        style_profile.get("color_palette_tags") or []
    )
    context = {
        "prompt": payload.get("prompt") or "",
        "persona_display_name": persona.get("display_name") or "",
        "persona_bio": persona.get("bio") or "None",
        "style_profile_realism_level": style_profile.get("realism_level") or "high",
        "style_tags_csv": ", ".join(style_tags),
        "preferences_stories_per_day": preferences.get("stories_per_day") or 0,
        "preferences_posts_per_day": preferences.get("posts_per_day") or 0,
        "world_summary_location_tags_csv": ", ".join(world_summary.get("location_tags") or []),
        "world_summary_wardrobe_tags_csv": ", ".join(world_summary.get("wardrobe_tags") or []),
    }
    prompt_lines = [str(line).format(**context) for line in definition.get("prompt_lines", [])]
    model_name = os.getenv(
        str(definition.get("model_env") or "GOOGLE_GEMINI_MODEL"),
        str(definition.get("default_model") or "gemini-2.5-flash"),
    )
    return {
        "system_instruction": str(definition.get("system_instruction", "")),
        "user_prompt": "\n".join(prompt_lines),
        "model_name": model_name,
        "temperature": float(definition.get("temperature") or 0.7),
    }


def _render_planner_rank(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    moment_lines: list[str] = []
    for index, moment in enumerate(payload.get("moments") or []):
        moment_lines.append(
            "\n".join(
                [
                    f"Moment {index}:",
                    f"  Description: {moment.get('description', '')}",
                    f"  Time: {moment.get('time_slot', '')}",
                    f"  Priority: {moment.get('priority', '')}",
                    f"  Location: {moment.get('location_name') or 'Unknown'} ({', '.join(moment.get('location_tags') or [])})",
                    f"  Outfit Items: {', '.join(moment.get('outfit_items') or [])}",
                ]
            )
        )

    context = {
        "persona_name": payload.get("persona_name") or "",
        "intent": payload.get("intent") or "",
        "tone": payload.get("tone") or "",
        "moments_text": "\n".join(moment_lines),
    }
    prompt_lines = [str(line).format(**context) for line in definition.get("prompt_lines", [])]
    model_name = os.getenv(
        str(definition.get("model_env") or "GOOGLE_GEMINI_MODEL"),
        str(definition.get("default_model") or "gemini-2.5-flash"),
    )
    return {
        "system_instruction": str(definition.get("system_instruction", "")),
        "user_prompt": "\n".join(prompt_lines),
        "model_name": model_name,
        "temperature": float(definition.get("temperature") or 0.3),
    }


_RENDERERS = {
    "image_defaults_v1": _render_image_defaults,
    "on_model_legacy_v1": _render_on_model_legacy,
    "on_model_sections_v1": _render_on_model_sections,
    "planner_enrich_v1": _render_planner_enrich,
    "planner_rank_v1": _render_planner_rank,
    "pure_jewelry_legacy_v1": _render_pure_jewelry_legacy,
    "pure_jewelry_sections_v1": _render_pure_jewelry_sections,
}


def render_engine_version(
    engine: dict[str, Any],
    version: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    renderer_key = str(engine.get("renderer_key") or "").strip()
    renderer = _RENDERERS.get(renderer_key)
    if renderer is None:
        raise PromptRegistryError(f"Unsupported prompt renderer: {renderer_key or '<missing>'}")
    definition = version.get("definition") or {}
    return renderer(definition, payload)


def render_default_task(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    registry = get_default_registry()
    engines = {engine["slug"]: engine for engine in registry["engines"]}
    routes = [
        route
        for route in registry["routes"]
        if route.get("task_type") == task_type and route.get("is_active", True)
    ]
    routes.sort(key=lambda row: (int(row.get("priority") or 0), str(row.get("slug") or "")))

    for route in routes:
        if not _match_rules(payload, route.get("match_rules")):
            continue
        engine = engines.get(route.get("engine_slug"))
        if not engine:
            continue
        version = engine.get("initial_version") or {}
        return render_engine_version(engine, version, payload)

    raise PromptRouteNotFound(f"No prompt route matched task_type={task_type}")


def _resolve_default_task_row(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    registry = get_default_registry()
    engines = {engine["slug"]: engine for engine in registry["engines"]}
    routes = [
        route
        for route in registry["routes"]
        if route.get("task_type") == task_type and route.get("is_active", True)
    ]
    routes.sort(key=lambda row: (int(row.get("priority") or 0), str(row.get("slug") or "")))

    for route in routes:
        if not _match_rules(payload, route.get("match_rules")):
            continue
        engine = engines.get(route.get("engine_slug"))
        if not engine:
            continue
        version = engine.get("initial_version") or {}
        return {
            "route": route,
            "engine": engine,
            "version": version,
        }

    raise PromptRouteNotFound(f"No prompt route matched task_type={task_type}")


def resolve_prompt_task_row(
    task_type: str,
    payload: dict[str, Any],
    *,
    client=None,
    allow_defaults_fallback: bool = True,
) -> dict[str, Any]:
    try:
        hydrated_rows = _load_task_rows_from_store(task_type, client=client)
        for row in hydrated_rows:
            if _match_rules(payload, row["route"].get("match_rules")):
                return row
        raise PromptRouteNotFound(f"No prompt route matched task_type={task_type}")
    except Exception:
        if allow_defaults_fallback:
            return _resolve_default_task_row(task_type, payload)
        raise


def ensure_default_prompt_registry(*, client=None, force: bool = False) -> bool:
    """Seed the prompt registry tables with default engines and routes if needed."""

    global _DEFAULTS_SYNCED
    if _DEFAULTS_SYNCED and not force:
        return False

    store = client or _get_store_client()
    if store is None:
        return False

    registry = get_default_registry()
    inserted_any = False
    engine_ids_by_slug: dict[str, str] = {}
    task_ids_by_key: dict[str, str] = {}

    for task_seed in registry.get("tasks", []):
        task_key = str(task_seed.get("key") or "").strip()
        if not task_key:
            continue
        try:
            existing_task = (
                store.table("prompt_tasks").select("*").eq("key", task_key).limit(1).execute().data or []
            )
        except Exception:
            existing_task = []
        if existing_task:
            existing_defaults = existing_task[0].get("display_defaults") or {}
            wanted_defaults = _json_safe(task_seed.get("display_defaults") or {})
            if wanted_defaults and existing_defaults != wanted_defaults:
                try:
                    store.table("prompt_tasks").update({"display_defaults": wanted_defaults}).eq(
                        "id", existing_task[0]["id"]
                    ).execute()
                except Exception:
                    pass
            task_ids_by_key[task_key] = existing_task[0]["id"]
            continue

        parent_task_key = str(task_seed.get("parent_task_key") or "").strip()
        parent_task_id = task_ids_by_key.get(parent_task_key) if parent_task_key else None
        try:
            created_task = (
                store.table("prompt_tasks")
                .insert(
                    {
                        "key": task_key,
                        "name": task_seed["name"],
                        "description": task_seed.get("description"),
                        "surface": task_seed.get("surface"),
                        "display_defaults": _json_safe(task_seed.get("display_defaults") or {}),
                        "parent_task_id": parent_task_id,
                        "is_active": True,
                    }
                )
                .execute()
                .data
                or []
            )
        except Exception:
            created_task = []
        if created_task:
            task_ids_by_key[task_key] = created_task[0]["id"]
            inserted_any = True

    for engine_seed in registry["engines"]:
        slug = str(engine_seed["slug"])
        existing = (
            store.table("prompt_engines").select("*").eq("slug", slug).limit(1).execute().data
            or []
        )

        if existing:
            engine_row = existing[0]
            selector_updates = {
                "selector_pill_label": engine_seed.get("selector_pill_label"),
                "selector_title": engine_seed.get("selector_title"),
                "selector_description": engine_seed.get("selector_description"),
                "selector_badge": engine_seed.get("selector_badge"),
                "selector_image_key": engine_seed.get("selector_image_key"),
                "selector_badge_image_key": engine_seed.get("selector_badge_image_key"),
            }
            if any(
                selector_updates[key] != engine_row.get(key)
                for key in selector_updates
                if selector_updates[key] is not None
            ):
                try:
                    store.table("prompt_engines").update(selector_updates).eq("id", engine_row["id"]).execute()
                except Exception:
                    pass
            engine_ids_by_slug[slug] = engine_row["id"]
            versions = (
                store.table("prompt_engine_versions")
                .select("*")
                .eq("engine_id", engine_row["id"])
                .execute()
                .data
                or []
            )
            if not versions:
                version_seed = engine_seed["initial_version"]
                created_version = (
                    store.table("prompt_engine_versions")
                    .insert(
                        {
                            "engine_id": engine_row["id"],
                            "version_number": int(version_seed["version_number"]),
                            "status": version_seed["status"],
                            "version_name": version_seed.get("version_name"),
                            "public_version_key": version_seed.get("public_version_key")
                            or f"v{int(version_seed['version_number'])}",
                            "change_note": version_seed.get("change_note"),
                            "definition": _json_safe(version_seed["definition"]),
                            "sample_input": _json_safe(version_seed.get("sample_input") or {}),
                        }
                    )
                    .execute()
                    .data
                    or []
                )
                if created_version:
                    store.table("prompt_engines").update(
                        {
                            "published_version_id": created_version[0]["id"],
                            "active_version_id": created_version[0]["id"],
                        }
                    ).eq("id", engine_row["id"]).execute()
                    inserted_any = True
            continue

        task_key = str(engine_seed.get("task_key") or engine_seed["task_type"])
        created_engine = (
            store.table("prompt_engines")
            .insert(
                {
                    "slug": slug,
                    "name": engine_seed["name"],
                    "description": engine_seed.get("description"),
                    "task_type": engine_seed["task_type"],
                    "task_id": task_ids_by_key.get(task_key),
                    "renderer_key": engine_seed["renderer_key"],
                    "public_engine_key": engine_seed.get("public_engine_key"),
                    "is_user_selectable": bool(engine_seed.get("is_user_selectable", False)),
                    "sort_order": int(engine_seed.get("sort_order") or 100),
                    "selector_pill_label": engine_seed.get("selector_pill_label"),
                    "selector_title": engine_seed.get("selector_title"),
                    "selector_description": engine_seed.get("selector_description"),
                    "selector_badge": engine_seed.get("selector_badge"),
                    "selector_image_key": engine_seed.get("selector_image_key"),
                    "selector_badge_image_key": engine_seed.get("selector_badge_image_key"),
                    "input_schema": _json_safe(engine_seed.get("input_schema") or {}),
                    "output_schema": _json_safe(engine_seed.get("output_schema") or {}),
                    "labels": _json_safe(engine_seed.get("labels") or {}),
                }
            )
            .execute()
            .data
            or []
        )
        if not created_engine:
            continue

        engine_row = created_engine[0]
        engine_ids_by_slug[slug] = engine_row["id"]
        version_seed = engine_seed["initial_version"]
        created_version = (
            store.table("prompt_engine_versions")
            .insert(
                {
                    "engine_id": engine_row["id"],
                    "version_number": int(version_seed["version_number"]),
                    "status": version_seed["status"],
                    "version_name": version_seed.get("version_name"),
                    "public_version_key": version_seed.get("public_version_key")
                    or f"v{int(version_seed['version_number'])}",
                    "change_note": version_seed.get("change_note"),
                    "definition": _json_safe(version_seed["definition"]),
                    "sample_input": _json_safe(version_seed.get("sample_input") or {}),
                }
            )
            .execute()
            .data
            or []
        )
        if created_version:
            store.table("prompt_engines").update(
                {
                    "published_version_id": created_version[0]["id"],
                    "active_version_id": created_version[0]["id"],
                }
            ).eq("id", engine_row["id"]).execute()
        inserted_any = True

    for route_seed in registry["routes"]:
        slug = str(route_seed["slug"])
        existing = (
            store.table("prompt_task_routes").select("*").eq("slug", slug).limit(1).execute().data
            or []
        )
        if existing:
            continue

        engine_slug = str(route_seed["engine_slug"])
        engine_id = engine_ids_by_slug.get(engine_slug)
        if not engine_id:
            engine_rows = (
                store.table("prompt_engines").select("id").eq("slug", engine_slug).limit(1).execute().data
                or []
            )
            if not engine_rows:
                continue
            engine_id = engine_rows[0]["id"]
            engine_ids_by_slug[engine_slug] = engine_id

        task_key = str(route_seed.get("task_key") or route_seed["task_type"])
        store.table("prompt_task_routes").insert(
            {
                "slug": slug,
                "name": route_seed["name"],
                "task_type": route_seed["task_type"],
                "task_id": task_ids_by_key.get(task_key),
                "priority": int(route_seed.get("priority") or 100),
                "is_active": bool(route_seed.get("is_active", True)),
                "match_rules": _json_safe(route_seed.get("match_rules") or {}),
                "engine_id": engine_id,
                "notes": route_seed.get("notes"),
            }
        ).execute()
        inserted_any = True

    _DEFAULTS_SYNCED = True
    if inserted_any:
        _STORE_CACHE.clear()
    return inserted_any


def _load_task_rows_from_store(task_type: str, *, client=None) -> list[dict[str, Any]]:
    store = client or _get_store_client()
    if store is None:
        raise PromptRegistryError("Prompt registry database is not configured")

    ensure_default_prompt_registry(client=store)

    ttl = _cache_ttl_seconds()
    cached = _STORE_CACHE.get(task_type)
    now = time.time()
    if ttl > 0 and cached and (now - cached[0]) < ttl:
        return cached[1]

    routes = (
        store.table("prompt_task_routes")
        .select("*")
        .eq("task_type", task_type)
        .eq("is_active", True)
        .order("priority")
        .execute()
        .data
        or []
    )
    if not routes:
        raise PromptRouteNotFound(f"No prompt routes configured for task_type={task_type}")

    engine_ids = sorted({route["engine_id"] for route in routes if route.get("engine_id")})
    engines = (
        store.table("prompt_engines").select("*").in_("id", engine_ids).execute().data
        or []
    )
    engines_by_id = {engine["id"]: engine for engine in engines}

    version_ids: set[str] = set()
    for route in routes:
        pinned = route.get("pinned_version_id")
        if pinned:
            version_ids.add(pinned)
            continue
        engine = engines_by_id.get(route.get("engine_id"))
        active_version_id = _engine_active_version_id(engine or {})
        if active_version_id:
            version_ids.add(active_version_id)

    versions = []
    if version_ids:
        versions = (
            store.table("prompt_engine_versions").select("*").in_("id", list(version_ids)).execute().data
            or []
        )
    versions_by_id = {version["id"]: version for version in versions}

    hydrated: list[dict[str, Any]] = []
    for route in routes:
        engine = engines_by_id.get(route.get("engine_id"))
        if not engine:
            continue
        version_id = route.get("pinned_version_id") or _engine_active_version_id(engine)
        version = versions_by_id.get(version_id)
        if not version:
            continue
        hydrated.append(
            {
                "route": route,
                "engine": engine,
                "version": version,
            }
        )

    if not hydrated:
        raise PromptRouteNotFound(f"No active prompt versions available for task_type={task_type}")

    _STORE_CACHE[task_type] = (now, hydrated)
    return hydrated


def resolve_prompt_task(
    task_type: str,
    payload: dict[str, Any],
    *,
    client=None,
    allow_defaults_fallback: bool = True,
) -> dict[str, Any]:
    """Resolve and render the active prompt engine for a task."""

    row = resolve_prompt_task_row(
        task_type,
        payload,
        client=client,
        allow_defaults_fallback=allow_defaults_fallback,
    )
    return render_engine_version(row["engine"], row["version"], payload)
