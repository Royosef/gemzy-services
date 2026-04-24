"""Persistence layer — plan cleanup + save all plan artifacts."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..supabase_client import get_client

logger = logging.getLogger(__name__)

MOMENTS_SCHEMA = "moments"


def _db():
    return get_client()


def cleanup_previous_plan(plan_id: str) -> None:
    """Delete all artifacts from a previous planner run."""
    db = _db()
    db.schema(MOMENTS_SCHEMA).table("moments").delete().eq("plan_id", plan_id).execute()
    db.schema(MOMENTS_SCHEMA).table("plan_blocks").delete().eq("plan_id", plan_id).execute()
    db.schema(MOMENTS_SCHEMA).table("planner_runs").delete().eq("plan_id", plan_id).execute()
    logger.info("Cleaned up previous plan artifacts for plan %s", plan_id)


def save_plan_results(
    plan_id: str,
    persona_id: str,
    blocks_data: list[dict[str, Any]],
    planning_model: str,
    engine_name: str,
    run_output: dict[str, Any],
    now: datetime | None = None,
) -> tuple[str, int]:
    """Save all plan artifacts to the database. Returns (run_id, version)."""
    now = now or datetime.now(timezone.utc)
    db = _db()

    try:
        for block_data in blocks_data:
            block_row = {
                "plan_id": plan_id,
                "time_of_day": block_data["time_of_day"],
                "target_posts": block_data.get("target_posts", 0),
                "target_stories": block_data.get("target_stories", 0),
            }
            block_result = (
                db.schema(MOMENTS_SCHEMA).table("plan_blocks")
                .insert(block_row).execute()
            )
            block_id = block_result.data[0]["id"]

            for moment_data in block_data.get("moments", []):
                moment_row = {
                    "plan_id": plan_id,
                    "block_id": block_id,
                    "moment_type": moment_data["moment_type"],
                    "image_count": moment_data.get("image_count", 1),
                    "caption_hint": moment_data.get("caption_hint", ""),
                    "status": "PLANNED",
                }
                moment_result = (
                    db.schema(MOMENTS_SCHEMA).table("moments")
                    .insert(moment_row).execute()
                )
                moment_id = moment_result.data[0]["id"]

                ctx = moment_data.get("context", {})
                ctx_row = {
                    "moment_id": moment_id,
                    "location_id": ctx.get("location_id"),
                    "wardrobe_item_ids": ctx.get("wardrobe_item_ids", []),
                    "outfit_composition": ctx.get("outfit_composition", {}),
                    "mood_tags": ctx.get("mood_tags", []),
                    "continuity_notes": ctx.get("continuity_notes"),
                }
                db.schema(MOMENTS_SCHEMA).table("moment_context").insert(ctx_row).execute()

                for item_id, item_type in moment_data.get("usage_items", []):
                    if item_id:
                        db.schema(MOMENTS_SCHEMA).table("usage_stats").upsert({
                            "persona_id": persona_id,
                            "item_type": item_type,
                            "item_id": item_id,
                            "last_used_at": now.isoformat(),
                            "fatigue_score": 0.1,
                            "updated_at": now.isoformat(),
                        }, on_conflict="persona_id,item_type,item_id").execute()

        existing_runs = (
            db.schema(MOMENTS_SCHEMA).table("planner_runs")
            .select("version").eq("plan_id", plan_id)
            .order("version", desc=True).limit(1).execute()
        ).data
        next_version = (existing_runs[0]["version"] + 1) if existing_runs else 1

        run_result = (
            db.schema(MOMENTS_SCHEMA).table("planner_runs").insert({
                "plan_id": plan_id,
                "model_name": f"{planning_model} + {engine_name}",
                "output_json": run_output,
                "version": next_version,
            }).execute()
        )
        run_id = run_result.data[0]["id"]

        db.schema(MOMENTS_SCHEMA).table("content_plans").update({
            "status": "AWAITING_CONFIRMATION",
            "updated_at": now.isoformat(),
        }).eq("id", plan_id).execute()

        logger.info(
            "Saved plan results: plan=%s, run=%s, version=%d, blocks=%d",
            plan_id, run_id, next_version, len(blocks_data),
        )
        return run_id, next_version

    except Exception:
        logger.exception("Failed to save plan results for plan %s", plan_id)
        try:
            db.schema(MOMENTS_SCHEMA).table("content_plans").update({
                "status": "DRAFT",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", plan_id).execute()
        except Exception:
            logger.exception("Failed to revert plan status for %s", plan_id)
        raise
