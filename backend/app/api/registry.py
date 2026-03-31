from fastapi import APIRouter, HTTPException
from ..registry.loader import get_registry
from ..models.api_models import RegistryResponse, ComponentSummary

router = APIRouter()

@router.get("/api/registry/components", response_model=RegistryResponse)
async def list_components():
    registry = get_registry()
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
            )
            for m in {m.id: m for m in registry.values()}.values()
        ]
    )

@router.get("/api/registry/components/{component_id}")
async def get_component(component_id: str):
    registry = get_registry()
    manifest = registry.get(component_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found")
    return manifest.model_dump()
