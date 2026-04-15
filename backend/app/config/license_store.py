"""License key storage — Hub HTTP API (via gateway) → local YAML fallback."""
import os
import json
import logging
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml

logger = logging.getLogger(__name__)

# Gateway endpoint for license reads — authenticated with FA API key
_HUB_URL = os.environ.get("DEMOFORGE_HUB_URL", "").rstrip("/")
_FA_API_KEY = os.environ.get("DEMOFORGE_API_KEY", "")
HUB_LICENSES_URL = f"{_HUB_URL}/api/hub/licenses" if _HUB_URL else ""


@dataclass
class LicenseEntry:
    license_id: str
    value: str
    label: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LicenseStore:
    """License store — tries HTTP hub gateway first, falls back to local YAML."""

    def __init__(self):
        data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
        self._yaml_path = os.path.join(data_dir, "licenses.yaml")

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

    # --- HTTP read (via hub gateway — no S3 signing needed) ---

    def _http_get(self, license_id: str) -> LicenseEntry | None:
        if not HUB_LICENSES_URL or not _FA_API_KEY:
            return None
        try:
            url = f"{HUB_LICENSES_URL}/{license_id}.json"
            req = urllib.request.Request(url, method="GET", headers={"X-Api-Key": _FA_API_KEY})
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return LicenseEntry(**data)
        except Exception:
            return None

    # --- Public API ---

    def get(self, license_id: str) -> LicenseEntry | None:
        # Local cache first — works offline after fa-update
        data = self._yaml_load()
        info = data.get(license_id)
        if info and isinstance(info, dict):
            return LicenseEntry(
                license_id=license_id,
                value=info.get("value", ""),
                label=info.get("label", ""),
                created_at=info.get("created_at", ""),
            )
        # Fall back to HTTP (hub) if not cached locally
        return self._http_get(license_id)

    def set(self, entry: LicenseEntry):
        # Write to local YAML (fallback + cache)
        data = self._yaml_load()
        data[entry.license_id] = {
            "value": entry.value,
            "label": entry.label,
            "created_at": entry.created_at,
        }
        self._yaml_save(data)

    def delete(self, license_id: str):
        data = self._yaml_load()
        data.pop(license_id, None)
        self._yaml_save(data)

    def list_all(self) -> list[LicenseEntry]:
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
