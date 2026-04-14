import os
from fastapi import APIRouter, HTTPException
from ..registry.loader import get_registry
from ..models.api_models import RegistryResponse, ComponentSummary
from ..engine.readiness import readiness

router = APIRouter()

@router.get("/api/registry/components", response_model=RegistryResponse)
async def list_components():
    registry = get_registry()
    manifests = {m.id: m for m in registry.values()}.values()

    # In dev and FA modes, filter to only released (FA-ready) components
    if os.getenv("DEMOFORGE_MODE") in ("fa", "dev"):
        if not readiness._components:
            readiness.load()
        ready_ids = readiness.get_ready_component_ids()
        manifests = [m for m in manifests if m.id in ready_ids]

    return RegistryResponse(
        components=[
            ComponentSummary(
                id=m.id,
                name=m.name,
                category=m.category,
                icon=m.icon,
                description=m.description,
                image=m.image,
                variants=list(m.variants.keys()),
                connections={
                    "provides": [p.model_dump() for p in m.connections.provides],
                    "accepts": [a.model_dump() for a in m.connections.accepts],
                },
                image_size_mb=m.image_size_mb,
                virtual=m.virtual,
                properties=[p.model_dump() for p in m.properties],
            )
            for m in manifests
        ]
    )

@router.get("/api/registry/components/{component_id}")
async def get_component(component_id: str):
    registry = get_registry()
    manifest = registry.get(component_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found")
    return manifest.model_dump()
