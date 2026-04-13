from __future__ import annotations

"""Connectivity health check — verbose multi-step chain checks for every component."""
import os
import asyncio
import logging
import time
import httpx

from fastapi import APIRouter

logger = logging.getLogger("demoforge.connectivity")
router = APIRouter()


def _mask_key(key: str) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return key[:2] + "***"
    return key[:6] + "..." + key[-4:]


async def _get(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict | None, str | None, float]:
    """GET url. Returns (status, json_or_none, text_preview, latency_ms)."""
    t0 = time.monotonic()
    try:
        r = await client.get(url, headers=headers or {}, timeout=timeout)
        latency = (time.monotonic() - t0) * 1000
        text = r.text[:200] if r.text else ""
        try:
            return r.status_code, r.json(), text, latency
        except Exception:
            return r.status_code, None, text, latency
    except httpx.ConnectError as e:
        return -1, None, str(e)[:120], 0.0
    except httpx.TimeoutException:
        return -2, None, f"Timed out after {timeout}s", 0.0
    except Exception as e:
        return -3, None, str(e)[:120], 0.0


def _step(name: str, ok: bool, detail: str = "", warn: bool = False) -> dict:
    return {"name": name, "ok": ok, "warn": warn, "detail": detail}


async def _check_hub_connector(hub_url: str) -> dict:
    """Full chain: connector reachable → gateway reachable → hub-api routed."""
    steps = []
    async with httpx.AsyncClient() as client:
        # Step 1: connector root
        code, _, text, ms = await _get(client, hub_url + "/")
        if code == -1:
            steps.append(_step("Connector reachable", False, f"Connection refused at {hub_url}"))
            return {"ok": False, "steps": steps}
        if code == -2:
            steps.append(_step("Connector reachable", False, "Timed out (>5s)"))
            return {"ok": False, "steps": steps}
        if code < 0:
            steps.append(_step("Connector reachable", False, text or "Network error"))
            return {"ok": False, "steps": steps}

        connector_running = "hub-connector" in (text or "").lower()
        steps.append(_step(
            "Connector reachable",
            True,
            f"HTTP {code} in {ms:.0f}ms — {text[:80].strip()!r}" if text else f"HTTP {code} in {ms:.0f}ms",
        ))

        # Step 2: gateway reachable via connector's /health proxy
        code2, _, text2, ms2 = await _get(client, hub_url + "/health")
        if code2 == 200 and text2 and ("ok" in text2.lower() or "demoforge" in text2.lower()):
            steps.append(_step("Gateway reachable", True, f"HTTP {code2} in {ms2:.0f}ms — {text2[:60].strip()!r}"))
        elif code2 > 0:
            preview2 = text2[:80].strip() if text2 else "(empty)"
            steps.append(_step("Gateway reachable", False,
                f"HTTP {code2} in {ms2:.0f}ms — {preview2!r}. "
                "Connector may be running but cannot reach the remote gateway."))
        else:
            steps.append(_step("Gateway reachable", False,
                f"Gateway check failed: {text2 or 'no response'}. Connector up but gateway unreachable."))

        # Step 3: hub-api route through connector → gateway → hub-api
        code3, data3, text3, ms3 = await _get(client, hub_url + "/api/hub/health")
        if code3 == 200 and data3 and data3.get("service") == "demoforge-hub-api":
            steps.append(_step("Hub API routed", True,
                f"HTTP {code3} in {ms3:.0f}ms — status={data3.get('status')}"))
            return {"ok": True, "steps": steps}
        elif code3 == 200 and data3 is None:
            raw_preview = (text3 or "").strip()[:80]
            steps.append(_step("Hub API routed", False,
                f"HTTP {code3} in {ms3:.0f}ms but non-JSON response: {raw_preview!r}. "
                "Connector does not have /api/hub/* route configured — "
                "rebuild connector image with `make hub-setup` or `minio-gcp.sh`."))
        elif code3 == 401:
            steps.append(_step("Hub API routed", False,
                f"HTTP 401 — gateway rejected the connector's API key. "
                "Re-run `make fa-setup` to refresh the connector credentials."))
        elif code3 > 0:
            steps.append(_step("Hub API routed", False,
                f"HTTP {code3} in {ms3:.0f}ms — {(text3 or '').strip()[:80]!r}"))
        else:
            steps.append(_step("Hub API routed", False,
                f"Request failed: {text3 or 'network error'}"))

    return {"ok": False, "steps": steps}


async def _check_fa_auth(hub_url: str, api_key: str, dev_mode: bool = False) -> dict:
    """FA API key chain: key configured → hub-api validates (direct in dev, via connector in standard)."""
    steps = []
    if not api_key:
        steps.append(_step("API key configured", False,
            "DEMOFORGE_API_KEY not set. Add it to .env.local or run `make fa-setup`."))
        return {"ok": False, "steps": steps}

    steps.append(_step("API key configured", True, f"Key: {_mask_key(api_key)}"))

    local_url = None
    target_url = hub_url
    if dev_mode:
        local_url, _ = await _find_local_hub_api()
        if local_url:
            target_url = local_url
            steps.append(_step("Target resolved", True,
                f"Using local hub-api at {local_url} (bypasses connector routing)"))
        else:
            steps.append(_step("Target resolved", False,
                f"Local hub-api not found — falling back to connector at {hub_url}"))

    reach_label = "Local hub-api reachable" if (dev_mode and local_url) else "Hub connector reachable"

    async with httpx.AsyncClient() as client:
        code, data, text, ms = await _get(client, target_url + "/api/hub/fa/me",
                                           {"X-Api-Key": api_key, "X-Fa-Api-Key": api_key})
        if code == -1:
            steps.append(_step(reach_label, False, f"Connection refused at {target_url}"))
            return {"ok": False, "steps": steps}
        if code == -2:
            steps.append(_step(reach_label, False, "Timed out"))
            return {"ok": False, "steps": steps}

        if code == 200 and data:
            steps.append(_step(reach_label, True, f"Responded in {ms:.0f}ms"))
            active = data.get("is_active", True)
            steps.append(_step("FA identity validated", active,
                f"fa_id={data.get('fa_id')!r}, name={data.get('fa_name')!r}, "
                f"active={active}, permissions={list(data.get('permissions', {}).keys())}",
                warn=not active))
            return {
                "ok": active,
                "fa_id": data.get("fa_id"),
                "fa_name": data.get("fa_name"),
                "is_active": active,
                "steps": steps,
            }

        if code == 401 and dev_mode and local_url:
            # FA not yet registered in local hub-api — auto-register
            steps.append(_step(reach_label, True, f"Responded in {ms:.0f}ms (FA not registered yet)"))
            from ..fa_identity import get_fa_id as _get_fa_id
            fa_id = os.getenv("DEMOFORGE_FA_ID", "") or _get_fa_id() or ""
            fa_name = os.getenv("DEMOFORGE_FA_NAME", fa_id)
            if not fa_id:
                steps.append(_step("FA auto-register", False,
                    "DEMOFORGE_FA_ID not set — cannot auto-register. Set it in .env.local."))
                return {"ok": False, "steps": steps}
            try:
                t0 = time.monotonic()
                reg_r = await client.post(
                    target_url + "/api/hub/fa/register",
                    json={"fa_id": fa_id, "fa_name": fa_name, "api_key": api_key},
                    timeout=5.0,
                )
                reg_ms = (time.monotonic() - t0) * 1000
                if reg_r.status_code == 200:
                    steps.append(_step("FA auto-register", True,
                        f"Registered fa_id={fa_id!r} in local hub-api in {reg_ms:.0f}ms"))
                    code2, data2, _, ms2 = await _get(client, target_url + "/api/hub/fa/me",
                                                      {"X-Api-Key": api_key})
                    if code2 == 200 and data2:
                        active = data2.get("is_active", True)
                        steps.append(_step("FA identity validated", active,
                            f"fa_id={data2.get('fa_id')!r}, name={data2.get('fa_name')!r}, "
                            f"active={active}",
                            warn=not active))
                        return {
                            "ok": active,
                            "fa_id": data2.get("fa_id"),
                            "fa_name": data2.get("fa_name"),
                            "is_active": active,
                            "steps": steps,
                        }
                else:
                    steps.append(_step("FA auto-register", False,
                        f"Registration failed: HTTP {reg_r.status_code}"))
            except Exception as e:
                steps.append(_step("FA auto-register", False, str(e)[:80]))
            return {"ok": False, "steps": steps}

        if code == 200 and data is None:
            steps.append(_step(reach_label, True, f"Responded in {ms:.0f}ms (non-JSON)"))
            steps.append(_step("FA identity validated", False,
                f"Response was not JSON: {(text or '').strip()[:80]!r}. "
                "Hub-api /api/hub/fa/* route not configured in connector."))
        elif code == 401:
            steps.append(_step(reach_label, True, f"Responded in {ms:.0f}ms"))
            steps.append(_step("FA identity validated", False,
                "HTTP 401 — API key not recognised. FA may not be registered or key is wrong. "
                "Run `make fa-setup` to re-register."))
        elif code == 403:
            steps.append(_step(reach_label, True, f"Responded in {ms:.0f}ms"))
            steps.append(_step("FA identity validated", False,
                "HTTP 403 — FA account is deactivated. Contact your DemoForge admin."))
        else:
            steps.append(_step(reach_label, code > 0,
                f"HTTP {code} in {ms:.0f}ms — {(text or '').strip()[:80]!r}"))
            if code > 0:
                steps.append(_step("FA identity validated", False,
                    f"Unexpected HTTP {code} from hub-api."))

    return {"ok": False, "steps": steps}


async def _check_admin_key(hub_url: str, admin_key: str, dev_mode: bool = False) -> dict:
    """Admin key: in dev mode hit local hub-api directly; otherwise go through connector."""
    steps = []
    if not admin_key:
        steps.append(_step("Admin key configured", False,
            "DEMOFORGE_HUB_API_ADMIN_KEY not set. Run `make dev-init` then restart the backend."))
        return {"ok": False, "skipped": True, "steps": steps}

    steps.append(_step("Admin key configured", True, f"Key: {_mask_key(admin_key)}"))

    target_url = hub_url
    if dev_mode:
        local_url, _ = await _find_local_hub_api()
        if local_url:
            target_url = local_url
            steps.append(_step("Target resolved", True,
                f"Using local hub-api at {local_url} (bypasses connector routing)"))
        else:
            steps.append(_step("Target resolved", False,
                f"Local hub-api not found — falling back to connector at {hub_url}"))

    async with httpx.AsyncClient() as client:
        code, data, text, ms = await _get(client, target_url + "/api/hub/admin/stats",
                                           {"X-Hub-Admin-Key": admin_key})
        if code == -1:
            steps.append(_step("Admin endpoint reachable", False,
                f"Connection refused at {target_url}. Is hub-api running?"))
            return {"ok": False, "steps": steps}
        if code == -2:
            steps.append(_step("Admin endpoint reachable", False, "Timed out"))
            return {"ok": False, "steps": steps}
        if code == 200 and data and "total_fas" in data:
            steps.append(_step("Admin endpoint reachable", True, f"Responded in {ms:.0f}ms"))
            steps.append(_step("Admin key accepted", True,
                f"total_fas={data['total_fas']}, active_fas={data.get('active_fas','?')}, "
                f"events_7d={data.get('events_last_7_days','?')}, "
                f"events_30d={data.get('events_last_30_days','?')}"))
            return {"ok": True, "total_fas": data["total_fas"], "steps": steps}
        if code == 200 and data is None:
            preview = (text or "").strip()[:80]
            steps.append(_step("Admin endpoint reachable", True, f"Responded in {ms:.0f}ms (non-JSON)"))
            steps.append(_step("Admin key accepted", False,
                f"Response not JSON: {preview!r}. Hub-api route not working."))
        elif code == 403:
            steps.append(_step("Admin endpoint reachable", True, f"Responded in {ms:.0f}ms"))
            steps.append(_step("Admin key accepted", False,
                f"HTTP 403 — key rejected. Start hub-api with "
                f"HUB_API_ADMIN_API_KEY={_mask_key(admin_key)}"))
        elif code == 401:
            steps.append(_step("Admin endpoint reachable", True, f"Responded in {ms:.0f}ms"))
            steps.append(_step("Admin key accepted", False, "HTTP 401 — missing key header"))
        else:
            preview = (text or "").strip()[:80]
            steps.append(_step("Admin endpoint reachable", code > 0,
                f"HTTP {code} — {preview!r}"))

    return {"ok": False, "steps": steps}


async def _find_local_hub_api() -> tuple[str | None, float]:
    """Return (base_url, latency_ms) for local hub-api, trying localhost then host.docker.internal."""
    candidates = ["http://localhost:8000", "http://host.docker.internal:8000"]
    async with httpx.AsyncClient() as client:
        for url in candidates:
            code, data, _, ms = await _get(client, url + "/api/hub/health", timeout=3.0)
            if code == 200 and data and data.get("service") == "demoforge-hub-api":
                return url, ms
    return None, 0.0


async def _check_template_sync() -> dict:
    """FA mode: verify hub-api templates endpoint is reachable and returns templates."""
    from ..engine.template_sync import HUB_URL, FA_API_KEY, TEMPLATES_URL
    steps = []

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{TEMPLATES_URL}/",
                headers={"X-Api-Key": FA_API_KEY},
            )
            if resp.status_code == 503:
                steps.append(_step("Template sync", False,
                    "Hub template sync not configured — contact your admin."))
                return {"ok": False, "steps": steps}
            if resp.status_code == 200:
                count = len(resp.json().get("templates", []))
                steps.append(_step("Template sync", True,
                    f"{count} template(s) available from hub ({HUB_URL})"))
                return {"ok": True, "template_count": count, "steps": steps}
            if resp.status_code in (401, 403):
                # Auth handled by FA auth check — treat as ok here
                steps.append(_step("Template sync", True, "Endpoint reachable (auth via FA key)"))
                return {"ok": True, "steps": steps}
            steps.append(_step("Template sync", False, f"Unexpected status {resp.status_code}"))
            return {"ok": False, "steps": steps}
    except Exception as e:
        steps.append(_step("Template sync", False, f"Unreachable: {str(e)[:80]}"))
        return {"ok": False, "steps": steps}


def _parse_semver(v: str) -> tuple:
    """Parse vX.Y.Z (or vX.Y.Z-N-gHASH from git describe) into (X, Y, Z, N) for ordering.
    A version with commits ahead of a tag (e.g. v0.0.4-2-g943f8cb) is newer than the tag itself."""
    import re
    m = re.match(r'^v?(\d+)\.(\d+)\.(\d+)(?:-(\d+)-g[0-9a-f]+)?', v)
    if m:
        major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
        commits_ahead = int(m.group(4)) if m.group(4) else 0
        return (major, minor, patch, commits_ahead)
    return (0, 0, 0, 0)


def _read_local_version() -> str:
    """Get local DemoForge version via git describe."""
    try:
        import subprocess
        from pathlib import Path
        root = Path(__file__).parent.parent.parent.parent
        r = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True, text=True, timeout=3, cwd=str(root),
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.getenv("DEMOFORGE_VERSION", "dev")


async def _check_version(hub_url: str, api_key: str, dev_mode: bool = False) -> dict:
    """Compare local DemoForge version against hub latest. Always ok/optional — informational only."""
    steps = []
    local_ver = _read_local_version()
    steps.append(_step("Local version", True, f"DemoForge {local_ver}"))

    target = hub_url
    if dev_mode:
        local_hub, _ = await _find_local_hub_api()
        if local_hub:
            target = local_hub

    headers = {}
    if api_key:
        headers["X-Api-Key"] = api_key

    async with httpx.AsyncClient() as client:
        code, data, text, ms = await _get(client, target + "/api/hub/version/latest", headers, timeout=5.0)

    if code == 200 and data and "demoforge" in data:
        hub_ver = data["demoforge"].get("version", "")
        if hub_ver:
            local_parsed = _parse_semver(local_ver)
            hub_parsed = _parse_semver(hub_ver)
            up_to_date = local_parsed >= hub_parsed
            logger.info("Version check: local=%s hub_latest=%s up_to_date=%s",
                        local_ver, hub_ver, up_to_date)
            if up_to_date:
                steps.append(_step("Up to date", True,
                    f"Running {local_ver} (hub latest: {hub_ver})"))
            else:
                steps.append(_step("Update available", False,
                    f"Running {local_ver} → {hub_ver} available — run `make fa-update` to upgrade",
                    warn=True))
            return {
                "ok": True,
                "local_version": local_ver,
                "hub_version": hub_ver,
                "up_to_date": up_to_date,
                "steps": steps,
            }

    # Hub endpoint not available yet or error — skip gracefully
    steps.append(_step("Hub version check", True,
        "Hub version endpoint not available yet" if code == 404 else f"Skipped (HTTP {code})",
        warn=False))
    return {"ok": True, "skipped": True, "local_version": local_ver, "steps": steps}


async def _check_components() -> dict:
    """FA mode: check component availability via readiness system."""
    steps = []
    try:
        from ..engine.readiness import readiness
        if not readiness._components:
            readiness.load()
        total = len(readiness._components)
        if total == 0:
            steps.append(_step("Component readiness loaded", False,
                "No component readiness config found. Check component-readiness.yaml is mounted."))
            return {"ok": False, "steps": steps}

        fa_ready = [c for c in readiness._components.values() if c.get("fa_ready")]
        blocked = [c for c in readiness._components.values() if not c.get("fa_ready")]

        steps.append(_step("Component readiness loaded", True,
            f"{len(fa_ready)}/{total} components FA-ready, {len(blocked)} blocked/pending"))
        if len(fa_ready) == 0:
            steps.append(_step("FA-ready components available", False,
                "No components are currently available to Field Architects. Contact your hub admin."))
            return {"ok": False, "steps": steps}

        steps.append(_step("FA-ready components available", True,
            f"{len(fa_ready)} component(s) available for demo creation"))
        from ..telemetry import emit_event
        asyncio.create_task(emit_event("components_checked", {
            "fa_ready_count": len(fa_ready),
            "total_count": total,
            "blocked_count": len(blocked),
        }))

        # Gather per-component version info from readiness + registry
        component_versions = []
        try:
            from ..registry.loader import get_registry
            reg = get_registry()
            for cid, cdata in readiness._components.items():
                manifest = reg.get(cid) if reg else None
                local_tag = manifest.image if manifest else None
                hub_tag = cdata.get("image_tag")
                component_versions.append({
                    "id": cid,
                    "name": cdata.get("name", cid),
                    "fa_ready": cdata.get("fa_ready", False),
                    "local_tag": local_tag,
                    "hub_tag": hub_tag,
                })
        except Exception:
            pass

        return {
            "ok": True,
            "fa_ready_count": len(fa_ready),
            "total_count": total,
            "component_versions": component_versions,
            "steps": steps,
        }
    except Exception as e:
        steps.append(_step("Component readiness loaded", False, str(e)[:120]))
        return {"ok": False, "steps": steps}


async def _check_local_hub_api() -> dict:
    """Dev: direct hub-api (localhost or host.docker.internal) — health + DB + admin."""
    steps = []
    local_url, ms = await _find_local_hub_api()

    if not local_url:
        steps.append(_step("Hub API process running", False,
            "Connection refused on localhost:8000 and host.docker.internal:8000. "
            "Start it: cd hub-api && HUB_API_DATABASE_PATH=./data/hub-api/hub.db "
            "uvicorn hub_api.main:app --port 8000 --reload"))
        return {"ok": False, "skipped": True, "steps": steps}

    steps.append(_step("Hub API process running", True,
        f"{local_url} responded in {ms:.0f}ms"))

    admin_key = os.getenv("DEMOFORGE_HUB_API_ADMIN_KEY", "")
    if not admin_key:
        steps.append(_step("DB + admin access", False,
            "DEMOFORGE_HUB_API_ADMIN_KEY not set — run `make dev-init` then restart backend."))
        return {"ok": False, "steps": steps}

    async with httpx.AsyncClient() as client:
        code3, data3, text3, ms3 = await _get(
            client, local_url + "/api/hub/admin/stats",
            {"X-Api-Key": admin_key}, timeout=3.0
        )
        if code3 == 200 and data3 and "total_fas" in data3:
            steps.append(_step("DB + admin access", True,
                f"total_fas={data3['total_fas']}, active={data3.get('active_fas','?')}, "
                f"total_events={data3.get('total_events','?')} in {ms3:.0f}ms"))
            return {"ok": True, "note": f"Running at {local_url}", "steps": steps}
        elif code3 == 403:
            steps.append(_step("DB + admin access", False,
                f"HTTP 403 — admin key rejected. Ensure hub-api started with "
                f"HUB_API_ADMIN_API_KEY={_mask_key(admin_key)}"))
        else:
            preview = (text3 or "").strip()[:80]
            steps.append(_step("DB + admin access", False,
                f"HTTP {code3} — {preview!r}"))

    return {"ok": False, "steps": steps}


@router.get("/api/connectivity/check")
async def check_connectivity():
    mode = os.getenv("DEMOFORGE_MODE", "standard")
    hub_url = os.getenv("DEMOFORGE_HUB_CONNECTOR_URL", "http://localhost:8080")
    api_key = os.getenv("DEMOFORGE_API_KEY", "")
    admin_key = os.getenv("DEMOFORGE_HUB_API_ADMIN_KEY", "")

    from ..fa_identity import get_fa_id
    fa_id = get_fa_id()

    if mode == "dev":
        # dev-start sets DEMOFORGE_HUB_LOCAL=1 (local hub-api on :8000)
        # dev-start-gcp does not set it (routes through GCP connector at :8080)
        hub_local = os.getenv("DEMOFORGE_HUB_LOCAL", "") == "1"

        if hub_local:
            # dev-start (local): local hub-api + admin key required; connector optional
            results = await asyncio.gather(
                _check_hub_connector(hub_url),
                _check_fa_auth(hub_url, api_key, dev_mode=True),
                _check_admin_key(hub_url, admin_key, dev_mode=True),
                _check_local_hub_api(),
                _check_version(hub_url, api_key, dev_mode=True),
                return_exceptions=True,
            )
            connector, fa_auth, admin, local, version_result = [
                r if not isinstance(r, Exception) else {"ok": False, "error": str(r), "steps": []}
                for r in results
            ]
            # Connector is N/A when local hub is healthy
            if local.get("ok"):
                connector = {
                    "ok": False,
                    "skipped": True,
                    "steps": [_step("Connector check skipped", True,
                        "Local hub-api is healthy — connector not needed in dev mode.")],
                }
            # If local hub-api is not running, admin key can't be validated — skip it
            # to avoid a confusing 403 from the GCP hub rejecting the local dev key
            if not local.get("ok"):
                admin = {
                    "ok": True,
                    "skipped": True,
                    "steps": [_step("Admin key check skipped", True,
                        "Local hub-api is not running — start it with `make dev-hub-api` to validate the admin key.")],
                }
            checks = {
                "local_hub_api": {
                    "label": "Local Hub API",
                    "description": "hub-api directly on localhost:8000 — preferred in dev mode",
                    **local,
                },
                "admin_key": {
                    "label": "Admin Key",
                    "description": "Admin access to hub-api (required for FA Management page)",
                    **admin,
                },
                "hub_connector": {
                    "label": "Hub Connector",
                    "description": f"Remote connector at {hub_url} (optional — alternative to local hub-api)",
                    "optional": True,
                    **connector,
                },
                "fa_auth": {
                    "label": "FA Authentication",
                    "description": "FA API key validated via hub-api (optional in dev — admin key takes precedence)",
                    "optional": True,
                    **fa_auth,
                },
                "version": {
                    "label": "DemoForge Version",
                    "description": "Current build vs latest release on hub",
                    "optional": True,
                    **version_result,
                },
            }
        else:
            # dev-start-gcp: developer connecting to real GCP hub via connector.
            # The developer authenticates as admin (admin key), not as a registered FA.
            # fa_auth is optional — a 401 here just means no FA registration, which is
            # expected for developers who manage the hub rather than use it as an FA.
            results = await asyncio.gather(
                _check_hub_connector(hub_url),
                _check_admin_key(hub_url, admin_key, dev_mode=True),
                _check_fa_auth(hub_url, api_key, dev_mode=False),
                _check_version(hub_url, api_key, dev_mode=True),
                return_exceptions=True,
            )
            connector, admin, fa_auth, version_result = [
                r if not isinstance(r, Exception) else {"ok": False, "error": str(r), "steps": []}
                for r in results
            ]
            checks = {
                "hub_connector": {
                    "label": "Hub Connector",
                    "description": f"Remote connector at {hub_url}",
                    **connector,
                },
                "admin_key": {
                    "label": "Admin Key",
                    "description": "Admin access to hub-api (used by developers in dev-gcp mode)",
                    **admin,
                },
                "fa_auth": {
                    "label": "FA Authentication",
                    "description": "FA API key — optional in dev-gcp (developers use admin key instead)",
                    "optional": True,
                    **fa_auth,
                },
                "version": {
                    "label": "DemoForge Version",
                    "description": "Current build vs latest release on hub",
                    "optional": True,
                    **version_result,
                },
            }
    else:
        results = await asyncio.gather(
            _check_hub_connector(hub_url),
            _check_fa_auth(hub_url, api_key),
            _check_template_sync(),
            _check_components(),
            _check_version(hub_url, api_key),
            return_exceptions=True,
        )
        connector, fa_auth, template_sync, components, version_result = [
            r if not isinstance(r, Exception) else {"ok": False, "error": str(r), "steps": []}
            for r in results
        ]
        checks = {
            "hub_connector": {
                "label": "Hub Connector",
                "description": f"Hub connector at {hub_url}",
                **connector,
            },
            "fa_auth": {
                "label": "FA Authentication",
                "description": "FA API key validated against hub-api",
                **fa_auth,
            },
            "template_sync": {
                "label": "Template Sync",
                "description": "Templates pulled from hub",
                **template_sync,
            },
            "components": {
                "label": "Component Availability",
                "description": "FA-ready components available for demo creation",
                **components,
            },
            "version": {
                "label": "DemoForge Version",
                "description": "Current build vs latest release on hub",
                "optional": True,
                **version_result,
            },
        }

    required = [v for v in checks.values() if not v.get("optional")]
    overall_ok = all(v.get("ok") or v.get("skipped") for v in required)

    hub_local = os.getenv("DEMOFORGE_HUB_LOCAL", "") == "1"
    return {
        "overall": "ok" if overall_ok else "degraded",
        "mode": mode,
        # dev sub-mode: True = dev-start (local hub-api), False = dev-start-gcp (GCP connector)
        "hub_local": hub_local if mode == "dev" else None,
        "hub_url": hub_url,
        "fa_id": fa_id,
        "fa_id_configured": bool(fa_id and fa_id != "dev"),
        "api_key_configured": bool(api_key),
        "admin_key_configured": bool(admin_key) if mode == "dev" else None,
        "checks": checks,
    }


@router.get("/api/connectivity/me")
async def get_me():
    """Return current FA's identity and permissions from hub-api."""
    api_key = os.getenv("DEMOFORGE_API_KEY", "")
    hub_url = os.getenv("DEMOFORGE_HUB_CONNECTOR_URL", "http://host.docker.internal:8080")

    if not api_key:
        return {"ok": False, "permissions": {}}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(
                hub_url + "/api/hub/fa/me",
                headers={"X-Api-Key": api_key, "X-Fa-Api-Key": api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "fa_id": data.get("fa_id"),
                    "fa_name": data.get("fa_name"),
                    "is_active": data.get("is_active", True),
                    "permissions": data.get("permissions", {}),
                }
        except Exception:
            pass
    return {"ok": False, "permissions": {}}
