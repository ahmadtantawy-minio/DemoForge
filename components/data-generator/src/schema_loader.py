"""
schema_loader.py — Parse scenario YAML files and return structured config objects.
"""

import os
import yaml


DATASETS_DIR = os.path.join(os.path.dirname(__file__), "..", "datasets")


def load_scenario(scenario_id: str) -> dict:
    """
    Load and parse a scenario YAML file by ID.

    Returns a dict with keys:
      - id, name, description
      - columns: list of column defs (name, type, generator)
      - volume: volume profile config
      - partitioning: partitioning config per format
      - iceberg: iceberg table config (may be None)
      - buckets: bucket name map by format
      - queries: list of query defs
      - metabase_dashboard: dashboard layout config
    """
    path = os.path.join(DATASETS_DIR, f"{scenario_id}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Scenario '{scenario_id}' not found. Expected file: {path}"
        )

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

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


def list_scenarios() -> list:
    """
    Return a list of available scenario summaries from the datasets directory.
    Each entry: {id, name, description, queries_count}
    """
    scenarios = []
    if not os.path.isdir(DATASETS_DIR):
        return scenarios

    for fname in sorted(os.listdir(DATASETS_DIR)):
        if not fname.endswith(".yaml"):
            continue
        scenario_id = fname[: -len(".yaml")]
        try:
            scenario = load_scenario(scenario_id)
            scenarios.append(
                {
                    "id": scenario["id"],
                    "name": scenario["name"],
                    "description": scenario["description"],
                    "queries_count": len(scenario["queries"]),
                }
            )
        except Exception as exc:
            print(f"Warning: could not load scenario '{scenario_id}': {exc}")

    return scenarios


def get_volume_profile(scenario: dict, profile_name: str) -> dict:
    """
    Return the volume config for the named profile (low/medium/high),
    falling back to the scenario defaults.
    """
    volume = scenario.get("volume", {})
    profiles = volume.get("profiles", {})
    if profile_name in profiles:
        return profiles[profile_name]
    return {
        "rows_per_batch": volume.get("default_rows_per_batch", 500),
        "batches_per_minute": volume.get("default_batches_per_minute", 12),
    }


def get_partitioning(scenario: dict, fmt: str) -> dict:
    """
    Return the partitioning config for the given format string (parquet/json/csv).
    Returns a dict or the string 'flat' for flat formats.
    """
    partitioning = scenario.get("partitioning", {})
    return partitioning.get(fmt, "flat")


def get_bucket(scenario: dict, fmt: str) -> str:
    """Return the bucket name for the given format."""
    buckets = scenario.get("buckets", {})
    return buckets.get(fmt) or f"{scenario['id']}-{fmt}"


def get_queries_resolved(scenario: dict, catalog: str, namespace: str) -> list:
    """
    Return the scenario's queries with {catalog} and {namespace} placeholders replaced.
    """
    resolved = []
    for q in scenario.get("queries", []):
        q2 = dict(q)
        q2["sql"] = q2.get("sql", "").replace("{catalog}", catalog).replace(
            "{namespace}", namespace
        )
        resolved.append(q2)
    return resolved
