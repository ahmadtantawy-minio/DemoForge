"""
schema_loader.py — Load + validate scenario YAML files for external-system engine.
"""

import os
import yaml


SCENARIOS_DIR = os.environ.get(
    "ES_SCENARIOS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios"),
)


REQUIRED_SCENARIO_FIELDS = ["id", "name"]
REQUIRED_DATASET_FIELDS = ["id", "target"]


class ScenarioValidationError(ValueError):
    pass


def load_scenario(scenario_id: str, scenarios_dir: str = None) -> dict:
    base = scenarios_dir or SCENARIOS_DIR
    path = os.path.join(base, f"{scenario_id}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Scenario '{scenario_id}' not found at {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return _validate(raw, scenario_id)


def _validate(raw: dict, scenario_id: str) -> dict:
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


def list_scenarios(scenarios_dir: str = None) -> list:
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
