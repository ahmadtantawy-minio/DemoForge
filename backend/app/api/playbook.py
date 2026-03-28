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


def _load_scenario_playbook(scenario_id: str) -> tuple[str, list[dict]] | None:
    """Load a scenario YAML and extract its playbook."""
    path = os.path.join(DATASETS_DIR, f"{scenario_id}.yaml")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        data = yaml.safe_load(f)
    name = data.get("name", scenario_id)
    playbook = data.get("playbook", [])
    return name, playbook


@router.get("/api/demos/{demo_id}/playbook", response_model=PlaybookResponse)
async def get_playbook(demo_id: str):
    """Return the SQL playbook for the demo's data generator scenario."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    scenario_id = _find_scenario_id(demo_id)
    if not scenario_id:
        raise HTTPException(404, "No data generator with scenario found in this demo")

    result = _load_scenario_playbook(scenario_id)
    if not result:
        raise HTTPException(404, f"Scenario '{scenario_id}' not found")

    name, playbook_raw = result
    if not playbook_raw:
        raise HTTPException(404, f"Scenario '{scenario_id}' has no playbook")

    steps = [
        PlaybookStep(
            step=s.get("step", i + 1),
            title=s.get("title", f"Step {i + 1}"),
            description=s.get("description", ""),
            sql=s.get("sql", ""),
            expected=s.get("expected", ""),
        )
        for i, s in enumerate(playbook_raw)
    ]

    return PlaybookResponse(
        scenario_id=scenario_id,
        scenario_name=name,
        steps=steps,
    )
