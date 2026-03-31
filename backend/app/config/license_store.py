"""License key storage — Hub HTTP API (via connector) → MinIO S3 SDK → local YAML fallback."""
import os
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml

logger = logging.getLogger(__name__)

# Hub connector endpoint for license reads (avoids S3 signature issues)
HUB_LICENSES_URL = os.environ.get("DEMOFORGE_HUB_LICENSES_URL", "")
# Auto-detect from registry host: if connector is at host.docker.internal:5000,
# the licenses endpoint is at host.docker.internal:8080/licenses
_REGISTRY_HOST = os.environ.get("DEMOFORGE_REGISTRY_HOST", "")
if not HUB_LICENSES_URL and _REGISTRY_HOST:
    _hub_host = _REGISTRY_HOST.split(":")[0]  # e.g. host.docker.internal
    HUB_LICENSES_URL = f"http://{_hub_host}:8080/licenses"


@dataclass
class LicenseEntry:
    license_id: str
    value: str
    label: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _get_minio_client():
    """Create a MinIO client from env vars. Returns None if not configured."""
    endpoint = os.environ.get("DEMOFORGE_SYNC_ENDPOINT", "")
    access_key = os.environ.get("DEMOFORGE_SYNC_ACCESS_KEY", "")
    secret_key = os.environ.get("DEMOFORGE_SYNC_SECRET_KEY", "")
    if not endpoint or not access_key or not secret_key:
        return None
    try:
        from minio import Minio
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        port = parsed.port
        secure = parsed.scheme == "https"
        endpoint_str = f"{host}:{port}" if port else host
        return Minio(endpoint_str, access_key=access_key, secret_key=secret_key, secure=secure)
    except Exception as e:
        logger.warning(f"Cannot create MinIO client for licenses: {e}")
        return None


LICENSES_BUCKET = "demoforge-licenses"


class LicenseStore:
    """License store — tries MinIO first, falls back to local YAML."""

    def __init__(self):
        data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
        self._yaml_path = os.path.join(data_dir, "licenses.yaml")

    def _ensure_bucket(self, client):
        """Create the licenses bucket if it doesn't exist."""
        try:
            if not client.bucket_exists(LICENSES_BUCKET):
                client.make_bucket(LICENSES_BUCKET)
                logger.info(f"Created bucket: {LICENSES_BUCKET}")
        except Exception as e:
            logger.warning(f"Cannot ensure bucket {LICENSES_BUCKET}: {e}")

    # --- MinIO operations ---

    def _minio_get(self, license_id: str) -> LicenseEntry | None:
        client = _get_minio_client()
        if not client:
            return None
        try:
            resp = client.get_object(LICENSES_BUCKET, f"{license_id}.json")
            data = json.loads(resp.read())
            resp.close()
            resp.release_conn()
            return LicenseEntry(**data)
        except Exception:
            return None

    def _minio_set(self, entry: LicenseEntry):
        client = _get_minio_client()
        if not client:
            return False
        try:
            self._ensure_bucket(client)
            data = json.dumps({
                "license_id": entry.license_id,
                "value": entry.value,
                "label": entry.label,
                "created_at": entry.created_at,
            }).encode()
            from io import BytesIO
            client.put_object(LICENSES_BUCKET, f"{entry.license_id}.json", BytesIO(data), len(data),
                            content_type="application/json")
            return True
        except Exception as e:
            logger.warning(f"Cannot write license to MinIO: {e}")
            return False

    def _minio_delete(self, license_id: str):
        client = _get_minio_client()
        if not client:
            return False
        try:
            client.remove_object(LICENSES_BUCKET, f"{license_id}.json")
            return True
        except Exception:
            return False

    def _minio_list(self) -> list[LicenseEntry] | None:
        client = _get_minio_client()
        if not client:
            return None
        try:
            if not client.bucket_exists(LICENSES_BUCKET):
                return []
            entries = []
            for obj in client.list_objects(LICENSES_BUCKET):
                if obj.object_name.endswith(".json"):
                    try:
                        resp = client.get_object(LICENSES_BUCKET, obj.object_name)
                        data = json.loads(resp.read())
                        resp.close()
                        resp.release_conn()
                        entries.append(LicenseEntry(**data))
                    except Exception:
                        continue
            return entries
        except Exception as e:
            logger.warning(f"Cannot list licenses from MinIO: {e}")
            return None

    # --- Local YAML fallback ---

    def _yaml_load(self) -> dict[str, dict]:
        if not os.path.isfile(self._yaml_path):
            return {}
        try:
            with open(self._yaml_path) as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _yaml_save(self, data: dict[str, dict]):
        os.makedirs(os.path.dirname(self._yaml_path), exist_ok=True)
        tmp_path = self._yaml_path + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            os.rename(tmp_path, self._yaml_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # --- HTTP read (via hub connector — no S3 signing needed) ---

    def _http_get(self, license_id: str) -> LicenseEntry | None:
        if not HUB_LICENSES_URL:
            return None
        try:
            url = f"{HUB_LICENSES_URL}/{license_id}.json"
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return LicenseEntry(**data)
        except Exception:
            return None

    def _http_list(self) -> list[LicenseEntry] | None:
        """List licenses via HTTP — tries MinIO S3 list since HTTP directory listing isn't available."""
        return None  # HTTP doesn't support listing; fall through to S3 or YAML

    # --- Public API ---

    def get(self, license_id: str) -> LicenseEntry | None:
        # Try HTTP (via connector — no S3 signing issues)
        entry = self._http_get(license_id)
        if entry:
            return entry
        # Try MinIO S3 SDK
        entry = self._minio_get(license_id)
        if entry:
            return entry
        # Fall back to local YAML
        data = self._yaml_load()
        info = data.get(license_id)
        if info and isinstance(info, dict):
            return LicenseEntry(
                license_id=license_id,
                value=info.get("value", ""),
                label=info.get("label", ""),
                created_at=info.get("created_at", ""),
            )
        return None

    def set(self, entry: LicenseEntry):
        # Write to MinIO (primary)
        wrote_minio = self._minio_set(entry)
        # Always write to local YAML too (fallback + cache)
        data = self._yaml_load()
        data[entry.license_id] = {
            "value": entry.value,
            "label": entry.label,
            "created_at": entry.created_at,
        }
        self._yaml_save(data)

    def delete(self, license_id: str):
        self._minio_delete(license_id)
        data = self._yaml_load()
        data.pop(license_id, None)
        self._yaml_save(data)

    def list_all(self) -> list[LicenseEntry]:
        # Try MinIO first
        entries = self._minio_list()
        if entries is not None:
            return entries
        # Fall back to local YAML
        data = self._yaml_load()
        return [
            LicenseEntry(
                license_id=lid,
                value=info.get("value", ""),
                label=info.get("label", ""),
                created_at=info.get("created_at", ""),
            )
            for lid, info in data.items()
            if isinstance(info, dict)
        ]


# Singleton
license_store = LicenseStore()
