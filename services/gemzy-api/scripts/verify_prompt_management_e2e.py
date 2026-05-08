from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _repo_sibling_path(name: str) -> Path:
    return Path(__file__).resolve().parents[4] / name


def _normalize_url(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _json_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> tuple[int, Any]:
    payload = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=payload,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return error.code, parsed
    except urllib.error.URLError as error:
        return 0, {"error": str(error.reason)}


def _append(results: list[CheckResult], name: str, status: str, detail: str) -> None:
    results.append(CheckResult(name=name, status=status, detail=detail))


def _find_engine_in_catalog(body: dict[str, Any], engine_slug: str) -> tuple[str, dict[str, Any]] | None:
    for surface_name in ("onModel", "pureJewelry"):
        surface = body.get(surface_name) or {}
        for engine in surface.get("engines") or []:
            if engine.get("engineSlug") == engine_slug:
                return surface_name, engine
    return None


def _query_supabase_rows(
    *,
    supabase_url: str,
    table: str,
    api_key: str,
    schema: str,
    params: dict[str, str],
    timeout: float,
) -> tuple[int, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{supabase_url}/rest/v1/{table}"
    if query:
        url = f"{url}?{query}"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept-Profile": schema,
    }
    return _json_request(url, headers=headers, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify prompt management wiring across dashboard, gemzy-api, and gemzy.",
    )
    parser.add_argument(
        "--dashboard-env",
        type=Path,
        default=_repo_sibling_path("gemzy-dashboard") / ".env",
    )
    parser.add_argument(
        "--api-env",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
    )
    parser.add_argument(
        "--app-config",
        type=Path,
        default=_repo_sibling_path("gemzy") / "mobile.dev.json",
    )
    parser.add_argument(
        "--engine-slug",
        default="",
        help="Optional engine slug to compare across admin API, DB, and /generations/ui-config.",
    )
    parser.add_argument(
        "--bearer-token",
        default=os.getenv("PROMPT_ENGINE_BEARER_TOKEN", ""),
        help="Optional admin bearer token for prompt-engine routes. Defaults to PROMPT_ENGINE_BEARER_TOKEN.",
    )
    parser.add_argument(
        "--supabase-service-key",
        default=os.getenv("SUPABASE_SERVICE_KEY", ""),
        help="Optional Supabase service key for direct DB verification. Defaults to SUPABASE_SERVICE_KEY.",
    )
    parser.add_argument(
        "--prompt-schema",
        default=os.getenv("SUPABASE_PROMPT_SCHEMA", "public"),
        help="Schema for prompt registry tables when querying Supabase REST. Defaults to public.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    results: list[CheckResult] = []

    dashboard_env = _load_env_file(args.dashboard_env)
    api_env = _load_env_file(args.api_env)
    app_config = {}
    if args.app_config.exists():
        app_config = json.loads(args.app_config.read_text(encoding="utf-8"))

    dashboard_prompt_url = _normalize_url(dashboard_env.get("VITE_PROMPT_ENGINE_API_URL"))
    dashboard_supabase_url = _normalize_url(dashboard_env.get("VITE_SUPABASE_URL"))
    api_supabase_url = _normalize_url(api_env.get("SUPABASE_URL"))
    app_api_base_url = _normalize_url(str(app_config.get("apiBaseUrl", "")))

    if dashboard_prompt_url and app_api_base_url and dashboard_prompt_url == app_api_base_url:
        _append(
            results,
            "config.api-base-alignment",
            "pass",
            f"Dashboard prompt API and gemzy app API both point at {app_api_base_url}.",
        )
    else:
        _append(
            results,
            "config.api-base-alignment",
            "fail",
            "Dashboard prompt API base and gemzy app API base are not aligned.",
        )

    if dashboard_supabase_url and api_supabase_url and dashboard_supabase_url == api_supabase_url:
        _append(
            results,
            "config.supabase-alignment",
            "pass",
            f"Dashboard and gemzy-api use the same Supabase project ({api_supabase_url}).",
        )
    else:
        _append(
            results,
            "config.supabase-alignment",
            "fail",
            "Dashboard and gemzy-api Supabase URLs are not aligned.",
        )

    if not app_api_base_url:
        _append(results, "runtime.ui-config", "skip", "Gemzy app API base URL is not configured.")
    else:
        status, body = _json_request(
            f"{app_api_base_url}/generations/ui-config",
            timeout=args.timeout,
        )
        if status == 200 and isinstance(body, dict):
            version = body.get("version")
            if version and body.get("onModel") and body.get("pureJewelry"):
                _append(
                    results,
                    "runtime.ui-config",
                    "pass",
                    f"/generations/ui-config returned version {version}.",
                )
            else:
                _append(
                    results,
                    "runtime.ui-config",
                    "fail",
                    "/generations/ui-config responded but did not return the expected catalog shape.",
                )

            if args.engine_slug:
                located = _find_engine_in_catalog(body, args.engine_slug)
                if located:
                    surface_name, engine = located
                    prompt_version = engine.get("promptVersion") or "<missing>"
                    _append(
                        results,
                        "runtime.catalog-engine",
                        "pass",
                        f"Engine {args.engine_slug} is present on {surface_name} with promptVersion={prompt_version}.",
                    )
                else:
                    _append(
                        results,
                        "runtime.catalog-engine",
                        "fail",
                        f"Engine {args.engine_slug} is missing from /generations/ui-config.",
                    )
        else:
            _append(
                results,
                "runtime.ui-config",
                "fail",
                f"/generations/ui-config returned HTTP {status}.",
            )

    engine_response: dict[str, Any] | None = None
    if not dashboard_prompt_url:
        _append(results, "admin.prompt-engines", "skip", "Dashboard prompt-engine API base URL is not configured.")
    elif not args.bearer_token:
        _append(results, "admin.prompt-engines", "skip", "No admin bearer token provided.")
    else:
        headers = {"Authorization": f"Bearer {args.bearer_token}"}
        status, body = _json_request(
            f"{dashboard_prompt_url}/prompt-engines",
            headers=headers,
            timeout=args.timeout,
        )
        if status == 200 and isinstance(body, list):
            _append(
                results,
                "admin.prompt-engines",
                "pass",
                f"Admin GET /prompt-engines returned {len(body)} engines.",
            )
        else:
            _append(
                results,
                "admin.prompt-engines",
                "fail",
                f"Admin GET /prompt-engines returned HTTP {status}.",
            )

        if args.engine_slug:
            status, body = _json_request(
                f"{dashboard_prompt_url}/prompt-engines/{urllib.parse.quote(args.engine_slug)}",
                headers=headers,
                timeout=args.timeout,
            )
            if status == 200 and isinstance(body, dict):
                engine_response = body
                published_version = body.get("publishedVersionId") or "<missing>"
                _append(
                    results,
                    "admin.engine-detail",
                    "pass",
                    f"Admin GET /prompt-engines/{args.engine_slug} returned publishedVersionId={published_version}.",
                )
            else:
                _append(
                    results,
                    "admin.engine-detail",
                    "fail",
                    f"Admin GET /prompt-engines/{args.engine_slug} returned HTTP {status}.",
                )

    supabase_key = args.supabase_service_key or api_env.get("SUPABASE_SERVICE_KEY", "")
    if not args.engine_slug:
        _append(results, "db.prompt-engine", "skip", "No --engine-slug provided for direct DB verification.")
    elif not api_supabase_url:
        _append(results, "db.prompt-engine", "skip", "SUPABASE_URL is not configured.")
    elif not supabase_key:
        _append(results, "db.prompt-engine", "skip", "No Supabase service key provided for direct DB verification.")
    else:
        status, rows = _query_supabase_rows(
            supabase_url=api_supabase_url,
            table="prompt_engines",
            api_key=supabase_key,
            schema=args.prompt_schema,
            params={
                "select": "id,slug,name,task_type,renderer_key,published_version_id,published_version_number",
                "slug": f"eq.{args.engine_slug}",
            },
            timeout=args.timeout,
        )
        if status == 200 and isinstance(rows, list) and rows:
            row = rows[0]
            _append(
                results,
                "db.prompt-engine",
                "pass",
                f"DB row for {args.engine_slug} found with published_version_id={row.get('published_version_id')}.",
            )
            if engine_response is not None:
                api_published = engine_response.get("publishedVersionId")
                db_published = row.get("published_version_id")
                if api_published == db_published:
                    _append(
                        results,
                        "db.admin-consistency",
                        "pass",
                        "Admin engine detail and DB row agree on published version.",
                    )
                else:
                    _append(
                        results,
                        "db.admin-consistency",
                        "fail",
                        f"Admin publishedVersionId={api_published} does not match DB published_version_id={db_published}.",
                    )

            published_version_id = row.get("published_version_id")
            if published_version_id:
                version_status, version_rows = _query_supabase_rows(
                    supabase_url=api_supabase_url,
                    table="prompt_engine_versions",
                    api_key=supabase_key,
                    schema=args.prompt_schema,
                    params={
                        "select": "id,engine_id,status,version_number,definition,sample_input,change_note",
                        "id": f"eq.{published_version_id}",
                    },
                    timeout=args.timeout,
                )
                if version_status == 200 and isinstance(version_rows, list) and version_rows:
                    version_row = version_rows[0]
                    _append(
                        results,
                        "db.prompt-engine-version",
                        "pass",
                        f"Published version row found with status={version_row.get('status')} version_number={version_row.get('version_number')}.",
                    )
                else:
                    _append(
                        results,
                        "db.prompt-engine-version",
                        "fail",
                        f"Prompt engine version query returned HTTP {version_status}.",
                    )

            route_status, route_rows = _query_supabase_rows(
                supabase_url=api_supabase_url,
                table="prompt_task_routes",
                api_key=supabase_key,
                schema=args.prompt_schema,
                params={
                    "select": "id,slug,task_type,priority,is_active,match_rules,engine_id,pinned_version_id",
                    "engine_id": f"eq.{row['id']}",
                    "order": "priority.desc",
                },
                timeout=args.timeout,
            )
            if route_status == 200 and isinstance(route_rows, list):
                _append(
                    results,
                    "db.prompt-routes",
                    "pass",
                    f"Found {len(route_rows)} prompt_task_routes rows for engine {args.engine_slug}.",
                )
            else:
                _append(
                    results,
                    "db.prompt-routes",
                    "fail",
                    f"Prompt task route query returned HTTP {route_status}.",
                )
        else:
            _append(
                results,
                "db.prompt-engine",
                "fail",
                f"Prompt engine query returned HTTP {status}.",
            )

    failed = 0
    skipped = 0
    for result in results:
        label = result.status.upper().ljust(4)
        print(f"[{label}] {result.name}: {result.detail}")
        if result.status == "fail":
            failed += 1
        elif result.status == "skip":
            skipped += 1

    print()
    print(f"Checks: {len(results)} total, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
