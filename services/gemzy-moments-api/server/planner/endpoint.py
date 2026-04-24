"""Planner endpoint — orchestrates the AI-hybrid planning pipeline."""
from __future__ import annotations

import hashlib
import logging
import os
import random as _random_module
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..moments_schemas import (
    MomentContextUpsert,
    PlannerRunResponse,
    PlannerSuggestedBlock,
    PlannerSuggestedMoment,
)
from ..supabase_client import get_client

from . import block_allocator, outfit_builder, prompt_parser, world_selector
from .continuity import update_usage_in_memory
from .persistence import cleanup_previous_plan, save_plan_results
from .prompt_parser import TIME_SLOTS, SLOT_TEMPLATES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/planner", tags=["planner"])

PEOPLE_SCHEMA = "people"
MOMENTS_SCHEMA = "moments"


def _db():
    return get_client()


def _get_generation_server_url() -> str | None:
    return os.getenv("GENERATION_SERVER_URL", "").strip() or None


def _get_shared_secret() -> str:
    return os.getenv("GENERATION_SHARED_SECRET", "").strip()


async def _call_ai_enrich(
    prompt: str,
    persona: dict,
    style: dict,
    prefs: dict,
    locations: list[dict],
    wardrobe: list[dict],
) -> dict[str, Any] | None:
    """Call generation_server /planner/enrich."""
    base_url = _get_generation_server_url()
    if not base_url:
        logger.info("GENERATION_SERVER_URL not configured; skipping AI enrichment")
        return None

    loc_tags: set[str] = set()
    loc_tiers: dict[str, str] = {}
    for loc in locations:
        for tag in loc.get("tags", []):
            loc_tags.add(str(tag))
        loc_tiers[loc.get("name", "")] = loc.get("tier", "SEMI_STABLE")

    wardrobe_tags: set[str] = set()
    for w in wardrobe:
        for tag in w.get("tags", []):
            wardrobe_tags.add(str(tag))

    payload = {
        "prompt": prompt,
        "persona": {
            "display_name": persona.get("display_name", ""),
            "bio": persona.get("bio"),
        },
        "style_profile": {
            "realism_level": style.get("realism_level", "high"),
            "camera_style_tags": style.get("camera_style_tags", []),
            "color_palette_tags": style.get("color_palette_tags", []),
        },
        "preferences": {
            "stories_per_day": prefs.get("default_stories_per_day", 3),
            "posts_per_day": prefs.get("default_posts_per_day", 1),
        },
        "world_summary": {
            "location_tags": list(loc_tags),
            "wardrobe_tags": list(wardrobe_tags),
            "location_tiers": loc_tiers,
        },
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = _get_shared_secret()
    if secret:
        headers["X-Generation-Secret"] = secret

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/planner/enrich",
                json=payload, headers=headers,
            )
        if resp.status_code >= 400:
            logger.warning("AI enrichment returned %d: %s", resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("AI enrichment call failed: %s", exc)
        return None


async def _call_ai_rank(
    persona_name: str,
    intent: str,
    tone: str,
    moments_for_ranking: list[dict],
) -> dict[str, Any] | None:
    """Call generation_server /planner/rank."""
    base_url = _get_generation_server_url()
    if not base_url:
        return None

    payload = {
        "persona_name": persona_name,
        "intent": intent,
        "tone": tone,
        "moments": moments_for_ranking,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = _get_shared_secret()
    if secret:
        headers["X-Generation-Secret"] = secret

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/planner/rank",
                json=payload, headers=headers,
            )
        if resp.status_code >= 400:
            logger.warning("AI ranking returned %d: %s", resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("AI ranking call failed: %s", exc)
        return None


def _should_inject_novelty(novelty_rate: float, rng: _random_module.Random) -> bool:
    return rng.random() < novelty_rate


@router.post("/plan/{plan_id}", response_model=PlannerRunResponse)
async def plan(plan_id: str, user=Depends(get_current_user)):
    """Execute the AI-hybrid planner for a content plan."""

    # 1. Fetch plan
    plan_data = (
        _db().schema(MOMENTS_SCHEMA).table("content_plans")
        .select("*").eq("id", plan_id).eq("owner_user_id", user.id)
        .single().execute()
    )
    if not plan_data.data:
        raise HTTPException(404, "Plan not found")

    if plan_data.data["status"] not in ("DRAFT",):
        raise HTTPException(400, f"Cannot plan in '{plan_data.data['status']}' status")

    persona_id = plan_data.data["persona_id"]
    prompt = plan_data.data.get("source_prompt", "")

    # 2. Fetch persona + world catalog
    persona = (
        _db().schema(PEOPLE_SCHEMA).table("personas")
        .select("*").eq("id", persona_id).single().execute()
    ).data or {}

    locations = (
        _db().schema(PEOPLE_SCHEMA).table("world_locations")
        .select("*").eq("persona_id", persona_id).execute()
    ).data or []

    wardrobe = (
        _db().schema(PEOPLE_SCHEMA).table("world_wardrobe_items")
        .select("*").eq("persona_id", persona_id).execute()
    ).data or []

    style_query = (
        _db()
        .schema(PEOPLE_SCHEMA)
        .table("persona_style_profile")
        .select("*")
        .eq("persona_id", persona_id)
        .maybe_single()
    ).execute()

    style = style_query.data if style_query else {}

    # 3. Fetch usage stats
    usage_rows = (
        _db().schema(MOMENTS_SCHEMA).table("usage_stats")
        .select("*").eq("persona_id", persona_id).execute()
    ).data or []

    usage_map: dict[str, dict] = {row["item_id"]: row for row in usage_rows}

    query_prefs = (
        _db().schema(MOMENTS_SCHEMA).table("user_preferences")
        .select("*").eq("user_id", user.id).maybe_single()
    ).execute()

    prefs = query_prefs.data if query_prefs else {}

    posts_per_day = prefs.get("default_posts_per_day", 1)
    stories_per_day = prefs.get("default_stories_per_day", 3)
    novelty_rate = prefs.get("novelty_rate", 0.15)
    distribution = prefs.get("distribution_profile", {
        "morning": 0.25, "midday": 0.2, "afternoon": 0.2,
        "evening": 0.25, "late_night": 0.1,
    })

    persona_name = persona.get("display_name", "the persona")
    total_target = posts_per_day + stories_per_day

    # Seeded randomness
    seed = int(hashlib.md5(plan_id.encode()).hexdigest()[:8], 16)
    rng = _random_module.Random(seed)
    now = datetime.now(timezone.utc)

    # STEP 2: AI ENRICHMENT (or fallback)
    planning_model = "none"
    intent = ""
    tone = ""
    day_arc: list[str] = []
    enriched_moments: list[dict] = []

    enrichment = await _call_ai_enrich(prompt, persona, style, prefs, locations, wardrobe)

    if enrichment and enrichment.get("moments"):
        planning_model = "moments_enricher_v1"
        intent = enrichment.get("intent", "")
        tone = enrichment.get("tone", "")
        day_arc = enrichment.get("day_arc", [])
        enriched_moments = enrichment.get("moments", [])
        logger.info("AI enrichment produced %d moments (intent=%s)", len(enriched_moments), intent[:50])
    else:
        planning_model = "fallback_rule_parser"
        activities = prompt_parser.parse_activities(prompt)
        if not activities:
            activities = block_allocator.generate_default_activities(distribution, total_target)
        enriched_moments = [
            {
                "description": act["description"],
                "time_slot": act["time_slot"],
                "priority": "medium",
                "desired_location_tags": [],
                "desired_outfit_tags": [],
                "mood_tags": SLOT_TEMPLATES.get(act["time_slot"], {}).get("moods", ["natural"])[:1],
            }
            for act in activities
        ]
        logger.info("Fallback parser produced %d moments", len(enriched_moments))

    # STEP 3: RULE-BASED WORLD RESOLUTION
    resolved_moments: list[dict] = []

    for em in enriched_moments:
        novelty = _should_inject_novelty(novelty_rate, rng)

        loc = world_selector.select_location(
            locations, usage_map, now,
            desired_tags=em.get("desired_location_tags", []),
            novelty=novelty, rng=rng,
        )
        loc_id = loc["id"] if loc else None

        outfit = outfit_builder.build_outfit(
            wardrobe, usage_map, now,
            desired_tags=em.get("desired_outfit_tags", []),
            rng=rng, novelty=novelty,
        )

        mood_tags = em.get("mood_tags", [])
        if not mood_tags:
            slot_template = SLOT_TEMPLATES.get(em.get("time_slot", "morning"), {})
            mood_tags = [rng.choice(slot_template.get("moods", ["natural"]))]

        notes_parts = []
        if novelty:
            notes_parts.append("novelty=yes")
        if intent:
            notes_parts.append(f"intent={intent[:50]}")
        if em.get("priority") == "high":
            notes_parts.append("hero_candidate")

        resolved_moments.append({
            "description": em.get("description", ""),
            "time_slot": em.get("time_slot", "morning"),
            "priority": em.get("priority", "medium"),
            "loc_id": loc_id,
            "loc_name": loc.get("name") if loc else None,
            "loc_tags": [str(t) for t in loc.get("tags", [])] if loc else [],
            "outfit": outfit,
            "wardrobe_ids": outfit.item_ids,
            "outfit_composition": outfit.to_composition_dict(),
            "mood_tags": mood_tags,
            "continuity_notes": "; ".join(notes_parts) if notes_parts else None,
            "usage_items": (
                [(loc_id, "location")] if loc_id else []
            ) + [(wid, "wardrobe") for wid in outfit.item_ids],
        })

    # STEP 4: AI FORMAT RANKING (or fallback)
    engine_name = "planner_v1_rule_based"

    moments_for_ranking = [
        {
            "description": rm["description"],
            "time_slot": rm["time_slot"],
            "priority": rm["priority"],
            "mood_tags": rm["mood_tags"],
            "location_name": rm.get("loc_name"),
            "location_tags": rm.get("loc_tags", []),
            "outfit_items": rm["outfit"].item_names,
        }
        for rm in resolved_moments
    ]

    ranking_result = await _call_ai_rank(persona_name, intent, tone, moments_for_ranking)

    if ranking_result and ranking_result.get("rankings"):
        rankings = ranking_result["rankings"]
        rank_map = {r["index"]: r for r in rankings}
        stories_remaining = stories_per_day
        posts_remaining = posts_per_day

        for i, rm in enumerate(resolved_moments):
            rank = rank_map.get(i, {})
            fmt = rank.get("format", "STORY").upper()
            if fmt == "POST" and posts_remaining > 0:
                rm["moment_type"] = "POST"
                posts_remaining -= 1
            elif fmt == "STORY" and stories_remaining > 0:
                rm["moment_type"] = "STORY"
                stories_remaining -= 1
            elif stories_remaining > 0:
                rm["moment_type"] = "STORY"
                stories_remaining -= 1
            elif posts_remaining > 0:
                rm["moment_type"] = "POST"
                posts_remaining -= 1
            else:
                rm["moment_type"] = "STORY"
            rm["hero_score"] = rank.get("hero_score", 0.0)

        engine_name = "planner_v1_ai_ranked"
        logger.info("AI ranking applied to %d moments", len(resolved_moments))
    else:
        slot_list = [rm["time_slot"] for rm in resolved_moments]
        unique_slots = list(dict.fromkeys(slot_list))
        format_dist = block_allocator.distribute_formats(stories_per_day, posts_per_day, unique_slots)
        slot_counters: dict[str, dict[str, int]] = {
            slot: {"stories": d["stories"], "posts": d["posts"]}
            for slot, d in format_dist.items()
        }

        for rm in resolved_moments:
            slot = rm["time_slot"]
            counters = slot_counters.get(slot, {"stories": 1, "posts": 0})
            if counters["stories"] > 0:
                rm["moment_type"] = "STORY"
                counters["stories"] -= 1
            elif counters["posts"] > 0:
                rm["moment_type"] = "POST"
                counters["posts"] -= 1
            else:
                rm["moment_type"] = "STORY"
            rm["hero_score"] = 0.0

        logger.info("Fallback format allocation applied")

    # STEP 5: CLEANUP + PERSIST
    cleanup_previous_plan(plan_id)

    slot_groups: dict[str, list[dict]] = {}
    for rm in resolved_moments:
        slot = rm["time_slot"]
        slot_groups.setdefault(slot, []).append(rm)

    blocks_data: list[dict] = []
    suggested_blocks: list[PlannerSuggestedBlock] = []

    for slot in TIME_SLOTS:
        slot_moments = slot_groups.get(slot, [])
        if not slot_moments:
            continue

        block_stories = sum(1 for m in slot_moments if m["moment_type"] == "STORY")
        block_posts = sum(1 for m in slot_moments if m["moment_type"] == "POST")

        block_moments_data: list[dict] = []
        block_suggested: list[PlannerSuggestedMoment] = []

        for rm in slot_moments:
            m_type = rm["moment_type"]
            image_count = 1 if m_type == "STORY" else rng.choice([1, 2, 3])

            ctx = MomentContextUpsert(
                location_id=rm["loc_id"],
                wardrobe_item_ids=rm["wardrobe_ids"],
                outfit_composition=rm["outfit_composition"],
                mood_tags=rm["mood_tags"],
                continuity_notes=rm.get("continuity_notes"),
            )

            block_suggested.append(PlannerSuggestedMoment(
                moment_type=m_type,
                image_count=image_count,
                caption_hint=rm["description"],
                context=ctx,
            ))

            block_moments_data.append({
                "moment_type": m_type,
                "image_count": image_count,
                "caption_hint": rm["description"],
                "context": {
                    "location_id": rm["loc_id"],
                    "wardrobe_item_ids": rm["wardrobe_ids"],
                    "outfit_composition": rm["outfit_composition"],
                    "mood_tags": rm["mood_tags"],
                    "continuity_notes": rm.get("continuity_notes"),
                },
                "usage_items": rm.get("usage_items", []),
            })

        blocks_data.append({
            "time_of_day": slot,
            "target_posts": block_posts,
            "target_stories": block_stories,
            "moments": block_moments_data,
        })

        suggested_blocks.append(PlannerSuggestedBlock(
            time_of_day=slot,
            target_posts=block_posts,
            target_stories=block_stories,
            moments=block_suggested,
        ))

    run_output = {
        "blocks": [b.model_dump() for b in suggested_blocks],
        "persona_name": persona_name,
        "prompt": prompt,
        "novelty_rate": novelty_rate,
        "intent": intent,
        "tone": tone,
        "day_arc": day_arc,
        "planning_model_name": planning_model,
        "execution_engine_name": engine_name,
    }

    run_id, version = save_plan_results(
        plan_id=plan_id,
        persona_id=persona_id,
        blocks_data=blocks_data,
        planning_model=planning_model,
        engine_name=engine_name,
        run_output=run_output,
        now=now,
    )

    return PlannerRunResponse(
        plan_id=plan_id,
        run_id=run_id,
        version=version,
        blocks=suggested_blocks,
    )
