"""Helpers for resolving the public generation UI catalog."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .ui_defaults import get_default_generation_ui_catalog

_SURFACE_KEYS = ("onModel", "pureJewelry")


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {key: deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return deepcopy(override)


def _sort_surface_engines(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (deepcopy(engine) for engine in engines),
        key=lambda engine: int((engine.get("selector") or {}).get("sortOrder") or 100),
    )


def _finalize_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    finalized = deepcopy(catalog)
    for surface_key in _SURFACE_KEYS:
        surface = finalized.get(surface_key) or {}
        ordered_engines = _sort_surface_engines(surface.get("engines") or [])
        default_engine_id = next(
            (str(engine.get("engineId")) for engine in ordered_engines if bool(engine.get("isDefault"))),
            str(surface.get("defaultEngineId") or "") or (
                str(ordered_engines[0].get("engineId")) if ordered_engines else ""
            ),
        )
        finalized[surface_key] = {
            "defaultEngineId": default_engine_id,
            "engines": ordered_engines,
        }
    finalized["fetchedAt"] = datetime.now(timezone.utc).isoformat()
    return finalized


def resolve_generation_ui_catalog(*, client: Any | None = None) -> dict[str, Any]:
    """Return the server-driven generation UI catalog.

    The DB-backed prompt registry is the source of truth when published versions
    carry a ``definition.ui`` block. For older databases we merge any available
    published UI blocks over the baked-in fallback catalog.
    """

    catalog = get_default_generation_ui_catalog()
    if client is None:
        return _finalize_catalog(catalog)

    try:
        engine_rows = client.table("prompt_engines").select("*").execute().data or []
    except Exception:
        return _finalize_catalog(catalog)

    published_version_ids = [
        str(row.get("published_version_id"))
        for row in engine_rows
        if row.get("published_version_id")
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

    surfaces: dict[str, dict[str, dict[str, Any]]] = {
        key: {
            str(engine.get("engineId")): deepcopy(engine)
            for engine in (catalog.get(key) or {}).get("engines") or []
            if engine.get("engineId")
        }
        for key in _SURFACE_KEYS
    }

    for engine_row in engine_rows:
        published_version_id = engine_row.get("published_version_id")
        version_row = versions_by_id.get(str(published_version_id))
        if not version_row:
            continue
        definition = version_row.get("definition") or {}
        ui_block = definition.get("ui") or {}
        surface_key = str(ui_block.get("surface") or "").strip()
        engine_id = str(ui_block.get("engineId") or "").strip()
        if surface_key not in surfaces or not engine_id:
            continue

        merged_engine = _deep_merge(surfaces[surface_key].get(engine_id) or {}, ui_block)
        merged_engine["engineSlug"] = str(engine_row.get("slug") or merged_engine.get("engineSlug") or "")
        selector = merged_engine.get("selector") or {}
        if selector and not selector.get("id"):
            selector["id"] = engine_id
        merged_engine["selector"] = selector
        surfaces[surface_key][engine_id] = merged_engine

    catalog["onModel"]["engines"] = list(surfaces["onModel"].values())
    catalog["pureJewelry"]["engines"] = list(surfaces["pureJewelry"].values())
    return _finalize_catalog(catalog)
