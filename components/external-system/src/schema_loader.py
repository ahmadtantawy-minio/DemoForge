"""
schema_loader.py — Load + validate scenario YAML files for external-system engine.

Also exposes Data Generator–compatible helpers (`get_volume_profile`, `get_bucket`,
`get_partitioning`) and one-arg `load_scenario` routing to bundled dataset YAML under
`ES_DG_VENDOR_ROOT/datasets/`, so `/app/vendor/data-generator/generate.py` can import
`src.schema_loader` from this package without colliding with a second `src` tree.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import yaml


SCENARIOS_DIR = os.environ.get(
    "ES_SCENARIOS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios"),
)

DG_VENDOR_ROOT = os.environ.get("ES_DG_VENDOR_ROOT", "/app/vendor/data-generator")


REQUIRED_SCENARIO_FIELDS = ["id", "name"]
REQUIRED_DATASET_FIELDS = ["id", "target"]


class ScenarioValidationError(ValueError):
    pass


def _load_datagen_scenario_yaml(path: str, scenario_id: str) -> dict[str, Any]:
    """Same shape as components/data-generator/src/schema_loader.load_scenario."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{scenario_id}: dataset YAML root must be a mapping")
    return {
        "id": raw.get("id", scenario_id),
        "name": raw.get("name", scenario_id),
        "description": raw.get("description", ""),
        "columns": raw.get("schema", {}).get("columns", []),
        "volume": raw.get("volume", {}),
        "partitioning": raw.get("partitioning", {}),
        "iceberg": raw.get("iceberg"),
        "buckets": raw.get("buckets", {}),
        "queries": raw.get("queries", []),
        "metabase_dashboard": raw.get("metabase_dashboard"),
    }


def _load_es_yaml(scenario_id: str, base: str) -> dict[str, Any]:
    path = os.path.join(base, f"{scenario_id}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Scenario '{scenario_id}' not found at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return _validate(raw, scenario_id)


def load_scenario(scenario_id: str, scenarios_dir: Optional[str] = None) -> dict[str, Any]:
    """
    Load a scenario YAML.

    - If ``scenarios_dir`` is set (e.g. ``ES_SCENARIOS_DIR`` from run.py), load external-system
      scenario format from that directory.
    - If ``scenarios_dir`` is omitted and ``{ES_DG_VENDOR_ROOT}/datasets/{id}.yaml`` exists,
      load Data Generator dataset format (used by vendored ``generate.py``).
    - Otherwise load from ``SCENARIOS_DIR``.
    """
    if scenarios_dir is not None:
        return _load_es_yaml(scenario_id, scenarios_dir)

    dg_path = os.path.join(DG_VENDOR_ROOT, "datasets", f"{scenario_id}.yaml")
    if os.path.isfile(dg_path):
        return _load_datagen_scenario_yaml(dg_path, scenario_id)

    return _load_es_yaml(scenario_id, SCENARIOS_DIR)


def _validate(raw: dict, scenario_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScenarioValidationError(f"{scenario_id}: root must be a mapping")

    scenario = raw.get("scenario", {})
    for f in REQUIRED_SCENARIO_FIELDS:
        if not scenario.get(f):
            raise ScenarioValidationError(f"{scenario_id}: scenario.{f} is required")

    datasets = raw.get("datasets", [])
    if not isinstance(datasets, list):
        raise ScenarioValidationError(f"{scenario_id}: datasets must be a list")

    for ds in datasets:
        for f in REQUIRED_DATASET_FIELDS:
            if not ds.get(f):
                raise ScenarioValidationError(
                    f"{scenario_id}: dataset missing '{f}' in {ds.get('id', '?')}"
                )
        target = ds["target"]
        if target == "table":
            if not ds.get("table_name"):
                raise ScenarioValidationError(
                    f"{scenario_id}: dataset '{ds['id']}' target=table requires table_name"
                )
        elif target == "object":
            if not ds.get("bucket"):
                raise ScenarioValidationError(
                    f"{scenario_id}: dataset '{ds['id']}' target=object requires bucket"
                )

    return {
        "id": scenario.get("id", scenario_id),
        "name": scenario.get("name"),
        "description": scenario.get("description", ""),
        "category": scenario.get("category", ""),
        "display": raw.get("display", {}),
        "datasets": datasets,
        "reference_data": raw.get("reference_data", []),
        "correlations": raw.get("correlations", []),
        "dashboards": raw.get("dashboards", []),
        "saved_queries": raw.get("saved_queries", {}),
        "_raw": raw,
    }


def list_scenarios(scenarios_dir: Optional[str] = None) -> list:
    base = scenarios_dir or SCENARIOS_DIR
    if not os.path.isdir(base):
        return []
    out = []
    for fname in sorted(os.listdir(base)):
        if not fname.endswith(".yaml") or fname.startswith("_"):
            continue
        sid = fname[:-5]
        try:
            s = load_scenario(sid, base)
            out.append({"id": s["id"], "name": s["name"], "description": s["description"]})
        except Exception as exc:
            print(f"[schema_loader] Skipping {sid}: {exc}")
    return out


# --- Data Generator compatibility (see components/data-generator/src/schema_loader.py) ---


def get_volume_profile(scenario: dict, profile_name: str) -> dict:
    volume = scenario.get("volume", {})
    profiles = volume.get("profiles", {})
    if profile_name in profiles:
        return profiles[profile_name]
    return {
        "rows_per_batch": volume.get("default_rows_per_batch", 500),
        "batches_per_minute": volume.get("default_batches_per_minute", 12),
    }


def get_partitioning(scenario: dict, fmt: str) -> Any:
    partitioning = scenario.get("partitioning", {})
    return partitioning.get(fmt, "flat")


def get_bucket(scenario: dict, fmt: str) -> str:
    buckets = scenario.get("buckets", {})
    return buckets.get(fmt) or f"{scenario['id']}-{fmt}"


def get_queries_resolved(scenario: dict, catalog: str, namespace: str) -> list:
    resolved = []
    for q in scenario.get("queries", []):
        q2 = dict(q)
        q2["sql"] = q2.get("sql", "").replace("{catalog}", catalog).replace("{namespace}", namespace)
        resolved.append(q2)
    return resolved
