"""Default prompt-engine registry definitions.

These seeds are used to bootstrap the DB-backed prompt registry and also act as
an offline fallback when the registry database is unavailable in tests.
"""

from __future__ import annotations

from copy import deepcopy
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
from .ui_defaults import get_default_engine_ui_blocks

PROMPT_TASK_IMAGE_GENERATION_COMPOSE = "image_generation.compose"
PROMPT_TASK_IMAGE_GENERATION_DEFAULTS = "image_generation.defaults"
PROMPT_TASK_PLANNER_ENRICH = "planner.enrich"
PROMPT_TASK_PLANNER_RANK = "planner.rank"

_ENGINE_UI_BLOCKS = get_default_engine_ui_blocks()

_DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, distorted, duplicate, text artifact, watermark, logo,"
    " extra limbs, cropped, bad anatomy, text overlays, captions, numbers"
)

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
            "prompt_version",
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
        "mapping": deepcopy(_ON_MODEL_MAPPING_V2),
        "ui": deepcopy(_ENGINE_UI_BLOCKS["on-model-v2"]),
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
        "mapping": deepcopy(_ON_MODEL_MAPPING_V45),
        "ui": deepcopy(_ENGINE_UI_BLOCKS["on-model-v4-5"]),
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
        "styles": deepcopy(_PURE_JEWELRY_STYLES),
        "ui": deepcopy(_ENGINE_UI_BLOCKS["pure-jewelry-v5-2"]),
    }


def _pure_jewelry_legacy_definition() -> dict[str, Any]:
    return {
        "negative_prompt": _DEFAULT_NEGATIVE_PROMPT,
        "templates": deepcopy(_LEGACY_PURE_JEWELRY_TEMPLATES),
        "fallback_definition": _on_model_legacy_definition(),
        "ui": deepcopy(_ENGINE_UI_BLOCKS["pure-jewelry-legacy"]),
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
        "engines": [
            {
                "slug": "image-generation-defaults",
                "name": "Image Generation Defaults",
                "description": "Shared negative prompt defaults for direct image-generation calls.",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
                "renderer_key": "image_defaults_v1",
                "input_schema": deepcopy(_IMAGE_DEFAULTS_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "change_note": "Seeded from the legacy inline negative-prompt defaults.",
                    "sample_input": {"extras": ["overexposed"], "items": [{"type": "Ring", "size": "Medium"}]},
                    "definition": _image_defaults_definition(),
                },
            },
            {
                "slug": "on-model-legacy",
                "name": "On-Model Legacy",
                "description": "Legacy on-model prompt builder for older clients without sectioned prompt versions.",
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "renderer_key": "on_model_legacy_v1",
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "on-model"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
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
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "renderer_key": "on_model_sections_v1",
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "on-model", "version": "v2"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "change_note": "Seeded from the legacy inline on-model V2 definitions.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "model"},
                            "style": {"prompt_version": "v2", "background": "Blue Hour Editorial"},
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
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "renderer_key": "on_model_sections_v1",
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "on-model", "version": "v4.5"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "change_note": "Seeded from the legacy inline on-model V4.5 definitions.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "model"},
                            "style": {"prompt_version": "v4.5", "background": "White Studio"},
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
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "renderer_key": "pure_jewelry_legacy_v1",
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "pure-jewelry", "version": "legacy"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
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
                "task_type": PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
                "renderer_key": "pure_jewelry_sections_v1",
                "input_schema": deepcopy(_IMAGE_COMPOSE_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "image-generation", "surface": "pure-jewelry", "version": "v5.2"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
                    "change_note": "Seeded from the legacy inline pure-jewelry V5.2 definitions.",
                    "sample_input": {
                        "request": {
                            "model": {"slug": "pure-jewelry"},
                            "style": {"prompt_version": "v5.2", "style_type": "pure-studio"},
                            "looks": 1,
                            "items": [{"type": "Ring", "size": "Very Small"}],
                        }
                    },
                    "definition": _pure_jewelry_v52_definition(),
                },
            },
            {
                "slug": "planner-enrich-default",
                "name": "Planner Enrich Default",
                "description": "Default system and user prompt templates for planner enrichment.",
                "task_type": PROMPT_TASK_PLANNER_ENRICH,
                "renderer_key": "planner_enrich_v1",
                "input_schema": deepcopy(_PLANNER_ENRICH_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "planner"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
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
                "renderer_key": "planner_rank_v1",
                "input_schema": deepcopy(_PLANNER_RANK_INPUT_SCHEMA),
                "output_schema": {"type": "object"},
                "labels": {"family": "planner"},
                "initial_version": {
                    "version_number": 1,
                    "status": "published",
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
                    "request.style.prompt_version": {"in": ["v5.2", "5.2"]},
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
                    "request.style.prompt_version": {"in": ["v4.5", "4.5", "v45", "45"]},
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
                    "request.style.prompt_version": {"in": ["v2", "2"]},
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
