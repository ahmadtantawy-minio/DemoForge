"""YAML-backed license key storage."""
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml

logger = logging.getLogger(__name__)


@dataclass
class LicenseEntry:
    license_id: str
    value: str
    label: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LicenseStore:
    """Persistent license store backed by a YAML file."""

    def __init__(self):
        data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
        self._path = os.path.join(data_dir, "licenses.yaml")

    def _load(self) -> dict[str, dict]:
        if not os.path.isfile(self._path):
            return {}
        try:
            with open(self._path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.warning("Invalid licenses.yaml format — returning empty")
                return {}
            return data
        except yaml.YAMLError:
            logger.warning("Failed to parse licenses.yaml — returning empty")
            return {}
        except OSError as e:
            logger.warning(f"Cannot read licenses.yaml: {e}")
            return {}

    def _save(self, data: dict[str, dict]):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        # Atomic write: write to temp file then rename
        tmp_path = self._path + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            os.rename(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, license_id: str) -> LicenseEntry | None:
        data = self._load()
        entry = data.get(license_id)
        if entry and isinstance(entry, dict):
            return LicenseEntry(
                license_id=license_id,
                value=entry.get("value", ""),
                label=entry.get("label", ""),
                created_at=entry.get("created_at", ""),
            )
        return None

    def set(self, entry: LicenseEntry):
        data = self._load()
        data[entry.license_id] = {
            "value": entry.value,
            "label": entry.label,
            "created_at": entry.created_at,
        }
        self._save(data)

    def delete(self, license_id: str):
        data = self._load()
        data.pop(license_id, None)
        self._save(data)

    def list_all(self) -> list[LicenseEntry]:
        data = self._load()
        entries = []
        for lid, info in data.items():
            if isinstance(info, dict):
                entries.append(LicenseEntry(
                    license_id=lid,
                    value=info.get("value", ""),
                    label=info.get("label", ""),
                    created_at=info.get("created_at", ""),
                ))
        return entries


# Singleton
license_store = LicenseStore()
