from __future__ import annotations

"""FA Admin proxy — dev-mode only routes that forward to hub-api admin endpoints."""
import os
import logging
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger("demoforge.fa_admin")
router = APIRouter()

_LOCAL_HUB_CANDIDATES = ["http://localhost:8000", "http://host.docker.internal:8000"]


async def _resolve_hub_url() -> str:
    """Find hub-api: try local candidates first, then DEMOFORGE_HUB_API_URL (direct Cloud Run
    URL), then DEMOFORGE_HUB_URL (gateway) as a last resort.
    Raises 503 only if no reachable endpoint is found.

    Priority:
      1. Local hub-api (localhost:8000 / host.docker.internal:8000) — dev-start
      2. DEMOFORGE_HUB_API_URL — direct Cloud Run URL, no gateway routing needed (dev-start-gcp)
      3. DEMOFORGE_HUB_URL — gateway URL (legacy fallback; requires X-Service routing by gateway)
    """
    direct_url = os.getenv("DEMOFORGE_HUB_API_URL", "").rstrip("/")
    gateway_url = os.getenv("DEMOFORGE_HUB_URL", "").rstrip("/")
    fallback = direct_url or gateway_url
    # Use short timeout when a remote fallback is available — avoids 6s wait per request
    local_timeout = 1.0 if fallback else 3.0
    async with httpx.AsyncClient() as client:
        for url in _LOCAL_HUB_CANDIDATES:
            try:
                r = await client.get(f"{url}/api/hub/health", timeout=local_timeout)
                if r.status_code == 200 and r.json().get("service") == "demoforge-hub-api":
                    return url
            except Exception:
                continue
        if fallback:
            return fallback
    raise HTTPException(
        503,
        "Hub API not reachable. Set DEMOFORGE_HUB_API_URL or start local hub-api with `make dev-hub-api`."
    )


def _dev_guard():
    if os.getenv("DEMOFORGE_MODE", "dev") != "dev":
        raise HTTPException(403, "FA admin endpoints are only available in dev mode.")
    if not os.getenv("DEMOFORGE_HUB_API_ADMIN_KEY", ""):
        raise HTTPException(503, "Hub API admin key not configured. Run `make dev-init` and restart the backend.")


def _admin_headers() -> dict:
    return {"X-Hub-Admin-Key": os.getenv("DEMOFORGE_HUB_API_ADMIN_KEY", ""), "Content-Type": "application/json"}


def _parse_response(r: httpx.Response) -> JSONResponse:
    """Return a JSONResponse, handling non-JSON bodies gracefully."""
    try:
        data = r.json()
        return JSONResponse(content=data, status_code=r.status_code)
    except Exception:
        hint = "Check DEMOFORGE_HUB_API_ADMIN_KEY." if r.status_code == 401 else "Check DEMOFORGE_HUB_URL."
        raise HTTPException(
            503,
            f"Hub API returned a non-JSON response (status {r.status_code}). {hint}"
        )


async def _proxy_get(path: str, params: dict | None = None) -> JSONResponse:
    hub_url = await _resolve_hub_url()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(f"{hub_url}{path}", headers=_admin_headers(), params=params)
            return _parse_response(r)
        except HTTPException:
            raise
        except httpx.ConnectError:
            raise HTTPException(503, f"Hub API is unreachable at {hub_url}. Is hub-api running?")
        except Exception as e:
            logger.warning(f"Hub API request failed: {e}")
            raise HTTPException(502, f"Hub API error: {e}")


async def _proxy_put(path: str, body: dict) -> JSONResponse:
    hub_url = await _resolve_hub_url()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.put(f"{hub_url}{path}", headers=_admin_headers(), json=body)
            return _parse_response(r)
        except HTTPException:
            raise
        except httpx.ConnectError:
            raise HTTPException(503, f"Hub API is unreachable at {hub_url}. Is hub-api running?")
        except Exception as e:
            logger.warning(f"Hub API request failed: {e}")
            raise HTTPException(502, f"Hub API error: {e}")


async def _proxy_post(path: str, body: dict) -> JSONResponse:
    hub_url = await _resolve_hub_url()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(f"{hub_url}{path}", headers=_admin_headers(), json=body)
            return _parse_response(r)
        except HTTPException:
            raise
        except httpx.ConnectError:
            raise HTTPException(503, f"Hub API is unreachable at {hub_url}. Is hub-api running?")
        except Exception as e:
            logger.warning(f"Hub API request failed: {e}")
            raise HTTPException(502, f"Hub API error: {e}")


async def _proxy_delete(path: str) -> JSONResponse:
    hub_url = await _resolve_hub_url()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.delete(f"{hub_url}{path}", headers=_admin_headers())
            return _parse_response(r)
        except HTTPException:
            raise
        except httpx.ConnectError:
            raise HTTPException(503, f"Hub API is unreachable at {hub_url}. Is hub-api running?")
        except Exception as e:
            logger.warning(f"Hub API request failed: {e}")
            raise HTTPException(502, f"Hub API error: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/api/fa-admin/stats")
async def get_admin_stats():
    _dev_guard()
    return await _proxy_get("/api/hub/admin/stats")


@router.get("/api/fa-admin/fas")
async def list_fas():
    _dev_guard()
    return await _proxy_get("/api/hub/admin/fas")


@router.get("/api/fa-admin/fas/{fa_id}")
async def get_fa(fa_id: str):
    _dev_guard()
    return await _proxy_get(f"/api/hub/admin/fas/{fa_id}")


@router.get("/api/fa-admin/fas/{fa_id}/activity")
async def get_fa_activity(fa_id: str, request: Request):
    _dev_guard()
    params = dict(request.query_params)
    return await _proxy_get(f"/api/hub/admin/fas/{fa_id}/activity", params=params)


@router.put("/api/fa-admin/fas/{fa_id}/permissions")
async def update_fa_permissions(fa_id: str, request: Request):
    _dev_guard()
    body = await request.json()
    return await _proxy_put(f"/api/hub/admin/fas/{fa_id}/permissions", body)


@router.put("/api/fa-admin/fas/{fa_id}/status")
async def update_fa_status(fa_id: str, request: Request):
    _dev_guard()
    body = await request.json()
    return await _proxy_put(f"/api/hub/admin/fas/{fa_id}/status", body)


@router.delete("/api/fa-admin/fas/{fa_id}")
async def purge_fa(fa_id: str):
    _dev_guard()
    return await _proxy_delete(f"/api/hub/admin/fas/{quote(fa_id, safe='')}")


@router.post("/api/fa-admin/fas")
async def create_fa(request: Request):
    _dev_guard()
    body = await request.json()
    return await _proxy_post("/api/hub/admin/fas", body)


@router.get("/api/fa-admin/fas/{fa_id}/key")
async def get_fa_key(fa_id: str):
    _dev_guard()
    return await _proxy_get(f"/api/hub/admin/fas/{quote(fa_id, safe='')}/key")


@router.put("/api/fa-admin/fas/{fa_id}/key")
async def update_fa_key(fa_id: str, request: Request):
    _dev_guard()
    body = await request.json()
    return await _proxy_put(f"/api/hub/admin/fas/{quote(fa_id, safe='')}/key", body)


@router.get("/api/fa/licenses/cache")
async def cache_licenses():
    """Pre-fetch and cache all licenses defined across component manifests."""
    from ..config.license_store import license_store
    from ..registry.loader import get_registry

    fa_key = os.getenv("DEMOFORGE_API_KEY", "")
    if not fa_key:
        return {"status": "skipped", "reason": "no FA key configured"}

    # Discover all unique license IDs from every component manifest
    license_ids: set[str] = set()
    for manifest in get_registry().values():
        for req in getattr(manifest, "license_requirements", []):
            if req.license_id:
                license_ids.add(req.license_id)

    cached, failed = 0, []
    for lid in sorted(license_ids):
        entry = license_store._http_get(lid)
        if entry:
            license_store.set(entry)
            cached += 1
        else:
            failed.append(lid)

    return {"status": "ok", "cached": cached, "failed": failed, "discovered": sorted(license_ids)}
