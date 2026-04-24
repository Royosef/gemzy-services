"""Default server-driven generation UI catalog.

The current mobile app has two existing generation surfaces that still need to
render exactly like the hard-coded client UI:

- on-model
- pure-jewelry

We keep the prompt runtime and the UI contract adjacent by attaching a small
``ui`` block to the published prompt-engine definitions. The public server
endpoint then exposes a catalog derived from those published versions, with a
local fallback defined here so older databases still work.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .on_model_constants import _ON_MODEL_MAPPING_V2, _ON_MODEL_MAPPING_V45
from .pure_jewelry_prompts import _PURE_JEWELRY_STYLES

GENERATION_UI_CATALOG_VERSION = "generation-ui-v1"


def _slugify_label(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def _option(
    label: str,
    *,
    option_id: str | None = None,
    has_color: bool = False,
    color_label: str | None = None,
) -> dict[str, Any]:
    return {
        "id": option_id or _slugify_label(label),
        "label": label,
        "hasColor": bool(has_color),
        "colorLabel": color_label,
    }


def _build_selector(
    engine_id: str,
    *,
    pill_label: str,
    title: str,
    description: str,
    sort_order: int,
    badge: str | None = None,
    image_key: str | None = None,
    badge_image_key: str | None = None,
) -> dict[str, Any]:
    return {
        "id": engine_id,
        "pillLabel": pill_label,
        "title": title,
        "description": description,
        "badge": badge,
        "imageKey": image_key,
        "badgeImageKey": badge_image_key,
        "sortOrder": sort_order,
    }


def _item_options(labels: list[str]) -> list[dict[str, Any]]:
    return [_option(label) for label in labels]


_ITEM_TYPE_LABELS = [
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

_ITEM_SIZE_LABELS = [
    "Very Small",
    "Small",
    "Medium",
    "Big",
    "Very Big",
]

_DEFAULT_ITEM_TYPES = _item_options(_ITEM_TYPE_LABELS)
_DEFAULT_ITEM_SIZES = _item_options(_ITEM_SIZE_LABELS)

_ENGINE_SELECTORS = {
    "v2": _build_selector(
        "v2",
        pill_label="Gemzy V2",
        title="Gemzy V2",
        description="Sharper placements, realistic lighting, true-to-jewelry detail.",
        badge="New",
        image_key="engine-v2",
        badge_image_key="new-badge",
        sort_order=10,
    ),
    "v1": _build_selector(
        "v1",
        pill_label="Gemzy V1",
        title="Gemzy V1 (Classic)",
        description="Our original engine. Best used for comparison.",
        image_key="engine-v1",
        sort_order=20,
    ),
}

_ON_MODEL_SECTION_META = {
    "background": {
        "label": "Scene",
        "description": "Set your model's environment",
        "iconKey": "mountains",
    },
    "emotion": {
        "label": "Emotion",
        "description": "Choose expression and mood",
        "iconKey": "smiley",
    },
    "hair": {
        "label": "Hair",
        "description": "Style your model's hair",
        "iconKey": "hairdryer",
    },
    "outfit": {
        "label": "Outfit",
        "description": "Pick outfit and styling",
        "iconKey": "coat-hanger",
    },
    "pose": {
        "label": "Pose",
        "description": "Control pose and framing",
        "iconKey": "person-arms-spread",
    },
    "lighting": {
        "label": "Lighting",
        "description": "Shape light and atmosphere",
        "iconKey": "sun",
    },
    "camera": {
        "label": "Camera Style",
        "description": "Adjust angle and lens feel",
        "iconKey": "aperture",
    },
    "image_style": {
        "label": "Style",
        "description": "Apply a visual style",
        "iconKey": "paint-brush",
    },
}

_ON_MODEL_V1_FREE_OPTION_LABELS = {
    "background": [],
    "emotion": "__all__",
    "hair": [],
    "outfit": [],
    "pose": "__all__",
    "lighting": [],
    "camera": "__all__",
    "image_style": [],
}

_ON_MODEL_V2_FREE_OPTION_LABELS = {
    "background": ["White Studio"],
    "emotion": ["Soft Warmth"],
    "hair": ["Natural"],
    "outfit": ["Casual Cool"],
    "pose": ["Candid", "At Rest"],
    "lighting": ["Soft Wrap"],
    "camera": ["Beauty Close-Up", "Portrait"],
    "image_style": ["Natural"],
}


def _build_on_model_sections(
    mapping: dict[str, dict[str, str]],
    *,
    free_option_labels: dict[str, list[str] | str],
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section_id, meta in _ON_MODEL_SECTION_META.items():
        labels = list((mapping.get(section_id) or {}).keys())
        free_values = free_option_labels.get(section_id)
        if free_values == "__all__":
            normalized_free = list(labels)
        else:
            normalized_free = list(free_values or [])
        sections.append(
            {
                "id": section_id,
                "label": meta["label"],
                "description": meta["description"],
                "iconKey": meta["iconKey"],
                "editTier": "Pro",
                "supportsRandom": True,
                "freeOptionLabels": normalized_free,
                "options": [_option(label) for label in labels],
            }
        )
    return sections


def _build_on_model_ui(
    *,
    engine_id: str,
    prompt_version: str,
    mapping: dict[str, dict[str, str]],
    free_option_labels: dict[str, list[str] | str],
    trial_task_label: str,
    is_default: bool,
) -> dict[str, Any]:
    return {
        "surface": "onModel",
        "engineId": engine_id,
        "promptVersion": prompt_version,
        "isDefault": is_default,
        "selector": deepcopy(_ENGINE_SELECTORS[engine_id]),
        "trialTaskLabel": trial_task_label,
        "trialPopupImageKey": "on-model-pro-popup",
        "itemTypes": deepcopy(_DEFAULT_ITEM_TYPES),
        "itemSizes": deepcopy(_DEFAULT_ITEM_SIZES),
        "sections": _build_on_model_sections(mapping, free_option_labels=free_option_labels),
    }


_PURE_JEWELRY_V2_STYLE_META = {
    "pure-studio": {
        "title": "Pure Studio",
        "imageKey": "pure-studio",
        "parameters": {
            "scene": {
                "label": "Scene",
                "description": "Studio environment",
                "iconKey": "mountains",
                "editTier": "Pro",
                "freeOptionLabels": ["Pure White"],
            },
            "surface": {
                "label": "Surface",
                "description": "What the jewelry rests on",
                "iconKey": "stack",
                "editTier": "Pro",
                "freeOptionLabels": ["Studio Seamless"],
            },
            "lighting": {
                "label": "Lighting",
                "description": "How light behaves",
                "iconKey": "sun",
                "editTier": "Pro",
                "freeOptionLabels": ["Soft Diffused"],
            },
            "shadow": {
                "label": "Shadow",
                "description": "Shadow behavior",
                "iconKey": "target",
                "editTier": "Pro",
                "freeOptionLabels": ["None", "Soft"],
            },
            "composition": {
                "label": "Composition",
                "description": "Camera position, angle & distance",
                "iconKey": "camera",
                "editTier": "Pro",
                "freeOptionLabels": ["Centered", "Flat Lay"],
            },
        },
    },
    "object-world": {
        "title": "Object World",
        "imageKey": "object-world",
        "parameters": {
            "object-territory": {
                "label": "Object Territory",
                "description": "The world the object comes from",
                "iconKey": "mountains",
                "editTier": "Pro",
                "freeOptionLabels": ["Living & Fresh"],
            },
            "relationship": {
                "label": "Relationship",
                "description": "How jewelry and object interact",
                "iconKey": "target",
                "editTier": "Pro",
                "freeOptionLabels": ["Resting On"],
            },
            "lighting": {
                "label": "Lighting",
                "description": "How light behaves",
                "iconKey": "sun",
                "editTier": "Pro",
                "freeOptionLabels": ["Soft Diffused"],
            },
            "mood": {
                "label": "Mood",
                "description": "The emotional register of the image",
                "iconKey": "magic-wand",
                "editTier": "Pro",
                "freeOptionLabels": ["Intimate"],
            },
            "composition": {
                "label": "Composition",
                "description": "Camera position, angle & distance",
                "iconKey": "camera",
                "editTier": "Pro",
                "freeOptionLabels": ["Centered", "Flat Lay"],
            },
            "brand-accent": {
                "label": "Brand Accent",
                "description": "Your brand color in the scene",
                "iconKey": "palette",
                "editTier": "Pro",
                "freeOptionLabels": ["None"],
            },
        },
    },
    "surface-light": {
        "title": "Surface & Light",
        "imageKey": "surface-light",
        "parameters": {
            "surface": {
                "label": "Surface",
                "description": "The natural surface",
                "iconKey": "stack",
                "editTier": "Pro",
                "freeOptionLabels": ["Sand", "Stone Slab"],
            },
            "light-direction": {
                "label": "Light Direction",
                "description": "Where light comes from",
                "iconKey": "sun",
                "editTier": "Pro",
                "freeOptionLabels": ["Diffused Overcast"],
            },
            "shadow-play": {
                "label": "Shadow Play",
                "description": "The role of shadows",
                "iconKey": "magic-wand",
                "editTier": "Pro",
                "freeOptionLabels": ["None"],
            },
            "color-temperature": {
                "label": "Color Temperature",
                "description": "The tonal world of the light",
                "iconKey": "palette",
                "editTier": "Pro",
                "freeOptionLabels": ["Cool Neutral"],
            },
            "composition": {
                "label": "Composition",
                "description": "Camera position, angle & distance",
                "iconKey": "camera",
                "editTier": "Pro",
                "freeOptionLabels": ["Centered", "Flat Lay"],
            },
            "brand-accent": {
                "label": "Brand Accent",
                "description": "Your brand color in the scene",
                "iconKey": "palette",
                "editTier": "Pro",
                "freeOptionLabels": ["None"],
            },
        },
    },
    "arranged": {
        "title": "Arranged",
        "imageKey": "arranged",
        "parameters": {
            "arrangement-style": {
                "label": "Arrangement Style",
                "description": "How pieces are organized",
                "iconKey": "squares-four",
                "editTier": "Pro",
                "freeOptionLabels": ["Clean Grid"],
            },
            "surface": {
                "label": "Surface",
                "description": "The stage for the arrangement",
                "iconKey": "stack",
                "editTier": "Pro",
                "freeOptionLabels": ["Pure White"],
            },
            "lighting": {
                "label": "Lighting",
                "description": "How light behaves",
                "iconKey": "sun",
                "editTier": "Pro",
                "freeOptionLabels": ["Soft Diffused"],
            },
            "quantity": {
                "label": "Quantity",
                "description": "How many pieces",
                "iconKey": "hash",
                "freeOptionLabels": ["Pair", "Small Collection", "Full Collection"],
            },
            "color-palette": {
                "label": "Color Palette",
                "description": "The tonal world of the image",
                "iconKey": "palette",
                "editTier": "Pro",
                "freeOptionLabels": ["Neutral & Clean"],
            },
            "composition": {
                "label": "Composition",
                "description": "Camera position, angle & distance",
                "iconKey": "camera",
                "editTier": "Pro",
                "freeOptionLabels": ["Centered", "Flat Lay"],
            },
        },
    },
    "on-display": {
        "title": "On Display",
        "imageKey": "on-display",
        "parameters": {
            "display-form": {
                "label": "Display Form",
                "description": "What holds the jewelry",
                "iconKey": "user",
                "editTier": "Pro",
                "freeOptionLabels": ["Ceramic Bust"],
            },
            "display-color": {
                "label": "Display Color",
                "description": "The tone of the display form",
                "iconKey": "palette",
                "editTier": "Pro",
                "freeOptionLabels": ["Pure White"],
            },
            "scene": {
                "label": "Scene",
                "description": "The environment behind the form",
                "iconKey": "mountains",
                "editTier": "Pro",
                "freeOptionLabels": ["Pure White"],
            },
            "lighting": {
                "label": "Lighting",
                "description": "How light behaves",
                "iconKey": "sun",
                "editTier": "Pro",
                "freeOptionLabels": ["Soft Diffused"],
            },
            "angle": {
                "label": "Angle",
                "description": "How the form is presented to camera",
                "iconKey": "camera",
                "editTier": "Pro",
                "freeOptionLabels": ["Front Facing", "Slight Tilt"],
            },
        },
    },
}


def _build_pure_v2_styles() -> list[dict[str, Any]]:
    styles: list[dict[str, Any]] = []
    for style_id, style_definition in _PURE_JEWELRY_STYLES.items():
        style_meta = _PURE_JEWELRY_V2_STYLE_META.get(style_id)
        if not style_meta:
            continue

        parameters: list[dict[str, Any]] = []
        for parameter_id, _heading, option_map in style_definition.get("categories") or []:
            parameter_meta = style_meta["parameters"].get(parameter_id)
            if not parameter_meta:
                continue
            options: list[dict[str, Any]] = []
            for option_label, option_definition in (option_map or {}).items():
                has_color = isinstance(option_definition, dict) and bool(option_definition.get("has_color"))
                options.append(
                    _option(
                        option_label,
                        has_color=has_color,
                        color_label=option_label if has_color else None,
                    )
                )
            parameters.append(
                {
                    "id": parameter_id,
                    "label": parameter_meta["label"],
                    "description": parameter_meta["description"],
                    "iconKey": parameter_meta["iconKey"],
                    "editTier": parameter_meta.get("editTier"),
                    "supportsRandom": False,
                    "freeOptionLabels": list(parameter_meta.get("freeOptionLabels") or []),
                    "options": options,
                }
            )
        styles.append(
            {
                "id": style_id,
                "title": style_meta["title"],
                "imageKey": style_meta["imageKey"],
                "parameters": parameters,
            }
        )
    return styles


_LEGACY_LIGHTING_OPTIONS = [
    "Soft Diffused",
    "Hard Directional",
    "Side Rim",
    "Top Down",
    "Backlit",
    "Bloom",
]

_LEGACY_COMPOSITION_OPTIONS = [
    "Centered",
    "Off Center",
    "Close Up",
    "Flat Lay",
    "Angled",
]


def _legacy_section(
    section_id: str,
    label: str,
    description: str,
    icon_key: str,
    option_labels: list[str],
    *,
    edit_tier: str | None = None,
    color_option_labels: set[str] | None = None,
    color_label_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    color_option_labels = color_option_labels or set()
    color_label_map = color_label_map or {}
    return {
        "id": section_id,
        "label": label,
        "description": description,
        "iconKey": icon_key,
        "editTier": edit_tier,
        "supportsRandom": False,
        "freeOptionLabels": [],
        "options": [
            _option(
                option_label,
                has_color=option_label in color_option_labels,
                color_label=color_label_map.get(option_label),
            )
            for option_label in option_labels
        ],
    }


def _build_pure_legacy_styles() -> list[dict[str, Any]]:
    return [
        {
            "id": "studio-shot",
            "title": "Studio Shot",
            "imageKey": "studio-shot",
            "parameters": [
                _legacy_section(
                    "background",
                    "Background",
                    "Studio backdrop",
                    "mountains",
                    ["Pure White", "Soft Gray", "Deep Black", "Warm Ivory", "Studio Color (Dynamic)"],
                    color_option_labels={"Studio Color (Dynamic)"},
                    color_label_map={"Studio Color (Dynamic)": "Studio Color"},
                ),
                _legacy_section(
                    "surface",
                    "Surface",
                    "What the jewelry rests on",
                    "stack",
                    ["Floating", "Studio Seamless", "Silk", "Velvet", "Marble", "Glass"],
                ),
                _legacy_section(
                    "lighting",
                    "Lighting",
                    "Light direction and softness",
                    "sun",
                    _LEGACY_LIGHTING_OPTIONS,
                    edit_tier="Pro",
                ),
                _legacy_section(
                    "add-ons",
                    "Add-ons",
                    "Subtle styling extras",
                    "magic-wand",
                    ["None", "Mirror Accent", "Stone Accent", "Ribbon", "Petals"],
                    edit_tier="Pro",
                ),
            ],
        },
        {
            "id": "lifestyle",
            "title": "Lifestyle",
            "imageKey": "lifestyle",
            "parameters": [
                _legacy_section(
                    "base",
                    "Base",
                    "Where the jewelry is placed",
                    "stack",
                    ["Fabric", "Stone", "Wood", "Ceramic", "Glass", "Marble"],
                ),
                _legacy_section(
                    "color-palette",
                    "Color Palette",
                    "The tonal mood of the image",
                    "palette",
                    ["Neutral", "Warm", "Cool", "Earthy", "Moody"],
                ),
                _legacy_section(
                    "lighting",
                    "Lighting",
                    "How light behaves",
                    "sun",
                    ["Natural Daylight", "Golden Hour", "Soft Diffused", "Backlit"],
                    edit_tier="Pro",
                ),
                _legacy_section(
                    "composition",
                    "Composition",
                    "Camera position, angle & distance",
                    "camera",
                    _LEGACY_COMPOSITION_OPTIONS,
                ),
                _legacy_section(
                    "add-ons",
                    "Add-ons",
                    "Subtle styling extras",
                    "magic-wand",
                    ["None", "Botanical Accent", "Paper Prop", "Glass Prop"],
                    edit_tier="Pro",
                ),
            ],
        },
        {
            "id": "collection",
            "title": "Collection",
            "imageKey": "collection",
            "parameters": [
                _legacy_section(
                    "quantity",
                    "Quantity",
                    "How many repeated pieces",
                    "hash",
                    ["2 items", "3 items", "5 items"],
                ),
                _legacy_section(
                    "arrangement",
                    "Arrangement",
                    "How the pieces are organized",
                    "squares-four",
                    ["Clean grid", "Organic scatter", "Radial", "Linear"],
                ),
                _legacy_section(
                    "emphasis",
                    "Emphasis",
                    "What the eye notices first",
                    "target",
                    ["Balanced focus", "Hero first", "Symmetry", "Texture play"],
                ),
                _legacy_section(
                    "background",
                    "Background",
                    "Backdrop for the arrangement",
                    "mountains",
                    ["Studio neutral", "Pure White", "Soft Gray", "Deep Black", "Studio Color (Dynamic)"],
                    color_option_labels={"Studio Color (Dynamic)"},
                    color_label_map={"Studio Color (Dynamic)": "Studio Color"},
                ),
                _legacy_section(
                    "lighting",
                    "Lighting",
                    "Light behavior across the set",
                    "sun",
                    ["Catalog lighting", "Soft Diffused", "Hard Directional"],
                    edit_tier="Pro",
                ),
            ],
        },
        {
            "id": "on-dummy",
            "title": "On Display",
            "imageKey": "on-dummy",
            "parameters": [
                _legacy_section(
                    "dummy-type",
                    "Display Form",
                    "What holds the jewelry",
                    "user",
                    ["Ceramic bust", "Stone bust", "Abstract form", "Minimal mannequin"],
                ),
                _legacy_section(
                    "dummy-color",
                    "Display Color",
                    "The tone of the display form",
                    "palette",
                    ["White", "Warm Beige", "Stone Gray", "Matte Black"],
                ),
                _legacy_section(
                    "pose-angle",
                    "Angle",
                    "How the form faces camera",
                    "camera",
                    ["Front-facing", "Slight tilt", "Profile", "Close-up"],
                ),
                _legacy_section(
                    "lighting",
                    "Lighting",
                    "How light shapes the form",
                    "sun",
                    ["Soft studio", "Soft Diffused", "Hard Directional"],
                    edit_tier="Pro",
                ),
                _legacy_section(
                    "background",
                    "Background",
                    "The environment behind the form",
                    "mountains",
                    ["Studio clean", "Pure White", "Soft Gray", "Deep Black", "Studio Color (Dynamic)"],
                    color_option_labels={"Studio Color (Dynamic)"},
                    color_label_map={"Studio Color (Dynamic)": "Studio Color"},
                ),
            ],
        },
    ]


def _build_pure_jewelry_ui(
    *,
    engine_id: str,
    prompt_version: str,
    styles: list[dict[str, Any]],
    default_style_id: str,
    is_default: bool,
) -> dict[str, Any]:
    return {
        "surface": "pureJewelry",
        "engineId": engine_id,
        "promptVersion": prompt_version,
        "isDefault": is_default,
        "selector": deepcopy(_ENGINE_SELECTORS[engine_id]),
        "trialTaskLabel": "Pure Jewelry Presets",
        "trialPopupImageKey": "pure-jewelry-pro-popup",
        "itemTypes": deepcopy(_DEFAULT_ITEM_TYPES),
        "itemSizes": deepcopy(_DEFAULT_ITEM_SIZES),
        "defaultStyleId": default_style_id,
        "styles": styles,
    }


def get_default_engine_ui_blocks() -> dict[str, dict[str, Any]]:
    """Return the default per-engine UI blocks keyed by prompt-engine slug."""

    return {
        "on-model-v2": _build_on_model_ui(
            engine_id="v1",
            prompt_version="v2",
            mapping=_ON_MODEL_MAPPING_V2,
            free_option_labels=_ON_MODEL_V1_FREE_OPTION_LABELS,
            trial_task_label="On Model - V1 Presets",
            is_default=False,
        ),
        "on-model-v4-5": _build_on_model_ui(
            engine_id="v2",
            prompt_version="v4.5",
            mapping=_ON_MODEL_MAPPING_V45,
            free_option_labels=_ON_MODEL_V2_FREE_OPTION_LABELS,
            trial_task_label="On Model - V2 Presets",
            is_default=True,
        ),
        "pure-jewelry-legacy": _build_pure_jewelry_ui(
            engine_id="v1",
            prompt_version="v1",
            styles=_build_pure_legacy_styles(),
            default_style_id="studio-shot",
            is_default=False,
        ),
        "pure-jewelry-v5-2": _build_pure_jewelry_ui(
            engine_id="v2",
            prompt_version="v5.2",
            styles=_build_pure_v2_styles(),
            default_style_id="pure-studio",
            is_default=True,
        ),
    }


def _finalize_surface(engines: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (deepcopy(engine) for engine in engines),
        key=lambda engine: int((engine.get("selector") or {}).get("sortOrder") or 100),
    )
    default_engine_id = next(
        (str(engine.get("engineId")) for engine in ordered if bool(engine.get("isDefault"))),
        str(ordered[0].get("engineId")) if ordered else "",
    )
    return {
        "defaultEngineId": default_engine_id,
        "engines": ordered,
    }


def get_default_generation_ui_catalog() -> dict[str, Any]:
    """Return the default public generation UI catalog."""

    blocks = get_default_engine_ui_blocks()
    on_model_engines = [
        {**deepcopy(blocks["on-model-v2"]), "engineSlug": "on-model-v2"},
        {**deepcopy(blocks["on-model-v4-5"]), "engineSlug": "on-model-v4-5"},
    ]
    pure_jewelry_engines = [
        {**deepcopy(blocks["pure-jewelry-legacy"]), "engineSlug": "pure-jewelry-legacy"},
        {**deepcopy(blocks["pure-jewelry-v5-2"]), "engineSlug": "pure-jewelry-v5-2"},
    ]
    return {
        "version": GENERATION_UI_CATALOG_VERSION,
        "onModel": _finalize_surface(on_model_engines),
        "pureJewelry": _finalize_surface(pure_jewelry_engines),
    }
