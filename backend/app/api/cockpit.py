"""Cockpit API — real-time bucket stats and throughput for running demos."""
import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..engine.docker_manager import exec_in_container

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/demos/{demo_id}/cockpit")
async def get_cockpit_data(demo_id: str):
    """Return real-time bucket stats and throughput for all clusters in a demo.

    Uses the mc-shell container to query each cluster's LB.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    mc_shell = f"demoforge-{demo_id}-mc-shell"

    # Check if mc-shell container exists
    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found — redeploy the demo")

    # Gather bucket stats and throughput for each cluster alias
    # First, list configured aliases
    try:
        exit_code, stdout, _ = await exec_in_container(
            mc_shell, "mc alias list --json"
        )
    except Exception:
        return {"demo_id": demo_id, "clusters": [], "error": "mc-shell not reachable"}

    # Parse aliases — each line is a JSON object
    aliases = []
    if exit_code == 0:
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # Skip built-in aliases and temporary automation aliases
                alias_name = obj.get("alias", "")
                url = obj.get("URL", "")
                skip_aliases = {"play", "local", "gcs", "s3", "site1", "site2", "hot", "cold", "source", "target"}
                if alias_name and "demoforge" in url and alias_name not in skip_aliases:
                    aliases.append(alias_name)
            except json.JSONDecodeError:
                continue

    # For each alias, get bucket stats and throughput in parallel
    async def get_cluster_stats(alias: str) -> dict:
        result = {"alias": alias, "buckets": [], "throughput": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0}}

        # Get bucket list with object counts
        try:
            exit_code, stdout, _ = await exec_in_container(
                mc_shell,
                f"mc ls {alias} --json"
            )
            if exit_code == 0:
                for line in stdout.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "folder":
                            bucket_name = obj.get("key", "").rstrip("/")
                            if bucket_name:
                                # Count objects via mc ls --json (count lines)
                                ec2, out2, _ = await exec_in_container(
                                    mc_shell,
                                    f"sh -c 'mc ls {alias}/{bucket_name}/ --json 2>/dev/null | wc -l'"
                                )
                                obj_count = 0
                                total_size = 0
                                if ec2 == 0 and out2.strip():
                                    try:
                                        obj_count = int(out2.strip())
                                    except ValueError:
                                        pass
                                # Get size via mc du
                                ec3, out3, _ = await exec_in_container(
                                    mc_shell,
                                    f"sh -c 'mc du {alias}/{bucket_name} --json 2>/dev/null'"
                                )
                                if ec3 == 0 and out3.strip():
                                    try:
                                        du = json.loads(out3.strip().split("\n")[-1])
                                        total_size = du.get("size", 0)
                                    except (json.JSONDecodeError, IndexError):
                                        pass
                                result["buckets"].append({
                                    "name": bucket_name,
                                    "objects": obj_count,
                                    "size": total_size,
                                })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to get bucket stats for {alias}: {e}")

        # Get throughput from Prometheus metrics endpoint
        try:
            exit_code, stdout, _ = await exec_in_container(
                mc_shell,
                f"sh -c 'mc admin prometheus metrics {alias} --type node 2>/dev/null | grep -E \"minio_node_io_r_bytes_total|minio_node_io_w_bytes_total\" | head -4'"
            )
            # Parse simple prometheus text format for total bytes
            # We just report the totals — the frontend can compute deltas
            rx_total = 0
            tx_total = 0
            if exit_code == 0:
                for line in stdout.strip().split("\n"):
                    if line.startswith("minio_node_io_r_bytes_total"):
                        try:
                            rx_total = int(float(line.split()[-1]))
                        except (ValueError, IndexError):
                            pass
                    elif line.startswith("minio_node_io_w_bytes_total"):
                        try:
                            tx_total = int(float(line.split()[-1]))
                        except (ValueError, IndexError):
                            pass
            result["throughput"]["rx_bytes_total"] = rx_total
            result["throughput"]["tx_bytes_total"] = tx_total
        except Exception as e:
            logger.warning(f"Failed to get throughput for {alias}: {e}")

        return result

    # Run all cluster stats in parallel
    tasks = [get_cluster_stats(alias) for alias in aliases]
    cluster_results = await asyncio.gather(*tasks, return_exceptions=True)

    clusters = []
    for r in cluster_results:
        if isinstance(r, Exception):
            logger.warning(f"Cockpit error: {r}")
        elif isinstance(r, dict):
            clusters.append(r)

    return {"demo_id": demo_id, "clusters": clusters}
