from __future__ import annotations

"""Component readiness gate for FA mode.

Loads component-readiness.yaml to determine which components (and thus
which templates) are available when DEMOFORGE_MODE=fa.

Override the config file path with the DEMOFORGE_READINESS_CONFIG env var.
"""
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger("demoforge.readiness")

_DEFAULT_CONFIG = "component-readiness.yaml"


class ComponentReadiness:
    def __init__(self):
        self._components: dict[str, dict] = {}
        self._path: Path | None = None

    def load(self, path: str | None = None):
        """Load readiness config from YAML. Safe to call multiple times."""
        p = Path(path) if path else Path(
            os.environ.get("DEMOFORGE_READINESS_CONFIG", _DEFAULT_CONFIG)
        )
        self._path = p
        if not p.exists():
            logger.warning(f"Readiness config not found at {p}, using empty defaults")
            self._components = {}
            return
        with open(p) as f:
            raw = yaml.safe_load(f) or {}
        self._components = raw.get("components", {})

    def save(self, path: str | None = None):
        """Write current state back to YAML."""
        p = Path(path) if path else self._path
        if not p:
            p = Path(os.environ.get("DEMOFORGE_READINESS_CONFIG", _DEFAULT_CONFIG))
        data = {"components": self._components}
        with open(p, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def is_fa_ready(self, component_id: str) -> bool:
        entry = self._components.get(component_id)
        if not entry:
            return False
        return bool(entry.get("fa_ready", False))

    def get_all(self) -> dict:
        return dict(self._components)

    def get_ready_component_ids(self) -> set[str]:
        return {cid for cid, entry in self._components.items() if entry.get("fa_ready")}

    def set_readiness(self, component_id: str, fa_ready: bool, notes: str = "", updated_by: str = ""):
        entry = self._components.get(component_id, {})
        entry["fa_ready"] = fa_ready
        if notes:
            entry["notes"] = notes
        if updated_by:
            entry["updated_by"] = updated_by
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._components[component_id] = entry

    def is_template_fa_ready(self, component_ids: list[str]) -> bool:
        """True only if ALL components used by a template are fa_ready."""
        return all(self.is_fa_ready(cid) for cid in component_ids)

    def get_blocking_components(self, component_ids: list[str]) -> list[str]:
        """Return component IDs that are NOT fa_ready."""
        return [cid for cid in component_ids if not self.is_fa_ready(cid)]


# Singleton — call readiness.load() during startup or on first use.
readiness = ComponentReadiness()
