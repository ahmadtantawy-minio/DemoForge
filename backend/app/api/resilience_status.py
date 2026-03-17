"""Resilience tester status: reads the latest probe result from the container log."""
import re
import logging
import docker
from fastapi import APIRouter, HTTPException
from ..state.store import state

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/demos/{demo_id}/resilience-status")
async def get_resilience_status(demo_id: str):
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Get failover info to resolve which cluster is responding
    from .failover_status import get_failover_status as _get_fs
    try:
        fs = await _get_fs(demo_id)
        failover_map = {f["gateway"]: f["active_upstream"] for f in fs.get("failover", []) if f.get("healthy")}
    except Exception:
        failover_map = {}

    results = []
    for node_id, container in running.containers.items():
        if container.component_id != "resilience-tester":
            continue

        container_name = container.container_name
        last_line = ""
        try:
            client = docker.from_env()
            c = client.containers.get(container_name)
            raw = c.logs(stdout=True, stderr=False, tail=10).decode("utf-8", errors="replace")
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            probe_lines = [l for l in lines if l.startswith("[OK]") or l.startswith("[FAIL]")]
            if probe_lines:
                last_line = probe_lines[-1]
        except Exception as e:
            logger.debug(f"Could not read logs for {container_name}: {e}")

        parsed = _parse_probe_line(last_line)

        # Find which cluster is responding by looking at the failover gateway
        # The tester targets a gateway node — find what upstream that gateway routes to
        upstream = ""
        demo_def = _load_demo_def(demo_id)
        if demo_def:
            # Find edges from this tester to find its target (the gateway)
            target_gateway = None
            for edge in demo_def.get("edges", []):
                if edge.get("source") == node_id:
                    target_gateway = edge.get("target")
                    break
            if target_gateway and target_gateway in failover_map:
                raw_upstream = failover_map[target_gateway]
                # Resolve node_id to a human-readable cluster label
                upstream = _resolve_to_cluster_label(raw_upstream, demo_def)

        parsed["upstream"] = upstream
        results.append({
            "node_id": node_id,
            "last_line": last_line,
            **parsed,
        })

    return {"demo_id": demo_id, "probes": results}


def _load_demo_def(demo_id: str) -> dict | None:
    """Load the demo YAML definition as a dict."""
    import os, yaml
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    path = os.path.join(demos_dir, f"{demo_id}.yaml")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _resolve_to_cluster_label(node_id: str, demo_def: dict) -> str:
    """Resolve a node_id (e.g. 'minio-site-a-node-1') to cluster label (e.g. 'Site A')."""
    # Check clusters first — node_id may contain the cluster id
    for cluster in demo_def.get("clusters", []):
        if node_id.startswith(cluster["id"]):
            return cluster.get("label", cluster["id"])
    # Check standalone nodes
    for node in demo_def.get("nodes", []):
        if node["id"] == node_id:
            return node.get("display_name", node.get("label", node["id"]))
    # Fallback: strip common prefixes to make it readable
    return node_id


def _parse_probe_line(line: str) -> dict:
    if not line:
        return {"status": "unknown", "seq": None, "write_ms": None, "read_ms": None, "objects": None}

    status = "ok" if line.startswith("[OK]") else "fail"
    result: dict = {"status": status, "seq": None, "write_ms": None, "read_ms": None, "objects": None}

    m = re.search(r"#(\d+)", line)
    if m:
        result["seq"] = int(m.group(1))

    m = re.search(r"Write:\s*(\d+)ms", line)
    if m:
        result["write_ms"] = int(m.group(1))

    m = re.search(r"Read:\s*(\d+)ms", line)
    if m:
        result["read_ms"] = int(m.group(1))

    m = re.search(r"Objects:\s*(\d+)", line)
    if m:
        result["objects"] = int(m.group(1))

    return result
