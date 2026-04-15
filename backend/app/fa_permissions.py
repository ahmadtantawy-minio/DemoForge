from __future__ import annotations

"""Cached FA permission fetcher — queries hub-api /me endpoint with a 60s TTL.

Fail-open: if hub-api is unreachable, returns last-known-good permissions from
disk cache, or hardcoded permissive defaults if no cache exists. This ensures
demo creation is never blocked by a transient network or auth failure.

Disk cache: written to DEMOFORGE_DATA_DIR/fa-permissions.json after every
successful hub fetch. Loaded on cold start when hub is unreachable.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("demoforge.fa_permissions")

_DEFAULTS: dict[str, Any] = {
    "manual_demo_creation": True,
    "template_publish": True,
    "template_fork": True,
    "max_concurrent_demos": 5,
}
_TTL = 60  # seconds


class FAPermissionCache:
    def __init__(self) -> None:
        self._permissions: dict[str, Any] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def _cache_path(self) -> str:
        data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
        return os.path.join(data_dir, "fa-permissions.json")

    def _load_disk_cache(self) -> dict[str, Any] | None:
        try:
            with open(self._cache_path) as f:
                data = json.load(f)
            perms = data.get("permissions") if isinstance(data, dict) else None
            return perms if isinstance(perms, dict) else None
        except Exception:
            return None

    def _save_disk_cache(self, permissions: dict[str, Any]) -> None:
        try:
            path = self._cache_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"permissions": permissions, "cached_at": time.time()}, f)
            os.replace(tmp, path)
        except Exception as e:
            logger.warning("Failed to write FA permission cache: %s", e)

    async def get_permissions(self) -> dict[str, Any]:
        async with self._lock:
            if time.monotonic() - self._fetched_at < _TTL and self._permissions:
                return self._permissions
            fresh = await self._fetch()
            if fresh is not None:
                self._permissions = fresh
                self._fetched_at = time.monotonic()
                self._save_disk_cache(fresh)
            elif not self._permissions:
                # Cold start or hub unreachable — prefer disk cache over hardcoded defaults
                disk = self._load_disk_cache()
                self._permissions = disk if disk is not None else dict(_DEFAULTS)
                if disk is not None:
                    logger.info("FA permissions loaded from disk cache (hub unreachable)")
            return self._permissions

    async def _fetch(self) -> dict[str, Any] | None:
        hub_url = os.getenv("DEMOFORGE_HUB_URL", "").rstrip("/")
        api_key = os.getenv("DEMOFORGE_API_KEY", "")
        if not api_key:
            return None
        # Gateway key for X-Api-Key (access control); FA key in X-Fa-Api-Key for identity
        gw_key = os.environ.get("DEMOFORGE_GATEWAY_API_KEY", "") or api_key
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{hub_url}/api/hub/fa/me",
                    headers={"X-Api-Key": gw_key, "X-Fa-Api-Key": api_key},
                )
                if r.status_code == 200:
                    data = r.json()
                    return data.get("permissions", {})
        except Exception as e:
            logger.warning("FA permission fetch failed (fail-open): %s", e)
        return None

    async def check_permission(self, name: str, default: bool = True) -> bool:
        perms = await self.get_permissions()
        return bool(perms.get(name, default))


permission_cache = FAPermissionCache()
