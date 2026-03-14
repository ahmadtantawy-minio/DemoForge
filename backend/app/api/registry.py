from fastapi import APIRouter
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
            )
            for m in registry.values()
        ]
    )
