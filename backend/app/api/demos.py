import os
import uuid
import yaml
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from ..models.demo import DemoDefinition, DemoNetwork, DemoNode, DemoEdge, DemoGroup, DemoCluster, NodePosition
from ..models.api_models import (
    DemoListResponse, DemoSummary, CreateDemoRequest, SaveDiagramRequest,
)
from ..state.store import state

router = APIRouter()
DEMOS_DIR = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")

def _load_demo(demo_id: str) -> DemoDefinition | None:
    path = os.path.join(DEMOS_DIR, f"{demo_id}.yaml")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return DemoDefinition(**yaml.safe_load(f))

def _save_demo(demo: DemoDefinition):
    os.makedirs(DEMOS_DIR, exist_ok=True)
    path = os.path.join(DEMOS_DIR, f"{demo.id}.yaml")
    with open(path, "w") as f:
        yaml.dump(demo.model_dump(), f, default_flow_style=False, sort_keys=False)

@router.get("/api/demos", response_model=DemoListResponse)
async def list_demos():
    demos = []
    if os.path.isdir(DEMOS_DIR):
        for fname in os.listdir(DEMOS_DIR):
            if fname.endswith(".yaml"):
                d = _load_demo(fname.replace(".yaml", ""))
                if d:
                    running = state.get_demo(d.id)
                    demos.append(DemoSummary(
                        id=d.id,
                        name=d.name,
                        description=d.description,
                        node_count=len(d.nodes),
                        status=running.status if running else "stopped",
                        mode=d.mode,
                    ))
    return DemoListResponse(demos=demos)

@router.post("/api/demos", response_model=DemoSummary)
async def create_demo(req: CreateDemoRequest):
    demo_id = str(uuid.uuid4())[:8]
    demo = DemoDefinition(
        id=demo_id,
        name=req.name,
        description=req.description,
        networks=[DemoNetwork(name="default")],
    )
    _save_demo(demo)
    return DemoSummary(id=demo.id, name=demo.name, description=demo.description, node_count=0, status="stopped", mode=demo.mode)

@router.get("/api/demos/{demo_id}")
async def get_demo(demo_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    return demo.model_dump()

@router.patch("/api/demos/{demo_id}")
async def update_demo(demo_id: str, req: dict):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    if "name" in req:
        demo.name = req["name"]
    if "description" in req:
        demo.description = req["description"]
    if "resources" in req:
        from ..models.demo import DemoResourceSettings
        demo.resources = DemoResourceSettings(**req["resources"])
    _save_demo(demo)
    running = state.get_demo(demo_id)
    status = running.status if running else "stopped"
    return DemoSummary(id=demo.id, name=demo.name, description=demo.description,
                       node_count=len(demo.nodes), status=status, mode=demo.mode)

@router.put("/api/demos/{demo_id}/diagram")
async def save_diagram(demo_id: str, req: SaveDiagramRequest):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    # Experience mode demos are read-only — skip saving
    if demo.mode == "experience":
        return {"status": "saved"}

    # Convert React Flow nodes → DemoNodes (skip group/sticky/annotation-type nodes)
    demo.nodes = []
    demo.groups = []
    demo.sticky_notes = []
    demo.clusters = []
    for rf_node in req.nodes:
        # Annotation and schematic nodes are preserved from the template, not from the frontend
        if rf_node.get("type") in ("annotation", "schematic"):
            continue

        # Sticky note nodes are stored separately
        if rf_node.get("type") == "sticky":
            s_data = rf_node.get("data", {})
            from ..models.demo import DemoStickyNote
            demo.sticky_notes.append(DemoStickyNote(
                id=rf_node["id"],
                text=s_data.get("text", ""),
                color=s_data.get("color", "#eab308"),
                position=NodePosition(x=rf_node.get("position", {}).get("x", 0),
                                       y=rf_node.get("position", {}).get("y", 0)),
                width=rf_node.get("style", {}).get("width", rf_node.get("width", 200)) if isinstance(rf_node.get("style"), dict) else rf_node.get("width", 200),
                height=rf_node.get("style", {}).get("height", rf_node.get("height", 120)) if isinstance(rf_node.get("style"), dict) else rf_node.get("height", 120),
            ))
            continue

        # Group nodes are stored separately
        if rf_node.get("type") == "group":
            grp_data = rf_node.get("data", {})
            demo.groups.append(DemoGroup(
                id=rf_node["id"],
                label=grp_data.get("label", ""),
                description=grp_data.get("description", ""),
                color=grp_data.get("color", "#3b82f6"),
                style=grp_data.get("style", "solid"),
                position=NodePosition(x=rf_node.get("position", {}).get("x", 0),
                                       y=rf_node.get("position", {}).get("y", 0)),
                width=rf_node.get("style", {}).get("width", rf_node.get("width", 400)) if isinstance(rf_node.get("style"), dict) else rf_node.get("width", 400),
                height=rf_node.get("style", {}).get("height", rf_node.get("height", 300)) if isinstance(rf_node.get("style"), dict) else rf_node.get("height", 300),
                mode=grp_data.get("mode", "visual"),
                cluster_config=grp_data.get("cluster_config", {}),
            ))
            continue

        # Cluster nodes are stored separately
        if rf_node.get("type") == "cluster":
            c_data = rf_node.get("data", {})
            demo.clusters.append(DemoCluster(
                id=rf_node["id"],
                component=c_data.get("componentId", "minio"),
                label=c_data.get("label", "MinIO Cluster"),
                position=NodePosition(x=rf_node.get("position", {}).get("x", 0),
                                       y=rf_node.get("position", {}).get("y", 0)),
                node_count=c_data.get("nodeCount", 4),
                drives_per_node=c_data.get("drivesPerNode", 1),
                credentials=c_data.get("credentials", {}),
                config=c_data.get("config", {}),
                width=rf_node.get("style", {}).get("width", rf_node.get("width", 280)) if isinstance(rf_node.get("style"), dict) else rf_node.get("width", 280),
                height=rf_node.get("style", {}).get("height", rf_node.get("height", 200)) if isinstance(rf_node.get("style"), dict) else rf_node.get("height", 200),
                mcp_enabled=c_data.get("mcpEnabled", True),
                aistor_tables_enabled=c_data.get("aistorTablesEnabled", False),
                ec_parity=c_data.get("ecParity", 4),
                ec_parity_upgrade_policy=c_data.get("ecParityUpgradePolicy", "upgrade"),
                disk_size_tb=c_data.get("diskSizeTb", 8),
            ))
            continue

        data = rf_node.get("data", {})
        # Preserve networks config from React Flow node data
        raw_networks = data.get("networks", {})
        networks = {}
        for net_name, net_cfg in raw_networks.items():
            if isinstance(net_cfg, dict):
                from ..models.demo import NodeNetworkConfig
                networks[net_name] = NodeNetworkConfig(**net_cfg)
            else:
                networks[net_name] = net_cfg
        demo.nodes.append(DemoNode(
            id=rf_node["id"],
            component=data.get("componentId", ""),
            variant=data.get("variant", "single"),
            position=NodePosition(x=rf_node.get("position", {}).get("x", 0),
                                   y=rf_node.get("position", {}).get("y", 0)),
            config=data.get("config", {}),
            networks=networks,
            display_name=data.get("displayName", ""),
            labels=data.get("labels", {}),
            group_id=data.get("groupId") or rf_node.get("parentId"),
        ))

    demo.edges = []
    for rf_edge in req.edges:
        # Skip annotation pointer edges — they're generated from annotations
        if rf_edge.get("type") == "annotation-pointer":
            continue
        edge_data = rf_edge.get("data", {})
        demo.edges.append(DemoEdge(
            id=rf_edge["id"],
            source=rf_edge["source"],
            target=rf_edge["target"],
            connection_type=edge_data.get("connectionType", "data"),
            network=edge_data.get("network", "default"),
            connection_config=edge_data.get("connectionConfig", {}),
            auto_configure=edge_data.get("autoConfigure", True),
            label=edge_data.get("label", rf_edge.get("label", "")),
            protocol=edge_data.get("protocol", ""),
            latency=edge_data.get("latency", ""),
            bandwidth=edge_data.get("bandwidth", ""),
            source_handle=rf_edge.get("sourceHandle"),
            target_handle=rf_edge.get("targetHandle"),
        ))

    _save_demo(demo)
    return {"status": "saved"}

@router.put("/api/demos/{demo_id}/layout")
async def save_layout(demo_id: str, req: dict):
    """Save node positions without changing structure. Used by Experience mode."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    positions = {p["id"]: (p["x"], p["y"]) for p in req.get("positions", [])}

    for node in demo.nodes:
        if node.id in positions:
            node.position.x, node.position.y = positions[node.id]

    for ann in getattr(demo, "annotations", []):
        if ann.id in positions:
            ann.position.x, ann.position.y = positions[ann.id]

    for cluster in demo.clusters:
        if cluster.id in positions:
            cluster.position.x, cluster.position.y = positions[cluster.id]

    for group in demo.groups:
        if group.id in positions:
            group.position.x, group.position.y = positions[group.id]

    for sch in getattr(demo, "schematics", []):
        if sch.id in positions:
            sch.position.x, sch.position.y = positions[sch.id]

    _save_demo(demo)
    return {"status": "saved", "positions_updated": len(positions)}


@router.get("/api/demos/{demo_id}/walkthrough")
async def get_walkthrough(demo_id: str):
    """Get walkthrough steps for a demo (from its template metadata if available)."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    # Try to find the template this demo was created from
    templates_dir = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")
    walkthrough = []

    # Check all templates for matching name/description
    if os.path.isdir(templates_dir):
        for fname in os.listdir(templates_dir):
            if not fname.endswith(".yaml"):
                continue
            try:
                with open(os.path.join(templates_dir, fname)) as f:
                    raw = yaml.safe_load(f)
                template_meta = raw.get("_template", {})
                template_name = raw.get("name", "")
                # Match by name (demos created from templates keep the template name)
                if template_name and template_name == demo.name:
                    walkthrough = template_meta.get("walkthrough", [])
                    break
            except Exception:
                continue

    return {"demo_id": demo_id, "walkthrough": walkthrough}


@router.get("/api/demos/{demo_id}/export")
async def export_demo(demo_id: str):
    """Export a demo as a downloadable YAML file."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    yaml_content = yaml.dump(demo.model_dump(), default_flow_style=False, sort_keys=False)

    filename = f"{demo.name.replace(' ', '-').lower()}-{demo.id}.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/api/demos/import")
async def import_demo(file: UploadFile):
    """Import a demo from a YAML file."""
    content = await file.read()
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Invalid YAML: {e}")

    # Generate a new ID to avoid conflicts
    new_id = str(uuid.uuid4())[:8]
    data["id"] = new_id

    # If name exists, add "(imported)" suffix to distinguish
    if "name" in data:
        data["name"] = data["name"] + " (imported)"

    # Validate and save
    try:
        demo = DemoDefinition(**data)
    except Exception as e:
        raise HTTPException(400, f"Invalid demo format: {e}")

    _save_demo(demo)
    return {"id": new_id, "name": demo.name, "status": "stopped"}


@router.delete("/api/demos/{demo_id}")
async def delete_demo(demo_id: str, destroy_containers: bool = False, remove_images: bool = False, force: bool = False):
    """Delete a demo. Optionally destroy running containers and/or remove images.

    Returns 409 if the demo is running unless ?force=true is passed, which stops it first.
    """
    from ..engine.docker_manager import stop_demo
    import docker as docker_lib

    running = state.get_demo(demo_id)

    # Safety check: refuse deletion of a running demo unless force=true
    if running and running.status == "running":
        if not force:
            raise HTTPException(409, "Demo is running. Stop it first before deleting.")
        # force=true: stop the demo first
        await stop_demo(demo_id)
        running = None

    # Stop containers if requested (or if running)
    if destroy_containers and running:
        await stop_demo(demo_id)

    # Remove pulled images for this demo's components
    if remove_images:
        try:
            client = docker_lib.from_env()
            images = client.images.list(filters={"label": f"demoforge.demo={demo_id}"})
            for img in images:
                try:
                    client.images.remove(img.id, force=True)
                except Exception:
                    pass
            # Also remove images used by this demo's components
            demo = _load_demo(demo_id)
            if demo:
                from ..registry.loader import get_component
                for node in demo.nodes:
                    manifest = get_component(node.component)
                    if manifest and manifest.image:
                        try:
                            client.images.remove(manifest.image, force=True)
                        except Exception:
                            pass
        except Exception:
            pass

    # Delete the config file
    path = os.path.join(DEMOS_DIR, f"{demo_id}.yaml")
    if os.path.exists(path):
        os.remove(path)

    # Clean up any generated compose files
    data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
    compose_path = os.path.join(data_dir, demo_id, "docker-compose.yaml")
    if os.path.exists(compose_path):
        import shutil
        shutil.rmtree(os.path.join(data_dir, demo_id), ignore_errors=True)

    return {"status": "deleted"}

@router.get("/api/demos/{demo_id}/generated-config")
async def get_generated_config(demo_id: str):
    """Return all generated config files for a demo."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
    project_name = f"demoforge-{demo_id}"

    configs = {}

    # Compose file
    compose_path = os.path.join(data_dir, f"{project_name}.yml")
    if os.path.isfile(compose_path):
        with open(compose_path) as f:
            configs["docker-compose.yml"] = f.read()

    # Generated config files in the data directory
    demo_data_dir = os.path.join(data_dir, project_name)
    if os.path.isdir(demo_data_dir):
        for root, dirs, files in os.walk(demo_data_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                relpath = os.path.relpath(fpath, demo_data_dir)
                try:
                    with open(fpath) as f:
                        configs[relpath] = f.read()
                except Exception:
                    pass

    return {"demo_id": demo_id, "configs": configs}


@router.get("/api/inventory")
async def get_inventory():
    """Return all DemoForge-managed containers and images."""
    import docker as docker_lib
    try:
        client = docker_lib.from_env()
    except Exception as e:
        return {"containers": [], "images": [], "error": str(e)}

    # Find all containers with demoforge labels
    containers = []
    try:
        for c in client.containers.list(all=True, filters={"label": "demoforge.demo"}):
            containers.append({
                "id": c.short_id,
                "name": c.name,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "status": c.status,
                "demo_id": c.labels.get("demoforge.demo", ""),
                "node_id": c.labels.get("demoforge.node", ""),
                "component": c.labels.get("demoforge.component", ""),
                "created": c.attrs.get("Created", ""),
            })
    except Exception:
        pass

    # Find images used by demos
    images = []
    try:
        for img in client.images.list():
            tags = img.tags
            if not tags:
                continue
            # Check if any demo uses this image
            images.append({
                "id": img.short_id,
                "tags": tags,
                "size_mb": round(img.attrs.get("Size", 0) / 1024 / 1024, 1),
                "created": img.attrs.get("Created", ""),
            })
    except Exception:
        pass

    return {"containers": containers, "images": images}

