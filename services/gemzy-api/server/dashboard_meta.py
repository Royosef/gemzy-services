from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Query

from .auth import get_current_user
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none, utc_now_iso
from .dashboard_fx import get_usd_to_ils_rate
from .schemas import (
    DashboardCampaignPerformanceResponse,
    DashboardCampaignPerformanceRowResponse,
    DashboardMetaSpendPointResponse,
    DashboardMetaSpendTimeseriesResponse,
    DashboardMetaSyncResponse,
    DashboardOverviewMetricsResponse,
    DashboardTopAdResponse,
    UserState,
)

router = APIRouter(prefix="/dashboard/meta", tags=["dashboard-meta"])
logger = logging.getLogger(__name__)

META_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"
AD_ACCOUNT_CURRENCY = (
    "USD" if (os.getenv("META_AD_ACCOUNT_CURRENCY") or "").upper() == "USD" else "ILS"
)
CAMPAIGN_PERFORMANCE_TTL_MS = 15 * 60 * 1000
REVENUECAT_PURCHASE_ACTION_TYPES = {
    "omni_purchase",
    "purchase",
    "subscribe",
    "start_trial",
    "omni_subscribe",
    "omni_start_trial",
}
_campaign_performance_cache: dict[int, tuple[float, DashboardCampaignPerformanceResponse]] = {}


def _read_env(name: str) -> str | None:
    raw = os.getenv(name)
    if not raw:
        return None
    value = raw.strip().strip("'").strip('"')
    return value or None


def _meta_config() -> tuple[str, str]:
    token = _read_env("META_SYSTEM_USER_TOKEN") or _read_env("META_ACCESS_TOKEN")
    raw_account_id = _read_env("META_AD_ACCOUNT_ID")
    if not token:
        raise RuntimeError("META_SYSTEM_USER_TOKEN or META_ACCESS_TOKEN is not set")
    if not raw_account_id:
        raise RuntimeError("META_AD_ACCOUNT_ID is not set")
    account_id = raw_account_id if raw_account_id.startswith("act_") else f"act_{raw_account_id}"
    return token, account_id


def _build_url(path: str, params: dict[str, str]) -> str:
    query = httpx.QueryParams(params)
    return f"{BASE_URL}{path}?{query}"


async def _fetch_all_pages(initial_url: str) -> list[dict]:
    items: list[dict] = []
    next_url: str | None = initial_url
    async with httpx.AsyncClient(timeout=90.0) as client:
        while next_url:
            response = await client.get(next_url)
            response.raise_for_status()
            payload = response.json()
            items.extend(payload.get("data") or [])
            next_url = ((payload.get("paging") or {}).get("next"))
    return items


def _minor_to_major(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return f"{float(value) / 100:.2f}"
    except ValueError:
        return None


def _pick_primary_result(actions: Iterable[dict] | None) -> dict | None:
    if not actions:
        return None
    primary_types = [
        "purchase",
        "omni_purchase",
        "app_install",
        "mobile_app_install",
        "lead",
        "complete_registration",
    ]
    rows = list(actions)
    for action_type in primary_types:
        hit = next((row for row in rows if row.get("action_type") == action_type), None)
        if hit:
            return hit
    return rows[0] if rows else None


def _sum_actions(actions: Iterable[dict] | None) -> int:
    if not actions:
        return 0
    primary = _pick_primary_result(actions)
    if primary:
        return int(float(primary.get("value") or 0))
    return sum(int(float(row.get("value") or 0)) for row in actions)


def _pick_cost_per_result(cost_rows: Iterable[dict] | None, actions: Iterable[dict] | None) -> str:
    rows = list(cost_rows or [])
    if not rows:
        return "0"
    primary = _pick_primary_result(actions)
    if primary:
        matched = next((row for row in rows if row.get("action_type") == primary.get("action_type")), None)
        if matched:
            return str(matched.get("value") or "0")
    return str(rows[0].get("value") or "0")


async def _sync_campaigns() -> int:
    token, account_id = _meta_config()
    items = await _fetch_all_pages(
        _build_url(
            f"/{account_id}/campaigns",
            {
                "fields": "id,name,status,objective,created_time,updated_time",
                "limit": "100",
                "access_token": token,
            },
        )
    )
    synced_at = utc_now_iso()
    if items:
        rows = [
            {
                "id": item["id"],
                "name": item.get("name") or "",
                "status": item.get("status") or "UNKNOWN",
                "objective": item.get("objective") or "UNKNOWN",
                "created_at": item.get("created_time"),
                "updated_at": item.get("updated_time"),
                "synced_at": synced_at,
            }
            for item in items
        ]
        dashboard_table("campaigns").upsert(rows, on_conflict="id").execute()
    return len(items)


async def _sync_ad_sets() -> tuple[int, int, int]:
    token, account_id = _meta_config()
    items = await _fetch_all_pages(
        _build_url(
            f"/{account_id}/adsets",
            {
                "fields": ",".join(
                    [
                        "id",
                        "name",
                        "campaign_id",
                        "status",
                        "effective_status",
                        "daily_budget",
                        "lifetime_budget",
                        "optimization_goal",
                        "billing_event",
                        "bid_strategy",
                        "learning_stage_info",
                        "created_time",
                        "updated_time",
                    ]
                ),
                "limit": "100",
                "access_token": token,
            },
        )
    )
    cbo = 0
    abo = 0
    synced_at = utc_now_iso()
    if items:
        rows = []
        for item in items:
            daily_budget = _minor_to_major(item.get("daily_budget"))
            lifetime_budget = _minor_to_major(item.get("lifetime_budget"))
            budget_mode = "ABO" if daily_budget or lifetime_budget else "CBO"
            if budget_mode == "CBO":
                cbo += 1
            else:
                abo += 1
            rows.append(
                {
                    "id": item["id"],
                    "campaign_id": item.get("campaign_id"),
                    "name": item.get("name") or "",
                    "status": item.get("status"),
                    "effective_status": item.get("effective_status"),
                    "budget_mode": budget_mode,
                    "daily_budget": daily_budget,
                    "lifetime_budget": lifetime_budget,
                    "optimization_goal": item.get("optimization_goal"),
                    "billing_event": item.get("billing_event"),
                    "bid_strategy": item.get("bid_strategy"),
                    "learning_stage": (item.get("learning_stage_info") or {}).get("status"),
                    "created_at": item.get("created_time"),
                    "updated_at": item.get("updated_time"),
                    "synced_at": synced_at,
                }
            )
        dashboard_table("ad_sets").upsert(rows, on_conflict="id").execute()
    return len(items), cbo, abo


async def _sync_ads() -> int:
    token, account_id = _meta_config()
    items = await _fetch_all_pages(
        _build_url(
            f"/{account_id}/ads",
            {
                "fields": ",".join(
                    [
                        "id",
                        "name",
                        "status",
                        "campaign_id",
                        "adset_id",
                        "created_time",
                        "updated_time",
                        "insights.date_preset(maximum){spend,impressions,reach,cpm,actions,cost_per_action_type}",
                    ]
                ),
                "limit": "100",
                "access_token": token,
            },
        )
    )
    synced_at = utc_now_iso()
    if items:
        ad_sets = dashboard_table("ad_sets").select("id").execute().data or []
        ad_set_ids = {row["id"] for row in ad_sets}
        rows = []
        for item in items:
            insight = ((item.get("insights") or {}).get("data") or [{}])[0]
            actions = insight.get("actions") or []
            rows.append(
                {
                    "id": item["id"],
                    "campaign_id": item.get("campaign_id"),
                    "ad_set_id": item.get("adset_id") if item.get("adset_id") in ad_set_ids else None,
                    "name": item.get("name") or "",
                    "status": item.get("status") or "UNKNOWN",
                    "spend": str(insight.get("spend") or "0"),
                    "impressions": int(float(insight.get("impressions") or 0)),
                    "reach": int(float(insight.get("reach") or 0)),
                    "results": _sum_actions(actions),
                    "landing_page_views": sum(
                        int(float(row.get("value") or 0))
                        for row in actions
                        if row.get("action_type") == "landing_page_view"
                    ),
                    "engagements": sum(
                        int(float(row.get("value") or 0))
                        for row in actions
                        if row.get("action_type") in {"link_click", "post_engagement"}
                    ),
                    "conversions": sum(
                        int(float(row.get("value") or 0))
                        for row in actions
                        if row.get("action_type")
                        in {
                            "purchase",
                            "omni_purchase",
                            "app_install",
                            "mobile_app_install",
                            "complete_registration",
                            "lead",
                            "onsite_conversion.lead_grouped",
                            "onsite_conversion.purchase",
                        }
                    ),
                    "cost_per_result": _pick_cost_per_result(insight.get("cost_per_action_type"), actions),
                    "cpm": str(insight.get("cpm") or "0"),
                    "created_at": item.get("created_time"),
                    "updated_at": item.get("updated_time"),
                    "synced_at": synced_at,
                }
            )
        dashboard_table("ads").upsert(rows, on_conflict="id").execute()
    return len(items)


def _source_currency_to_usd_multiplier() -> float:
    if AD_ACCOUNT_CURRENCY != "ILS":
        return 1.0
    try:
        fx = get_usd_to_ils_rate()
    except Exception:
        logger.exception("Failed to load USD/ILS rate; using passthrough multiplier")
        return 1.0
    return 1.0 / fx.rate if fx.rate > 0 else 1.0


def _bucket_label(dt: datetime, granularity: str) -> str:
    if granularity == "day":
        return dt.date().isoformat()
    if granularity == "month":
        return f"{dt.year:04d}-{dt.month:02d}-01"
    monday = dt - timedelta(days=dt.weekday())
    return monday.date().isoformat()


def _granularity_for_days(range_days: int) -> str:
    if range_days <= 14:
        return "day"
    if range_days <= 90:
        return "week"
    return "month"


def _date_preset_for_range_days(range_days: int) -> str:
    if range_days <= 7:
        return "last_7d"
    if range_days <= 14:
        return "last_14d"
    if range_days <= 30:
        return "last_30d"
    return "last_90d"


def _safe_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


async def _fetch_campaign_performance_from_meta(range_days: int) -> DashboardCampaignPerformanceResponse:
    token, account_id = _meta_config()
    date_preset = _date_preset_for_range_days(range_days)
    url = _build_url(
        f"/{account_id}/insights",
        {
            "level": "campaign",
            "date_preset": date_preset,
            "fields": "campaign_id,campaign_name,spend,actions,action_values",
            "limit": "500",
            "access_token": token,
        },
    )
    started = time.perf_counter()
    rows = await _fetch_all_pages(url)
    campaigns = dashboard_table("campaigns").select("id,status").execute().data or []
    status_by_id = {row["id"]: row.get("status") or "UNKNOWN" for row in campaigns if row.get("id")}
    usd_multiplier = _source_currency_to_usd_multiplier()

    has_any_attribution = False
    results: list[DashboardCampaignPerformanceRowResponse] = []
    for row in rows:
        campaign_id = row.get("campaign_id")
        if not campaign_id:
            continue
        spend_usd = round(_safe_float(row.get("spend")) * usd_multiplier, 2)
        purchases = 0
        revenue_usd = 0.0
        has_attribution = False
        for action in row.get("actions") or []:
            action_type = action.get("action_type")
            if action_type in REVENUECAT_PURCHASE_ACTION_TYPES:
                purchases += _safe_int(action.get("value"))
                has_attribution = True
        for action_value in row.get("action_values") or []:
            action_type = action_value.get("action_type")
            if action_type in REVENUECAT_PURCHASE_ACTION_TYPES:
                revenue_usd += _safe_float(action_value.get("value")) * usd_multiplier
                has_attribution = True
        revenue_usd = round(revenue_usd, 2)
        roas = round(revenue_usd / spend_usd, 2) if spend_usd > 0 and revenue_usd > 0 else None
        cac_usd = round(spend_usd / purchases, 2) if spend_usd > 0 and purchases > 0 else None
        if has_attribution:
            has_any_attribution = True
        results.append(
            DashboardCampaignPerformanceRowResponse(
                campaignId=str(campaign_id),
                campaignName=str(row.get("campaign_name") or campaign_id),
                status=str(status_by_id.get(campaign_id) or "UNKNOWN"),
                spendUsd=spend_usd,
                purchases=purchases,
                revenueUsd=revenue_usd,
                roas=roas,
                cacUsd=cac_usd,
                hasAttribution=has_attribution,
            )
        )
    logger.info(
        "dashboard campaign performance fetched",
        extra={
            "rangeDays": range_days,
            "campaignCount": len(results),
            "hasAnyAttribution": has_any_attribution,
            "durationMs": int((time.perf_counter() - started) * 1000),
        },
    )
    return DashboardCampaignPerformanceResponse(
        rangeDays=range_days,
        fetchedAt=utc_now_iso(),
        rows=results,
        hasAnyAttribution=has_any_attribution,
    )


async def _load_campaign_performance(range_days: int) -> DashboardCampaignPerformanceResponse:
    cached = _campaign_performance_cache.get(range_days)
    now_ms = time.time() * 1000
    if cached and now_ms < cached[0]:
        return cached[1]
    result = await _fetch_campaign_performance_from_meta(range_days)
    _campaign_performance_cache[range_days] = (now_ms + CAMPAIGN_PERFORMANCE_TTL_MS, result)
    return result


@router.post("/sync", response_model=DashboardMetaSyncResponse)
async def sync_dashboard_meta(current: UserState = Depends(get_current_user)) -> DashboardMetaSyncResponse:
    ensure_dashboard_admin(current)
    started = time.perf_counter()
    campaigns = await _sync_campaigns()
    ad_sets, ad_sets_cbo, ad_sets_abo = await _sync_ad_sets()
    ads = await _sync_ads()
    duration_ms = int((time.perf_counter() - started) * 1000)
    return DashboardMetaSyncResponse(
        campaigns=campaigns,
        adSets=ad_sets,
        adSetsCbo=ad_sets_cbo,
        adSetsAbo=ad_sets_abo,
        ads=ads,
        durationMs=duration_ms,
    )


@router.get("/overview", response_model=DashboardOverviewMetricsResponse)
def get_overview_metrics(current: UserState = Depends(get_current_user)) -> DashboardOverviewMetricsResponse:
    ensure_dashboard_admin(current)
    ads = dashboard_table("ads").select("spend,impressions,results,synced_at").execute().data or []
    total_spend = sum(float(row.get("spend") or 0) for row in ads)
    total_impressions = sum(int(row.get("impressions") or 0) for row in ads)
    total_results = sum(int(row.get("results") or 0) for row in ads)
    last_synced_at = max((iso_or_none(row.get("synced_at")) for row in ads), default=None)
    return DashboardOverviewMetricsResponse(
        totalSpend=f"{total_spend:.2f}",
        totalImpressions=total_impressions,
        totalResults=total_results,
        avgRoas="0",
        lastSyncedAt=last_synced_at,
    )


@router.get("/spend-timeseries", response_model=DashboardMetaSpendTimeseriesResponse)
def get_spend_timeseries(
    rangeDays: int = Query(default=30, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardMetaSpendTimeseriesResponse:
    ensure_dashboard_admin(current)
    granularity = _granularity_for_days(rangeDays)
    cutoff = datetime.now(timezone.utc) - timedelta(days=rangeDays)
    buckets: dict[str, float] = {}
    for row in dashboard_table("ads").select("spend,synced_at").execute().data or []:
        synced_at = iso_or_none(row.get("synced_at"))
        if not synced_at:
            continue
        try:
            synced_dt = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if synced_dt.tzinfo is None:
            synced_dt = synced_dt.replace(tzinfo=timezone.utc)
        else:
            synced_dt = synced_dt.astimezone(timezone.utc)
        if synced_dt < cutoff:
            continue
        bucket = _bucket_label(synced_dt, granularity)
        buckets[bucket] = buckets.get(bucket, 0.0) + _safe_float(row.get("spend"))
    usd_multiplier = _source_currency_to_usd_multiplier()
    points = [
        DashboardMetaSpendPointResponse(date=date, spend=round(spend * usd_multiplier, 2))
        for date, spend in sorted(buckets.items())
    ]
    return DashboardMetaSpendTimeseriesResponse(
        granularity=granularity,
        currency="USD",
        points=points,
    )


@router.get("/campaign-performance", response_model=DashboardCampaignPerformanceResponse)
async def get_campaign_performance(
    rangeDays: int = Query(default=30, ge=1, le=90),
    current: UserState = Depends(get_current_user),
) -> DashboardCampaignPerformanceResponse:
    ensure_dashboard_admin(current)
    return await _load_campaign_performance(rangeDays)


@router.get("/top-ads", response_model=list[DashboardTopAdResponse])
def get_top_ads(current: UserState = Depends(get_current_user)) -> list[DashboardTopAdResponse]:
    ensure_dashboard_admin(current)
    ads = dashboard_table("ads").select("id,name,campaign_id,spend,results,cost_per_result").execute().data or []
    campaigns = dashboard_table("campaigns").select("id,name").execute().data or []
    campaign_names = {row["id"]: row.get("name") for row in campaigns}
    ranked = sorted(ads, key=lambda row: int(row.get("results") or 0), reverse=True)[:10]
    return [
        DashboardTopAdResponse(
            id=row["id"],
            adName=row.get("name") or "",
            campaignName=campaign_names.get(row.get("campaign_id")),
            spend=str(row.get("spend") or "0"),
            results=int(row.get("results") or 0),
            costPerResult=str(row.get("cost_per_result") or "0"),
        )
        for row in ranked
    ]
