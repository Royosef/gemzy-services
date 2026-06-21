"""Background generation worker for Gemzy Moments.

Polls `moments.generation_jobs` for queued jobs, builds a prompt from
the moment's world context, forwards to the generation server, and
stores result URLs back into the job record.

Follows the same auth pattern as Gemzy Core's generations.py:
  - GENERATION_SERVER_URL + /generate-sync endpoint
  - GENERATION_SHARED_SECRET header auth
  - GENERATION_CALLBACK_URL for async callbacks

Lifecycle:
  1. Startup: launched as asyncio background task from main.py
  2. Poll: every POLL_INTERVAL_SECONDS, query for queued jobs
  3. Process: for each job, build prompt → call generation server → store results
  4. Shutdown: cancelled gracefully on app shutdown
"""
from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import os
from datetime import datetime, timezone

import httpx
from postgrest.exceptions import APIError

from . import storage
from .supabase_client import get_client

logger = logging.getLogger(__name__)

MOMENTS_SCHEMA = "moments"
PEOPLE_SCHEMA = "people"

# How often to poll for new jobs (seconds)
POLL_INTERVAL = float(os.getenv("GENERATION_POLL_SECONDS", "10"))

# Max concurrent generation jobs
MAX_CONCURRENT = int(os.getenv("GENERATION_MAX_CONCURRENT", "3"))

# Max retry attempts per job before marking as failed
MAX_ATTEMPTS = int(os.getenv("GENERATION_MAX_ATTEMPTS", "3"))
REFERENCE_IMAGE_TIMEOUT = float(os.getenv("GENERATION_REFERENCE_IMAGE_TIMEOUT", "20"))
REFERENCE_IMAGE_MAX_BYTES = int(os.getenv("GENERATION_REFERENCE_IMAGE_MAX_BYTES", str(10 * 1024 * 1024)))
_REFERENCE_ASSETS_AVAILABLE: bool | None = None


def _db():
    return get_client()


def _is_reference_assets_missing_error(exc: Exception) -> bool:
    if isinstance(exc, APIError):
        code = str(getattr(exc, "code", "") or "")
        message = str(getattr(exc, "message", "") or "")
        if not message and hasattr(exc, "json"):
            try:
                payload = exc.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                code = code or str(payload.get("code") or "")
                message = str(payload.get("message") or "")
        return code == "PGRST205" and "reference_assets" in message

    payload = exc.args[0] if exc.args else None
    if isinstance(payload, dict):
        code = str(payload.get("code") or "")
        message = str(payload.get("message") or "")
        return code == "PGRST205" and "reference_assets" in message

    return False


def _reference_assets_enabled() -> bool:
    return _REFERENCE_ASSETS_AVAILABLE is not False


def _disable_reference_assets(exc: Exception) -> None:
    global _REFERENCE_ASSETS_AVAILABLE
    if _is_reference_assets_missing_error(exc):
        if _REFERENCE_ASSETS_AVAILABLE is not False:
            logger.warning(
                "people.reference_assets is unavailable in this environment; skipping reference asset lookups and promotions"
            )
        _REFERENCE_ASSETS_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
#  PROMPT BUILDER
# ═══════════════════════════════════════════════════════════

_PHONE_REALISM_BY_CAMERA_TYPE: dict[str, list[str]] = {
    "front_selfie": [
        "23mm-equivalent front-camera perspective with slight wide-angle distortion near the lens",
        "casual handheld framing with tiny tilt and imperfect centering",
        "iPhone-style color science and realistic phone processing, not glossy editorial polish",
    ],
    "mirror_selfie": [
        "rear-phone-camera mirror capture with realistic handheld tilt",
        "ambient room light with believable mirror imperfections",
        "natural phone-camera dynamic range with slight highlight lift and soft shadow detail",
    ],
    "pov_holding_object": [
        "first-person phone snapshot with hands entering from the lower frame edge",
        "small-sensor focus behavior and believable near-field emphasis",
        "casual handheld capture rather than a styled product photograph",
    ],
    "environment_only": [
        "quick iPhone environment snapshot with slight off-axis tilt",
        "phone HDR behavior with natural highlights and mild shadow lift",
        "grabbed in passing, not composed like a magazine shoot",
    ],
    "friend_captured": [
        "casual friend-shot iPhone framing from conversational distance",
        "ambient light and candid social snapshot energy",
        "natural handheld imperfection, not professional portrait polish",
    ],
    "default": [
        "phone-camera realism with natural contrast and handheld imperfection",
        "real-world smartphone framing rather than editorial composition",
        "authentic social-media capture, not a stylized AI beauty shot",
    ],
}

_IMPERFECTION_BY_CAMERA_TYPE: dict[str, list[str]] = {
    "front_selfie": [
        "slightly imperfect framing with the head a touch off-center",
        "natural skin texture and flyaway hair, no beauty filter",
    ],
    "mirror_selfie": [
        "a few mirror smudges or fingerprints near the edge",
        "freehand phone tilt of a few degrees, not tripod-straight symmetry",
    ],
    "pov_holding_object": [
        "tiny handheld angle inconsistency",
        "a natural in-passing feel instead of product-shot precision",
    ],
    "environment_only": [
        "slight accidental tilt and casual composition",
        "a real snapshot register rather than a curated editorial setup",
    ],
    "friend_captured": [
        "imperfect candid framing with mild breathing-room imbalance",
        "natural expression and posture instead of a polished influencer pose",
    ],
    "default": [
        "small framing imperfections that keep the image believable",
        "natural texture and no magazine-perfect polish",
    ],
}

_FORBIDDEN_BY_CAMERA_TYPE: dict[str, list[str]] = {
    "front_selfie": [
        "third-person observer composition",
        "a second camera implied outside the selfie device",
        "the phone fully visible as if someone else photographed the selfie",
    ],
    "mirror_selfie": [
        "two phones anywhere in the image",
        "observer view of someone standing in front of a mirror",
        "the phone visible anywhere except the mirror reflection",
    ],
    "pov_holding_object": [
        "face visible in frame",
        "over-the-shoulder composition",
        "another person holding the object for the persona",
    ],
    "environment_only": [
        "the persona appearing in frame",
        "editorial magazine styling",
        "tripod-perfect symmetry",
    ],
    "friend_captured": [
        "professional portrait framing",
        "magazine editorial posing",
        "studio-photographer polish",
    ],
    "default": [
        "editorial perfection",
        "over-polished beauty-shot styling",
        "generic AI glamour language",
    ],
}


def _normalize_camera_type(value: str | None) -> str:
    raw = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "selfie": "front_selfie",
        "front_selfie_3_4": "front_selfie",
        "front_selfie_three_quarter": "front_selfie",
        "mirror": "mirror_selfie",
        "mirror_selfie_full_body": "mirror_selfie",
        "mirror_selfie_torso_only": "mirror_selfie",
        "pov": "pov_holding_object",
        "pov_holding": "pov_holding_object",
        "environment": "environment_only",
        "friend_capture": "friend_captured",
    }
    return aliases.get(raw, raw or "default")


def _planner_prompt_spec(context: dict | None) -> dict:
    if not context:
        return {}
    outfit_composition = context.get("outfit_composition") or {}
    if not isinstance(outfit_composition, dict):
        return {}
    spec = outfit_composition.get("planner_prompt_spec") or {}
    return spec if isinstance(spec, dict) else {}


def _camera_opening_line(camera_type: str, camera_perspective: str | None, persona_name: str) -> str:
    if camera_perspective:
        return str(camera_perspective)
    if camera_type == "front_selfie":
        return f"Smartphone front-camera selfie. The viewer's perspective IS {persona_name}'s phone screen held at arm's length."
    if camera_type == "mirror_selfie":
        return f"Mirror selfie captured on {persona_name}'s phone rear camera. The image IS the mirror reflection from that single phone, visible in reflection only."
    if camera_type == "pov_holding_object":
        return f"First-person POV. The viewer's eye IS {persona_name}'s eye and the image shows what {persona_name}'s phone captured in that moment."
    if camera_type == "environment_only":
        return f"Casual phone snapshot. {persona_name} is not in frame; this is the environment their phone captured in passing."
    if camera_type == "friend_captured":
        return f"Casual iPhone photo taken by {persona_name}'s friend from the friend's point of view."
    return f"Natural smartphone photo of {persona_name} captured as a believable social-media moment."


def _format_and_ui_constraints(moment_type: str) -> list[str]:
    if moment_type == "POST":
        return [
            "Aspect Ratio: square 1:1 image intended as a hero Instagram post.",
            "Composition: polished but still phone-native and believable, not a magazine-perfect editorial.",
            "Critical UI restriction: do not render any platform UI, captions, buttons, top bars, phone frames, or interface chrome.",
        ]
    return [
        "Aspect Ratio: vertical 9:16 image intended as a Story.",
        "Composition: immersive and casual, with room for future overlays but no visible interface elements.",
        "Critical UI restriction: do not render any platform UI, progress bars, names, captions, reply fields, stickers, or interface chrome.",
    ]


def _build_prompt_from_context(
    moment: dict,
    context: dict | None,
    persona: dict | None,
    location: dict | None,
    wardrobe_items: list[dict] | None,
) -> str:
    """Build a generation prompt from moment + world context."""
    prompt_spec = _planner_prompt_spec(context)
    moment_type = moment.get("moment_type", "STORY")
    caption = str(moment.get("caption_hint") or "").strip()
    persona_name = (persona or {}).get("display_name") or "the persona"
    camera_type = _normalize_camera_type(prompt_spec.get("camera_type"))
    scene = str(prompt_spec.get("scene") or caption).strip()
    light = str(prompt_spec.get("light") or "").strip()
    moment_reasoning = str(prompt_spec.get("moment_reasoning") or "").strip()
    arc_id = str(prompt_spec.get("arc_id") or "").strip()

    sections: list[str] = [
        _camera_opening_line(camera_type, prompt_spec.get("camera_perspective"), persona_name),
        "\n".join(_format_and_ui_constraints(moment_type)),
        "Final requirement: output only the photographic or designed asset itself. No visible app UI, interface chrome, or overlaid interface text.",
    ]

    identity_lines = [f"PERSONA LOCK: {persona_name}."]
    if persona and persona.get("bio"):
        identity_lines.append(f"Persona context: {persona.get('bio')}")
    if arc_id:
        identity_lines.append(f"Continuity anchor: same day and same arc ({arc_id}) unless the scene clearly indicates a transition.")
    sections.append("\n".join(identity_lines))

    scene_lines: list[str] = []
    if scene:
        scene_lines.append(f"SCENE: {scene}")
    if location:
        if location.get("name"):
            scene_lines.append(f"Location: {location.get('name')}")
        loc_tags = [str(tag) for tag in (location.get("tags") or []) if str(tag).strip()]
        if loc_tags:
            scene_lines.append(f"Location traits: {', '.join(loc_tags)}")
        if location.get("description"):
            scene_lines.append(f"Location description: {location.get('description')}")
        if location.get("visual_notes"):
            scene_lines.append(f"Location visual notes: {location.get('visual_notes')}")
        if location.get("lighting_notes"):
            scene_lines.append(f"Location lighting notes: {location.get('lighting_notes')}")
    if scene_lines:
        sections.append("\n".join(scene_lines))

    outfit_lines: list[str] = []
    if wardrobe_items:
        outfit_desc: list[str] = []
        for item in wardrobe_items:
            cat = item.get("category", "")
            name = item.get("name", "")
            tags = [str(tag) for tag in (item.get("tags") or []) if str(tag).strip()]
            desc = f"{name} ({cat})" if cat else name
            if tags:
                desc += f" [{', '.join(tags)}]"
            if item.get("description"):
                desc += f" - {item.get('description')}"
            outfit_desc.append(desc)
        if outfit_desc:
            outfit_lines.append(f"OUTFIT BLOCK: {'; '.join(outfit_desc)}")
            outfit_lines.append("Keep the outfit stable within this arc unless the scene explicitly signals a wardrobe change.")
    if outfit_lines:
        sections.append("\n".join(outfit_lines))

    light_and_mood: list[str] = []
    if light:
        light_and_mood.append(f"LIGHT: {light}")
    if context and context.get("mood_tags"):
        light_and_mood.append(f"MOOD: {', '.join(context.get('mood_tags') or [])}")
    if moment_reasoning:
        light_and_mood.append(f"Shot intent: {moment_reasoning}")
    if light_and_mood:
        sections.append("\n".join(light_and_mood))

    if context and context.get("continuity_notes"):
        sections.append(
            "CONTINUITY: "
            f"{context.get('continuity_notes')}. Preserve same day, same person, same hair, same makeup, and same outfit whenever the continuity notes imply a continuous arc."
        )

    style = _fetch_style_profile(persona["id"]) if persona else None
    realism_lines = [
        "PHONE REALISM: " + "; ".join(_PHONE_REALISM_BY_CAMERA_TYPE.get(camera_type, _PHONE_REALISM_BY_CAMERA_TYPE["default"])),
        "IMPERFECTIONS: " + "; ".join(_IMPERFECTION_BY_CAMERA_TYPE.get(camera_type, _IMPERFECTION_BY_CAMERA_TYPE["default"])),
    ]
    forbidden_phrases = list(_FORBIDDEN_BY_CAMERA_TYPE.get(camera_type, _FORBIDDEN_BY_CAMERA_TYPE["default"]))
    if style:
        realism_lines.append(f"Realism level: {style.get('realism_level', 'high')}")
        cam_tags = [str(tag) for tag in (style.get("camera_style_tags") or []) if str(tag).strip()]
        if cam_tags:
            realism_lines.append(f"Style camera tags: {', '.join(cam_tags)}")
        palette = [str(tag) for tag in (style.get("color_palette_tags") or []) if str(tag).strip()]
        if palette:
            realism_lines.append(f"Palette tags: {', '.join(palette)}")
        forbidden_phrases.extend(str(tag) for tag in (style.get("negative_rules") or []) if str(tag).strip())
    sections.append("\n".join(realism_lines))

    forbidden_phrases.extend(
        [
            "masterpiece",
            "8k glamour look",
            "magazine editorial perfection",
            "beauty-filter skin smoothing",
        ]
    )
    sections.append("FORBIDDEN / NEGATIVE CONSTRAINTS: " + "; ".join(dict.fromkeys(forbidden_phrases)))

    return "\n\n".join(section for section in sections if section) or "Generate a believable social media phone photo"


def _fetch_style_profile(persona_id: str) -> dict | None:
    """Fetch the style profile for a persona."""
    try:
        result = (
            _db()
            .schema(PEOPLE_SCHEMA)
            .table("persona_style_profile")
            .select("*")
            .eq("persona_id", persona_id)
            .maybe_single()
            .execute()
        )
        return result.data
    except Exception:
        logger.warning("Failed to fetch style profile for persona %s", persona_id)
        return None


def _normalize_image_mime_type(content_type: str | None, source_url: str | None = None) -> str:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if mime_type.startswith("image/"):
        return mime_type

    if source_url and source_url.startswith("data:image/"):
        return source_url[len("data:"):].split(";", 1)[0].strip().lower()

    guessed, _ = mimetypes.guess_type(source_url or "")
    if guessed and guessed.startswith("image/"):
        return guessed

    return "image/jpeg"


def _resolve_fetchable_image_url(url: str | None) -> str | None:
    if not url or "storage.googleapis.com/" not in url:
        return url

    try:
        _, path = url.split("storage.googleapis.com/", 1)
        bucket_name, blob_name = path.split("/", 1)
        bucket = storage.get_bucket(bucket_name, None)
        blob = bucket.blob(blob_name)
        return storage.generate_signed_read_url_v4(blob, seconds=900)
    except Exception as exc:
        logger.warning("Failed to sign reference image URL %s: %s", url[:200], exc)
        return url


async def _download_reference_image(url: str | None) -> tuple[bytes, str] | None:
    if not url:
        return None

    try:
        if url.startswith("data:image/") and ";base64," in url:
            header, encoded = url.split(",", 1)
            mime_type = header[len("data:"):].split(";", 1)[0].strip().lower() or "image/jpeg"
            return base64.b64decode(encoded), mime_type

        fetch_url = _resolve_fetchable_image_url(url)
        if not fetch_url:
            return None
        async with httpx.AsyncClient(timeout=REFERENCE_IMAGE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(fetch_url)
        response.raise_for_status()

        image_bytes = response.content
        if not image_bytes:
            return None
        if len(image_bytes) > REFERENCE_IMAGE_MAX_BYTES:
            logger.warning("Reference image too large to include (%d bytes): %s", len(image_bytes), url[:200])
            return None

        mime_type = _normalize_image_mime_type(response.headers.get("content-type"), fetch_url)
        return image_bytes, mime_type
    except Exception as exc:
        logger.warning("Failed to fetch reference image from %s: %s", url[:200], exc)
        return None


def _fetch_reference_asset(asset_id: str | None) -> dict | None:
    if not asset_id or not _reference_assets_enabled():
        return None

    try:
        result = (
            _db()
            .schema(PEOPLE_SCHEMA)
            .table("reference_assets")
            .select("*")
            .eq("id", asset_id)
            .maybe_single()
            .execute()
        )
        return result.data
    except Exception as exc:
        _disable_reference_assets(exc)
        if not _reference_assets_enabled():
            return None
        logger.exception("Failed to fetch reference asset %s", asset_id)
        return None


def _list_persona_reference_assets(persona_id: str, limit: int = 3) -> list[dict]:
    if not _reference_assets_enabled():
        return []

    try:
        result = (
            _db()
            .schema(PEOPLE_SCHEMA)
            .table("reference_assets")
            .select("*")
            .eq("persona_id", persona_id)
            .eq("asset_kind", "persona")
            .eq("is_active", True)
            .order("is_canonical", desc=True)
            .order("consistency_score", desc=True)
            .order("quality_score", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        _disable_reference_assets(exc)
        if not _reference_assets_enabled():
            return []
        logger.exception("Failed to list persona reference assets for %s", persona_id)
        return []


async def _resolve_generation_references(
    persona: dict | None,
    location: dict | None,
    wardrobe_items: list[dict] | None,
) -> tuple[tuple[bytes, str] | None, list[tuple[bytes, str]]]:
    model_image: tuple[bytes, str] | None = None
    reference_images: list[tuple[bytes, str]] = []

    if persona:
        persona_assets = _list_persona_reference_assets(persona["id"], limit=3)
        for index, asset in enumerate(persona_assets):
            resolved = await _download_reference_image(asset.get("storage_url"))
            if not resolved:
                continue
            if index == 0 and model_image is None:
                model_image = resolved
            else:
                reference_images.append(resolved)

        if model_image is None:
            model_image = await _download_reference_image(persona.get("avatar_url"))

    if location and location.get("ref_asset_id"):
        location_asset = _fetch_reference_asset(location.get("ref_asset_id"))
        resolved_location = await _download_reference_image(location_asset.get("storage_url") if location_asset else None)
        if resolved_location:
            reference_images.append(resolved_location)

    if wardrobe_items:
        for item in wardrobe_items:
            if not item.get("ref_asset_id"):
                continue
            asset = _fetch_reference_asset(item.get("ref_asset_id"))
            resolved_item = await _download_reference_image(asset.get("storage_url") if asset else None)
            if resolved_item:
                reference_images.append(resolved_item)
            if len(reference_images) >= 4:
                break

    return model_image, reference_images[:4]


def _promote_reference_assets(
    *,
    moment: dict,
    context: dict | None,
    persona: dict | None,
    location: dict | None,
    result_urls: list[str],
    job_id: str,
) -> None:
    if not persona or not result_urls or not _reference_assets_enabled():
        return

    primary_url = next((url for url in result_urls if url), None)
    if not primary_url:
        return

    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "moment_type": moment.get("moment_type"),
        "caption_hint": moment.get("caption_hint"),
        "mood_tags": (context or {}).get("mood_tags", []),
    }

    try:
        existing_persona_assets = _list_persona_reference_assets(persona["id"], limit=1)
        persona_asset_result = (
            db.schema(PEOPLE_SCHEMA)
            .table("reference_assets")
            .insert({
                "persona_id": persona["id"],
                "asset_kind": "persona",
                "source_kind": "generation",
                "storage_url": primary_url,
                "mime_type": _normalize_image_mime_type(None, primary_url),
                "origin_moment_id": moment.get("id"),
                "origin_job_id": job_id,
                "quality_score": 0.6,
                "consistency_score": 0.75,
                "metadata_json": metadata,
                "updated_at": now,
            })
            .execute()
        )

        if not existing_persona_assets:
            asset_id = persona_asset_result.data[0]["id"]
            db.schema(PEOPLE_SCHEMA).table("reference_assets").update({
                "is_canonical": True,
                "updated_at": now,
            }).eq("id", asset_id).execute()
    except Exception as exc:
        _disable_reference_assets(exc)
        if not _reference_assets_enabled():
            return
        logger.exception("Failed to promote persona reference asset for moment %s", moment.get("id"))

    if not location:
        return

    try:
        location_asset_result = (
            db.schema(PEOPLE_SCHEMA)
            .table("reference_assets")
            .insert({
                "persona_id": persona["id"],
                "asset_kind": "location",
                "source_kind": "generation",
                "storage_url": primary_url,
                "mime_type": _normalize_image_mime_type(None, primary_url),
                "origin_moment_id": moment.get("id"),
                "origin_job_id": job_id,
                "location_id": location.get("id"),
                "quality_score": 0.5,
                "consistency_score": 0.55,
                "metadata_json": metadata,
                "updated_at": now,
            })
            .execute()
        )
        location_asset_id = location_asset_result.data[0]["id"]
        db.schema(PEOPLE_SCHEMA).table("world_locations").update({
            "ref_asset_id": location_asset_id,
        }).eq("id", location.get("id")).execute()
    except Exception as exc:
        _disable_reference_assets(exc)
        if not _reference_assets_enabled():
            return
        logger.exception("Failed to promote location reference asset for location %s", location.get("id"))


# ═══════════════════════════════════════════════════════════
#  CONTEXT FETCHER
# ═══════════════════════════════════════════════════════════

def _fetch_moment_with_context(job: dict) -> tuple[dict, dict | None, dict | None, dict | None, list[dict] | None]:
    """Fetch the moment, its context, persona, location, and wardrobe items.

    Returns (moment, context, persona, location, wardrobe_items)
    """
    moment_id = job["moment_id"]
    db = _db()

    # Fetch moment
    moment = (
        db.schema(MOMENTS_SCHEMA)
        .table("moments")
        .select("*, content_plans!inner(persona_id, owner_user_id)")
        .eq("id", moment_id)
        .single()
        .execute()
    ).data

    if not moment:
        return {}, None, None, None, None

    plan = moment.pop("content_plans", {})
    persona_id = plan.get("persona_id")

    # Fetch context
    context = (
        db.schema(MOMENTS_SCHEMA)
        .table("moment_context")
        .select("*")
        .eq("moment_id", moment_id)
        .maybe_single()
        .execute()
    ).data

    # Fetch persona
    persona = None
    if persona_id:
        try:
            persona = (
                db.schema(PEOPLE_SCHEMA)
                .table("personas")
                .select("*")
                .eq("id", persona_id)
                .single()
                .execute()
            ).data
        except Exception:
            logger.warning("Failed to fetch persona %s", persona_id)

    # Fetch location
    location = None
    if context and context.get("location_id"):
        try:
            location = (
                db.schema(PEOPLE_SCHEMA)
                .table("world_locations")
                .select("*")
                .eq("id", context["location_id"])
                .single()
                .execute()
            ).data
        except Exception:
            logger.warning("Failed to fetch location %s", context["location_id"])

    # Fetch wardrobe items
    wardrobe_items = None
    if context and context.get("wardrobe_item_ids"):
        item_ids = context["wardrobe_item_ids"]
        if item_ids:
            try:
                wardrobe_items = (
                    db.schema(PEOPLE_SCHEMA)
                    .table("world_wardrobe_items")
                    .select("*")
                    .in_("id", item_ids)
                    .execute()
                ).data
            except Exception:
                logger.warning("Failed to fetch wardrobe items")

    return moment, context, persona, location, wardrobe_items


# ═══════════════════════════════════════════════════════════
#  GENERATION SERVER INTEGRATION
# ═══════════════════════════════════════════════════════════

def _get_generation_url() -> str | None:
    """Get the generation server URL from env."""
    base = os.getenv("GENERATION_SERVER_URL", "").strip()
    if not base:
        return None
    # Moments uses the generation server's synchronous API, not the queued
    # callback-based `/generate` contract used by the core app.
    endpoint = os.getenv("GENERATION_SERVER_ENDPOINT", "/generate-sync").strip()
    if not endpoint:
        endpoint = "/generate-sync"
    base = base.rstrip("/")
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"
    return f"{base}{endpoint}"


async def _call_generation_server(
    prompt: str,
    image_count: int,
    moment_type: str,
    model_image: tuple[bytes, str] | None = None,
    reference_images: list[tuple[bytes, str]] | None = None,
) -> list[str]:
    """Call the generation server and return a list of result URLs.

    If the generation server is not configured, returns placeholder URLs
    for development purposes.
    """
    gen_url = _get_generation_url()

    if not gen_url:
        logger.warning("GENERATION_SERVER_URL not configured; returning placeholder URLs")
        return [f"https://placehold.co/600x{'1067' if moment_type == 'STORY' else '600'}/2a2a2a/white?text=Moment+{i+1}"
                for i in range(image_count)]

    shared_secret = os.getenv("GENERATION_SHARED_SECRET", "").strip()
    timeout = float(os.getenv("GENERATION_SERVER_TIMEOUT", "120"))

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if shared_secret:
        headers["X-Generation-Secret"] = shared_secret

    payload = {
        "prompt": prompt,
        "num_images": image_count,
        "aspect_ratio": "9:16" if moment_type == "STORY" else "1:1",
        "quality": "high",
    }
    if model_image:
        model_bytes, model_mime_type = model_image
        payload["model_image_base64"] = base64.b64encode(model_bytes).decode("utf-8")
        payload["model_image_mime_type"] = model_mime_type
    if reference_images:
        payload["reference_images_base64"] = [
            base64.b64encode(image_bytes).decode("utf-8")
            for image_bytes, _ in reference_images
        ]
        payload["reference_image_mime_types"] = [mime_type for _, mime_type in reference_images]

    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            response = await http_client.post(gen_url, json=payload, headers=headers)

        if response.status_code >= 400:
            logger.error(
                "Generation server returned %d: %s",
                response.status_code,
                response.text[:200],
            )
            return []

        data = response.json()

        # Support multiple response formats
        if isinstance(data, dict):
            # { "results": [{"url": "..."}, ...] }
            if "results" in data:
                return [r.get("url", "") for r in data["results"] if r.get("url")]
            # { "urls": ["...", ...] }
            if "urls" in data:
                return data["urls"]
            # { "url": "..." } (single image)
            if "url" in data:
                return [data["url"]]
        elif isinstance(data, list):
            # [{"url": "..."}, ...] or ["...", ...]
            urls = []
            for item in data:
                if isinstance(item, dict):
                    urls.append(item.get("url", ""))
                elif isinstance(item, str):
                    urls.append(item)
            return [u for u in urls if u]

        logger.error("Unexpected generation response format: %s", type(data))
        return []

    except httpx.RequestError as exc:
        logger.error("Failed to reach generation server: %s", exc)
        return []
    except Exception:
        logger.exception("Unexpected error calling generation server")
        return []


# ═══════════════════════════════════════════════════════════
#  JOB PROCESSING
# ═══════════════════════════════════════════════════════════

async def _process_job(job: dict) -> None:
    """Process a single generation job.

    Steps:
      1. Mark job as 'running'
      2. Fetch moment + context
      3. Build prompt
      4. Call generation server
      5. Store result URLs + mark 'done' or 'failed'
    """
    job_id = job["id"]
    moment_id = job["moment_id"]
    db = _db()
    now = datetime.now(timezone.utc).isoformat()

    logger.info("Processing generation job %s for moment %s", job_id, moment_id)

    # Mark as running
    db.schema(MOMENTS_SCHEMA).table("generation_jobs").update({
        "status": "running",
        "started_at": now,
        "attempts": job.get("attempts", 0) + 1,
    }).eq("id", job_id).execute()

    try:
        # Fetch all context
        moment, context, persona, location, wardrobe_items = _fetch_moment_with_context(job)
        if not moment:
            raise ValueError(f"Moment {moment_id} not found")

        # Build prompt
        prompt = _build_prompt_from_context(moment, context, persona, location, wardrobe_items)
        logger.info("Built prompt for job %s:\n%s", job_id, prompt[:200])

        model_image, reference_images = await _resolve_generation_references(
            persona,
            location,
            wardrobe_items,
        )

        # Call generation server
        image_count = moment.get("image_count", 1)
        moment_type = moment.get("moment_type", "STORY")
        result_urls = await _call_generation_server(
            prompt,
            image_count,
            moment_type,
            model_image=model_image,
            reference_images=reference_images,
        )

        if not result_urls:
            raise ValueError("Generation server returned no results")

        # Store results
        db.schema(MOMENTS_SCHEMA).table("generation_jobs").update({
            "status": "done",
            "result_urls": result_urls,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

        # Update moment status to READY
        db.schema(MOMENTS_SCHEMA).table("moments").update({
            "status": "READY",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", moment_id).execute()

        _promote_reference_assets(
            moment=moment,
            context=context,
            persona=persona,
            location=location,
            result_urls=result_urls,
            job_id=job_id,
        )

        # Check if all moments in the plan are done
        _check_plan_completion(moment.get("plan_id"))

        logger.info("Job %s completed: %d images generated", job_id, len(result_urls))

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)

        attempts = job.get("attempts", 0) + 1
        if attempts >= MAX_ATTEMPTS:
            # Mark as permanently failed
            db.schema(MOMENTS_SCHEMA).table("generation_jobs").update({
                "status": "failed",
                "error": str(exc)[:500],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).execute()

            # Mark moment as failed too
            db.schema(MOMENTS_SCHEMA).table("moments").update({
                "status": "FAILED",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", moment_id).execute()
        else:
            # Re-queue for retry
            db.schema(MOMENTS_SCHEMA).table("generation_jobs").update({
                "status": "queued",
                "error": f"Attempt {attempts} failed: {str(exc)[:300]}",
            }).eq("id", job_id).execute()


def _check_plan_completion(plan_id: str | None) -> None:
    """Check if all moments in a plan are done and update plan status."""
    if not plan_id:
        return

    try:
        db = _db()
        moments = (
            db.schema(MOMENTS_SCHEMA)
            .table("moments")
            .select("status")
            .eq("plan_id", plan_id)
            .execute()
        ).data or []

        if not moments:
            return

        statuses = {m["status"] for m in moments}

        if statuses == {"READY"}:
            new_status = "READY"
        elif "FAILED" in statuses and "GENERATING" not in statuses and "PLANNED" not in statuses:
            new_status = "PARTIAL_READY" if "READY" in statuses else "FAILED"
        else:
            return  # Still has pending moments

        db.schema(MOMENTS_SCHEMA).table("content_plans").update({
            "status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", plan_id).execute()

        logger.info("Plan %s status updated to %s", plan_id, new_status)
    except Exception:
        logger.exception("Failed to check plan completion for %s", plan_id)


# ═══════════════════════════════════════════════════════════
#  POLLING LOOP
# ═══════════════════════════════════════════════════════════

async def _poll_and_process() -> int:
    """Poll for queued jobs and process them.

    Returns the number of jobs processed.
    """
    try:
        result = (
            _db()
            .schema(MOMENTS_SCHEMA)
            .table("generation_jobs")
            .select("*")
            .eq("status", "queued")
            .order("created_at")
            .limit(MAX_CONCURRENT)
            .execute()
        )

        jobs = result.data or []
        if not jobs:
            return 0

        logger.info("Found %d queued generation jobs", len(jobs))

        # Process jobs concurrently (up to MAX_CONCURRENT)
        tasks = [_process_job(job) for job in jobs]
        await asyncio.gather(*tasks, return_exceptions=True)

        return len(jobs)

    except Exception:
        logger.exception("Error polling for generation jobs")
        return 0


async def run_worker() -> None:
    """Main worker loop — polls for jobs and processes them."""
    logger.info(
        "Generation worker started (poll=%.0fs, max_concurrent=%d, max_attempts=%d)",
        POLL_INTERVAL, MAX_CONCURRENT, MAX_ATTEMPTS,
    )

    while True:
        try:
            processed = await _poll_and_process()
            if processed:
                logger.info("Processed %d generation jobs", processed)
        except asyncio.CancelledError:
            logger.info("Generation worker cancelled")
            raise
        except Exception:
            logger.exception("Unexpected error in generation worker loop")

        try:
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Generation worker cancelled during sleep")
            raise
