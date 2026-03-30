"""
Template sync — pulls templates from a remote MinIO bucket.

Environment variables:
  DEMOFORGE_SYNC_ENABLED=true|false       (default: false)
  DEMOFORGE_SYNC_ENDPOINT=http://34.18.90.197:9000
  DEMOFORGE_SYNC_BUCKET=demoforge-templates
  DEMOFORGE_SYNC_PREFIX=templates/        (prefix within bucket)
  DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
  DEMOFORGE_SYNC_SECRET_KEY=<from .env.hub>
  DEMOFORGE_SYNC_REGION=us-east-1
  DEMOFORGE_SYNCED_TEMPLATES_DIR=./synced-templates
"""

import os
import json
import logging
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


def sync_templates() -> dict:
    """
    Pull templates from remote bucket. Returns summary of changes.
    Only downloads files whose ETag has changed since last sync.
    """
    if not SYNC_ENABLED:
        return {"status": "disabled", "message": "Template sync is not enabled."}

    if not SYNC_ACCESS_KEY or not SYNC_SECRET_KEY:
        return {"status": "error", "message": "Sync credentials not configured. Run scripts/hub-setup.sh and copy .env.hub to .env.local."}

    os.makedirs(SYNCED_DIR, exist_ok=True)
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
