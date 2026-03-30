"""Settings API — license key management and app mode."""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..config.license_store import license_store, LicenseEntry
from ..registry.loader import get_registry

router = APIRouter()


class LicenseBody(BaseModel):
    license_id: str
    value: str
    label: str


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


@router.get("/api/settings/licenses")
def list_licenses():
    """List all stored licenses with masked values."""
    entries = license_store.list_all()
    return [
        {
            "license_id": e.license_id,
            "label": e.label,
            "value_masked": _mask(e.value),
            "created_at": e.created_at,
        }
        for e in entries
    ]


@router.post("/api/settings/licenses")
def upsert_license(body: LicenseBody):
    """Add or update a license key."""
    entry = LicenseEntry(
        license_id=body.license_id,
        value=body.value,
        label=body.label,
    )
    license_store.set(entry)
    return {"status": "ok", "license_id": body.license_id}


@router.delete("/api/settings/licenses/{license_id}")
def delete_license(license_id: str):
    """Remove a license key."""
    license_store.delete(license_id)
    return {"status": "ok", "license_id": license_id}


@router.get("/api/settings/licenses/status")
def license_status():
    """Cross-reference registry license_requirements with stored licenses."""
    registry = get_registry()
    results = []
    for manifest in registry.values():
        for req in manifest.license_requirements:
            entry = license_store.get(req.license_id)
            results.append({
                "license_id": req.license_id,
                "label": req.label,
                "description": req.description,
                "required": req.required,
                "component_id": manifest.id,
                "component_name": manifest.name,
                "configured": entry is not None,
            })
    return results


@router.get("/api/settings/mode")
async def get_app_mode():
    return {"mode": os.environ.get("DEMOFORGE_MODE", "standard")}
