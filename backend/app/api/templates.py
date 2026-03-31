import os
import re
import uuid
import logging
from datetime import datetime
import yaml
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from ..models.demo import DemoDefinition
from ..models.api_models import DemoSummary
from ..engine.template_backup import backup_original, get_override_info, remove_override, BackupError
from ..fa_identity import get_fa_id

logger = logging.getLogger("demoforge.templates")

router = APIRouter()
BUILTIN_TEMPLATES_DIR = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
USER_TEMPLATES_DIR = os.environ.get("DEMOFORGE_USER_TEMPLATES_DIR", "./user-templates")
SYNCED_TEMPLATES_DIR = os.environ.get("DEMOFORGE_SYNCED_TEMPLATES_DIR", "./synced-templates")
DEMOS_DIR = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")

# Template source mode: "all" (default) or "synced" (MinIO-only for testing)
TEMPLATES_MODE = os.environ.get("DEMOFORGE_TEMPLATES_MODE", "all")

# Template source priority: user > synced > builtin
_ALL_SOURCES = [
    ("user", USER_TEMPLATES_DIR),
    ("synced", SYNCED_TEMPLATES_DIR),
    ("builtin", BUILTIN_TEMPLATES_DIR),
]

if TEMPLATES_MODE == "synced":
    TEMPLATE_SOURCES = [("synced", SYNCED_TEMPLATES_DIR)]
else:
    TEMPLATE_SOURCES = _ALL_SOURCES


def _discover_all_templates() -> list[tuple[str, str, dict]]:
    """
    Scan all template directories. Returns list of (template_id, source, raw_dict).
    Higher-priority sources shadow lower-priority ones on ID collision.
    """
    seen_ids: set[str] = set()
    results: list[tuple[str, str, dict]] = []

    for source_name, source_dir in TEMPLATE_SOURCES:
        if not os.path.isdir(source_dir):
            continue
        for fname in sorted(os.listdir(source_dir)):
            if not fname.endswith(".yaml"):
                continue
            template_id = fname.replace(".yaml", "")
            if template_id in seen_ids:
                continue  # Higher-priority source already has this ID
            try:
                path = os.path.join(source_dir, fname)
                with open(path) as f:
                    raw = yaml.safe_load(f)
                if raw:
                    seen_ids.add(template_id)
                    results.append((template_id, source_name, raw))
            except Exception as e:
                logger.warning(f"Failed to load template {fname} from {source_name}: {e}")
    return results


def _load_template_raw(template_id: str) -> tuple[dict | None, str | None, str | None]:
    """
    Load a template by ID from the highest-priority source.
    Returns (raw_dict, source_name, file_path) or (None, None, None).
    """
    for source_name, source_dir in TEMPLATE_SOURCES:
        path = os.path.join(source_dir, f"{template_id}.yaml")
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(source_dir)):
            continue
        if os.path.exists(path):
            with open(path) as f:
                raw = yaml.safe_load(f)
            return raw, source_name, path
    return None, None, None


def _save_template_raw(template_id: str, raw: dict, target_dir: str | None = None):
    target = target_dir or USER_TEMPLATES_DIR
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, f"{template_id}.yaml")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(target)):
        raise ValueError(f"Invalid template ID: {template_id}")
    with open(path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _template_summary(fname: str, raw: dict, source: str = "builtin") -> dict:
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

    override_info = get_override_info(template_id)

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
        "source": source,
        "editable": source == "user",
        "customized": override_info is not None or meta.get("customized", False),
        "origin": meta.get("origin", source),
        "saved_by": meta.get("saved_by", ""),
    }


@router.get("/api/templates")
async def list_templates(mine: bool = False):
    templates = []
    source_counts = {"builtin": 0, "synced": 0, "user": 0}
    for template_id, source, raw in _discover_all_templates():
        summary = _template_summary(f"{template_id}.yaml", raw, source=source)
        templates.append(summary)
        source_counts[source] = source_counts.get(source, 0) + 1

    if mine:
        current_fa = get_fa_id()
        if current_fa:
            templates = [t for t in templates if t.get("saved_by") == current_fa]
        else:
            templates = []

    # Get sync status for frontend indicator
    from ..engine.template_sync import get_sync_status, SYNC_ENABLED
    sync_info = get_sync_status() if SYNC_ENABLED else {"enabled": False}

    return {
        "templates": templates,
        "sources": source_counts,
        "mode": TEMPLATES_MODE,
        "sync": sync_info,
    }


@router.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    fname = f"{template_id}.yaml"
    summary = _template_summary(fname, raw, source=source)
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
    """Return the Field Architect guide for a template."""
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    meta = raw.get("_template", {})
    guide = meta.get("se_guide")
    if not guide:
        raise HTTPException(404, "No guide for this template")
    return guide


@router.patch("/api/templates/{template_id}")
async def update_template(template_id: str, req: dict):
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    if source != "user":
        raise HTTPException(403, "Only user-saved templates can be edited. Use 'Save as Template' to create an editable copy.")

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
    return _template_summary(fname, raw, source="user")


@router.post("/api/demos/from-template/{template_id}")
async def create_from_template(template_id: str):
    raw, source, path = _load_template_raw(template_id)
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


# ── Save as Template ────────────────���───────────────────────────────────

class SaveAsTemplateRequest(BaseModel):
    demo_id: str
    template_name: str
    description: str = ""
    tier: str = "advanced"
    category: str = "general"
    tags: list[str] = []
    objective: str = ""
    minio_value: str = ""
    overwrite: bool = False


def _slugify(name: str) -> str:
    """Convert template name to a safe filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug or "custom-template"


def _estimate_resources(demo_raw: dict) -> dict:
    """Estimate resource requirements from demo topology."""
    node_count = len(demo_raw.get("nodes", []))
    cluster_containers = sum(
        c.get("node_count", 0) for c in demo_raw.get("clusters", [])
    )
    total_containers = node_count + cluster_containers
    est_memory_gb = max(1, round(total_containers * 0.5))
    return {
        "memory": f"{est_memory_gb}GB",
        "cpu": max(1, total_containers // 2),
        "containers": total_containers,
    }


@router.post("/api/templates/save-from-demo")
async def save_as_template(req: SaveAsTemplateRequest):
    # 1. Load the demo
    demo_path = os.path.join(DEMOS_DIR, f"{req.demo_id}.yaml")
    if not os.path.exists(demo_path):
        raise HTTPException(404, "Demo not found")
    with open(demo_path) as f:
        demo_raw = yaml.safe_load(f)

    # 2. Generate template ID from name
    template_id = _slugify(req.template_name)

    # 3. Check for collision
    existing_path = os.path.join(USER_TEMPLATES_DIR, f"{template_id}.yaml")
    if os.path.exists(existing_path) and not req.overwrite:
        raise HTTPException(
            409,
            f"A user template with ID '{template_id}' already exists. "
            "Set overwrite=true to replace it, or choose a different name."
        )

    # 4. Build template metadata
    template_meta = {
        "name": req.template_name,
        "tier": req.tier,
        "category": req.category,
        "tags": req.tags,
        "description": req.description,
        "objective": req.objective,
        "minio_value": req.minio_value,
        "estimated_resources": _estimate_resources(demo_raw),
        "external_dependencies": [],
        "walkthrough": [],
        "saved_from_demo": req.demo_id,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "saved_by": get_fa_id(),
    }

    # 5. Build template YAML
    template_raw = {"_template": template_meta}
    for key in ["name", "description", "mode", "networks", "nodes", "edges",
                 "groups", "sticky_notes", "annotations", "schematics",
                 "clusters", "resources"]:
        if key in demo_raw:
            template_raw[key] = demo_raw[key]

    template_raw["id"] = f"template-{template_id}"
    template_raw["name"] = req.template_name
    template_raw["description"] = req.description or demo_raw.get("description", "")

    # 6. Write
    _save_template_raw(template_id, template_raw)

    logger.info(f"Saved template '{template_id}' from demo '{req.demo_id}'")

    return {
        "template_id": template_id,
        "source": "user",
        "message": f"Template '{req.template_name}' saved successfully.",
    }


@router.delete("/api/templates/{template_id}")
async def delete_template(template_id: str):
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    if source != "user":
        raise HTTPException(403, "Only user-saved templates can be deleted.")
    os.remove(path)
    logger.info(f"Deleted user template '{template_id}'")
    return {"deleted": template_id}


@router.post("/api/templates/{template_id}/fork")
async def fork_template(template_id: str, req: dict = Body(default={})):
    """Copy a builtin or synced template into user-templates for editing."""
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")

    new_name = req.get("name", raw.get("_template", {}).get("name", template_id) + " (custom)")
    new_id = _slugify(new_name)

    existing = os.path.join(USER_TEMPLATES_DIR, f"{new_id}.yaml")
    if os.path.exists(existing):
        raise HTTPException(409, f"User template '{new_id}' already exists.")

    # Update metadata
    meta = raw.get("_template", {})
    meta["name"] = new_name
    meta["forked_from"] = template_id
    meta["forked_at"] = datetime.utcnow().isoformat() + "Z"
    meta["forked_by"] = get_fa_id()
    raw["_template"] = meta
    raw["name"] = new_name
    raw["id"] = f"template-{new_id}"

    _save_template_raw(new_id, raw)

    return {
        "template_id": new_id,
        "source": "user",
        "forked_from": template_id,
    }


# ── Override / Revert ──────────────────────────────────────────────────

class OverrideTemplateRequest(BaseModel):
    demo_id: str  # The demo to save as the override


@router.post("/api/templates/{template_id}/override")
async def override_template(template_id: str, req: OverrideTemplateRequest):
    """Override an existing template with a demo's current state.

    Safety-first: the override is ABORTED if:
    - The original template cannot be found or read
    - The backup cannot be created or verified (hash mismatch, disk error)
    - The demo source data cannot be loaded
    This prevents any data loss scenario.
    """
    # 1. Load original template
    raw, source, path = _load_template_raw(template_id)
    if not raw or not path:
        raise HTTPException(404, f"Template '{template_id}' not found")

    # 2. Back up the original (mandatory for non-user templates)
    if source != "user":
        try:
            backup_original(template_id, path, source)
        except BackupError as e:
            logger.error(f"Backup failed for template '{template_id}': {e}")
            raise HTTPException(
                500,
                f"Override aborted — could not safely back up the original template. "
                f"No changes were made. Detail: {e}"
            )

        # 3. Verify the backup is actually retrievable before we overwrite anything
        override_info = get_override_info(template_id)
        if not override_info:
            raise HTTPException(
                500,
                f"Override aborted — backup was written but cannot be found in the manifest. "
                f"No changes were made to the template."
            )
        backup_path = override_info.get("backup_path", "")
        if not os.path.isfile(backup_path):
            raise HTTPException(
                500,
                f"Override aborted — backup manifest references '{backup_path}' but the file "
                f"does not exist. No changes were made to the template."
            )
    else:
        override_info = get_override_info(template_id)

    # 4. Load the demo
    demo_path = os.path.join(DEMOS_DIR, f"{req.demo_id}.yaml")
    if not os.path.isfile(demo_path):
        raise HTTPException(404, f"Demo '{req.demo_id}' not found")

    try:
        with open(demo_path) as f:
            demo_data = yaml.safe_load(f)
    except Exception as e:
        raise HTTPException(
            500,
            f"Override aborted — cannot read demo '{req.demo_id}': {e}. "
            f"The original template backup is safe."
        )

    if not demo_data:
        raise HTTPException(
            500,
            f"Override aborted — demo '{req.demo_id}' is empty or invalid. "
            f"The original template backup is safe."
        )

    # 5. Build template from demo, preserving original metadata
    original_meta = raw.get("_template", {})
    template_data = {
        "_template": {
            **original_meta,
            "origin": source,
            "original_hash": override_info.get("original_hash", "") if override_info else "",
            "overridden_at": datetime.utcnow().isoformat() + "Z",
            "overridden_by": get_fa_id(),
            "customized": True,
        },
        **{k: v for k, v in demo_data.items() if k != "_template"},
        "id": raw.get("id", template_id),
        "name": raw.get("name", demo_data.get("name", template_id)),
    }

    # 6. Write to user-templates (shadows the original)
    try:
        _save_template_raw(template_id, template_data, USER_TEMPLATES_DIR)
    except Exception as e:
        raise HTTPException(
            500,
            f"Override aborted — failed to write the override file: {e}. "
            f"The original template backup is safe."
        )

    logger.info(f"Template '{template_id}' overridden from demo '{req.demo_id}' (backup from {source})")
    return {"template_id": template_id, "overridden": True, "source": source}


@router.post("/api/templates/{template_id}/revert")
async def revert_template(template_id: str):
    """Revert an overridden template to its original. Dev mode only."""
    mode = os.environ.get("DEMOFORGE_MODE", "standard")
    if mode != "dev":
        raise HTTPException(403, "Revert is only available in dev mode. Set DEMOFORGE_MODE=dev.")

    # Delete the user-templates override
    user_path = os.path.join(USER_TEMPLATES_DIR, f"{template_id}.yaml")
    if os.path.exists(user_path):
        os.remove(user_path)

    # Clean up override manifest entry
    remove_override(template_id)

    return {"reverted": template_id}


# ── Sync endpoints ──────────────────────────────────────────────────────

@router.post("/api/templates/sync")
async def trigger_sync():
    """Manually trigger template sync from remote."""
    from ..engine.template_sync import sync_templates
    result = sync_templates()
    return result


@router.get("/api/templates/sync/status")
async def sync_status():
    """Get sync configuration and state."""
    from ..engine.template_sync import get_sync_status
    return get_sync_status()


@router.post("/api/templates/{template_id}/publish")
async def publish_template_endpoint(template_id: str):
    """Publish a user template to the remote bucket for team sharing."""
    raw, source, path = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    if source != "user":
        raise HTTPException(403, "Only user-saved templates can be published.")
    meta = raw.get("_template", {})
    meta["published_by"] = get_fa_id()
    raw["_template"] = meta
    _save_template_raw(template_id, raw)
    from ..engine.template_sync import publish_template
    result = publish_template(template_id)
    if result["status"] == "error":
        raise HTTPException(500, result["message"])
    return result
