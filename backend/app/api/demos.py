import os
import uuid
import yaml
from fastapi import APIRouter, HTTPException
from ..models.demo import DemoDefinition, DemoNetwork, DemoNode, DemoEdge, NodePosition
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
                    ))
    return DemoListResponse(demos=demos)

@router.post("/api/demos", response_model=DemoSummary)
async def create_demo(req: CreateDemoRequest):
    demo_id = str(uuid.uuid4())[:8]
    demo = DemoDefinition(
        id=demo_id,
        name=req.name,
        description=req.description,
        network=DemoNetwork(name=f"demoforge-{demo_id}-net"),
    )
    _save_demo(demo)
    return DemoSummary(id=demo.id, name=demo.name, description=demo.description, node_count=0, status="stopped")

@router.get("/api/demos/{demo_id}")
async def get_demo(demo_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    return demo.model_dump()

@router.put("/api/demos/{demo_id}/diagram")
async def save_diagram(demo_id: str, req: SaveDiagramRequest):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    # Convert React Flow nodes → DemoNodes
    demo.nodes = []
    for rf_node in req.nodes:
        data = rf_node.get("data", {})
        demo.nodes.append(DemoNode(
            id=rf_node["id"],
            component=data.get("componentId", ""),
            variant=data.get("variant", "single"),
            position=NodePosition(x=rf_node.get("position", {}).get("x", 0),
                                   y=rf_node.get("position", {}).get("y", 0)),
            config=data.get("config", {}),
        ))

    demo.edges = []
    for rf_edge in req.edges:
        demo.edges.append(DemoEdge(
            id=rf_edge["id"],
            source=rf_edge["source"],
            target=rf_edge["target"],
            label=rf_edge.get("label", ""),
        ))

    _save_demo(demo)
    return {"status": "saved"}

@router.delete("/api/demos/{demo_id}")
async def delete_demo(demo_id: str):
    path = os.path.join(DEMOS_DIR, f"{demo_id}.yaml")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "deleted"}
