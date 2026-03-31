"""
Template sync — pulls templates from a remote MinIO bucket.

Supports two sync modes:
  1. HTTP (via hub connector) — no S3 signing, works for FAs behind gateway
  2. S3 SDK (direct) — used as fallback, or for publish (dev mode only)

Environment variables:
  DEMOFORGE_SYNC_ENABLED=true|false
  DEMOFORGE_SYNC_ENDPOINT=http://34.18.90.197:9000   (S3 SDK endpoint)
  DEMOFORGE_SYNC_BUCKET=demoforge-templates
  DEMOFORGE_SYNC_PREFIX=templates/
  DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
  DEMOFORGE_SYNC_SECRET_KEY=<from .env.hub>
  DEMOFORGE_SYNC_REGION=us-east-1
  DEMOFORGE_SYNCED_TEMPLATES_DIR=./synced-templates
  DEMOFORGE_REGISTRY_HOST=host.docker.internal:5000  (used to derive connector URL)
"""

import os
import json
import logging
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger("demoforge.template_sync")

SYNC_ENABLED = os.environ.get("DEMOFORGE_SYNC_ENABLED", "false").lower() == "true"
SYNC_ENDPOINT = os.environ.get("DEMOFORGE_SYNC_ENDPOINT", "http://34.18.90.197:9000")
SYNC_BUCKET = os.environ.get("DEMOFORGE_SYNC_BUCKET", "demoforge-templates")
SYNC_PREFIX = os.environ.get("DEMOFORGE_SYNC_PREFIX", "templates/")
SYNC_ACCESS_KEY = os.environ.get("DEMOFORGE_SYNC_ACCESS_KEY", "")
SYNC_SECRET_KEY = os.environ.get("DEMOFORGE_SYNC_SECRET_KEY", "")
SYNC_REGION = os.environ.get("DEMOFORGE_SYNC_REGION", "us-east-1")
SYNCED_DIR = os.environ.get("DEMOFORGE_SYNCED_TEMPLATES_DIR", "./synced-templates")

# Hub connector URL for HTTP-based sync (no S3 signing)
_REGISTRY_HOST = os.environ.get("DEMOFORGE_REGISTRY_HOST", "")
HUB_TEMPLATES_URL = ""
if _REGISTRY_HOST:
    _hub_host = _REGISTRY_HOST.split(":")[0]
    HUB_TEMPLATES_URL = f"http://{_hub_host}:8080/templates"

SYNC_MANIFEST_PATH = os.path.join(SYNCED_DIR, ".sync-manifest.json")


def _get_s3_client():
    """Create an S3 client for the remote MinIO endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=SYNC_ENDPOINT,
        aws_access_key_id=SYNC_ACCESS_KEY,
        aws_secret_access_key=SYNC_SECRET_KEY,
        region_name=SYNC_REGION,
        config=BotoConfig(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


def _load_manifest() -> dict:
    if os.path.exists(SYNC_MANIFEST_PATH):
        with open(SYNC_MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def _save_manifest(manifest: dict):
    with open(SYNC_MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def _sync_via_http() -> dict | None:
    """Sync templates via HTTP (hub connector). Returns stats dict or None if unavailable."""
    if not HUB_TEMPLATES_URL:
        return None

    try:
        # List templates via S3 ListObjectsV2 through the connector
        # The connector proxies /templates/* → gateway → MinIO bucket
        list_url = f"{HUB_TEMPLATES_URL}/?list-type=2&prefix={SYNC_PREFIX}"
        req = urllib.request.Request(list_url)
        resp = urllib.request.urlopen(req, timeout=10)
        xml_data = resp.read()
        resp.close()
    except Exception as e:
        logger.debug(f"HTTP sync listing failed: {e}")
        return None

    try:
        root = ET.fromstring(xml_data)
        ns = root.tag.split("}")[0] + "}" if "}" in root.tag else ""

        manifest = _load_manifest()
        stats = {"downloaded": 0, "unchanged": 0, "deleted": 0, "errors": 0}
        remote_keys: set[str] = set()

        for content in root.findall(f"{ns}Contents"):
            key_el = content.find(f"{ns}Key")
            etag_el = content.find(f"{ns}ETag")
            if key_el is None:
                continue
            key = key_el.text or ""
            if not key.endswith(".yaml"):
                continue

            fname = key.removeprefix(SYNC_PREFIX).lstrip("/")
            if "/" in fname or not fname:
                continue

            remote_keys.add(fname)
            remote_etag = (etag_el.text or "").strip('"') if etag_el is not None else ""

            if manifest.get(fname, {}).get("etag") == remote_etag and remote_etag:
                stats["unchanged"] += 1
                continue

            # Download the template file
            try:
                file_url = f"{HUB_TEMPLATES_URL}/{SYNC_PREFIX}{fname}"
                file_req = urllib.request.Request(file_url)
                file_resp = urllib.request.urlopen(file_req, timeout=10)
                content_bytes = file_resp.read()
                file_resp.close()

                local_path = os.path.join(SYNCED_DIR, fname)
                if not os.path.realpath(local_path).startswith(os.path.realpath(SYNCED_DIR)):
                    continue
                with open(local_path, "wb") as f:
                    f.write(content_bytes)

                manifest[fname] = {
                    "etag": remote_etag,
                    "synced_at": datetime.utcnow().isoformat() + "Z",
                    "size": len(content_bytes),
                }
                stats["downloaded"] += 1
                logger.info(f"Synced template (HTTP): {fname}")
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Failed to download {fname} via HTTP: {e}")

        # Remove locally synced templates no longer on remote
        for fname in list(manifest.keys()):
            if fname not in remote_keys:
                local_path = os.path.join(SYNCED_DIR, fname)
                if os.path.exists(local_path):
                    os.remove(local_path)
                del manifest[fname]
                stats["deleted"] += 1

        _save_manifest(manifest)
        return stats

    except ET.ParseError as e:
        logger.debug(f"HTTP sync XML parse failed: {e}")
        return None


def sync_templates() -> dict:
    """
    Pull templates from remote bucket. Returns summary of changes.
    Tries HTTP (via connector) first, falls back to S3 SDK.
    """
    if not SYNC_ENABLED:
        return {"status": "disabled", "message": "Template sync is not enabled."}

    os.makedirs(SYNCED_DIR, exist_ok=True)

    # Try HTTP sync first (works for FAs behind gateway — no S3 signing)
    http_stats = _sync_via_http()
    if http_stats is not None:
        return {"status": "ok", "method": "http", **http_stats}

    # Fall back to S3 SDK (needs direct access or valid S3 credentials)
    if not SYNC_ACCESS_KEY or not SYNC_SECRET_KEY:
        return {"status": "error", "message": "Sync credentials not configured. Run scripts/hub-setup.sh and copy .env.hub to .env.local."}

    manifest = _load_manifest()
    s3 = _get_s3_client()

    stats = {"downloaded": 0, "unchanged": 0, "deleted": 0, "errors": 0}
    remote_keys: set[str] = set()

    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=SYNC_BUCKET, Prefix=SYNC_PREFIX):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".yaml"):
                    continue

                fname = key.removeprefix(SYNC_PREFIX).lstrip("/")
                if "/" in fname:
                    continue
                if not fname:
                    continue

                remote_keys.add(fname)
                remote_etag = obj.get("ETag", "").strip('"')

                if manifest.get(fname, {}).get("etag") == remote_etag:
                    stats["unchanged"] += 1
                    continue

                try:
                    local_path = os.path.join(SYNCED_DIR, fname)
                    if not os.path.realpath(local_path).startswith(os.path.realpath(SYNCED_DIR)):
                        logger.warning(f"Skipping suspicious template path: {fname}")
                        continue
                    s3.download_file(SYNC_BUCKET, key, local_path)
                    manifest[fname] = {
                        "etag": remote_etag,
                        "synced_at": datetime.utcnow().isoformat() + "Z",
                        "size": obj.get("Size", 0),
                    }
                    stats["downloaded"] += 1
                    logger.info(f"Synced template: {fname}")
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Failed to download {fname}: {e}")

        # Remove locally synced templates that no longer exist on remote
        for fname in list(manifest.keys()):
            if fname not in remote_keys:
                local_path = os.path.join(SYNCED_DIR, fname)
                if os.path.exists(local_path):
                    os.remove(local_path)
                del manifest[fname]
                stats["deleted"] += 1
                logger.info(f"Removed template no longer on remote: {fname}")

        _save_manifest(manifest)

    except Exception as e:
        logger.error(f"Template sync failed: {e}")
        return {"status": "error", "message": str(e), **stats}

    return {"status": "ok", **stats}


def get_sync_status() -> dict:
    """Return current sync configuration and last sync state."""
    manifest = _load_manifest() if os.path.exists(SYNC_MANIFEST_PATH) else {}
    synced_count = len(manifest)

    return {
        "enabled": SYNC_ENABLED,
        "endpoint": SYNC_ENDPOINT,
        "bucket": SYNC_BUCKET,
        "prefix": SYNC_PREFIX,
        "synced_count": synced_count,
        "last_sync": max(
            (v.get("synced_at", "") for v in manifest.values() if isinstance(v, dict)),
            default=None,
        ),
    }


def publish_template(template_id: str) -> dict:
    """Upload a user template to the remote bucket for team sharing."""
    if not SYNC_ENABLED:
        return {"status": "error", "message": "Sync not enabled."}

    local_path = os.path.join(
        os.environ.get("DEMOFORGE_USER_TEMPLATES_DIR", "./user-templates"),
        f"{template_id}.yaml",
    )
    if not os.path.exists(local_path):
        return {"status": "error", "message": f"User template '{template_id}' not found."}

    s3 = _get_s3_client()
    remote_key = f"{SYNC_PREFIX}{template_id}.yaml"

    try:
        s3.upload_file(local_path, SYNC_BUCKET, remote_key)
        logger.info(f"Published template '{template_id}' to {SYNC_BUCKET}/{remote_key}")
        return {"status": "ok", "template_id": template_id, "remote_key": remote_key}
    except Exception as e:
        logger.error(f"Failed to publish template: {e}")
        return {"status": "error", "message": str(e)}


def publish_single_builtin(template_id: str) -> dict:
    """Push a single builtin template file to the remote bucket. Dev mode only."""
    if not SYNC_ENABLED:
        return {"status": "skipped", "message": "Sync not enabled."}

    if not SYNC_ACCESS_KEY or not SYNC_SECRET_KEY:
        return {"status": "skipped", "message": "Sync credentials not configured."}

    builtin_dir = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
    local_path = os.path.join(builtin_dir, f"{template_id}.yaml")
    if not os.path.exists(local_path):
        return {"status": "error", "message": f"Builtin template file not found: {local_path}"}

    remote_key = f"{SYNC_PREFIX}{template_id}.yaml"
    try:
        s3 = _get_s3_client()
        s3.upload_file(local_path, SYNC_BUCKET, remote_key)
        logger.info(f"Pushed builtin template '{template_id}' to {SYNC_BUCKET}/{remote_key}")
        return {"status": "ok", "remote_key": remote_key}
    except Exception as e:
        logger.error(f"Failed to push builtin template '{template_id}': {e}")
        return {"status": "error", "message": str(e)}


def publish_builtin_templates() -> dict:
    """Push all builtin templates to the remote bucket. Dev mode only."""
    if not SYNC_ENABLED:
        return {"status": "error", "message": "Sync not enabled."}

    if not SYNC_ACCESS_KEY or not SYNC_SECRET_KEY:
        return {"status": "error", "message": "Sync credentials not configured."}

    builtin_dir = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
    if not os.path.isdir(builtin_dir):
        return {"status": "error", "message": f"Builtin templates dir not found: {builtin_dir}"}

    s3 = _get_s3_client()
    stats = {"uploaded": 0, "errors": 0, "templates": []}

    for fname in sorted(os.listdir(builtin_dir)):
        if not fname.endswith(".yaml"):
            continue
        local_path = os.path.join(builtin_dir, fname)
        remote_key = f"{SYNC_PREFIX}{fname}"
        try:
            s3.upload_file(local_path, SYNC_BUCKET, remote_key)
            stats["uploaded"] += 1
            stats["templates"].append(fname)
            logger.info(f"Pushed builtin template: {fname}")
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Failed to push {fname}: {e}")

    return {"status": "ok", **stats}
