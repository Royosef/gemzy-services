"""Helpers for resolving the public generation UI catalog."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any

from .ui_defaults import get_default_generation_ui_catalog

_SURFACE_KEYS = ("onModel", "pureJewelry")
_FALLBACK_TASK_META = {
    "on-model": {
        "name": "On Model",
        "description": "Primary on-model jewelry generation task.",
        "surface": "onModel",
        "parentTaskKey": None,
    },
    "on-model/edited": {
        "name": "On Model Edit",
        "description": "Edit flow for on-model generations.",
        "surface": "onModel",
        "parentTaskKey": "on-model",
    },
    "pure-jewelry": {
        "name": "Pure Jewelry",
        "description": "Primary pure-jewelry generation task.",
        "surface": "pureJewelry",
        "parentTaskKey": None,
    },
    "pure-jewelry/edited": {
        "name": "Pure Jewelry Edit",
        "description": "Edit flow for pure-jewelry generations.",
        "surface": "pureJewelry",
        "parentTaskKey": "pure-jewelry",
    },
}


def _slugify_label(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {key: deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return deepcopy(override)


def _normalize_ui_option(raw_option: Any, *, fallback_id: str) -> dict[str, Any] | None:
    if isinstance(raw_option, str):
        label = raw_option.strip()
        if not label:
            return None
        return {
            "id": _slugify_label(label) or fallback_id,
            "label": label,
            "hasColor": False,
            "colorLabel": None,
        }
    if isinstance(raw_option, dict):
        label = str(raw_option.get("label") or raw_option.get("name") or "").strip()
        if not label:
            return None
        option_id = str(raw_option.get("id") or "").strip() or _slugify_label(label) or fallback_id
        has_color = bool(raw_option.get("hasColor") or raw_option.get("has_color"))
        color_label = raw_option.get("colorLabel") or raw_option.get("color_label")
        return {
            "id": option_id,
            "label": label,
            "hasColor": has_color,
            "colorLabel": str(color_label).strip() if color_label is not None else (label if has_color else None),
        }
    return None


def _normalize_definition_option(
    *,
    option_key: str,
    option_definition: Any,
    fallback_id: str,
) -> dict[str, Any] | None:
    if isinstance(option_definition, dict):
        label = str(option_definition.get("label") or option_key).strip()
        if not label:
            return None
        option_id = str(option_definition.get("id") or "").strip() or _slugify_label(label) or fallback_id
        has_color = bool(option_definition.get("has_color") or option_definition.get("hasColor"))
        color_label = option_definition.get("color_label") or option_definition.get("colorLabel")
        return {
            "id": option_id,
            "label": label,
            "hasColor": has_color,
            "colorLabel": str(color_label).strip() if color_label is not None else (label if has_color else None),
        }
    return _normalize_ui_option(
        {
            "id": _slugify_label(option_key) or fallback_id,
            "label": option_key,
            "hasColor": False,
            "colorLabel": None,
        },
        fallback_id=fallback_id,
    )


def _normalize_option_list(raw_options: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_options, list):
        return []
    options: list[dict[str, Any]] = []
    for index, raw_option in enumerate(raw_options, start=1):
        normalized = _normalize_ui_option(raw_option, fallback_id=f"option-{index}")
        if normalized is not None:
            options.append(normalized)
    return options


def _build_edit_config_from_definition(definition: dict[str, Any]) -> dict[str, Any] | None:
    raw_options = definition.get("editOptions") or []
    raw_categories = definition.get("editCategories") or []
    if not isinstance(raw_options, list) or not isinstance(raw_categories, list):
        return None

    options: list[dict[str, Any]] = []
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            continue
        option_id = str(raw_option.get("id") or "").strip()
        label = str(raw_option.get("label") or "").strip()
        description = str(raw_option.get("description") or "").strip()
        category = str(raw_option.get("category") or "").strip()
        if not option_id or not label or not description or not category:
            continue
        options.append(
            {
                "id": option_id,
                "label": label,
                "description": description,
                "category": category,
                "parentId": str(raw_option.get("parentId") or "").strip() or None,
                "parentLabel": str(raw_option.get("parentLabel") or "").strip() or None,
                "exclusiveGroup": str(raw_option.get("exclusiveGroup") or "").strip() or None,
                "conflictsWith": [
                    str(conflict_id).strip()
                    for conflict_id in (raw_option.get("conflictsWith") or [])
                    if str(conflict_id).strip()
                ],
            }
        )

    categories: list[dict[str, Any]] = []
    for raw_category in raw_categories:
        if not isinstance(raw_category, dict):
            continue
        category_id = str(raw_category.get("id") or "").strip()
        label = str(raw_category.get("label") or "").strip()
        option_ids = [
            str(option_id).strip()
            for option_id in (raw_category.get("options") or [])
            if str(option_id).strip()
        ]
        if not category_id or not label or not option_ids:
            continue
        categories.append(
            {
                "id": category_id,
                "label": label,
                "options": option_ids,
                "disabled": bool(raw_category.get("disabled", False)),
                "disabledReason": str(raw_category.get("disabledReason") or "").strip() or None,
            }
        )

    if not options or not categories:
        return None
    return {
        "categories": categories,
        "options": options,
    }


def _humanize_identifier(value: str) -> str:
    words = [part for part in re.split(r"[-_]+", value.strip()) if part]
    return " ".join(word.capitalize() for word in words) or value


def _build_on_model_sections_from_definition(
    *,
    definition: dict[str, Any],
    display_defaults: dict[str, Any],
    base_engine: dict[str, Any],
) -> list[dict[str, Any]]:
    mapping = definition.get("mapping") or {}
    if not isinstance(mapping, dict):
        return []

    base_sections = {
        str(section.get("id") or "").strip(): section
        for section in (base_engine.get("sections") or [])
        if isinstance(section, dict) and section.get("id")
    }
    section_defaults = display_defaults.get("sectionDefaults") or {}
    ordered_section_ids = list(base_sections.keys())
    for section_id in mapping.keys():
        normalized_section_id = str(section_id or "").strip()
        if normalized_section_id and normalized_section_id not in ordered_section_ids:
            ordered_section_ids.append(normalized_section_id)

    sections: list[dict[str, Any]] = []
    for section_id in ordered_section_ids:
        option_map = mapping.get(section_id) or {}
        if not isinstance(option_map, dict):
            continue
        section_default = section_defaults.get(section_id) or {}
        base_section = base_sections.get(section_id) or {}
        options: list[dict[str, Any]] = []
        for index, (option_label, option_definition) in enumerate(option_map.items(), start=1):
            normalized_option = _normalize_definition_option(
                option_key=str(option_label or "").strip(),
                option_definition=option_definition,
                fallback_id=f"{section_id}-{index}",
            )
            if normalized_option is not None:
                options.append(normalized_option)
        sections.append(
            {
                "id": section_id,
                "label": str(section_default.get("label") or base_section.get("label") or section_id),
                "description": section_default.get("description") or base_section.get("description"),
                "iconKey": section_default.get("iconKey") or base_section.get("iconKey"),
                "editTier": section_default.get("editTier") or base_section.get("editTier"),
                "supportsRandom": bool(
                    section_default.get("supportsRandom", base_section.get("supportsRandom", False))
                ),
                "freeOptionLabels": list(base_section.get("freeOptionLabels") or []),
                "options": options,
            }
        )
    return sections


def _build_pure_jewelry_styles_from_definition(
    *,
    definition: dict[str, Any],
    display_defaults: dict[str, Any],
    base_engine: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_styles = definition.get("styles") or {}
    if not isinstance(raw_styles, dict):
        return []

    base_styles = {
        str(style.get("id") or "").strip(): style
        for style in (base_engine.get("styles") or [])
        if isinstance(style, dict) and style.get("id")
    }
    section_defaults = display_defaults.get("sectionDefaults") or {}
    ordered_style_ids = list(base_styles.keys())
    for style_id in raw_styles.keys():
        normalized_style_id = str(style_id or "").strip()
        if normalized_style_id and normalized_style_id not in ordered_style_ids:
            ordered_style_ids.append(normalized_style_id)

    styles: list[dict[str, Any]] = []
    for style_id in ordered_style_ids:
        style_definition = raw_styles.get(style_id) or {}
        if not isinstance(style_definition, dict):
            continue
        base_style = base_styles.get(style_id) or {}
        base_parameters = {
            str(parameter.get("id") or "").strip(): parameter
            for parameter in (base_style.get("parameters") or [])
            if isinstance(parameter, dict) and parameter.get("id")
        }
        parameters: list[dict[str, Any]] = []
        categories = style_definition.get("categories") or []
        for index, raw_category in enumerate(categories, start=1):
            if isinstance(raw_category, (list, tuple)) and len(raw_category) >= 3:
                parameter_id = str(raw_category[0] or "").strip()
                parameter_heading = str(raw_category[1] or "").strip()
                option_map = raw_category[2] or {}
            elif isinstance(raw_category, dict):
                parameter_id = str(
                    raw_category.get("id") or raw_category.get("key") or raw_category.get("parameterId") or ""
                ).strip()
                parameter_heading = str(raw_category.get("label") or raw_category.get("title") or "").strip()
                option_map = raw_category.get("options") or raw_category.get("values") or {}
            else:
                continue
            if not parameter_id or not isinstance(option_map, dict):
                continue

            base_parameter = base_parameters.get(parameter_id) or {}
            parameter_default = section_defaults.get(parameter_id) or {}
            options: list[dict[str, Any]] = []
            for option_position, (option_label, option_definition) in enumerate(option_map.items(), start=1):
                normalized_option = _normalize_definition_option(
                    option_key=str(option_label or "").strip(),
                    option_definition=option_definition,
                    fallback_id=f"{parameter_id}-{option_position}",
                )
                if normalized_option is not None:
                    options.append(normalized_option)
            parameters.append(
                {
                    "id": parameter_id,
                    "label": str(
                        parameter_default.get("label")
                        or base_parameter.get("label")
                        or parameter_heading
                        or _humanize_identifier(parameter_id)
                    ),
                    "description": parameter_default.get("description") or base_parameter.get("description"),
                    "iconKey": parameter_default.get("iconKey") or base_parameter.get("iconKey"),
                    "editTier": parameter_default.get("editTier") or base_parameter.get("editTier"),
                    "supportsRandom": bool(
                        parameter_default.get("supportsRandom", base_parameter.get("supportsRandom", False))
                    ),
                    "freeOptionLabels": list(base_parameter.get("freeOptionLabels") or []),
                    "options": options,
                    "_order": index,
                }
            )
        styles.append(
            {
                "id": style_id,
                "title": str(
                    style_definition.get("title")
                    or base_style.get("title")
                    or _humanize_identifier(style_id)
                ),
                "imageKey": str(
                    style_definition.get("imageKey")
                    or style_definition.get("image_key")
                    or base_style.get("imageKey")
                    or style_id
                ),
                "parameters": [
                    {
                        key: value
                        for key, value in parameter.items()
                        if key != "_order"
                    }
                    for parameter in sorted(parameters, key=lambda parameter: int(parameter.get("_order") or 0))
                ],
            }
        )
    return styles


def _apply_definition_surface_overrides(
    *,
    engine: dict[str, Any],
    definition: dict[str, Any],
    task_payload: dict[str, Any],
    surface_key: str,
    base_engine: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(engine)
    display_defaults = task_payload.get("displayDefaults") or {}

    item_types = _normalize_option_list(display_defaults.get("itemTypes"))
    if item_types:
        merged["itemTypes"] = item_types
    item_sizes = _normalize_option_list(display_defaults.get("itemSizes"))
    if item_sizes:
        merged["itemSizes"] = item_sizes
    if display_defaults.get("trialPopupImageKey"):
        merged["trialPopupImageKey"] = display_defaults.get("trialPopupImageKey")

    if surface_key == "onModel":
        derived_sections = _build_on_model_sections_from_definition(
            definition=definition,
            display_defaults=display_defaults,
            base_engine=base_engine,
        )
        if derived_sections:
            merged["sections"] = derived_sections
    if surface_key == "pureJewelry":
        derived_styles = _build_pure_jewelry_styles_from_definition(
            definition=definition,
            display_defaults=display_defaults,
            base_engine=base_engine,
        )
        if derived_styles:
            merged["styles"] = derived_styles
    edit_config = _build_edit_config_from_definition(definition)
    if edit_config is not None:
        merged["editConfig"] = edit_config
    return merged


def _sort_surface_engines(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (deepcopy(engine) for engine in engines),
        key=lambda engine: int((engine.get("selector") or {}).get("sortOrder") or 100),
    )


def _normalize_renderable_engine(
    engine: dict[str, Any],
    *,
    task_key: str,
    task_surface: str | None,
    engine_row: dict[str, Any],
) -> dict[str, Any] | None:
    normalized = deepcopy(engine)
    surface_key = str(
        normalized.get("surface")
        or task_surface
        or _FALLBACK_TASK_META.get(task_key, {}).get("surface")
        or ""
    ).strip()
    if surface_key not in _SURFACE_KEYS:
        return None

    engine_id = str(normalized.get("engineId") or engine_row.get("public_engine_key") or engine_row.get("slug") or "").strip()
    engine_slug = str(normalized.get("engineSlug") or engine_row.get("slug") or "").strip()
    if not engine_id or not engine_slug:
        return None

    selector = deepcopy(normalized.get("selector") or {})
    display_name = str(
        engine_row.get("selector_title")
        or selector.get("title")
        or selector.get("pillLabel")
        or engine_row.get("name")
        or engine_slug
        or engine_id
    ).strip()
    selector["id"] = str(selector.get("id") or engine_id)
    selector["pillLabel"] = str(
        engine_row.get("selector_pill_label")
        or selector.get("pillLabel")
        or display_name
    )
    selector["title"] = str(
        engine_row.get("selector_title")
        or selector.get("title")
        or display_name
    )
    selector["description"] = str(
        engine_row.get("selector_description")
        or selector.get("description")
        or engine_row.get("description")
        or f"{display_name} engine"
    )
    if engine_row.get("selector_badge") is not None:
        selector["badge"] = engine_row.get("selector_badge")
    if engine_row.get("selector_image_key") is not None:
        selector["imageKey"] = engine_row.get("selector_image_key")
    if engine_row.get("selector_badge_image_key") is not None:
        selector["badgeImageKey"] = engine_row.get("selector_badge_image_key")

    normalized["surface"] = surface_key
    normalized["engineId"] = engine_id
    normalized["engineSlug"] = engine_slug
    normalized["selector"] = selector
    return normalized


def _finalize_engines_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ordered_engines = _sort_surface_engines(payload.get("engines") or [])
    default_engine_id = next(
        (str(engine.get("engineId")) for engine in ordered_engines if bool(engine.get("isDefault"))),
        str(payload.get("defaultEngineId") or "") or (
            str(ordered_engines[0].get("engineId")) if ordered_engines else ""
        ),
    )
    return {
        **payload,
        "defaultEngineId": default_engine_id or None,
        "engines": ordered_engines,
    }


def _fallback_tasks(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tasks = catalog.get("tasks") or []
    if raw_tasks:
        return deepcopy(raw_tasks)

    tasks: list[dict[str, Any]] = []
    for task_key, meta in _FALLBACK_TASK_META.items():
        surface_key = meta.get("surface")
        surface_payload = deepcopy(catalog.get(surface_key) or {"defaultEngineId": None, "engines": []})
        if task_key.endswith("/edited"):
            surface_payload = {"defaultEngineId": None, "engines": []}
        tasks.append(
            {
                "key": task_key,
                "name": meta["name"],
                "description": meta["description"],
                "surface": surface_key,
                "parentTaskKey": meta.get("parentTaskKey"),
                "displayDefaults": {},
                **surface_payload,
            }
        )
    return tasks


def _infer_task_key(engine_row: dict[str, Any], task_surface: str | None) -> str | None:
    explicit = str(engine_row.get("task_key") or "").strip()
    if explicit:
        return explicit
    task_type = str(engine_row.get("task_type") or "").strip()
    if task_type in _FALLBACK_TASK_META:
        return task_type
    labels = engine_row.get("labels") or {}
    surface_label = str(labels.get("surface") or "").strip().lower()
    if surface_label == "on-model":
        return "on-model"
    if surface_label == "pure-jewelry":
        return "pure-jewelry"
    surface_key = str(task_surface or "").strip()
    if surface_key == "onModel":
        return "on-model"
    if surface_key == "pureJewelry":
        return "pure-jewelry"
    return task_type or None


def _finalize_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    finalized = deepcopy(catalog)
    for surface_key in _SURFACE_KEYS:
        finalized[surface_key] = _finalize_engines_payload(finalized.get(surface_key) or {})
    finalized["tasks"] = [
        _finalize_engines_payload(task_payload)
        for task_payload in (finalized.get("tasks") or _fallback_tasks(finalized))
    ]
    finalized["fetchedAt"] = datetime.now(timezone.utc).isoformat()
    return finalized


def resolve_generation_ui_catalog(*, client: Any | None = None) -> dict[str, Any]:
    """Return the server-driven generation UI catalog.

    The DB-backed prompt registry is the source of truth. For older databases we
    merge any available published engines over the baked-in fallback catalog.
    """

    catalog = get_default_generation_ui_catalog()
    if client is None:
        return _finalize_catalog(catalog)

    try:
        engine_rows = client.table("prompt_engines").select("*").execute().data or []
    except Exception:
        return _finalize_catalog(catalog)

    task_rows: list[dict[str, Any]] = []
    task_rows_by_id: dict[str, dict[str, Any]] = {}
    try:
        task_rows = client.table("prompt_tasks").select("*").execute().data or []
    except Exception:
        task_rows = []
    if task_rows:
        task_rows_by_id = {str(row["id"]): row for row in task_rows if row.get("id")}

    published_version_ids = [
        str(row.get("active_version_id") or row.get("published_version_id"))
        for row in engine_rows
        if row.get("active_version_id") or row.get("published_version_id")
    ]
    versions_by_id: dict[str, dict[str, Any]] = {}
    if published_version_ids:
        try:
            version_rows = (
                client.table("prompt_engine_versions")
                .select("*")
                .in_("id", published_version_ids)
                .execute()
                .data
                or []
            )
        except Exception:
            version_rows = []
        versions_by_id = {str(row["id"]): row for row in version_rows if row.get("id")}

    use_fallback_catalog = not task_rows and not engine_rows
    surfaces: dict[str, dict[str, dict[str, Any]]] = (
        {
            key: {
                str(engine.get("engineId")): deepcopy(engine)
                for engine in (catalog.get(key) or {}).get("engines") or []
                if engine.get("engineId")
            }
            for key in _SURFACE_KEYS
        }
        if use_fallback_catalog
        else {key: {} for key in _SURFACE_KEYS}
    )
    tasks: dict[str, dict[str, Any]] = {}
    if use_fallback_catalog:
        for task in _fallback_tasks(catalog):
            tasks[str(task["key"])] = {
                "key": str(task["key"]),
                "name": str(task.get("name") or task["key"]),
                "description": task.get("description"),
                "surface": task.get("surface"),
                "parentTaskKey": task.get("parentTaskKey"),
                "defaultEngineId": task.get("defaultEngineId"),
                "engines": list(task.get("engines") or []),
            }

    if task_rows:
        key_by_task_id = {
            task_id: str(row.get("key") or "")
            for task_id, row in task_rows_by_id.items()
        }
        for row in task_rows:
            task_id = str(row.get("id") or "")
            task_key = str(row.get("key") or "").strip()
            if not task_key:
                continue
            parent_task_id = str(row.get("parent_task_id") or "").strip()
            tasks[task_key] = {
                "key": task_key,
                "name": str(row.get("name") or task_key),
                "description": row.get("description"),
                "surface": row.get("surface"),
                "parentTaskKey": key_by_task_id.get(parent_task_id) if parent_task_id else None,
                "displayDefaults": row.get("display_defaults") or {},
                "defaultEngineId": tasks.get(task_key, {}).get("defaultEngineId"),
                "engines": list(tasks.get(task_key, {}).get("engines") or []),
            }

    for engine_row in engine_rows:
        published_version_id = engine_row.get("active_version_id") or engine_row.get("published_version_id")
        version_row = versions_by_id.get(str(published_version_id))
        if not version_row:
            continue
        definition = version_row.get("definition") or {}
        task_row = task_rows_by_id.get(str(engine_row.get("task_id")) or "", {}) if task_rows_by_id else {}
        surface_key = str(task_row.get("surface") or _FALLBACK_TASK_META.get(str(task_row.get("key") or ""), {}).get("surface") or "").strip()
        task_key = str(
            (
                task_row.get("key")
                if task_rows_by_id
                else None
            )
            or _infer_task_key(engine_row, surface_key or None)
            or ""
        ).strip()
        engine_id = str(engine_row.get("public_engine_key") or engine_row.get("slug") or "").strip()
        if not engine_id:
            continue

        existing_task_engine = next(
            (
                engine
                for engine in (tasks.get(task_key, {}).get("engines") or [])
                if str(engine.get("engineId")) == engine_id
            ),
            {},
        )
        base_engine = (surfaces.get(surface_key, {}) or {}).get(engine_id) or existing_task_engine or {}
        merged_engine = deepcopy(base_engine)
        merged_engine["taskKey"] = task_key or None
        merged_engine["engineId"] = engine_id
        merged_engine["publicEngineKey"] = engine_id
        merged_engine["engineSlug"] = str(engine_row.get("slug") or merged_engine.get("engineSlug") or "")
        merged_engine["publicVersionKey"] = str(
            version_row.get("public_version_key")
            or ""
        ).strip() or None
        merged_engine["isUserSelectable"] = bool(
            engine_row.get("is_user_selectable", merged_engine.get("isUserSelectable", True))
        )
        selector = merged_engine.get("selector") or {}
        if selector and not selector.get("id"):
            selector["id"] = engine_id
        if not selector.get("sortOrder") and engine_row.get("sort_order") is not None:
            selector["sortOrder"] = int(engine_row.get("sort_order") or 100)
        merged_engine["selector"] = selector
        if task_key:
            task_payload = tasks.setdefault(
                task_key,
                {
                    "key": task_key,
                    "name": _FALLBACK_TASK_META.get(task_key, {}).get("name", task_key),
                    "description": _FALLBACK_TASK_META.get(task_key, {}).get("description"),
                    "surface": surface_key or _FALLBACK_TASK_META.get(task_key, {}).get("surface"),
                    "parentTaskKey": _FALLBACK_TASK_META.get(task_key, {}).get("parentTaskKey"),
                    "displayDefaults": {},
                    "defaultEngineId": None,
                    "engines": [],
                },
            )
            task_payload["surface"] = task_payload.get("surface") or surface_key or None
            merged_engine = _apply_definition_surface_overrides(
                engine=merged_engine,
                definition=definition if isinstance(definition, dict) else {},
                task_payload=task_payload,
                surface_key=str(task_payload.get("surface") or surface_key or "").strip(),
                base_engine=base_engine,
            )
            normalized_engine = _normalize_renderable_engine(
                merged_engine,
                task_key=task_key,
                task_surface=str(task_payload.get("surface") or "").strip() or None,
                engine_row=engine_row,
            )
            if normalized_engine is None:
                continue
            existing_task_engines = {
                str(engine.get("engineId")): engine for engine in task_payload.get("engines") or [] if engine.get("engineId")
            }
            existing_task_engines[engine_id] = normalized_engine
            task_payload["engines"] = list(existing_task_engines.values())
            if normalized_engine.get("isDefault"):
                task_payload["defaultEngineId"] = engine_id
        merged_engine = _apply_definition_surface_overrides(
            engine=merged_engine,
            definition=definition if isinstance(definition, dict) else {},
            task_payload=tasks.get(task_key, {}) if task_key else {},
            surface_key=surface_key or "",
            base_engine=base_engine,
        )
        normalized_engine = _normalize_renderable_engine(
            merged_engine,
            task_key=task_key,
            task_surface=surface_key or None,
            engine_row=engine_row,
        )
        if (
            normalized_engine is not None
            and normalized_engine["surface"] in surfaces
            and normalized_engine.get("isUserSelectable", True)
        ):
            surfaces[normalized_engine["surface"]][engine_id] = normalized_engine

    catalog["onModel"]["engines"] = list(surfaces["onModel"].values())
    catalog["pureJewelry"]["engines"] = list(surfaces["pureJewelry"].values())
    catalog["tasks"] = list(tasks.values())
    return _finalize_catalog(catalog)
