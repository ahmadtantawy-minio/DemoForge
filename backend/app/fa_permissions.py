from __future__ import annotations

"""Cached FA permission fetcher — queries hub-api /me endpoint with a 60s TTL.

Fail-open: if hub-api is unreachable, returns default permissive values so the
FA-mode UX is not degraded by a transient network issue.
"""
import asyncio
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

    async def get_permissions(self) -> dict[str, Any]:
        async with self._lock:
            if time.monotonic() - self._fetched_at < _TTL and self._permissions:
                return self._permissions
            fresh = await self._fetch()
            if fresh:
                self._permissions = fresh
                self._fetched_at = time.monotonic()
            elif not self._permissions:
                self._permissions = dict(_DEFAULTS)
            return self._permissions

    async def _fetch(self) -> dict[str, Any] | None:
        hub_url = os.getenv("DEMOFORGE_HUB_URL", "").rstrip("/")
        api_key = os.getenv("DEMOFORGE_API_KEY", "")
        if not api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{hub_url}/api/hub/fa/me",
                    headers={"X-Api-Key": api_key},
                )
                if r.status_code == 200:
                    data = r.json()
                    return data.get("permissions", {})
        except Exception as e:
            logger.warning(f"FA permission fetch failed (fail-open): {e}")
        return None

    async def check_permission(self, name: str, default: bool = True) -> bool:
        perms = await self.get_permissions()
        return bool(perms.get(name, default))


permission_cache = FAPermissionCache()
