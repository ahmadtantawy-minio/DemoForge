"""
Template sync — pulls templates from hub-api (authenticated with FA API key).

The GCP gateway forwards /api/hub/templates* without org gateway auth; hub-api
validates the FA key (get_current_fa). No separate DEMOFORGE_GATEWAY_API_KEY needed for sync.

Environment variables:
  DEMOFORGE_HUB_URL=https://demoforge-gateway-64xwtiev6q-ww.a.run.app
  DEMOFORGE_API_KEY=<fa-api-key>
  DEMOFORGE_SYNCED_TEMPLATES_DIR=./synced-templates
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger("demoforge.template_sync")

HUB_URL = os.environ.get("DEMOFORGE_HUB_URL", "").rstrip("/")
FA_API_KEY = os.environ.get("DEMOFORGE_API_KEY", "")
SYNCED_DIR = os.environ.get("DEMOFORGE_SYNCED_TEMPLATES_DIR", "./synced-templates")
HUB_LOCAL = os.environ.get("DEMOFORGE_HUB_LOCAL", "") == "1"
SYNC_MANIFEST_PATH = os.path.join(SYNCED_DIR, ".sync-manifest.json")

TEMPLATES_URL = f"{HUB_URL}/api/hub/templates"


def _load_manifest() -> dict:
    if os.path.exists(SYNC_MANIFEST_PATH):
        with open(SYNC_MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def _save_manifest(manifest: dict):
    with open(SYNC_MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def sync_templates() -> dict:
    """Pull templates from hub-api. Returns summary of changes."""
    if not FA_API_KEY:
        return {"status": "error", "message": "DEMOFORGE_API_KEY not set."}

    os.makedirs(SYNCED_DIR, exist_ok=True)
    manifest = _load_manifest()
    stats = {"downloaded": 0, "unchanged": 0, "deleted": 0, "errors": 0}

    # Hub-api validates the FA key (get_current_fa). GCP gateway exempts this path from org-key auth.
    headers = {"X-Api-Key": FA_API_KEY}

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{TEMPLATES_URL}/", headers=headers)
            if resp.status_code == 503:
                return {"status": "error", "message": "Hub template sync not configured — contact your admin."}
            resp.raise_for_status()
            remote_templates = resp.json().get("templates", [])
    except Exception as e:
        return {"status": "error", "message": f"Failed to list templates: {e}"}

    remote_names: set[str] = set()

    for tmpl in remote_templates:
        fname = tmpl["name"]
        remote_etag = tmpl.get("etag", "")
        remote_names.add(fname)

        if manifest.get(fname, {}).get("etag") == remote_etag and remote_etag:
            stats["unchanged"] += 1
            continue

        try:
            with httpx.Client(timeout=30) as client:
                file_resp = client.get(f"{TEMPLATES_URL}/{fname}", headers=headers)
                file_resp.raise_for_status()
                content = file_resp.content

            local_path = os.path.join(SYNCED_DIR, fname)
            if not os.path.realpath(local_path).startswith(os.path.realpath(SYNCED_DIR)):
                continue
            with open(local_path, "wb") as f:
                f.write(content)

            manifest[fname] = {
                "etag": remote_etag,
                "synced_at": datetime.utcnow().isoformat() + "Z",
                "size": len(content),
            }
            stats["downloaded"] += 1
            logger.info(f"Synced template: {fname}")
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Failed to download {fname}: {e}")

    # Remove templates no longer on remote
    for fname in list(manifest.keys()):
        if fname not in remote_names:
            local_path = os.path.join(SYNCED_DIR, fname)
            if os.path.exists(local_path):
                os.remove(local_path)
            del manifest[fname]
            stats["deleted"] += 1

    _save_manifest(manifest)
    return {"status": "ok", "method": "hub-api", **stats}


def get_sync_status() -> dict:
    manifest = _load_manifest() if os.path.exists(SYNC_MANIFEST_PATH) else {}
    synced_count = len(manifest)
    return {
        "hub_url": HUB_URL,
        "enabled": synced_count > 0,  # True when hub templates are present locally
        "synced_count": synced_count,
        "last_sync": max(
            (v.get("synced_at", "") for v in manifest.values() if isinstance(v, dict)),
            default=None,
        ),
    }


_NON_TEMPLATES = {"CHANGELOG.yaml", "ORDER.yaml"}

ADMIN_KEY = os.environ.get("DEMOFORGE_HUB_API_ADMIN_KEY", "")


def _hub_upload(filename: str, content: bytes) -> dict:
    """
    PUT a template YAML to the hub. In GCP mode this goes via the Caddy gateway
    (requires X-Api-Key); in local hub mode it hits hub-api directly (no gateway, no key needed).
    """
    if not HUB_URL:
        return {"status": "error", "message": "DEMOFORGE_HUB_URL not set — cannot reach hub gateway."}
    if not ADMIN_KEY:
        return {"status": "error", "message": "DEMOFORGE_HUB_API_ADMIN_KEY not set — cannot authenticate to hub-api."}

    # Gateway exempts /api/hub/templates* from org-key auth; hub-api checks X-Hub-Admin-Key for admin PUT.
    headers: dict[str, str] = {
        "X-Hub-Admin-Key": ADMIN_KEY,
        "Content-Type": "application/x-yaml",
    }

    url = f"{HUB_URL}/api/hub/templates/{filename}"
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.put(url, content=content, headers=headers)
        if resp.status_code == 200:
            return {"status": "ok", "remote_key": filename}
        return {"status": "error", "message": f"Gateway returned HTTP {resp.status_code}: {resp.text[:200]}"}
    except httpx.TimeoutException:
        return {"status": "error", "message": "Upload timed out after 30s"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def publish_template(template_id: str) -> dict:
    """Upload a user template YAML via the hub gateway to GCS. Dev mode only.

    Injects fa_ready: true into _template before uploading so the template
    appears in tier/category tabs for all FAs after sync, not just My Templates.
    Also updates the local file so the publisher sees it in categories immediately.

    The gateway is the write path — no GCS credentials needed on the dev machine.
    Fails loudly if the gateway is unreachable or auth fails.
    """
    user_dir = os.environ.get("DEMOFORGE_USER_TEMPLATES_DIR", "./user-templates")
    src = Path(user_dir) / f"{template_id}.yaml"
    if not src.exists():
        return {"status": "error", "message": f"Template file not found: {src}"}

    raw_bytes = src.read_bytes()
    try:
        data = yaml.safe_load(raw_bytes) or {}
        if "_template" not in data:
            data["_template"] = {}
        data["_template"]["fa_ready"] = True
        upload_bytes = yaml.dump(data, allow_unicode=True, sort_keys=False).encode()
    except Exception as e:
        logger.warning("Could not parse YAML for %s, uploading raw: %s", template_id, e)
        upload_bytes = raw_bytes

    result = _hub_upload(f"{template_id}.yaml", upload_bytes)
    if result["status"] == "ok":
        result["template_id"] = template_id
        logger.info("Published user template %s via gateway", template_id)
        # Update local copy so publisher sees it in categories immediately
        try:
            src.write_bytes(upload_bytes)
        except Exception as e:
            logger.warning("Could not update local template file %s: %s", src, e)
    return result


def publish_single_builtin(template_id: str) -> dict:
    """Push a single builtin template via the hub gateway to GCS. Called after promote. Dev mode only.

    Fails loudly — never silently skips.
    """
    templates_dir = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
    src = Path(templates_dir) / f"{template_id}.yaml"
    if not src.exists():
        return {"status": "error", "message": f"Template file not found: {src}"}
    result = _hub_upload(f"{template_id}.yaml", src.read_bytes())
    if result["status"] == "ok":
        logger.info("Pushed builtin template %s via gateway", template_id)
    return result


def publish_builtin_templates() -> dict:
    """Upload all builtin templates via the hub gateway to GCS. Dev mode only."""
    templates_dir = Path(os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates"))
    srcs = sorted(f for f in templates_dir.glob("*.yaml") if f.name not in _NON_TEMPLATES)
    if not srcs:
        return {"status": "error", "message": f"No template files found in {templates_dir}"}

    uploaded = errors = 0
    for src in srcs:
        result = _hub_upload(src.name, src.read_bytes())
        if result["status"] == "ok":
            uploaded += 1
            logger.info("Uploaded %s via gateway", src.name)
        else:
            logger.error("Failed to upload %s: %s", src.name, result.get("message"))
            errors += 1

    if errors:
        return {"status": "error", "message": f"{errors} upload(s) failed", "uploaded": uploaded, "errors": errors}
    return {"status": "ok", "uploaded": uploaded, "errors": 0}
