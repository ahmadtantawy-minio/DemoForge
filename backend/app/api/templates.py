import os
import uuid
import yaml
from fastapi import APIRouter, HTTPException
from ..models.demo import DemoDefinition
from ..models.api_models import DemoSummary

router = APIRouter()
TEMPLATES_DIR = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
DEMOS_DIR = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")


def _load_template_raw(template_id: str) -> dict | None:
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.yaml")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _save_template_raw(template_id: str, raw: dict):
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.yaml")
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

    return {
        "id": template_id,
        "name": meta.get("name", raw.get("name", "")),
        "description": meta.get("description", raw.get("description", "")),
        "category": meta.get("category", "general"),
        "tags": meta.get("tags", []),
        "objective": meta.get("objective", ""),
        "minio_value": meta.get("minio_value", ""),
        "component_count": node_count + len(raw.get("clusters", [])),
        "container_count": container_count,
        "estimated_resources": resources,
        "walkthrough": meta.get("walkthrough", []),
        "external_dependencies": meta.get("external_dependencies", []),
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
    return summary


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
        node_count=len(demo.nodes), status="stopped",
    )
