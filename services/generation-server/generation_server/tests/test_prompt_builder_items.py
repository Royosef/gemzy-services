
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from generation_server.models import GenerationRequest, GenerationDimensions, GenerationModel, GenerationUpload, GenerationItem
from generation_server.prompt_builder import build_prompts

def _base_request() -> GenerationRequest:
    return GenerationRequest(
        uploads=[
            GenerationUpload(
                id="u1", uri="x", base64="x", name="x.png"
            )
        ],
        model=GenerationModel(
            id="m1", slug="m", name="M", planTier="Pro", imageUri="x"
        ),
        style={}, # defaults
        mode="SIMPLE",
        aspect="1:1",
        dims=GenerationDimensions(w=512, h=512),
        looks=1,
        quality="1k",
        plan="Pro",
        creditsNeeded=1,
    )

def test_prompt_includes_item_descriptions():
    req = _base_request()
    req.items = [
        GenerationItem(id="i1", type="Necklace", size="Small", uploadId="u1"),
        GenerationItem(id="i2", type="Ring", size="Medium", uploadId="u2"),
    ]
    
    prompts = build_prompts(req)
    prompt = prompts[0]
    
    assert "a Small Necklace" in prompt
    assert "a Medium Ring" in prompt
    assert "Generate an image of the model wearing the following jewelry pieces: a Small Necklace, a Medium Ring." in prompt

def test_prompt_backward_compatibility_empty_items():
    req = _base_request()
    req.items = [] # Empty items
    req.style["product"] = "Earrings"
    
    prompts = build_prompts(req)
    prompt = prompts[0]
    
    # Should fall back to style.product
    assert "Generate an image of the model wearing the following jewelry pieces: Earrings." in prompt

def test_prompt_backward_compatibility_missing_types():
    req = _base_request()
    # Items without type/size
    req.items = [
        GenerationItem(id="i1", type="", size="", uploadId="u1")
    ]
    req.style["product"] = "Bracelet" 
    
    prompts = build_prompts(req)
    prompt = prompts[0]
    
    # If items exist but have no description, our logic currently returns empty string for them
    # and since the list is not empty, it returns empty string? 
    # Let's check the implementation:
    # item_descriptions = _build_item_descriptions(request.items)
    # loops over items... if parts is empty, description is empty.
    # returns ""
    # if not item_descriptions: fallback to product_type
    
    # So it should fall back to style.product "Bracelet"
    assert "Generate an image of the model wearing the following jewelry pieces: Bracelet." in prompt

def test_prompt_partial_item_info():
    req = _base_request()
    req.items = [
        GenerationItem(id="i1", type="Necklace", size="", uploadId="u1"), # Type only
        GenerationItem(id="i2", type="", size="Large", uploadId="u2"),    # Size only
    ]
    
    prompts = build_prompts(req)
    prompt = prompts[0]
    
    assert "a Necklace" in prompt
    assert "a Large" in prompt # "a Large" might look weird but that's what the logic dictates


def test_prompt_includes_per_item_type_guidance():
    req = _base_request()
    req.style["public_version_key"] = "v4.5"
    req.items = [
        GenerationItem(id="i1", type="Necklace", size="Small", uploadId="u1"),
        GenerationItem(id="i2", type="Ring", size="Medium", uploadId="u2"),
    ]

    prompt = build_prompts(req)[0]

    assert "JEWELRY TYPE: Necklace" in prompt
    assert "Jewelry worn around the neck against the chest or collarbone." in prompt
    assert "JEWELRY ITEM 2 TYPE: Ring" in prompt
    assert "JEWELRY ITEM 2 SIZE: Medium" in prompt


def test_v52_pure_jewelry_prompt_includes_each_item_type_and_size():
    req = _base_request()
    req.model.slug = "pure-jewelry"
    req.style.update(
        {
            "task_type": "pure-jewelry",
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
        }
    )
    req.items = [
        GenerationItem(id="i1", type="Necklace", size="Small", uploadId="u1"),
        GenerationItem(id="i2", type="Ring", size="Medium", uploadId="u2"),
    ]

    prompt = build_prompts(req)[0]

    assert "JEWELRY TYPE: Necklace" in prompt
    assert "JEWELRY SIZE: Small" in prompt
    assert "JEWELRY ITEM 2 TYPE: Ring" in prompt
    assert "JEWELRY ITEM 2 SIZE: Medium" in prompt


def test_prompt_includes_medium_size_guidance():
    req = _base_request()
    req.style["public_version_key"] = "v4.5"
    req.items = [
        GenerationItem(id="i1", type="Ring", size="Medium", uploadId="u1"),
    ]

    prompt = build_prompts(req)[0]

    assert "JEWELRY SIZE: Medium" in prompt
    assert "WEARER-RELATIVE PHYSICAL SCALE OVERRIDE" in prompt
    assert "moderate physical scale relative to the adjacent anatomy" in prompt


@pytest.mark.parametrize("public_version_key", ["v2", "v4.5"])
def test_on_model_very_small_size_is_wearer_relative(public_version_key: str):
    req = _base_request()
    req.style["public_version_key"] = public_version_key
    req.items = [
        GenerationItem(id="i1", type="Earrings", size="Very Small", uploadId="u1"),
    ]

    prompt = build_prompts(req)[0]

    assert "JEWELRY SIZE: Very Small" in prompt or "SCALE & PROPORTION" in prompt
    assert "WEARER-RELATIVE PHYSICAL SCALE OVERRIDE" in prompt
    assert "source image crop and pixel size are not evidence of physical size" in prompt
    assert "product-to-anatomy size ratio must remain very small" in prompt
    assert "scale each earring separately; never treat the pair as one combined object" in prompt
    assert "entire intact product" not in prompt


def test_v45_size_fidelity_treats_an_earring_set_as_separate_pieces():
    req = _base_request()
    req.style["public_version_key"] = "v4.5"
    req.items = [
        GenerationItem(id="i1", type="Earrings", size="Very Small", uploadId="u1"),
    ]

    prompt = build_prompts(req)[0]

    assert "scale each distinct piece independently" in prompt
    assert "Never fuse, group, or co-locate separate pieces" in prompt
    assert "never let scale override the one-earring-per-ear placement grid" in prompt


@pytest.mark.parametrize("public_version_key", ["v2", "v4.5"])
def test_on_model_earrings_preserve_mismatched_pair(public_version_key: str):
    req = _base_request()
    req.style["public_version_key"] = public_version_key
    req.items = [
        GenerationItem(id="i1", type="Earrings", size="Medium", uploadId="u1"),
    ]

    prompt = build_prompts(req)[0]

    assert "two non-identical earrings" in prompt
    assert "EAR PLACEMENT GRID" in prompt
    assert "strict [1 left, 1 right] distribution" in prompt
    assert "Never place both product earrings on the same ear" in prompt
    assert "overrides conflicting pose, hair, camera" in prompt
    assert "Never duplicate one design" in prompt


def test_v52_pure_jewelry_earrings_preserve_mismatched_pair():
    req = _base_request()
    req.model.slug = "pure-jewelry"
    req.style.update(
        {
            "task_type": "pure-jewelry",
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
        }
    )
    req.items = [
        GenerationItem(id="i1", type="Earrings", size="Medium", uploadId="u1"),
    ]

    prompt = build_prompts(req)[0]

    assert "two non-identical earrings" in prompt
    assert "both distinct pieces are the product" in prompt
    assert "Never duplicate one design" in prompt


def test_v52_pure_jewelry_very_small_size_uses_scene_scale_cues():
    req = _base_request()
    req.model.slug = "pure-jewelry"
    req.style.update(
        {
            "task_type": "pure-jewelry",
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
        }
    )
    req.items = [
        GenerationItem(id="i1", type="Ring", size="Very Small", uploadId="u1"),
    ]

    prompt = build_prompts(req)[0]

    assert "JEWELRY SIZE: Very Small" in prompt
    assert "SCENE-RELATIVE PHYSICAL SCALE OVERRIDE" in prompt
    assert "Surface grain, contact shadow, permitted props, and generous negative space" in prompt
    assert "must never read as large relative to its environment" in prompt


def test_v45_prompt_uses_html_section_labels():
    req = _base_request()
    req.style.update({
        "public_version_key": "v4.5",
        "background": "White Studio",
        "camera": "Portrait",
        "image_style": "Natural",
    })
    req.items = [GenerationItem(id="i1", type="Ring", size="Small", uploadId="u1")]

    prompt = build_prompts(req)[0]

    assert prompt.startswith("HERO\nUltra-realistic editorial jewelry photograph.")
    assert "\nMODEL\nSkin is photographically real" in prompt
    assert "\nSCENE: White Studio\n" in prompt
    assert "\nJEWELRY TYPE: Ring\n" in prompt
    assert "\nCAMERA STYLE: Portrait\n" in prompt
    assert "\nSTYLE: Natural\n" in prompt
    assert "QUALITY CONTROL" in prompt


def test_v45_prompt_accepts_option_ids():
    req = _base_request()
    req.style.update({
        "public_version_key": "v4.5",
        "background": "white-studio",
        "camera": "portrait",
        "image_style": "natural",
    })
    req.items = [GenerationItem(id="i1", type="Ring", size="Small", uploadId="u1")]

    prompt = build_prompts(req)[0]

    assert "\nSCENE: White Studio\n" in prompt
    assert "\nCAMERA STYLE: Portrait\n" in prompt
    assert "\nSTYLE: Natural\n" in prompt


def test_prompt_v2_labels_still_expand_with_v2_version():
    req = _base_request()
    req.style.update({
        "public_version_key": "v2",
        "background": "Blue Hour Editorial",
        "hair": "Natural Hair",
        "outfit": "Minimal Luxury",
        "lighting": "Soft Studio Light",
        "camera": "Editorial Portrait",
        "image_style": "Natural Balanced",
    })

    prompt = build_prompts(req)[0]

    assert "Blue Hour Editorial — Portrait captured during blue hour twilight" in prompt
    assert "Natural Hair — Hair styled naturally according to the model's hairstyle" in prompt
    assert "Minimal Luxury — Minimal luxury fashion styling" in prompt
    assert "Soft Studio Light — Large diffused key light softly illuminating the subject" in prompt
    assert "Natural Balanced — Natural color grading, balanced contrast" in prompt
