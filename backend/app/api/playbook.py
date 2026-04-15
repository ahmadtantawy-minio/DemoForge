"""Fetch playbook steps for a demo's active dataset scenario."""
from __future__ import annotations

import os

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..state.store import state

router = APIRouter()

DATASETS_DIR = os.path.join(
    os.getenv("DEMOFORGE_COMPONENTS_DIR", "/app/components"),
    "data-generator", "datasets",
)


class PlaybookStep(BaseModel):
    step: int
    title: str
    description: str = ""
    sql: str
    expected: str = ""


class PlaybookResponse(BaseModel):
    scenario_id: str
    scenario_name: str
    steps: list[PlaybookStep]


def _find_scenario_id(demo_id: str) -> str | None:
    """Find the DG_SCENARIO from a running demo's data-generator node."""
    running = state.get_demo(demo_id)
    if not running:
        return None

    # Check running containers for data-generator
    for node_id, container in running.containers.items():
        if container.component_id == "data-generator":
            # Try to get scenario from the demo definition
            from ..api.demos import _load_demo
            demo = _load_demo(demo_id)
            if demo:
                for node in demo.nodes:
                    if node.id == node_id and node.config:
                        return node.config.get("DG_SCENARIO")
            # Fallback: check container env
            try:
                import docker
                client = docker.from_env()
                c = client.containers.get(container.container_name)
                for env in c.attrs.get("Config", {}).get("Env", []):
                    if env.startswith("DG_SCENARIO="):
                        return env.split("=", 1)[1]
            except Exception:
                pass
    return None


def _resolve_catalog_namespace(demo_id: str, scenario_id: str) -> tuple[str, str]:
    """Determine the Trino catalog and namespace for a scenario in a running demo."""
    from ..api.demos import _load_demo
    demo = _load_demo(demo_id)
    if not demo:
        return ("iceberg", "demo")

    # Find the data-generator node — prefer one with matching DG_SCENARIO,
    # fall back to any data-generator (covers nodes with empty config)
    dg_node = next(
        (n for n in demo.nodes if n.component == "data-generator"
         and n.config.get("DG_SCENARIO") == scenario_id),
        None,
    ) or next(
        (n for n in demo.nodes if n.component == "data-generator"),
        None,
    )
    if dg_node is None:
        return ("iceberg", "demo")

    wm = dg_node.config.get("DG_WRITE_MODE", "iceberg")
    if wm == "raw":
        return ("hive", "raw")

    # Prefer catalog_name from the MinIO↔Trino edge if defined
    trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
    if trino_node:
        for edge in demo.edges:
            if edge.target == trino_node.id and edge.connection_type in ("sql-query", "aistor-tables", "iceberg"):
                cat = (edge.connection_config or {}).get("catalog_name")
                if cat:
                    return (cat, "demo")

    # Check if this generator targets an AIStor cluster via an edge
    for edge in demo.edges:
        if edge.source == dg_node.id and edge.connection_type in ("structured-data", "s3"):
            target = edge.target
            for cl in demo.clusters:
                if cl.id == target and getattr(cl, "aistor_tables_enabled", False):
                    return ("aistor", "demo")

    # Check if any minio node is AIStor edition
    for n in demo.nodes:
        if n.component == "minio" and n.config.get("MINIO_EDITION", "ce") == "aistor":
            return ("aistor", "demo")

    return ("iceberg", "demo")


def _load_scenario_playbook(scenario_id: str) -> tuple[str, list[dict], dict] | None:
    """Load a scenario YAML and return (name, playbook_steps, iceberg_config)."""
    path = os.path.join(DATASETS_DIR, f"{scenario_id}.yaml")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        data = yaml.safe_load(f)
    name = data.get("name", scenario_id)
    playbook = data.get("playbook", [])
    iceberg = data.get("iceberg", {})
    return name, playbook, iceberg


@router.get("/api/demos/{demo_id}/playbook", response_model=PlaybookResponse)
async def get_playbook(demo_id: str):
    """Return the SQL playbook for the demo's data generator scenario.

    Resolves {catalog}, {namespace}, and {table} placeholders in SQL before
    returning steps so queries run correctly against Trino.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    scenario_id = _find_scenario_id(demo_id)
    if not scenario_id:
        raise HTTPException(404, "No data generator with scenario found in this demo")

    result = _load_scenario_playbook(scenario_id)
    if not result:
        raise HTTPException(404, f"Scenario '{scenario_id}' not found")

    name, playbook_raw, iceberg_cfg = result
    if not playbook_raw:
        raise HTTPException(404, f"Scenario '{scenario_id}' has no playbook")

    catalog, namespace = _resolve_catalog_namespace(demo_id, scenario_id)
    table = iceberg_cfg.get("table", scenario_id.replace("-", "_"))

    steps = [
        PlaybookStep(
            step=s.get("step", i + 1),
            title=s.get("title", f"Step {i + 1}"),
            description=s.get("description", ""),
            sql=(s.get("sql", "")
                 .replace("{catalog}", catalog)
                 .replace("{namespace}", namespace)
                 .replace("{table}", table)),
            expected=s.get("expected", ""),
        )
        for i, s in enumerate(playbook_raw)
    ]

    return PlaybookResponse(
        scenario_id=scenario_id,
        scenario_name=name,
        steps=steps,
    )
