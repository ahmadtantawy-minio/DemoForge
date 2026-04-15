import os
import glob as glob_module
import yaml
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

@router.get("/api/registry/components/{component_id}/scenarios")
async def list_component_scenarios(component_id: str):
    """List available scenarios for a scenario-based component."""
    components_dir = os.getenv("DEMOFORGE_COMPONENTS_DIR",
                               os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "components")))
    base_dir = os.path.join(components_dir, component_id, "scenarios")

    if not os.path.isdir(base_dir):
        return {"scenarios": [], "component_id": component_id}

    scenarios = []
    for yaml_path in sorted(glob_module.glob(os.path.join(base_dir, "*.yaml"))):
        filename = os.path.basename(yaml_path)
        if filename.startswith("_"):
            continue
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            scen = data.get("scenario", {})
            disp = data.get("display", {})
            first_ds = next(iter(data.get("datasets", [])), {})
            datasets = [
                {
                    "id": ds.get("id", ""),
                    "target": ds.get("target", "table"),
                    "format": ds.get("format"),
                    "namespace": ds.get("namespace") or ds.get("bucket", ""),
                    "table_name": ds.get("table_name", ""),
                    "generation_mode": ds.get("generation", {}).get("mode", ""),
                    "description": ds.get("description", ""),
                }
                for ds in data.get("datasets", [])
            ]
            scenarios.append({
                "id": scen.get("id", filename.replace(".yaml", "")),
                "name": scen.get("name", scen.get("id", filename)),
                "description": scen.get("description", ""),
                "category": scen.get("category", ""),
                "icon": scen.get("icon", ""),
                "default_name": disp.get("default_name", ""),
                "default_subtitle": disp.get("default_subtitle", ""),
                "format": first_ds.get("format"),
                "primary_table": first_ds.get("table_name"),
                "datasets": datasets,
            })
        except Exception as e:
            print(f"[registry] Failed to load scenario {yaml_path}: {e}")

    return {"scenarios": scenarios, "component_id": component_id}


@router.get("/api/registry/components/{component_id}")
async def get_component(component_id: str):
    registry = get_registry()
    manifest = registry.get(component_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found")
    return manifest.model_dump()
