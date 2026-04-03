from __future__ import annotations

"""Readiness API — component and template FA-readiness status."""
import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..engine.readiness import readiness
from ..registry.loader import get_registry

logger = logging.getLogger("demoforge.readiness")

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────

class ReadinessUpdate(BaseModel):
    fa_ready: bool
    notes: str | None = None
    updated_by: str | None = None


class BatchReadinessItem(BaseModel):
    component_id: str
    fa_ready: bool
    notes: str | None = None
    updated_by: str | None = None


class BatchReadinessUpdate(BaseModel):
    updates: list[BatchReadinessItem]


# ── Helpers ───────────────────────────────────────────────────────────

def _ensure_loaded():
    """Load readiness config if not yet loaded."""
    if not readiness._components:
        readiness.load()


def _extract_component_ids(raw: dict) -> list[str]:
    """Extract unique component IDs from a raw template dict."""
    ids: list[str] = []
    for node in raw.get("nodes", []):
        cid = node.get("component")
        if cid and cid not in ids:
            ids.append(cid)
    for cluster in raw.get("clusters", []):
        cid = cluster.get("component")
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def _discover_templates() -> list[tuple[str, dict]]:
    """Reuse template discovery from the templates module."""
    from .templates import _discover_all_templates
    return [(tid, raw) for tid, _source, raw in _discover_all_templates()]


def _discover_templates_with_source() -> list[tuple[str, dict, str]]:
    """Like _discover_templates but also returns the source (builtin/synced/user)."""
    from .templates import _discover_all_templates
    return [(tid, raw, source) for tid, source, raw in _discover_all_templates()]


def _write_guard():
    """Block write operations in FA mode."""
    if os.getenv("DEMOFORGE_MODE") not in ("dev", "standard", None, ""):
        raise HTTPException(403, "Readiness updates are not allowed in FA mode.")


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/api/readiness/components")
async def list_readiness_components():
    """All components with readiness status and which templates reference them."""
    _ensure_loaded()
    registry = get_registry()
    all_readiness = readiness.get_all()

    # Build reverse map: component_id -> [(template_id, template_name, component_ids)]
    templates = _discover_templates()
    component_templates: dict[str, list[dict]] = {}
    for tid, raw in templates:
        meta = raw.get("_template", {})
        tname = meta.get("name", raw.get("name", tid))
        cids = _extract_component_ids(raw)
        for cid in cids:
            component_templates.setdefault(cid, []).append({
                "template_id": tid,
                "template_name": tname,
                "component_ids": cids,
            })

    components = []
    seen = set()
    for cid, manifest in registry.items():
        entry = all_readiness.get(cid, {})
        fa_ready = bool(entry.get("fa_ready", False))
        trefs = component_templates.get(cid, [])
        template_items = [
            {
                "template_id": t["template_id"],
                "template_name": t["template_name"],
                "is_fa_ready": readiness.is_template_fa_ready(t["component_ids"]),
                "blocking_components": readiness.get_blocking_components(t["component_ids"]),
            }
            for t in trefs
        ]
        components.append({
            "component_id": cid,
            "component_name": manifest.name,
            "category": manifest.category,
            "fa_ready": fa_ready,
            "notes": entry.get("notes", ""),
            "updated_by": entry.get("updated_by", "") or None,
            "updated_at": entry.get("updated_at", "") or None,
            "template_count": len(template_items),
            "templates": template_items,
        })
        seen.add(cid)

    # Include readiness entries for components not in registry
    for cid, entry in all_readiness.items():
        if cid not in seen:
            fa_ready = bool(entry.get("fa_ready", False))
            trefs = component_templates.get(cid, [])
            template_items = [
                {
                    "template_id": t["template_id"],
                    "template_name": t["template_name"],
                    "is_fa_ready": readiness.is_template_fa_ready(t["component_ids"]),
                    "blocking_components": readiness.get_blocking_components(t["component_ids"]),
                }
                for t in trefs
            ]
            components.append({
                "component_id": cid,
                "component_name": cid,
                "category": "unknown",
                "fa_ready": fa_ready,
                "notes": entry.get("notes", ""),
                "updated_by": entry.get("updated_by", "") or None,
                "updated_at": entry.get("updated_at", "") or None,
                "template_count": len(template_items),
                "templates": template_items,
            })

    fa_ready_count = sum(1 for c in components if c["fa_ready"])
    return {
        "components": components,
        "summary": {
            "total": len(components),
            "fa_ready": fa_ready_count,
            "not_ready": len(components) - fa_ready_count,
        },
    }


@router.get("/api/readiness/templates")
async def list_readiness_templates():
    """All templates with derived readiness status."""
    _ensure_loaded()

    results = []
    for tid, raw, source in _discover_templates_with_source():
        component_ids = _extract_component_ids(raw)
        blocking = readiness.get_blocking_components(component_ids)
        meta = raw.get("_template", {})
        ready_count = len(component_ids) - len(blocking)
        results.append({
            "template_id": tid,
            "template_name": meta.get("name", raw.get("name", tid)),
            "source": source,
            "is_fa_ready": len(blocking) == 0,
            "component_count": len(component_ids),
            "components": component_ids,
            "blocking_components": blocking,
            "ready_component_count": ready_count,
        })

    fa_ready_count = sum(1 for t in results if t["is_fa_ready"])
    return {
        "templates": results,
        "summary": {
            "total": len(results),
            "fa_ready": fa_ready_count,
            "not_ready": len(results) - fa_ready_count,
        },
    }


@router.put("/api/readiness/components/{component_id}")
async def update_component_readiness(component_id: str, req: ReadinessUpdate):
    """Update readiness for a single component. Dev/standard mode only."""
    _write_guard()
    _ensure_loaded()
    readiness.set_readiness(
        component_id,
        fa_ready=req.fa_ready,
        notes=req.notes or "",
        updated_by=req.updated_by or "",
    )
    readiness.save()
    return {"component_id": component_id, "fa_ready": req.fa_ready}


@router.put("/api/readiness/components/batch")
async def batch_update_readiness(req: BatchReadinessUpdate):
    """Batch update readiness for multiple components. Dev/standard mode only."""
    _write_guard()
    _ensure_loaded()
    updated = []
    for item in req.updates:
        readiness.set_readiness(
            item.component_id,
            fa_ready=item.fa_ready,
            notes=item.notes or "",
            updated_by=item.updated_by or "",
        )
        updated.append(item.component_id)
    readiness.save()
    return {"updated": updated}
