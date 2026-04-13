"""
Template sync — pulls templates from hub-api (authenticated with FA API key).

No on/off flag — sync attempts whenever called. If hub is unreachable or
FA key is missing, sync returns an error status; no separate enable flag needed.

Environment variables:
  DEMOFORGE_HUB_URL=http://host.docker.internal:8080
  DEMOFORGE_API_KEY=<fa-api-key>
  DEMOFORGE_SYNCED_TEMPLATES_DIR=./synced-templates
"""

import os
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger("demoforge.template_sync")

HUB_URL = os.environ.get("DEMOFORGE_HUB_URL", "http://host.docker.internal:8080").rstrip("/")
FA_API_KEY = os.environ.get("DEMOFORGE_API_KEY", "")
SYNCED_DIR = os.environ.get("DEMOFORGE_SYNCED_TEMPLATES_DIR", "./synced-templates")
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


def publish_template(template_id: str) -> dict:
    """Upload a user template to the hub for team sharing. Stub — not yet implemented via proxy."""
    return {"status": "error", "message": "Template publishing via hub-api proxy not yet implemented."}


def publish_single_builtin(template_id: str) -> dict:
    return {"status": "skipped", "message": "Direct publish only available in dev mode with hub access."}


def publish_builtin_templates() -> dict:
    """Run hub-seed.sh to rsync demo-templates/ to GCS. Dev mode only."""
    project_root = Path(__file__).parent.parent.parent.parent  # backend/app/engine -> project root
    script = project_root / "scripts" / "hub-seed.sh"
    templates_dir = project_root / "demo-templates"

    if not script.exists():
        return {"status": "error", "message": f"hub-seed.sh not found at {script}"}

    # Count actual template files (exclude non-template YAMLs like CHANGELOG, ORDER)
    _NON_TEMPLATES = {"CHANGELOG.yaml", "ORDER.yaml"}
    uploaded = sum(
        1 for f in templates_dir.glob("*.yaml") if f.name not in _NON_TEMPLATES
    )

    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            err_msg = (result.stderr or result.stdout or "hub-seed.sh failed").strip()
            logger.error(f"hub-seed.sh failed: {err_msg}")
            return {"status": "error", "message": err_msg}
        logger.info(f"hub-seed.sh succeeded: {result.stdout.strip()}")
        return {"status": "ok", "uploaded": uploaded, "errors": 0}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Push timed out after 120s"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
