from prompting import render_default_task


def _rendered_prompt(task_type: str, style: dict[str, str]) -> str:
    rendered = render_default_task(
        task_type,
        {
            "request": {
                "style": style,
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )
    return "\n".join(rendered["prompts"])


def _rendered_prompts(task_type: str, style: dict[str, str], looks: int) -> list[str]:
    rendered = render_default_task(
        task_type,
        {
            "request": {
                "style": style,
                "items": [{"type": "Ring", "size": "Small"}],
                "looks": looks,
            }
        },
    )
    return rendered["prompts"]


def test_on_model_appends_curated_creative_direction() -> None:
    prompt = _rendered_prompt(
        "on-model",
        {
            "task_type": "on-model",
            "public_version_key": "v4.5",
            "background": "Dark Studio",
            "creative_direction": "SEASONAL_ON_MODEL_SENTINEL",
        },
    )

    assert "CURATED CREATIVE DIRECTION" in prompt
    assert "SEASONAL_ON_MODEL_SENTINEL" in prompt
    assert "flexible creative guardrail" in prompt
    assert "Vary nonessential styling, props, framing, and composition" in prompt
    assert "PRODUCT FIDELITY OVERRIDE" in prompt
    assert "immutable product specification" in prompt
    assert "exact count, order, spacing" in prompt
    assert "product fidelity wins" in prompt


def test_pure_jewelry_appends_curated_creative_direction() -> None:
    prompt = _rendered_prompt(
        "pure-jewelry",
        {
            "task_type": "pure-jewelry",
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
            "scene": "Deep Black",
            "creative_direction": "SEASONAL_PURE_JEWELRY_SENTINEL",
        },
    )

    assert "CURATED CREATIVE DIRECTION" in prompt
    assert "SEASONAL_PURE_JEWELRY_SENTINEL" in prompt
    assert "flexible creative guardrail" in prompt
    assert "Vary nonessential styling, props, framing, and composition" in prompt


def test_on_model_curated_looks_receive_distinct_variation_lanes() -> None:
    prompts = _rendered_prompts(
        "on-model",
        {
            "task_type": "on-model",
            "public_version_key": "v4.5",
            "creative_direction": "SEASONAL_ON_MODEL_SENTINEL",
        },
        looks=2,
    )

    assert len(prompts) == 2
    assert prompts[0] != prompts[1]
    assert "LOOK 1 OF 2" in prompts[0]
    assert "LOOK 2 OF 2" in prompts[1]
    assert "not a near-duplicate" in prompts[0]
    assert "different body and face angle" in prompts[1]
    assert "Keep the model identity" in prompts[1]


def test_pure_jewelry_curated_looks_receive_distinct_variation_lanes() -> None:
    prompts = _rendered_prompts(
        "pure-jewelry",
        {
            "task_type": "pure-jewelry",
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
            "creative_direction": "SEASONAL_PURE_JEWELRY_SENTINEL",
        },
        looks=2,
    )

    assert len(prompts) == 2
    assert prompts[0] != prompts[1]
    assert "LOOK 1 OF 2" in prompts[0]
    assert "LOOK 2 OF 2" in prompts[1]
    assert "generous negative space" in prompts[1]
    assert "Always change the jewelry orientation or position" in prompts[1]
    assert "camera angle or distance" in prompts[1]
    assert "Keep the jewelry design" in prompts[1]


def test_pure_jewelry_uses_preset_specific_variation_lanes() -> None:
    rendered = render_default_task(
        "pure-jewelry",
        {
            "request": {
                "looks": 2,
                "style": {
                    "task_type": "pure-jewelry",
                    "public_version_key": "v5.2",
                    "creative_direction": "Abstract pumpkin jewelry scene.",
                    "creative_variation_lanes": "CROPPED PUMPKIN LANE||OVERHEAD PUMPKIN LANE",
                },
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )

    assert "CROPPED PUMPKIN LANE" in rendered["prompts"][0]
    assert "OVERHEAD PUMPKIN LANE" in rendered["prompts"][1]


def test_curated_exclusions_are_added_to_the_negative_prompt() -> None:
    rendered = render_default_task(
        "pure-jewelry",
        {
            "request": {
                "style": {
                    "task_type": "pure-jewelry",
                    "public_version_key": "v5.2",
                    "style_type": "object-world",
                    "creative_direction": "Include a clearly recognizable pumpkin.",
                    "creative_exclusions": "tomatoes, tomato vines, substitute produce",
                },
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )

    assert "tomatoes, tomato vines, substitute produce" in rendered["negative_prompt"]


def test_server_owned_object_territory_replaces_kitchen_territory() -> None:
    prompt = _rendered_prompt(
        "pure-jewelry",
        {
            "task_type": "pure-jewelry",
            "public_version_key": "v5.2",
            "style_type": "object-world",
            "object-territory": "Table & Kitchen",
            "relationship": "Inside",
            "creative_object_territory": "Jewelry Presentation Box",
            "creative_direction": "Use an open jewelry presentation box.",
        },
    )

    assert "OBJECT TERRITORY: Jewelry Presentation Box" in prompt
    assert "The only supporting object is a small luxury jewelry presentation box" in prompt
    assert "TABLE & KITCHEN" not in prompt
