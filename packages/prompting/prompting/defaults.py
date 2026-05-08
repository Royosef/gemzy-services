"""Default prompt-engine registry definitions.

These seeds are used to bootstrap the DB-backed prompt registry and also act as
an offline fallback when the registry database is unavailable in tests.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .on_model_constants import (
    _ON_MODEL_BASE_HERO,
    _ON_MODEL_BASE_JEWELRY,
    _ON_MODEL_BASE_MODEL,
    _ON_MODEL_BASE_STYLE,
    _ON_MODEL_MAPPING_V2,
    _ON_MODEL_MAPPING_V45,
    _ON_MODEL_RULES,
    _ON_MODEL_V45_HERO,
    _ON_MODEL_V45_MODEL_BASE,
    _ON_MODEL_V45_QUALITY,
)
from .pure_jewelry_prompts import (
    _DEFAULT_COLOR_HEX,
    _HERO as _PURE_JEWELRY_HERO,
    _PURE_JEWELRY_STYLES,
    _QUALITY as _PURE_JEWELRY_QUALITY,
    _SIZE_PROMPTS as _PURE_JEWELRY_SIZE_PROMPTS,
    _TYPE_ALIASES as _PURE_JEWELRY_TYPE_ALIASES,
    _TYPE_PROMPTS as _PURE_JEWELRY_TYPE_PROMPTS,
)

PROMPT_TASK_IMAGE_GENERATION_COMPOSE = "image_generation.compose"
PROMPT_TASK_IMAGE_GENERATION_DEFAULTS = "image_generation.defaults"
PROMPT_TASK_ON_MODEL = "on-model"
PROMPT_TASK_ON_MODEL_EDIT = "on-model/edited"
PROMPT_TASK_PURE_JEWELRY = "pure-jewelry"
PROMPT_TASK_PURE_JEWELRY_EDIT = "pure-jewelry/edited"
PROMPT_TASK_PLANNER_ENRICH = "planner.enrich"
PROMPT_TASK_PLANNER_RANK = "planner.rank"

_PURE_STYLE_DISPLAY_META = {
    "pure-studio": {"title": "Pure Studio", "imageKey": "pure-studio"},
    "object-world": {"title": "Object World", "imageKey": "object-world"},
    "surface-light": {"title": "Surface & Light", "imageKey": "surface-light"},
    "arranged": {"title": "Arranged", "imageKey": "arranged"},
    "on-display": {"title": "On Display", "imageKey": "on-display"},
}

_ENGINE_SELECTOR_SEEDS = {
    "image-generation-defaults": {
        "selector_pill_label": "Defaults",
        "selector_title": "Image Defaults",
        "selector_description": "Shared image-generation defaults.",
        "selector_badge": None,
        "selector_image_key": None,
        "selector_badge_image_key": None,
    },
    "on-model-legacy": {
        "selector_pill_label": "Legacy",
        "selector_title": "On-Model Legacy",
        "selector_description": "Legacy on-model builder kept for compatibility.",
        "selector_badge": None,
        "selector_image_key": "engine-v1",
        "selector_badge_image_key": None,
    },
    "on-model-v2": {
        "selector_pill_label": "On-Model V2",
        "selector_title": "On-Model V2",
        "selector_description": "Original structured on-model prompt engine.",
        "selector_badge": None,
        "selector_image_key": "engine-v1",
        "selector_badge_image_key": None,
    },
    "on-model-v4-5": {
        "selector_pill_label": "On-Model V4.5",
        "selector_title": "On-Model V4.5",
        "selector_description": "Editorial on-model prompt engine with the newer mapping set.",
        "selector_badge": "New",
        "selector_image_key": "engine-v2",
        "selector_badge_image_key": "new-badge",
    },
    "pure-jewelry-legacy": {
        "selector_pill_label": "Pure Legacy",
        "selector_title": "Pure Jewelry Legacy",
        "selector_description": "Legacy pure-jewelry prompt builder.",
        "selector_badge": None,
        "selector_image_key": "engine-v1",
        "selector_badge_image_key": None,
    },
    "pure-jewelry-v5-2": {
        "selector_pill_label": "Pure V5.2",
        "selector_title": "Pure Jewelry V5.2",
        "selector_description": "Section-based pure-jewelry engine synced to the richer V5.2 definitions.",
        "selector_badge": "New",
        "selector_image_key": "engine-v2",
        "selector_badge_image_key": "new-badge",
    },
    "on-model-edit-default": {
        "selector_pill_label": "Edit",
        "selector_title": "On-Model Edit",
        "selector_description": "DB-managed edit engine for on-model generations.",
        "selector_badge": None,
        "selector_image_key": None,
        "selector_badge_image_key": None,
    },
    "pure-jewelry-edit-default": {
        "selector_pill_label": "Edit",
        "selector_title": "Pure Jewelry Edit",
        "selector_description": "DB-managed edit engine for pure-jewelry generations.",
        "selector_badge": None,
        "selector_image_key": None,
        "selector_badge_image_key": None,
    },
    "planner-enrich-default": {
        "selector_pill_label": "Planner",
        "selector_title": "Planner Enrich",
        "selector_description": "Internal planner enrichment engine.",
        "selector_badge": None,
        "selector_image_key": None,
        "selector_badge_image_key": None,
    },
    "planner-rank-default": {
        "selector_pill_label": "Planner",
        "selector_title": "Planner Rank",
        "selector_description": "Internal planner ranking engine.",
        "selector_badge": None,
        "selector_image_key": None,
        "selector_badge_image_key": None,
    },
}

_ON_MODEL_SECTION_DISPLAY_DEFAULTS = {
    "background": {"label": "Scene", "description": "Set your model's environment", "iconKey": "mountains"},
    "emotion": {"label": "Emotion", "description": "Choose expression and mood", "iconKey": "smiley"},
    "hair": {"label": "Hair", "description": "Style your model's hair", "iconKey": "hairdryer"},
    "outfit": {"label": "Outfit", "description": "Pick outfit and styling", "iconKey": "coat-hanger"},
    "pose": {"label": "Pose", "description": "Control pose and framing", "iconKey": "person-arms-spread"},
    "lighting": {"label": "Lighting", "description": "Shape light and atmosphere", "iconKey": "sun"},
    "camera": {"label": "Camera Style", "description": "Adjust angle and lens feel", "iconKey": "aperture"},
    "image_style": {"label": "Style", "description": "Apply a visual style", "iconKey": "paint-brush"},
}

_DEFAULT_ITEM_TYPE_LABELS = [
    "Necklace",
    "Earrings",
    "Ring",
    "Bracelet",
    "Pendant",
    "Watch",
    "Choker",
    "Glasses",
    "Brooch",
    "Hair Clips",
    "Cufflinks",
    "Anklet",
    "Body Chain",
    "Tiara",
    "Headpiece",
]

_DEFAULT_ITEM_SIZE_LABELS = ["Very Small", "Small", "Medium", "Big", "Very Big"]


def _humanize_heading(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("&", " & ").replace("-", " ").split())


def _slugify_label(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


_DEFAULT_ITEM_TYPES = [{"id": _slugify_label(label), "label": label} for label in _DEFAULT_ITEM_TYPE_LABELS]
_DEFAULT_ITEM_SIZES = [{"id": _slugify_label(label), "label": label} for label in _DEFAULT_ITEM_SIZE_LABELS]


def _option_entry(label: str, option_definition: Any) -> dict[str, Any]:
    if isinstance(option_definition, dict):
        prompt = option_definition.get("prompt", "")
        has_color = bool(option_definition.get("has_color") or option_definition.get("hasColor"))
        color_label = option_definition.get("color_label") or option_definition.get("colorLabel")
        return {
            "id": str(option_definition.get("id") or "").strip() or _slugify_label(label),
            "label": str(option_definition.get("label") or label),
            "prompt": prompt,
            "has_color": has_color,
            **({"color_label": color_label} if color_label else {}),
        }
    return {
        "id": _slugify_label(label),
        "label": label,
        "prompt": str(option_definition),
    }


def _normalize_on_model_mapping(mapping: dict[str, dict[str, str]]) -> dict[str, dict[str, dict[str, Any]]]:
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for section_id, option_map in mapping.items():
        normalized[section_id] = {
            option_label: _option_entry(option_label, prompt)
            for option_label, prompt in (option_map or {}).items()
        }
    return normalized


def _normalize_pure_jewelry_styles(styles: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for style_id, style_definition in styles.items():
        style_meta = _PURE_STYLE_DISPLAY_META.get(style_id, {})
        categories: list[tuple[str, str, dict[str, dict[str, Any]]]] = []
        for category_id, category_name, option_map in style_definition.get("categories") or []:
            categories.append(
                (
                    category_id,
                    category_name,
                    {
                        option_label: _option_entry(option_label, option_definition)
                        for option_label, option_definition in (option_map or {}).items()
                    },
                )
            )
        normalized[style_id] = {
            "title": style_meta.get("title") or style_id.replace("-", " ").title(),
            "imageKey": style_meta.get("imageKey") or style_id,
            "atmosphere": style_definition.get("atmosphere", ""),
            "categories": categories,
        }
    return normalized


def _selector_seed(slug: str) -> dict[str, Any]:
    return deepcopy(_ENGINE_SELECTOR_SEEDS.get(slug) or {})


def _build_pure_section_defaults() -> dict[str, dict[str, Any]]:
    section_defaults: dict[str, dict[str, Any]] = {}
    for style_definition in _PURE_JEWELRY_STYLES.values():
        for category_id, category_name, _option_map in style_definition.get("categories") or []:
            if category_id in section_defaults:
                continue
            section_defaults[category_id] = {
                "label": _humanize_heading(category_name),
                "description": None,
                "iconKey": None,
                "editTier": "Pro",
                "supportsRandom": False,
            }
    return section_defaults


def _task_display_defaults() -> dict[str, dict[str, Any]]:
    pure_section_defaults = _build_pure_section_defaults()
    return {
        PROMPT_TASK_ON_MODEL: {
            "layout": "flat-sections",
            "trialPopupImageKey": "on-model-pro-popup",
            "itemTypes": deepcopy(_DEFAULT_ITEM_TYPES),
            "itemSizes": deepcopy(_DEFAULT_ITEM_SIZES),
            "sectionDefaults": {
                section_id: {
                    "label": meta.get("label"),
                    "description": meta.get("description"),
                    "iconKey": meta.get("iconKey"),
                    "editTier": "Pro",
                    "supportsRandom": True,
                }
                for section_id, meta in _ON_MODEL_SECTION_DISPLAY_DEFAULTS.items()
            },
        },
        PROMPT_TASK_ON_MODEL_EDIT: {
            "layout": "flat-sections",
            "trialPopupImageKey": "on-model-pro-popup",
            "itemTypes": deepcopy(_DEFAULT_ITEM_TYPES),
            "itemSizes": deepcopy(_DEFAULT_ITEM_SIZES),
            "sectionDefaults": {
                section_id: {
                    "label": meta.get("label"),
                    "description": meta.get("description"),
                    "iconKey": meta.get("iconKey"),
                    "editTier": "Pro",
                    "supportsRandom": True,
                }
                for section_id, meta in _ON_MODEL_SECTION_DISPLAY_DEFAULTS.items()
            },
        },
        PROMPT_TASK_PURE_JEWELRY: {
            "layout": "style-cards",
            "trialPopupImageKey": "pure-jewelry-pro-popup",
            "itemTypes": deepcopy(_DEFAULT_ITEM_TYPES),
            "itemSizes": deepcopy(_DEFAULT_ITEM_SIZES),
            "sectionDefaults": pure_section_defaults,
        },
        PROMPT_TASK_PURE_JEWELRY_EDIT: {
            "layout": "style-cards",
            "trialPopupImageKey": "pure-jewelry-pro-popup",
            "itemTypes": deepcopy(_DEFAULT_ITEM_TYPES),
            "itemSizes": deepcopy(_DEFAULT_ITEM_SIZES),
            "sectionDefaults": pure_section_defaults,
        },
    }


_TASK_DISPLAY_DEFAULTS = _task_display_defaults()

_DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, distorted, duplicate, text artifact, watermark, logo,"
    " extra limbs, cropped, bad anatomy, text overlays, captions, numbers"
)


def _image_edit_option(
    option_id: str,
    *,
    label: str,
    description: str,
    category: str,
    prompt: str,
    parent_id: str | None = None,
    parent_label: str | None = None,
    exclusive_group: str | None = None,
    conflicts_with: list[str] | None = None,
) -> dict[str, Any]:
    option = {
        "id": option_id,
        "label": label,
        "description": description,
        "category": category,
        "prompt": prompt,
    }
    if parent_id:
        option["parentId"] = parent_id
    if parent_label:
        option["parentLabel"] = parent_label
    if exclusive_group:
        option["exclusiveGroup"] = exclusive_group
    if conflicts_with:
        option["conflictsWith"] = list(conflicts_with)
    return option


def _image_edit_definition(*, disable_model_category: bool) -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "editOptions": [
            _image_edit_option(
                "jewelry_smaller",
                label="Make the jewelry a bit smaller",
                description="Reduce the size slightly",
                category="jewelry",
                conflicts_with=["jewelry_bigger"],
                prompt="Reduce the overall scale of the jewelry by approximately 10% - uniformly across all dimensions, preserving the exact proportions of the original piece. Width, height, and depth must all reduce by the same proportional amount. The jewelry's design, material, color, gemstones, metal tone, surface finish, and position on the body all remain identical to the original. Do not stretch, squash, narrow, or alter any individual dimension independently. The only difference between the new jewelry and the original is uniform scale. If the size reduction exceeds 15%, or if any property of the jewelry changes other than its scale, the image is not ready.",
            ),
            _image_edit_option(
                "jewelry_bigger",
                label="Make the jewelry a bit bigger",
                description="Increase the size slightly",
                category="jewelry",
                conflicts_with=["jewelry_smaller"],
                prompt="Increase the overall scale of the jewelry by approximately 10% - uniformly across all dimensions, preserving the exact proportions of the original piece. Width, height, and depth must all increase by the same proportional amount. The jewelry's design, material, color, gemstones, metal tone, surface finish, and position on the body all remain identical to the original. Do not stretch, expand, widen, or alter any individual dimension independently. The only difference between the new jewelry and the original is uniform scale. If the size increase exceeds 15%, or if any property of the jewelry changes other than its scale, the image is not ready.",
            ),
            _image_edit_option(
                "enhance_shine",
                label="Enhance shine & reflections",
                description="More dimension and glow",
                category="jewelry",
                prompt="Enhance the metal and gemstone surfaces of the jewelry - increase specular highlights, deepen reflectivity, and add realistic polish and depth to the material surfaces. The enhancement must look photographically real - no artificial sparkle, no starburst effects, no graphic overlays. The jewelry should look like it was lit more precisely, not digitally altered.",
            ),
            _image_edit_option(
                "zoom_in",
                label="Zoom in on the jewelry",
                description="Closer jewelry-focused crop",
                category="framing",
                conflicts_with=["zoom_out"],
                prompt="Crop the frame approximately 15% closer toward the jewelry, keeping the jewelry sharp, fully visible, and centered within the new frame. The jewelry must remain completely unobstructed.",
            ),
            _image_edit_option(
                "zoom_out",
                label="Zoom out for full context",
                description="Wider framing of the look",
                category="framing",
                conflicts_with=["zoom_in"],
                prompt="Pull the camera back so the jewelry and subject appear approximately 15% smaller within the frame - more of the existing scene, surface, and surroundings become visible around them. The jewelry remains sharp and fully visible. Do not invent new content beyond the original frame edges; only redistribute the existing scene composition so the subject occupies less of the frame than before.",
            ),
            _image_edit_option(
                "camera_low_angle",
                label="Low angle",
                description="Choose a different perspective",
                category="framing",
                parent_id="camera_angle",
                parent_label="Change camera angle",
                exclusive_group="camera_angle",
                prompt="Reframe the image from a subtle low angle perspective - the camera shifts slightly downward, looking up toward the subject. The shift is gentle and editorial, not extreme. The jewelry remains fully visible and sharp.",
            ),
            _image_edit_option(
                "camera_high_angle",
                label="High angle",
                description="Choose a different perspective",
                category="framing",
                parent_id="camera_angle",
                parent_label="Change camera angle",
                exclusive_group="camera_angle",
                prompt="Reframe the image from a subtle high angle perspective - the camera shifts slightly upward, looking down toward the subject. The shift is gentle and editorial, not extreme. The jewelry remains fully visible and sharp.",
            ),
            _image_edit_option(
                "camera_rotate_left",
                label="Rotate Slight Left",
                description="Choose a different perspective",
                category="framing",
                parent_id="camera_angle",
                parent_label="Change camera angle",
                exclusive_group="camera_angle",
                prompt="Rotate the composition slightly to the left - a subtle, natural tilt of no more than 5 degrees. The jewelry remains sharp and fully visible.",
            ),
            _image_edit_option(
                "lighting_soft_diffused",
                label="Soft Diffused",
                description="How light shapes your jewelry",
                category="lighting_photo",
                parent_id="lighting",
                parent_label="Change the lighting",
                exclusive_group="lighting",
                prompt="Apply soft, diffused lighting across the scene - light wraps from multiple directions, shadow edges become gradual and gentle, no harsh contrast. The jewelry is fully revealed under the soft light.",
            ),
            _image_edit_option(
                "lighting_side_rim",
                label="Side Rim",
                description="How light shapes your jewelry",
                category="lighting_photo",
                parent_id="lighting",
                parent_label="Change the lighting",
                exclusive_group="lighting",
                prompt="Add a side rim light along one edge of the subject - a narrow, precise light source that creates a bright separation line along the jewelry, the jaw, or the shoulder depending on the composition. The rim light is subtle and editorial - it adds depth and separation without overpowering the existing lighting.",
            ),
            _image_edit_option(
                "lighting_top_down",
                label="Top Down",
                description="How light shapes your jewelry",
                category="lighting_photo",
                parent_id="lighting",
                parent_label="Change the lighting",
                exclusive_group="lighting",
                prompt="Shift the primary light source to a top-down position - light falls from directly above, illuminating the top surfaces of the jewelry and the subject while allowing the sides to fall into natural shadow. The jewelry's top face and any gemstones catch the overhead light directly.",
            ),
            _image_edit_option(
                "gradient_background",
                label="Add a background gradient",
                description="Soft gradient in the background",
                category="lighting_photo",
                prompt="If the background is a solid or near-solid color: introduce a subtle, natural gradient across that color - lighter at one edge, slightly deeper at the opposite edge, as if studio light is wrapping softly around the scene. The gradient must feel like natural light behavior, not a graphic effect. The color itself does not change - only its tonal depth. If the background is an environmental scene - a location, a textured surface, a real place - do not add a gradient. Instead, deepen the existing atmospheric depth of the scene by subtly darkening the corners and edges while keeping the center bright and sharp.",
            ),
            _image_edit_option(
                "model_pose",
                label="Change the model's pose",
                description="A more natural or dynamic stance",
                category="model",
                prompt="Change the model's pose to a clearly different position than the original - a different arm placement, a different head angle, a different body orientation, or a combination of these. The new pose must be visibly and immediately different from the original to a viewer comparing the two images. The pose remains natural and editorial - never stiff or performed. The jewelry must remain fully visible and in its original position on the body. The model's identity, outfit, and all other elements remain unchanged. If the pose appears unchanged or only barely different from the original, the image is not ready.",
            ),
            _image_edit_option(
                "outfit_color",
                label="Change the outfit color",
                description="Adjust the clothing tone",
                category="model",
                prompt="Change the color of the outfit to a different complementary tone - keep the same fabric, the same silhouette, and the same garment entirely. Only the color changes.",
            ),
            _image_edit_option(
                "upscale_image",
                label="Upscale the image",
                description="Upscale to improve resolution",
                category="upscale_sharpen",
                prompt="Upscale the image to higher resolution while preserving all natural detail - skin texture, fabric texture, jewelry surface, and background all retain their original quality without over-sharpening or introducing artificial detail. The image must look like a higher resolution version of the original, not a processed version of it.",
            ),
            _image_edit_option(
                "sharpen_image",
                label="Sharpen the image",
                description="Sharpen to enhance details",
                category="upscale_sharpen",
                prompt="Sharpen the image to improve micro-contrast and edge clarity while preserving a completely photographic result. Fine edges in gemstones, metal, eyelashes, and fabric become slightly more defined, but no halos, oversharpening, or artificial crispness appear.",
            ),
        ],
        "editCategories": [
            {
                "id": "jewelry",
                "label": "Jewelry",
                "options": ["jewelry_smaller", "jewelry_bigger", "enhance_shine"],
            },
            {
                "id": "framing",
                "label": "Framing",
                "options": ["zoom_in", "zoom_out", "camera_angle"],
            },
            {
                "id": "lighting_photo",
                "label": "Lighting/Photo",
                "options": ["lighting", "gradient_background"],
            },
            {
                "id": "model",
                "label": "Model",
                "options": ["model_pose", "outfit_color"],
                "disabled": disable_model_category,
                "disabledReason": "Not available for Pure Jewelry" if disable_model_category else None,
            },
            {
                "id": "upscale_sharpen",
                "label": "Upscale/Sharpen",
                "options": ["upscale_image", "sharpen_image"],
            },
        ],
    }

_LEGACY_PURE_JEWELRY_TEMPLATES = {
    "studio-shot": (
        "Use the uploaded jewelry image as the exact visual reference.\n"
        "Preserve the original jewelry design, shape, materials, proportions, and details.\n\n"
        "Studio product photography of a single jewelry piece.\n"
        "Presentation style: clean, minimal, premium catalog shot.\n\n"
        "Background: {background}.\n"
        "Surface: {surface}.\n"
        "Lighting: {lighting}, soft and controlled.\n"
        "Shadows: natural and subtle, grounded and realistic.\n\n"
        "Add-ons: {addons}, minimal and understated.\n\n"
        "High realism, sharp focus, accurate reflections and materials.\n"
        "No people, no text, no logos."
    ),
    "lifestyle": (
        "Use the uploaded jewelry image as the exact visual reference.\n"
        "Preserve the original jewelry design, shape, materials, proportions, and details.\n\n"
        "Lifestyle product photography of jewelry in a real-world styled setting.\n"
        "The jewelry is placed naturally on {base}.\n"
        "Color palette: {color_palette}.\n\n"
        "Lighting: {lighting}, natural and realistic.\n"
        "Composition: {composition}, editorial and balanced.\n\n"
        "Add-ons: {addons}, subtle and tasteful.\n\n"
        "Premium lifestyle aesthetic, soft depth, realistic textures and shadows.\n"
        "No people, no text, no logos."
    ),
    "collection": (
        "Use the uploaded jewelry image as the exact visual reference.\n"
        "Preserve the original jewelry design, shape, materials, proportions, and details.\n\n"
        "Product photography showing a collection of {quantity} identical jewelry pieces.\n"
        "Arrangement: {arrangement}.\n"
        "Visual emphasis: {emphasis}.\n\n"
        "Background: {background}.\n"
        "Lighting: {lighting}, balanced across all items.\n\n"
        "Clean, premium brand presentation with clear hierarchy and depth.\n"
        "High realism, accurate reflections, consistent materials.\n"
        "No people, no text, no logos."
    ),
    "on-dummy": (
        "Use the uploaded jewelry image as the exact visual reference.\n"
        "Preserve the original jewelry design, shape, materials, proportions, and details.\n\n"
        "Jewelry displayed on a {dummy_type}.\n"
        "Dummy color: {dummy_color}.\n"
        "Presentation angle: {pose_angle}.\n\n"
        "Lighting: {lighting}, sculptural and soft.\n"
        "Background: {background}, clean and unobtrusive.\n\n"
        "Gallery-style product presentation with realistic scale and depth.\n"
        "High realism, refined shadows and reflections.\n"
        "No people, no text, no logos."
    ),
}

_BACKGROUND_ALIASES = {
    "Studio Color (Dynamic)": "Studio Color",
}

_JEWELRY_TYPE_ALIASES = {
    "Earring": "Earrings",
    "Earrings": "Earring",
    "Hair Clip": "Hair Clips",
    "Headpiece": "Headpieces",
    "Headpieces": "Headpiece",
    "Cufflink": "Cufflinks",
    "Cufflinks": "Cufflink",
}

_IMAGE_COMPOSE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "request": {
            "type": "object",
            "description": "Normalized generation request payload sent to the worker.",
        }
    },
    "required": ["request"],
}

_IMAGE_DEFAULTS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "extras": {"type": "array", "items": {"type": "string"}},
        "items": {
            "type": "array",
            "items": {"type": "object"},
        },
    },
}

_PLANNER_ENRICH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "persona": {"type": "object"},
        "style_profile": {"type": "object"},
        "preferences": {"type": "object"},
        "world_summary": {"type": "object"},
    },
    "required": ["prompt", "persona", "style_profile", "preferences", "world_summary"],
}

_PLANNER_RANK_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "persona_name": {"type": "string"},
        "intent": {"type": "string"},
        "tone": {"type": "string"},
        "moments": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["persona_name", "intent", "tone", "moments"],
}


def _on_model_legacy_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "jewelry_type_aliases": deepcopy(_JEWELRY_TYPE_ALIASES),
        "defaults": {
            "camera": "85mm Portrait",
            "pose": "Portrait (Product Touch)",
            "background": "Studio (Pure White)",
            "emotion": "Sophisticated Calm",
            "lighting": "Studio Beauty Dish",
        },
        "advanced_exclude_keys": [
            "product",
            "camera",
            "camera_style",
            "pose",
            "background",
            "emotion",
            "lighting",
            "outfit",
            "public_version_key",
        ],
    }


def _image_defaults_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
    }


def _on_model_v2_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "variant": "v2",
        "background_aliases": deepcopy(_BACKGROUND_ALIASES),
        "jewelry_type_aliases": deepcopy(_JEWELRY_TYPE_ALIASES),
        "mapping": _normalize_on_model_mapping(deepcopy(_ON_MODEL_MAPPING_V2)),
        "texts": {
            "hero": _ON_MODEL_BASE_HERO,
            "model_base": _ON_MODEL_BASE_MODEL,
            "jewelry_base": _ON_MODEL_BASE_JEWELRY,
            "style_base": _ON_MODEL_BASE_STYLE,
            "rules": _ON_MODEL_RULES,
        },
    }


def _on_model_v45_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "variant": "v4.5",
        "background_aliases": deepcopy(_BACKGROUND_ALIASES),
        "jewelry_type_aliases": deepcopy(_JEWELRY_TYPE_ALIASES),
        "mapping": _normalize_on_model_mapping(deepcopy(_ON_MODEL_MAPPING_V45)),
        "texts": {
            "hero": _ON_MODEL_V45_HERO,
            "model_base": _ON_MODEL_V45_MODEL_BASE,
            "quality": _ON_MODEL_V45_QUALITY,
        },
    }


def _pure_jewelry_v52_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "default_color_hex": _DEFAULT_COLOR_HEX,
        "hero": _PURE_JEWELRY_HERO,
        "quality": _PURE_JEWELRY_QUALITY,
        "type_aliases": deepcopy(_PURE_JEWELRY_TYPE_ALIASES),
        "type_prompts": deepcopy(_PURE_JEWELRY_TYPE_PROMPTS),
        "size_prompts": deepcopy(_PURE_JEWELRY_SIZE_PROMPTS),
        "styles": _normalize_pure_jewelry_styles(deepcopy(_PURE_JEWELRY_STYLES)),
    }


def _pure_jewelry_legacy_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "templates": deepcopy(_LEGACY_PURE_JEWELRY_TEMPLATES),
        "fallback_definition": _on_model_legacy_definition(),
    }


def _planner_enrich_definition() -> dict[str, Any]:
    return {
        "model_env": "GOOGLE_GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
        "temperature": 0.7,
        "system_instruction": (
            "You are an expert social media manager and creative director for an influencer."
            "You craft realistic, engaging day plans for their content feed. You output strict JSON matching the requested schema."
        ),
        "prompt_lines": [
            "Prompt from User: {prompt}",
            "Persona Name: {persona_display_name}",
            "Persona Bio: {persona_bio}",
            "Realism Level: {style_profile_realism_level}",
            "Style Tags: {style_tags_csv}",
            "Total target stories: {preferences_stories_per_day}",
            "Total target posts: {preferences_posts_per_day}",
            "Available Locations: {world_summary_location_tags_csv}",
            "Available Wardrobe Tags: {world_summary_wardrobe_tags_csv}",
            "",
            "Based on the user's prompt, create a cohesive content plan for the day.",
            "Include an overarching intent, tone, and a day_arc summary.",
            "Break the plan down into individual moments (e.g., morning, midday, afternoon, evening, late_night).",
            "For each moment, give a detailed description of the photo/video, appropriate mood_tags, and desired location and outfit tags from the available lists.",
        ],
    }


def _planner_rank_definition() -> dict[str, Any]:
    return {
        "model_env": "GOOGLE_GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
        "temperature": 0.3,
        "system_instruction": (
            "You are a social media feed curator."
            "Given a list of planned content moments for the day, score each moment's potential to be a 'hero' post (hero_score from 0.0 to 1.0)."
            "Then, suggest whether it should be a 'STORY' (ephemeral, candid) or a 'POST' (high-quality, feed-worthy)."
            "Output strict JSON matching the requested schema."
        ),
        "prompt_lines": [
            "Persona: {persona_name}",
            "Intent of the day: {intent}",
            "Tone: {tone}",
            "",
            "Moments:",
            "{moments_text}",
            "",
            "Please analyze the moments above. For each moment (using its 0-based index), provide:",
            "1. The index number.",
            "2. format: either STORY or POST.",
            "3. hero_score: 0.0 to 1.0 rating its feed-worthiness.",
            "4. reasoning: a brief explanation.",
        ],
    }


def get_default_registry() -> dict[str, list[dict[str, Any]]]:
    """Return the default registry snapshot used for seeding and offline fallback."""

    return {
        "tasks": [
            {
                "key": PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
                "name": "Image Generation Defaults",
                "description": "Shared negative prompt defaults for image generation.",
                "surface": None,
            },
            {
                "key": PROMPT_TASK_ON_MODEL,
                "name": "On Model",
                "description": "Primary on-model jewelry generation task.",
                "surface": "onModel",
                "display_defaults": deepcopy(_TASK_DISPLAY_DEFAULTS[PROMPT_TASK_ON_MODEL]),
            },
            {
                "key": PROMPT_TASK_ON_MODEL_EDIT,
                "name": "On Model Edit",
                "description": "Edit flow for on-model generations.",
                "surface": "onModel",
                "parent_task_key": PROMPT_TASK_ON_MODEL,
                "display_defaults": deepcopy(_TASK_DISPLAY_DEFAULTS[PROMPT_TASK_ON_MODEL_EDIT]),
            },
            {
                "key": PROMPT_TASK_PURE_JEWELRY,
                "name": "Pure Jewelry",
                "description": "Primary pure-jewelry generation task.",
                "surface": "pureJewelry",
                "display_defaults": deepcopy(_TASK_DISPLAY_DEFAULTS[PROMPT_TASK_PURE_JEWELRY]),
            },
            {
                "key": PROMPT_TASK_PURE_JEWELRY_EDIT,
                "name": "Pure Jewelry Edit",
                "description": "Edit flow for pure-jewelry generations.",
                "surface": "pureJewelry",
                "parent_task_key": PROMPT_TASK_PURE_JEWELRY,
                "display_defaults": deepcopy(_TASK_DISPLAY_DEFAULTS[PROMPT_TASK_PURE_JEWELRY_EDIT]),
            },
            {
                "key": PROMPT_TASK_PLANNER_ENRICH,
                "name": "Planner Enrich",
                "description": "Planner enrichment task.",
                "surface": None,
            },
            {
                "key": PROMPT_TASK_PLANNER_RANK,
                "name": "Planner Rank",
                "description": "Planner ranking task.",
                "surface": None,
            },
        ],
        "engines": [
            {
                "slug": "image-generation-defaults",
                "name": "Image Generation Defaults",
                "description": "Shared negative prompt defaults for direct image-generation calls.",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
                "task_key": PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
                "renderer_key": "image_defaults_v1",
                "public_engine_key": "image-generation-defaults",
                "is_user_selectable": False,
                "sort_order": 100,
                **_selector_seed("image-generation-defaults"),
                "input_schema": deepcopy(_IMAGE_DEFAULTS_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Default",
                    "public_version_key": "default",
                    "change_note": "Seeded from the legacy inline negative-prompt defaults.",
                    "sample_input": {"extras": ["overexposed"], "items": [{"type": "Ring", "size": "Medium"}]},
                    "definition": _image_defaults_definition(),
                },
            },
            {
                "slug": "on-model-legacy",
                "name": "On-Model Legacy",
                "description": "Legacy on-model prompt builder for older clients without sectioned prompt versions.",
                "task_type": PROMPT_TASK_ON_MODEL,
                "task_key": PROMPT_TASK_ON_MODEL,
                "renderer_key": "on_model_legacy_v1",
                "public_engine_key": "on-model-legacy",
                "is_user_selectable": False,
                "sort_order": 100,
                **_selector_seed("on-model-legacy"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "on-model"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Legacy",
                    "public_version_key": "legacy",
                    "change_note": "Seeded from the legacy inline on-model prompt builder.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "model"},
                            "style": {"product": "Ring", "camera": "DSLR"},
                            "mode": "ADVANCED",
                            "looks": 1,
                            "items": [{"type": "Ring", "size": "Medium"}],
                        }
                    },
                    "definition": _on_model_legacy_definition(),
                },
            },
            {
                "slug": "on-model-v2",
                "name": "On-Model V2",
                "description": "Structured section-based on-model prompt definition using the original V2 mappings.",
                "task_type": PROMPT_TASK_ON_MODEL,
                "task_key": PROMPT_TASK_ON_MODEL,
                "renderer_key": "on_model_sections_v1",
                "public_engine_key": "on-model-v2",
                "is_user_selectable": True,
                "sort_order": 20,
                **_selector_seed("on-model-v2"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "on-model", "version": "v2"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "V2",
                    "public_version_key": "v2",
                    "change_note": "Seeded from the legacy inline on-model V2 definitions.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "model"},
                            "style": {"public_version_key": "v2", "background": "Blue Hour Editorial"},
                            "mode": "SIMPLE",
                            "looks": 1,
                            "items": [{"type": "Ring", "size": "Small"}],
                        }
                    },
                    "definition": _on_model_v2_definition(),
                },
            },
            {
                "slug": "on-model-v4-5",
                "name": "On-Model V4.5",
                "description": "Editorial on-model prompt definition using the newer section layout and mapping set.",
                "task_type": PROMPT_TASK_ON_MODEL,
                "task_key": PROMPT_TASK_ON_MODEL,
                "renderer_key": "on_model_sections_v1",
                "public_engine_key": "on-model-v4-5",
                "is_user_selectable": True,
                "sort_order": 10,
                **_selector_seed("on-model-v4-5"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "on-model", "version": "v4.5"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "V4.5 Editorial",
                    "public_version_key": "v4.5",
                    "change_note": "Seeded from the legacy inline on-model V4.5 definitions.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "model"},
                            "style": {"public_version_key": "v4.5", "background": "White Studio"},
                            "mode": "SIMPLE",
                            "looks": 1,
                            "items": [{"type": "Ring", "size": "Small"}],
                        }
                    },
                    "definition": _on_model_v45_definition(),
                },
            },
            {
                "slug": "pure-jewelry-legacy",
                "name": "Pure Jewelry Legacy",
                "description": "Legacy pure-jewelry prompt builder for classic style-type variants.",
                "task_type": PROMPT_TASK_PURE_JEWELRY,
                "task_key": PROMPT_TASK_PURE_JEWELRY,
                "renderer_key": "pure_jewelry_legacy_v1",
                "public_engine_key": "pure-jewelry-legacy",
                "is_user_selectable": True,
                "sort_order": 20,
                **_selector_seed("pure-jewelry-legacy"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "pure-jewelry", "version": "legacy"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Legacy",
                    "public_version_key": "v1",
                    "change_note": "Seeded from the legacy inline pure-jewelry prompt templates.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "pure-jewelry"},
                            "style": {"style_type": "studio-shot", "background": "Pure white"},
                            "looks": 1,
                            "items": [{"type": "Ring", "size": "Medium"}],
                        }
                    },
                    "definition": _pure_jewelry_legacy_definition(),
                },
            },
            {
                "slug": "pure-jewelry-v5-2",
                "name": "Pure Jewelry V5.2",
                "description": "Sectioned pure-jewelry prompt definition synced from the richer V5.2 prompt system.",
                "task_type": PROMPT_TASK_PURE_JEWELRY,
                "task_key": PROMPT_TASK_PURE_JEWELRY,
                "renderer_key": "pure_jewelry_sections_v1",
                "public_engine_key": "pure-jewelry-v5-2",
                "is_user_selectable": True,
                "sort_order": 10,
                **_selector_seed("pure-jewelry-v5-2"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "pure-jewelry", "version": "v5.2"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "V5.2",
                    "public_version_key": "v5.2",
                    "change_note": "Seeded from the legacy inline pure-jewelry V5.2 definitions.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "pure-jewelry"},
                            "style": {"public_version_key": "v5.2", "style_type": "pure-studio"},
                            "looks": 1,
                            "items": [{"type": "Ring", "size": "Very Small"}],
                        }
                    },
                    "definition": _pure_jewelry_v52_definition(),
                },
            },
            {
                "slug": "on-model-edit-default",
                "name": "On-Model Edit",
                "description": "DB-managed image edit engine for on-model generations.",
                "task_type": PROMPT_TASK_ON_MODEL_EDIT,
                "task_key": PROMPT_TASK_ON_MODEL_EDIT,
                "renderer_key": "image_defaults_v1",
                "public_engine_key": "on-model-edit-default",
                "is_user_selectable": False,
                "sort_order": 10,
                **_selector_seed("on-model-edit-default"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-edit", "surface": "on-model", "version": "default"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Default Edit",
                    "public_version_key": "default",
                    "change_note": "Seeded from the current hardcoded on-model edit flow.",
                    "sample_input": {
                        "request": {
                            "style": {"task_type": PROMPT_TASK_ON_MODEL_EDIT},
                            "promptOverrides": ["Generate this exact same image with the selected edit instructions."],
                            "looks": 1,
                        }
                    },
                    "definition": _image_edit_definition(disable_model_category=False),
                },
            },
            {
                "slug": "pure-jewelry-edit-default",
                "name": "Pure Jewelry Edit",
                "description": "DB-managed image edit engine for pure-jewelry generations.",
                "task_type": PROMPT_TASK_PURE_JEWELRY_EDIT,
                "task_key": PROMPT_TASK_PURE_JEWELRY_EDIT,
                "renderer_key": "image_defaults_v1",
                "public_engine_key": "pure-jewelry-edit-default",
                "is_user_selectable": False,
                "sort_order": 10,
                **_selector_seed("pure-jewelry-edit-default"),
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-edit", "surface": "pure-jewelry", "version": "default"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Default Edit",
                    "public_version_key": "default",
                    "change_note": "Seeded from the current hardcoded pure-jewelry edit flow.",
                    "sample_input": {
                        "request": {
                            "style": {"task_type": PROMPT_TASK_PURE_JEWELRY_EDIT},
                            "promptOverrides": ["Generate this exact same image with the selected edit instructions."],
                            "looks": 1,
                        }
                    },
                    "definition": _image_edit_definition(disable_model_category=True),
                },
            },
            {
                "slug": "planner-enrich-default",
                "name": "Planner Enrich Default",
                "description": "Default system and user prompt templates for planner enrichment.",
                "task_type": PROMPT_TASK_PLANNER_ENRICH,
                "task_key": PROMPT_TASK_PLANNER_ENRICH,
                "renderer_key": "planner_enrich_v1",
                "public_engine_key": "planner-enrich-default",
                "is_user_selectable": False,
                "sort_order": 100,
                **_selector_seed("planner-enrich-default"),
                "input_schema": deepcopy(_PLANNER_ENRICH_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "planner"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Default",
                    "public_version_key": "default",
                    "change_note": "Seeded from the legacy inline planner-enrichment prompts.",
                    "sample_input": {
                        "prompt": "A productive but glamorous day in Tel Aviv",
                        "persona": {"display_name": "Maya", "bio": "Fashion founder"},
                        "style_profile": {
                            "realism_level": "high",
                            "camera_style_tags": ["editorial"],
                            "color_palette_tags": ["warm"],
                        },
                        "preferences": {"stories_per_day": 3, "posts_per_day": 1},
                        "world_summary": {
                            "location_tags": ["beach", "cafe"],
                            "wardrobe_tags": ["linen", "gold"],
                        },
                    },
                    "definition": _planner_enrich_definition(),
                },
            },
            {
                "slug": "planner-rank-default",
                "name": "Planner Rank Default",
                "description": "Default system and user prompt templates for planner ranking.",
                "task_type": PROMPT_TASK_PLANNER_RANK,
                "task_key": PROMPT_TASK_PLANNER_RANK,
                "renderer_key": "planner_rank_v1",
                "public_engine_key": "planner-rank-default",
                "is_user_selectable": False,
                "sort_order": 100,
                **_selector_seed("planner-rank-default"),
                "input_schema": deepcopy(_PLANNER_RANK_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "planner"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "version_name": "Default",
                    "public_version_key": "default",
                    "change_note": "Seeded from the legacy inline planner-ranking prompts.",
                    "sample_input": {
                        "persona_name": "Maya",
                        "intent": "Launch week energy",
                        "tone": "aspirational",
                        "moments": [
                            {
                                "description": "Morning coffee on the balcony",
                                "time_slot": "morning",
                                "priority": "high",
                                "location_name": "Balcony",
                                "location_tags": ["home"],
                                "outfit_items": ["robe"],
                            }
                        ],
                    },
                    "definition": _planner_rank_definition(),
                },
            },
        ],
        "routes": [
            {
                "slug": "image-generation-defaults",
                "name": "Image Generation Defaults",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
                "priority": 10,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "image-generation-defaults",
                "notes": "Fallback defaults for direct sync image generation requests.",
            },
            {
                "slug": "pure-jewelry-v5-2-route",
                "name": "Pure Jewelry V5.2",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "priority": 10,
                "is_active": True,
                "match_rules": {
                    "request.model.slug": "pure-jewelry",
                    "request.style.public_version_key": {"in": ["v5.2", "5.2"]},
                },
                "engine_slug": "pure-jewelry-v5-2",
                "notes": "Use the V5.2 pure-jewelry prompt when the request explicitly asks for it.",
            },
            {
                "slug": "pure-jewelry-legacy-route",
                "name": "Pure Jewelry Legacy",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "priority": 20,
                "is_active": True,
                "match_rules": {
                    "request.model.slug": "pure-jewelry",
                },
                "engine_slug": "pure-jewelry-legacy",
                "notes": "Fallback for pure-jewelry requests without a V5.2 prompt version.",
            },
            {
                "slug": "on-model-v4-5-route",
                "name": "On-Model V4.5",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "priority": 30,
                "is_active": True,
                "match_rules": {
                    "request.style.public_version_key": {"in": ["v4.5", "4.5", "v45", "45"]},
                },
                "engine_slug": "on-model-v4-5",
                "notes": "Default on-model route for the newer editorial prompt version.",
            },
            {
                "slug": "on-model-v2-route",
                "name": "On-Model V2",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "priority": 40,
                "is_active": True,
                "match_rules": {
                    "request.style.public_version_key": {"in": ["v2", "2"]},
                },
                "engine_slug": "on-model-v2",
                "notes": "Older sectioned on-model prompt route.",
            },
            {
                "slug": "on-model-legacy-route",
                "name": "On-Model Legacy",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "priority": 100,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "on-model-legacy",
                "notes": "Catch-all prompt route for legacy on-model requests.",
            },
            {
                "slug": "pure-jewelry-v5-2-task-route",
                "name": "Pure Jewelry V5.2 Task",
                "task_type": PROMPT_TASK_PURE_JEWELRY,
                "priority": 10,
                "is_active": True,
                "match_rules": {
                    "request.style.public_version_key": {"in": ["v5.2", "5.2"]},
                },
                "engine_slug": "pure-jewelry-v5-2",
                "notes": "Task-first route for pure-jewelry V5.2 requests.",
            },
            {
                "slug": "pure-jewelry-legacy-task-route",
                "name": "Pure Jewelry Legacy Task",
                "task_type": PROMPT_TASK_PURE_JEWELRY,
                "priority": 20,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "pure-jewelry-legacy",
                "notes": "Task-first fallback route for pure-jewelry requests.",
            },
            {
                "slug": "pure-jewelry-edit-default-task-route",
                "name": "Pure Jewelry Edit",
                "task_type": PROMPT_TASK_PURE_JEWELRY_EDIT,
                "priority": 1,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "pure-jewelry-edit-default",
                "notes": "DB-managed image edit route for pure-jewelry requests.",
            },
            {
                "slug": "on-model-v4-5-task-route",
                "name": "On-Model V4.5 Task",
                "task_type": PROMPT_TASK_ON_MODEL,
                "priority": 10,
                "is_active": True,
                "match_rules": {
                    "request.style.public_version_key": {"in": ["v4.5", "4.5", "v45", "45"]},
                },
                "engine_slug": "on-model-v4-5",
                "notes": "Task-first route for on-model V4.5 requests.",
            },
            {
                "slug": "on-model-v2-task-route",
                "name": "On-Model V2 Task",
                "task_type": PROMPT_TASK_ON_MODEL,
                "priority": 20,
                "is_active": True,
                "match_rules": {
                    "request.style.public_version_key": {"in": ["v2", "2"]},
                },
                "engine_slug": "on-model-v2",
                "notes": "Task-first route for on-model V2 requests.",
            },
            {
                "slug": "on-model-legacy-task-route",
                "name": "On-Model Legacy Task",
                "task_type": PROMPT_TASK_ON_MODEL,
                "priority": 100,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "on-model-legacy",
                "notes": "Task-first fallback route for on-model requests.",
            },
            {
                "slug": "on-model-edit-default-task-route",
                "name": "On-Model Edit",
                "task_type": PROMPT_TASK_ON_MODEL_EDIT,
                "priority": 1,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "on-model-edit-default",
                "notes": "DB-managed image edit route for on-model requests.",
            },
            {
                "slug": "planner-enrich-default-route",
                "name": "Planner Enrich Default",
                "task_type": PROMPT_TASK_PLANNER_ENRICH,
                "priority": 10,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "planner-enrich-default",
                "notes": "Default planner enrichment route.",
            },
            {
                "slug": "planner-rank-default-route",
                "name": "Planner Rank Default",
                "task_type": PROMPT_TASK_PLANNER_RANK,
                "priority": 10,
                "is_active": True,
                "match_rules": {},
                "engine_slug": "planner-rank-default",
                "notes": "Default planner ranking route.",
            },
        ],
    }
