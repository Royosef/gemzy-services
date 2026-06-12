from __future__ import annotations

import argparse
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve()
SERVICE_ROOT = SCRIPT_PATH.parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from server.dashboard_personas import (  # noqa: E402
    _coerce_dict,
    _enqueue_generation_for_queue_item,
    _moments_table,
    _sync_queue_item_to_moments_draft,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill existing dashboard persona queue rows into the Moments "
            "content_plans/moments pipeline."
        )
    )
    parser.add_argument(
        "--persona-id",
        help="Backfill only one persona's queue instead of all personas.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum queue rows to inspect. Default: 500",
    )
    parser.add_argument(
        "--enqueue-approved",
        action="store_true",
        help=(
            "Also enqueue generation for rows already in approved/published status. "
            "Without this flag, the script only creates draft sync records."
        ),
    )
    return parser.parse_args()


def fetch_queue_rows(*, persona_id: str | None, limit: int) -> list[dict]:
    query = (
        _moments_table("persona_content_queue")
        .select("*")
        .order("created_at", desc=False)
        .limit(limit)
    )
    if persona_id:
        query = query.eq("persona_id", persona_id)
    return query.execute().data or []


def main() -> int:
    args = parse_args()
    rows = fetch_queue_rows(persona_id=args.persona_id, limit=args.limit)
    if not rows:
        print("No persona queue rows found.")
        return 0

    inspected = 0
    synced = 0
    already_synced = 0
    enqueued = 0
    failures = 0

    for row in rows:
        inspected += 1
        queue_payload = _coerce_dict(row.get("queue_payload"))
        had_sync = bool(queue_payload.get("contentPlanId") and queue_payload.get("momentId"))
        status = str(row.get("status") or "draft").lower()
        try:
            synced_row = _sync_queue_item_to_moments_draft(row)
            synced_payload = _coerce_dict(synced_row.get("queue_payload"))
            has_sync = bool(synced_payload.get("contentPlanId") and synced_payload.get("momentId"))
            if had_sync:
                already_synced += 1
            elif has_sync:
                synced += 1

            if args.enqueue_approved and status in {"approved", "published"}:
                before_job_id = synced_payload.get("generationJobId")
                generated_row = _enqueue_generation_for_queue_item(synced_row)
                generated_payload = _coerce_dict(generated_row.get("queue_payload"))
                after_job_id = generated_payload.get("generationJobId")
                if after_job_id and after_job_id != before_job_id:
                    enqueued += 1
        except Exception as exc:
            failures += 1
            print(f"[FAIL] queue_id={row.get('id')} persona_id={row.get('persona_id')} error={exc}")

    print("Backfill complete")
    print(f"  inspected: {inspected}")
    print(f"  newly synced into Moments drafts: {synced}")
    print(f"  already synced: {already_synced}")
    print(f"  generation jobs enqueued: {enqueued}")
    print(f"  failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
