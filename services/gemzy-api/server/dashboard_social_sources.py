from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .auth import get_current_user
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none, utc_now_iso
from .schemas import (
    DashboardInstagramInsightResponse,
    DashboardInstagramSyncResponse,
    DashboardSocialDiscoveryRunPayload,
    DashboardSocialDiscoveryRunResponse,
    DashboardSocialSourceSyncPayload,
    UserState,
)

router = APIRouter(prefix="/dashboard/social", tags=["dashboard-social-sources"])
logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
META_API_VERSION = "v21.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"

HANDLE_RE = re.compile(r"(?:^|[^a-zA-Z0-9._])@([a-zA-Z0-9][a-zA-Z0-9._]{0,28}[a-zA-Z0-9])")
URL_HANDLE_RE = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?instagram\.com\/([a-zA-Z0-9][a-zA-Z0-9._]{0,28}[a-zA-Z0-9])"
)
FOLLOWER_PATTERNS = [
    re.compile(r"([\d,]+(?:\.\d+)?)\s*([kKmMbB])?\s*followers"),
    re.compile(r"followers[:\s]+([\d,]+(?:\.\d+)?)\s*([kKmMbB])?"),
]
LOCATION_PATTERNS = [
    re.compile(r"based\s+(?:in|out\s+of)\s+([A-Z][A-Za-z.\- ]+?(?:,\s*[A-Z]{2,})?)(?=[\s.,;]|$)"),
    re.compile(r"located\s+in\s+([A-Z][A-Za-z.\- ]+?(?:,\s*[A-Z]{2,})?)(?=[\s.,;]|$)"),
    re.compile(r"from\s+([A-Z][A-Za-z.\- ]+?,\s*[A-Z]{2,})(?=[\s.,;]|$)"),
]
RESERVED_HANDLES = {
    "explore",
    "reels",
    "reel",
    "p",
    "tv",
    "stories",
    "accounts",
    "about",
    "developer",
    "developers",
    "directory",
    "legal",
    "privacy",
    "terms",
    "press",
    "web",
    "api",
    "help",
    "blog",
    "jobs",
    "ig",
}
NICHE_KEYWORDS = [
    "handmade",
    "handcrafted",
    "artisan",
    "fine jewelry",
    "demi-fine",
    "fine jewellery",
    "minimalist",
    "bohemian",
    "vintage",
    "silver",
    "sterling silver",
    "gold",
    "14k",
    "18k",
    "gemstone",
    "diamond",
    "pearl",
    "enamel",
    "ethical",
    "sustainable",
]
US_TOKENS = [
    "united states",
    " usa",
    ", us",
    " u.s.",
    "new york",
    "los angeles",
    "brooklyn",
    "austin",
    "seattle",
    "portland",
    "california",
    "texas",
    "chicago",
]
ANGLOSPHERE_TOKENS = [
    "united kingdom",
    "england",
    "london",
    "brighton",
    "manchester",
    "edinburgh",
    ", uk",
    "canada",
    "toronto",
    "vancouver",
    "montreal",
    "australia",
    "sydney",
    "melbourne",
    "ireland",
    "dublin",
    "new zealand",
    "auckland",
    "israel",
    "tel aviv",
    "tel-aviv",
    "germany",
    "berlin",
    "france",
    "paris",
    "netherlands",
    "amsterdam",
    "sweden",
    "stockholm",
    "denmark",
    "copenhagen",
    "norway",
    "oslo",
    "finland",
    "spain",
    "madrid",
    "barcelona",
    "italy",
    "milan",
    "rome",
]
PREFERRED_NICHE_KEYWORDS = [
    "handmade",
    "handcrafted",
    "artisan",
    "fine jewelry",
    "fine jewellery",
    "demi-fine",
    "silver",
    "sterling silver",
    "gold",
    "14k",
    "18k",
    "gemstone",
    "diamond",
    "pearl",
]

_cached_business_account_id: str | None = None


@dataclass
class ExtractedAccount:
    handle: str
    follower_count: int | None
    location: str | None
    niche: str | None
    source_url: str
    source_title: str


def _env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    raise RuntimeError(f"{' or '.join(names)} is not set")


def _normalize_handle(raw: str) -> str | None:
    handle = raw.lower().rstrip(".")
    if len(handle) < 2 or len(handle) > 30:
        return None
    if handle in RESERVED_HANDLES or handle.isdigit() or ".." in handle:
        return None
    return handle


def _parse_follower_count(text: str) -> int | None:
    for pattern in FOLLOWER_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        number = (match.group(1) or "").replace(",", "")
        suffix = (match.group(2) or "").lower()
        try:
            value = float(number)
        except ValueError:
            continue
        multiplier = 1
        if suffix == "k":
            multiplier = 1_000
        elif suffix == "m":
            multiplier = 1_000_000
        elif suffix == "b":
            multiplier = 1_000_000_000
        return round(value * multiplier)
    return None


def _parse_location(text: str) -> str | None:
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if match and match.group(1):
            return re.sub(r"\s+", " ", match.group(1).strip())
    return None


def _parse_niche(text: str) -> str | None:
    lower = text.lower()
    hits = [keyword for keyword in NICHE_KEYWORDS if keyword in lower]
    if not hits:
        return None
    return ", ".join(hits[:4])


def extract_ig_handles(result: dict[str, Any]) -> list[ExtractedAccount]:
    text = "\n".join(
        part
        for part in (
            str(result.get("title") or ""),
            str(result.get("content") or ""),
        )
        if part
    )
    raw_handles: set[str] = set()
    for pattern in (HANDLE_RE, URL_HANDLE_RE):
        for match in pattern.finditer(text):
            normalized = _normalize_handle(match.group(1))
            if normalized:
                raw_handles.add(normalized)
    if not raw_handles:
        return []
    location = _parse_location(text)
    niche = _parse_niche(text)
    follower_count = _parse_follower_count(text)
    return [
        ExtractedAccount(
            handle=handle,
            follower_count=follower_count,
            location=location,
            niche=niche,
            source_url=str(result.get("url") or ""),
            source_title=str(result.get("title") or ""),
        )
        for handle in raw_handles
    ]


def score_account_fit(*, follower_count: int | None, location: str | None, niche: str | None) -> float:
    if follower_count is None:
        follower_score = 0.5
    elif follower_count < 1_000:
        follower_score = 0.45
    elif follower_count <= 10_000:
        follower_score = 1.0
    elif follower_count <= 50_000:
        follower_score = 0.75
    elif follower_count <= 200_000:
        follower_score = 0.5
    else:
        follower_score = 0.3

    if niche is None:
        niche_score = 0.5
    else:
        lower = niche.lower()
        hits = sum(1 for keyword in PREFERRED_NICHE_KEYWORDS if keyword in lower)
        niche_score = min(1.0, 0.5 + hits * 0.1)

    if location is None:
        location_score = 0.5
    else:
        lower = f" {location.lower()} "
        if any(token in lower for token in US_TOKENS):
            location_score = 1.0
        elif any(token in lower for token in ANGLOSPHERE_TOKENS):
            location_score = 0.7
        else:
            location_score = 0.4

    weighted = 0.4 * follower_score + 0.35 * niche_score + 0.25 * location_score
    return max(0.0, min(1.0, round(weighted, 3)))


def generate_seed_queries() -> list[str]:
    return [
        "best small jewelry brands to follow on instagram",
        "handmade fine jewelry designers instagram USA",
        "emerging independent silver jewelry brands instagram 2026",
        "minimalist gold jewelry boutique instagram small business",
        "handmade gemstone jewelry brands to watch on instagram",
        "bohemian jewelry designers instagram under 10k followers",
        "best jewelry brands to buy on instagram UK",
        "ethical handcrafted jewelry designers instagram",
        "family-owned jewelry brand instagram Canada",
        "up and coming demi-fine jewelry brands instagram",
        "pearl jewelry designer instagram small business",
        "vintage inspired jewelry brand instagram 2026",
        "artisan goldsmith instagram independent",
        "handcrafted sterling silver jewelry instagram shop",
        "emerging diamond jewelry designer instagram new brand",
    ]


async def search_tavily(query: str, max_results: int = 20) -> tuple[list[dict[str, Any]], int]:
    payload = {
        "api_key": _env("TAVILY_API_KEY"),
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_images": False,
    }
    start = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(4):
            response = await client.post(TAVILY_URL, json=payload)
            if response.status_code == 429:
                if attempt >= 3:
                    raise RuntimeError("Tavily rate limit: exhausted retries")
                await asyncio.sleep(min(60, (2**attempt) * 5))
                continue
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                raise RuntimeError(f"Tavily returned error: {data['error']}")
            elapsed = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            return list(data.get("results") or []), elapsed
    raise RuntimeError("Tavily request failed")


def _merge_social_account(existing: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return payload
    merged = dict(existing)
    merged.update(
        {
            "id": payload["id"],
            "username": payload["username"],
            "follower_count": existing.get("follower_count") or payload.get("follower_count"),
            "location": existing.get("location") or payload.get("location"),
            "niche": existing.get("niche") or payload.get("niche"),
            "fit_score": existing.get("fit_score") or payload.get("fit_score"),
            "synced_at": payload.get("synced_at"),
        }
    )
    for preserved in ("source_url", "discovered_via_query", "source", "discovery_source", "first_seen_at"):
        merged[preserved] = existing.get(preserved) or payload.get(preserved)
    return merged


async def run_discovery_session(queries: list[str], max_results: int = 20) -> DashboardSocialDiscoveryRunResponse:
    queries_run = 0
    queries_failed = 0
    total_results = 0
    total_extracted = 0
    seen_this_session: set[str] = set()
    new_accounts_added = 0
    already_known = 0
    total_response_ms = 0
    errors: list[dict[str, str]] = []

    for query in queries:
        try:
            results, response_ms = await search_tavily(query, max_results=max_results)
        except Exception as exc:
            message = str(exc)
            logger.warning("Tavily discovery failed for %s: %s", query, message)
            errors.append({"query": query, "error": message})
            queries_failed += 1
            dashboard_table("search_queries").insert(
                {
                    "query": query,
                    "purpose": "discovery",
                    "results_count": 0,
                    "unique_accounts_extracted": 0,
                    "new_accounts_added": 0,
                }
            ).execute()
            continue

        queries_run += 1
        total_response_ms += response_ms
        total_results += len(results)
        extracted = [item for result in results for item in extract_ig_handles(result)]
        total_extracted += len(extracted)

        per_query: dict[str, ExtractedAccount] = {}
        for item in extracted:
            previous = per_query.get(item.handle)
            if previous is None:
                per_query[item.handle] = item
                continue
            per_query[item.handle] = ExtractedAccount(
                handle=item.handle,
                follower_count=previous.follower_count or item.follower_count,
                location=previous.location or item.location,
                niche=previous.niche or item.niche,
                source_url=previous.source_url,
                source_title=previous.source_title,
            )

        handles = list(per_query.keys())
        existing_rows = (
            dashboard_table("social_accounts").select("*").in_("id", handles).execute().data or []
            if handles
            else []
        )
        existing_by_id = {str(row.get("id")): row for row in existing_rows}

        rows_to_upsert: list[dict[str, Any]] = []
        new_this_query = 0
        now_iso = utc_now_iso()
        for handle, item in per_query.items():
            is_new = handle not in existing_by_id
            if is_new and handle not in seen_this_session:
                new_this_query += 1
            seen_this_session.add(handle)
            payload = {
                "id": handle,
                "username": handle,
                "account_type": "UNKNOWN",
                "follower_count": item.follower_count,
                "is_verified": False,
                "location": item.location,
                "niche": item.niche,
                "fit_score": score_account_fit(
                    follower_count=item.follower_count,
                    location=item.location,
                    niche=item.niche,
                ),
                "source_url": item.source_url,
                "discovered_via_query": query,
                "source": "tavily_search",
                "discovery_source": "tavily_search",
                "first_seen_at": now_iso,
                "synced_at": now_iso,
            }
            rows_to_upsert.append(_merge_social_account(existing_by_id.get(handle), payload))

        if rows_to_upsert:
            dashboard_table("social_accounts").upsert(rows_to_upsert, on_conflict="id").execute()

        new_accounts_added += new_this_query
        already_known += max(0, len(handles) - new_this_query)
        dashboard_table("search_queries").insert(
            {
                "query": query,
                "purpose": "discovery",
                "results_count": len(results),
                "unique_accounts_extracted": len(per_query),
                "new_accounts_added": new_this_query,
            }
        ).execute()

    return DashboardSocialDiscoveryRunResponse(
        queriesRun=queries_run,
        queriesFailed=queries_failed,
        totalResultsFromTavily=total_results,
        totalExtractedHandles=total_extracted,
        totalUniqueHandles=len(seen_this_session),
        newAccountsAdded=new_accounts_added,
        alreadyKnown=already_known,
        totalResponseMs=total_response_ms,
        errors=errors,
    )


def _build_meta_url(path: str, params: dict[str, str]) -> str:
    query = httpx.QueryParams(params)
    return f"{META_BASE_URL}{path}?{query}"


async def _fetch_meta_json(url: str, *, attempt: int = 0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.get(url)
    if response.status_code in {429, 613}:
        if attempt >= 4:
            raise RuntimeError(f"IG rate limit: exhausted retries at {response.status_code}")
        retry_after = int(response.headers.get("retry-after") or "30")
        await asyncio.sleep(min(retry_after, (2**attempt) * 10))
        return await _fetch_meta_json(url, attempt=attempt + 1)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        error = payload["error"]
        raise RuntimeError(f"IG Graph {error.get('code')}: {error.get('message')}")
    return payload


async def _fetch_all_meta_pages(initial_url: str, max_pages: int = 20) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    next_url: str | None = initial_url
    pages = 0
    while next_url and pages < max_pages:
        payload = await _fetch_meta_json(next_url)
        results.extend(payload.get("data") or [])
        next_url = (payload.get("paging") or {}).get("next")
        pages += 1
    return results


def _meta_system_token() -> str:
    return _env("META_SYSTEM_USER_TOKEN", "META_ACCESS_TOKEN")


def _page_id() -> str:
    return _env("META_PAGE_ID")


def _page_token() -> str:
    return _env("META_PAGE_ACCESS_TOKEN")


async def get_business_account_id() -> str:
    global _cached_business_account_id
    if _cached_business_account_id:
        return _cached_business_account_id
    payload = await _fetch_meta_json(
        _build_meta_url(
            f"/{_page_id()}",
            {
                "fields": "instagram_business_account",
                "access_token": _meta_system_token(),
            },
        )
    )
    account = payload.get("instagram_business_account") or {}
    business_id = account.get("id")
    if not business_id:
        raise RuntimeError("No instagram_business_account linked to Page")
    _cached_business_account_id = str(business_id)
    return _cached_business_account_id


def _map_media_type(value: str | None) -> str:
    if value == "CAROUSEL_ALBUM":
        return "CAROUSEL"
    if value in {"VIDEO", "REELS"}:
        return "VIDEO"
    return "IMAGE"


def _later_iso(left: str | None, right: str | None) -> str | None:
    if not left:
        return right
    if not right:
        return left
    return max(left, right)


def _merge_engagement_account(existing: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return payload
    merged = dict(existing)
    merged.update(
        {
            "id": payload["id"],
            "username": payload["username"],
            "last_engaged_with_us_at": _later_iso(
                iso_or_none(existing.get("last_engaged_with_us_at")),
                iso_or_none(payload.get("last_engaged_with_us_at")),
            ),
            "synced_at": payload.get("synced_at"),
        }
    )
    for preserved in ("first_seen_at", "source", "discovery_source", "source_url", "discovered_via_query"):
        merged[preserved] = existing.get(preserved) or payload.get(preserved)
    return merged


async def _get_recent_media(ig_id: str, days: int) -> list[dict[str, Any]]:
    url = _build_meta_url(
        f"/{ig_id}/media",
        {
            "fields": "id,timestamp,caption,media_type,permalink,like_count,comments_count,username",
            "limit": "50",
            "access_token": _meta_system_token(),
        },
    )
    all_media = await _fetch_all_meta_pages(url, max_pages=10)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for item in all_media:
        timestamp = iso_or_none(item.get("timestamp"))
        if not timestamp:
            continue
        if datetime.fromisoformat(timestamp.replace("Z", "+00:00")) >= cutoff:
            recent.append(item)
    return recent


async def sync_recent_engagers(days: int = 30) -> dict[str, Any]:
    ig_id = await get_business_account_id()
    media = await _get_recent_media(ig_id, days)
    by_username: dict[str, str] = {}
    comments_seen = 0
    posts_skipped = 0

    for post in media:
        url = _build_meta_url(
            f"/{post['id']}/comments",
            {
                "fields": "id,text,timestamp,username",
                "limit": "100",
                "access_token": _meta_system_token(),
            },
        )
        try:
            comments = await _fetch_all_meta_pages(url, max_pages=5)
        except Exception as exc:
            posts_skipped += 1
            logger.warning("Instagram comment fetch failed for %s: %s", post.get("id"), exc)
            continue
        comments_seen += len(comments)
        for comment in comments:
            username = str(comment.get("username") or "").strip()
            if not username or username.lower() == "gemzy_co":
                continue
            timestamp = iso_or_none(comment.get("timestamp")) or utc_now_iso()
            by_username[username] = _later_iso(by_username.get(username), timestamp) or timestamp

    if by_username:
        existing_rows = (
            dashboard_table("social_accounts").select("*").in_("id", list(by_username.keys())).execute().data or []
        )
        existing_by_id = {str(row.get("id")): row for row in existing_rows}
        now_iso = utc_now_iso()
        rows = []
        for username, last_at in by_username.items():
            payload = {
                "id": username,
                "username": username,
                "account_type": "UNKNOWN",
                "is_verified": False,
                "first_seen_at": now_iso,
                "last_engaged_with_us_at": last_at,
                "source": "post_engager",
                "synced_at": now_iso,
            }
            rows.append(_merge_engagement_account(existing_by_id.get(username), payload))
        dashboard_table("social_accounts").upsert(rows, on_conflict="id").execute()

    return {
        "postsScanned": len(media),
        "commentsSeen": comments_seen,
        "uniqueAccounts": len(by_username),
        "postsSkipped": posts_skipped,
    }


async def sync_recent_mentioners(days: int = 30) -> dict[str, Any]:
    ig_id = await get_business_account_id()
    url = _build_meta_url(
        f"/{ig_id}/tags",
        {
            "fields": "id,caption,media_type,permalink,timestamp,username,like_count,comments_count",
            "limit": "50",
            "access_token": _meta_system_token(),
        },
    )
    try:
        tagged = await _fetch_all_meta_pages(url, max_pages=10)
    except Exception as exc:
        message = str(exc)
        logger.warning("Instagram tags endpoint failed: %s", message)
        return {"mediaFound": 0, "uniqueAccounts": 0, "postsUpserted": 0, "note": f"tags endpoint failed: {message}"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for item in tagged:
        timestamp = iso_or_none(item.get("timestamp"))
        if not timestamp:
            continue
        if datetime.fromisoformat(timestamp.replace("Z", "+00:00")) >= cutoff:
            recent.append(item)

    accounts: dict[str, str] = {}
    post_rows: list[dict[str, Any]] = []
    now_iso = utc_now_iso()
    for item in recent:
        username = str(item.get("username") or "").strip()
        if not username or username.lower() == "gemzy_co":
            continue
        timestamp = iso_or_none(item.get("timestamp")) or now_iso
        accounts[username] = _later_iso(accounts.get(username), timestamp) or timestamp
        post_rows.append(
            {
                "id": item["id"],
                "account_id": username,
                "caption": item.get("caption"),
                "media_type": _map_media_type(item.get("media_type")),
                "permalink": item.get("permalink"),
                "like_count": item.get("like_count"),
                "comment_count": item.get("comments_count"),
                "published_at": timestamp,
                "synced_at": now_iso,
            }
        )

    if accounts:
        existing_rows = dashboard_table("social_accounts").select("*").in_("id", list(accounts.keys())).execute().data or []
        existing_by_id = {str(row.get("id")): row for row in existing_rows}
        rows = []
        for username, last_at in accounts.items():
            payload = {
                "id": username,
                "username": username,
                "account_type": "UNKNOWN",
                "is_verified": False,
                "first_seen_at": now_iso,
                "last_engaged_with_us_at": last_at,
                "source": "mentioner",
                "synced_at": now_iso,
            }
            rows.append(_merge_engagement_account(existing_by_id.get(username), payload))
        dashboard_table("social_accounts").upsert(rows, on_conflict="id").execute()

    if post_rows:
        dashboard_table("social_posts").upsert(post_rows, on_conflict="id").execute()

    return {
        "mediaFound": len(recent),
        "uniqueAccounts": len(accounts),
        "postsUpserted": len(post_rows),
    }


async def sync_dm_senders(days: int = 30) -> dict[str, Any]:
    url = _build_meta_url(
        f"/{_page_id()}/conversations",
        {
            "platform": "instagram",
            "fields": "participants,updated_time",
            "limit": "50",
            "access_token": _page_token(),
        },
    )
    try:
        conversations = await _fetch_all_meta_pages(url, max_pages=10)
    except Exception as exc:
        message = str(exc)
        logger.warning("Instagram conversations endpoint failed: %s", message)
        return {"conversations": 0, "uniqueAccounts": 0, "note": f"conversations endpoint failed: {message}"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    accounts: dict[str, str] = {}
    for conversation in conversations:
        updated_time = iso_or_none(conversation.get("updated_time"))
        if not updated_time:
            continue
        updated_at = datetime.fromisoformat(updated_time.replace("Z", "+00:00"))
        if updated_at < cutoff:
            continue
        for participant in (conversation.get("participants") or {}).get("data") or []:
            username = str(participant.get("username") or participant.get("name") or "").strip()
            if not username or "gemzy" in username.lower():
                continue
            accounts[username] = _later_iso(accounts.get(username), updated_time) or updated_time

    if accounts:
        existing_rows = dashboard_table("social_accounts").select("*").in_("id", list(accounts.keys())).execute().data or []
        existing_by_id = {str(row.get("id")): row for row in existing_rows}
        now_iso = utc_now_iso()
        rows = []
        for username, last_at in accounts.items():
            payload = {
                "id": username,
                "username": username,
                "account_type": "UNKNOWN",
                "is_verified": False,
                "first_seen_at": now_iso,
                "last_engaged_with_us_at": last_at,
                "source": "dm_sender",
                "synced_at": now_iso,
            }
            rows.append(_merge_engagement_account(existing_by_id.get(username), payload))
        dashboard_table("social_accounts").upsert(rows, on_conflict="id").execute()

    return {"conversations": len(conversations), "uniqueAccounts": len(accounts)}


async def get_account_insights(metrics: list[str], days: int = 7) -> list[DashboardInstagramInsightResponse]:
    ig_id = await get_business_account_id()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    since = now_ts - days * 86400
    payload = await _fetch_meta_json(
        _build_meta_url(
            f"/{ig_id}/insights",
            {
                "metric": ",".join(metrics),
                "metric_type": "total_value",
                "period": "day",
                "since": str(since),
                "until": str(now_ts),
                "access_token": _meta_system_token(),
            },
        )
    )
    rows = []
    for row in payload.get("data") or []:
        rows.append(
            DashboardInstagramInsightResponse(
                name=str(row.get("name") or ""),
                total=int(((row.get("total_value") or {}).get("value")) or 0),
            )
        )
    return rows


async def sync_all_instagram(days: int = 30) -> DashboardInstagramSyncResponse:
    start = datetime.now(timezone.utc)

    async def _safe(label: str, fn) -> dict[str, Any]:
        try:
            return await fn()
        except Exception as exc:
            logger.error("Instagram sync step %s failed: %s", label, exc)
            return {"error": str(exc)}

    engagers = await _safe("engagers", lambda: sync_recent_engagers(days))
    mentioners = await _safe("mentioners", lambda: sync_recent_mentioners(days))
    dm_senders = await _safe("dm_senders", lambda: sync_dm_senders(days))
    duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    return DashboardInstagramSyncResponse(
        engagers=engagers,
        mentioners=mentioners,
        dmSenders=dm_senders,
        durationMs=duration_ms,
    )


@router.post("/discovery/run", response_model=DashboardSocialDiscoveryRunResponse)
async def run_social_discovery(
    payload: DashboardSocialDiscoveryRunPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardSocialDiscoveryRunResponse:
    ensure_dashboard_admin(current)
    queries = payload.queries or generate_seed_queries()
    if not queries:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No discovery queries supplied")
    return await run_discovery_session(queries, max_results=payload.maxResults)


@router.post("/instagram/sync", response_model=DashboardInstagramSyncResponse)
async def sync_social_instagram(
    payload: DashboardSocialSourceSyncPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardInstagramSyncResponse:
    ensure_dashboard_admin(current)
    return await sync_all_instagram(days=payload.days)


@router.get("/instagram/insights", response_model=list[DashboardInstagramInsightResponse])
async def get_social_instagram_insights(
    metrics: str = Query("reach,profile_views"),
    days: int = Query(default=7, ge=1, le=90),
    current: UserState = Depends(get_current_user),
) -> list[DashboardInstagramInsightResponse]:
    ensure_dashboard_admin(current)
    parsed_metrics = [metric.strip() for metric in metrics.split(",") if metric.strip()]
    if not parsed_metrics:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one metric is required")
    return await get_account_insights(parsed_metrics, days=days)
