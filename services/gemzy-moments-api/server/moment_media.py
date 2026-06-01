"""Helpers for env-driven moment media availability."""
from __future__ import annotations

import os

MomentMediaMode = str

_MEDIA_MODE_ALIASES = {
    "photo": "photos",
    "photos": "photos",
    "video": "videos",
    "videos": "videos",
    "both": "both",
}


def get_moment_media_mode() -> MomentMediaMode:
    raw = os.getenv("MOMENTS_MEDIA_MODE", "photos").strip().lower()
    return _MEDIA_MODE_ALIASES.get(raw, "photos")


def get_available_moment_media() -> list[str]:
    mode = get_moment_media_mode()
    if mode == "videos":
        return ["video"]
    if mode == "both":
        return ["photo", "video"]
    return ["photo"]


def build_generation_capabilities() -> dict[str, object]:
    return {
        "mode": get_moment_media_mode(),
        "available_media": get_available_moment_media(),
    }


def attach_generation_capabilities(record: dict | None) -> dict | None:
    if record is None:
        return None
    record["generation_capabilities"] = build_generation_capabilities()
    return record
