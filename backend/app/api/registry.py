import os
import glob as glob_module
import yaml
from fastapi import APIRouter, HTTPException
from ..registry.loader import get_registry
from ..models.api_models import RegistryResponse, ComponentSummary
from ..engine.readiness import readiness

router = APIRouter()


def _load_external_system_scenario_option(yaml_path: str) -> dict | None:
    """Parse one external-system scenario YAML into the UI/API scenario shape."""
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        filename = os.path.basename(yaml_path)
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
                "stream_rate": ds.get("generation", {}).get("stream_rate"),
                "seed_rows": ds.get("generation", {}).get("seed_rows"),
                "has_raw_landing": bool(ds.get("raw_landing")),
                "seed_count": ds.get("generation", {}).get("seed_count"),
            }
            for ds in data.get("datasets", [])
        ]
        default_raw_bucket = ""
        default_raw_format = ""
        for ds in data.get("datasets", []):
            rl = ds.get("raw_landing")
            if isinstance(rl, dict) and rl.get("bucket"):
                default_raw_bucket = str(rl["bucket"])
                default_raw_format = str(ds.get("format") or "csv").lower()
                break
        return {
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
            "default_raw_bucket": default_raw_bucket,
            "default_raw_format": default_raw_format,
            "scenario_kind": "external-system",
        }
    except Exception as e:
        print(f"[registry] Failed to load scenario {yaml_path}: {e}")
        return None


def _load_data_generator_scenario_option(yaml_path: str) -> dict | None:
    """Map a data-generator dataset YAML into the same scenario option shape (for External System UI)."""
    try:
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        sid = raw.get("id", os.path.basename(yaml_path).replace(".yaml", ""))
        name = raw.get("name", sid)
        desc = raw.get("description", "")
        iceberg = raw.get("iceberg") or {}
        buckets = raw.get("buckets") or {}
        # Default raw landing: prefer csv/json over parquet so "Files only" labels match typical raw demos.
        default_raw_format = "csv"
        default_raw_bucket = ""
        for candidate in ("csv", "json", "parquet"):
            b = buckets.get(candidate)
            if b:
                default_raw_format = candidate
                default_raw_bucket = str(b)
                break
        # Display format for Files + Iceberg context (prefer parquet when available)
        display_fmt = "parquet"
        for candidate in ("parquet", "json", "csv"):
            if buckets.get(candidate):
                display_fmt = candidate
                break
        ns = iceberg.get("namespace", "demo")
        table = iceberg.get("table", "")
        return {
            "id": sid,
            "name": name,
            "description": f"{desc} Same S3 paths and batching as the Data Generator component.",
            "category": "structured-data",
            "icon": "",
            "default_name": name,
            "default_subtitle": "Data Generator scenario",
            "format": display_fmt,
            "primary_table": table,
            "default_raw_format": default_raw_format,
            "default_raw_bucket": default_raw_bucket,
            "datasets": [
                {
                    "id": "dg_stream",
                    "target": "table",
                    "namespace": ns,
                    "table_name": table,
                    "format": display_fmt,
                    "generation_mode": "stream",
                    "description": "Structured batches (partitioning + buckets match Data Generator).",
                    "stream_rate": "volume profile (low / medium / high)",
                    "seed_rows": None,
                    "has_raw_landing": False,
                    "seed_count": None,
                }
            ],
            "scenario_kind": "data-generator",
        }
    except Exception as e:
        print(f"[registry] Failed to load data-generator dataset {yaml_path}: {e}")
        return None

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

    scenarios: list = []
    if os.path.isdir(base_dir):
        for yaml_path in sorted(glob_module.glob(os.path.join(base_dir, "*.yaml"))):
            filename = os.path.basename(yaml_path)
            if filename.startswith("_"):
                continue
            opt = _load_external_system_scenario_option(yaml_path)
            if opt:
                scenarios.append(opt)

    # External System: also offer every Data Generator dataset (same YAML + same file layout in the container).
    if component_id == "external-system":
        dg_dir = os.path.join(components_dir, "data-generator", "datasets")
        if os.path.isdir(dg_dir):
            for yaml_path in sorted(glob_module.glob(os.path.join(dg_dir, "*.yaml"))):
                if os.path.basename(yaml_path).startswith("_"):
                    continue
                opt = _load_data_generator_scenario_option(yaml_path)
                if opt:
                    scenarios.append(opt)

    return {"scenarios": scenarios, "component_id": component_id}


@router.get("/api/registry/components/{component_id}")
async def get_component(component_id: str):
    registry = get_registry()
    manifest = registry.get(component_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found")
    return manifest.model_dump()
