import os
import uuid
import yaml
from fastapi import APIRouter, HTTPException
from ..models.demo import DemoDefinition
from ..models.api_models import DemoSummary

router = APIRouter()
TEMPLATES_DIR = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
DEMOS_DIR = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")


def _safe_path(template_id: str) -> str | None:
    """Resolve template path and validate it stays within TEMPLATES_DIR."""
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.yaml")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(TEMPLATES_DIR)):
        return None
    return path


def _load_template_raw(template_id: str) -> dict | None:
    path = _safe_path(template_id)
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _save_template_raw(template_id: str, raw: dict):
    path = _safe_path(template_id)
    if not path:
        raise ValueError(f"Invalid template ID: {template_id}")
    with open(path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _template_summary(fname: str, raw: dict) -> dict:
    """Build a template summary from raw YAML data."""
    meta = raw.get("_template", {})
    template_id = fname.replace(".yaml", "")

    # Count containers: nodes + cluster node counts
    node_count = len(raw.get("nodes", []))
    container_count = node_count
    for cluster in raw.get("clusters", []):
        container_count += cluster.get("node_count", 0)

    resources = meta.get("estimated_resources", {})

    # Derive tier from mode or explicit field
    mode = meta.get("mode", raw.get("mode", "standard"))
    tier = meta.get("tier", "experience" if mode == "experience" else "essentials")

    return {
        "id": template_id,
        "name": meta.get("name", raw.get("name", "")),
        "description": meta.get("description", raw.get("description", "")),
        "tier": tier,
        "category": meta.get("category", "general"),
        "tags": meta.get("tags", []),
        "objective": meta.get("objective", ""),
        "minio_value": meta.get("minio_value", ""),
        "mode": mode,
        "component_count": node_count + len(raw.get("clusters", [])),
        "container_count": container_count,
        "estimated_resources": resources,
        "walkthrough": meta.get("walkthrough", []),
        "external_dependencies": meta.get("external_dependencies", []),
        "has_se_guide": bool(meta.get("se_guide")),
    }


@router.get("/api/templates")
async def list_templates():
    templates = []
    if os.path.isdir(TEMPLATES_DIR):
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if fname.endswith(".yaml"):
                try:
                    with open(os.path.join(TEMPLATES_DIR, fname)) as f:
                        raw = yaml.safe_load(f)
                    templates.append(_template_summary(fname, raw))
                except Exception:
                    pass
    return {"templates": templates}


@router.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    raw = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    meta = raw.get("_template", {})
    fname = f"{template_id}.yaml"
    summary = _template_summary(fname, raw)
    # Include the full demo definition fields too
    summary["nodes"] = raw.get("nodes", [])
    summary["edges"] = raw.get("edges", [])
    summary["clusters"] = raw.get("clusters", [])
    summary["networks"] = raw.get("networks", [])
    summary["groups"] = raw.get("groups", [])
    summary["annotations"] = raw.get("annotations", [])
    summary["schematics"] = raw.get("schematics", [])
    summary["sticky_notes"] = raw.get("sticky_notes", [])
    return summary


@router.get("/api/templates/{template_id}/guide")
async def get_template_guide(template_id: str):
    """Return the SE guide for a template."""
    raw = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    meta = raw.get("_template", {})
    guide = meta.get("se_guide")
    if not guide:
        raise HTTPException(404, "No SE guide for this template")
    return guide


@router.patch("/api/templates/{template_id}")
async def update_template(template_id: str, req: dict):
    raw = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")

    meta = raw.get("_template", {})

    # Update allowed metadata fields
    if "name" in req:
        meta["name"] = req["name"]
        raw["name"] = req["name"]
    if "description" in req:
        meta["description"] = req["description"]
        raw["description"] = req["description"]
    if "objective" in req:
        meta["objective"] = req["objective"]
    if "minio_value" in req:
        meta["minio_value"] = req["minio_value"]

    raw["_template"] = meta
    _save_template_raw(template_id, raw)

    fname = f"{template_id}.yaml"
    return _template_summary(fname, raw)


@router.post("/api/demos/from-template/{template_id}")
async def create_from_template(template_id: str):
    raw = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")

    # Strip template metadata before creating the demo
    demo_raw = {k: v for k, v in raw.items() if k != "_template"}
    demo_id = str(uuid.uuid4())[:8]
    demo_raw["id"] = demo_id
    demo = DemoDefinition(**demo_raw)

    # Save to demos directory
    os.makedirs(DEMOS_DIR, exist_ok=True)
    path = os.path.join(DEMOS_DIR, f"{demo.id}.yaml")
    with open(path, "w") as f:
        yaml.dump(demo.model_dump(), f, default_flow_style=False, sort_keys=False)

    return DemoSummary(
        id=demo.id, name=demo.name, description=demo.description,
        node_count=len(demo.nodes), status="stopped", mode=demo.mode,
    )
