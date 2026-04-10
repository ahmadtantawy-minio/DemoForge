"""Cockpit API — real-time bucket stats and throughput for running demos."""
import asyncio
import json
import logging
import time
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..engine.docker_manager import exec_in_container, docker_client

logger = logging.getLogger(__name__)
router = APIRouter()

# Cache for host stats: {demo_id: (timestamp, result)}
_host_stats_cache: dict[str, tuple[float, dict]] = {}
_HOST_STATS_TTL = 5.0  # seconds

# In-memory cache for prometheus counter snapshots: {(demo_id, alias): (timestamp, counters_dict)}
_prom_snapshot: dict[tuple[str, str], tuple[float, dict]] = {}


async def _get_throughput_from_prometheus(mc_shell: str, alias: str, demo_id: str) -> dict:
    """Try mc admin prometheus metrics for s3 request rates.

    Parses Prometheus text-format counters and computes per-second rates by
    diffing against the previous snapshot stored in _prom_snapshot.
    """
    try:
        exit_code, stdout, _ = await exec_in_container(
            mc_shell, f"mc admin prometheus metrics {alias} 2>/dev/null | head -200"
        )
        if exit_code != 0 or not stdout.strip():
            return {}

        put_total = 0.0
        get_total = 0.0
        sent_bytes = 0.0
        recv_bytes = 0.0

        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            metric_def = parts[0].lower()
            try:
                val = float(parts[1])
            except ValueError:
                continue

            if "s3_requests_total" in metric_def:
                if "putobject" in metric_def or '"put"' in metric_def:
                    put_total += val
                elif "getobject" in metric_def or '"get"' in metric_def:
                    get_total += val
            elif "s3_traffic_sent_bytes" in metric_def or "traffic_sent" in metric_def:
                sent_bytes += val
            elif "s3_traffic_received_bytes" in metric_def or "traffic_recv" in metric_def:
                recv_bytes += val

        now = time.monotonic()
        key = (demo_id, alias)
        prev = _prom_snapshot.get(key)
        _prom_snapshot[key] = (now, {"put": put_total, "get": get_total, "sent": sent_bytes, "recv": recv_bytes})

        if prev:
            dt = now - prev[0]
            if 0 < dt < 60:
                prev_data = prev[1]
                put_rate = max(0.0, (put_total - prev_data["put"]) / dt)
                get_rate = max(0.0, (get_total - prev_data["get"]) / dt)
                tx_rate = max(0.0, (sent_bytes - prev_data["sent"]) / dt)
                rx_rate = max(0.0, (recv_bytes - prev_data["recv"]) / dt)
                return {
                    "put_ops_per_sec": round(put_rate, 2),
                    "get_ops_per_sec": round(get_rate, 2),
                    "rx_bytes_per_sec": rx_rate,
                    "tx_bytes_per_sec": tx_rate,
                }
    except Exception as e:
        logger.debug(f"Prometheus metrics failed for {alias}: {e}")
    return {}


async def _get_host_stats(demo_id: str) -> dict:
    """Return aggregated CPU% and memory usage for all demo containers.

    Cached for 5 seconds to avoid hammering Docker stats API.
    """
    now = time.monotonic()
    cached = _host_stats_cache.get(demo_id)
    if cached and (now - cached[0]) < _HOST_STATS_TTL:
        return cached[1]

    def _get_containers():
        return docker_client.containers.list(
            filters={"label": f"demoforge.demo={demo_id}"}
        )

    def _stats_for(c):
        try:
            s = c.stats(stream=False)
            cpu_delta = (
                s["cpu_stats"]["cpu_usage"]["total_usage"]
                - s["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                s["cpu_stats"].get("system_cpu_usage", 0)
                - s["precpu_stats"].get("system_cpu_usage", 0)
            )
            num_cpus = s["cpu_stats"].get("online_cpus") or len(
                s["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
            )
            cpu_pct = (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 and cpu_delta >= 0 else 0.0
            mem = s.get("memory_stats", {})
            return {"cpu": cpu_pct, "mem": mem.get("usage", 0), "limit": mem.get("limit", 0)}
        except Exception:
            return None

    try:
        containers = await asyncio.to_thread(_get_containers)
        # Fetch stats for all containers in parallel (each stats call blocks ~1s)
        stats_list = await asyncio.gather(
            *[asyncio.to_thread(_stats_for, c) for c in containers],
            return_exceptions=True,
        )
        total_cpu = 0.0
        total_mem_bytes = 0
        mem_limit_bytes = 0
        count = 0
        for s in stats_list:
            if isinstance(s, dict):
                total_cpu += s["cpu"]
                total_mem_bytes += s["mem"]
                mem_limit_bytes = max(mem_limit_bytes, s["limit"])
                count += 1
        result = {
            "cpu_percent": round(total_cpu, 1),
            "memory_mb": round(total_mem_bytes / 1024 / 1024, 1),
            "memory_limit_mb": round(mem_limit_bytes / 1024 / 1024, 1),
            "container_count": count,
        }
    except Exception as e:
        logger.warning(f"Failed to collect host stats for {demo_id}: {e}")
        result = {"cpu_percent": 0.0, "memory_mb": 0.0, "memory_limit_mb": 0.0, "container_count": 0}

    _host_stats_cache[demo_id] = (now, result)
    return result


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
        return {"demo_id": demo_id, "clusters": [], "error": "mc-shell container not found — redeploy the demo to enable cockpit"}

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
                skip_aliases = {"play", "local", "gcs", "s3"}
                if alias_name and "demoforge" in url and alias_name not in skip_aliases:
                    aliases.append(alias_name)
            except json.JSONDecodeError:
                continue

    # For each alias, get bucket stats and throughput in parallel
    async def get_cluster_stats(alias: str) -> dict:
        result = {"alias": alias, "buckets": [], "throughput": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0}}

        # Single batched exec: list buckets + count objects + get sizes in one shell script
        # Uses text mc ls (not JSON) for bucket names, then batches counts
        batch_script = (
            f'for b in $(mc ls {alias} 2>/dev/null | tr -s " " | cut -d" " -f5 | tr -d "/"); do '
            f'[ -z "$b" ] && continue; '
            f'count=$(mc ls --recursive {alias}/$b/ --json 2>/dev/null | wc -l); '
            f'size=$(mc du {alias}/$b --json 2>/dev/null | tail -1); '
            f'echo "BUCKET:$b:$count:$size"; '
            f'done'
        )
        try:
            exit_code, stdout, _ = await exec_in_container(
                mc_shell, f"sh -c '{batch_script}'"
            )
            if exit_code == 0:
                for line in stdout.strip().split("\n"):
                    if not line.startswith("BUCKET:"):
                        continue
                    parts = line.split(":", 3)
                    if len(parts) < 4:
                        continue
                    bucket_name = parts[1]
                    try:
                        obj_count = int(parts[2])
                    except ValueError:
                        obj_count = 0
                    total_size = 0
                    try:
                        du = json.loads(parts[3])
                        total_size = du.get("size", 0)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    result["buckets"].append({
                        "name": bucket_name,
                        "objects": obj_count,
                        "size": total_size,
                    })
        except Exception as e:
            logger.warning(f"Failed to get bucket stats for {alias}: {e}")

        # Get throughput via mc admin bandwidth --json (returns instantaneous rates)
        try:
            exit_code, stdout, _ = await exec_in_container(
                mc_shell,
                f"mc admin bandwidth {alias} --json 2>/dev/null"
            )
            rx_sum = 0.0
            tx_sum = 0.0
            if exit_code == 0 and stdout.strip():
                for line in stdout.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        # Response may be {"bandwidth": [...]} or a direct object per server
                        entries = obj.get("bandwidth") if isinstance(obj, dict) and "bandwidth" in obj else [obj]
                        for entry in (entries or []):
                            if isinstance(entry, dict):
                                rx_sum += entry.get("rx", 0) or 0
                                tx_sum += entry.get("tx", 0) or 0
                    except (json.JSONDecodeError, TypeError):
                        continue
            if rx_sum > 0 or tx_sum > 0:
                # bandwidth returns bytes/sec rates directly — expose them as-is
                result["throughput"]["rx_bytes_per_sec"] = rx_sum
                result["throughput"]["tx_bytes_per_sec"] = tx_sum
            else:
                logger.debug(f"mc admin bandwidth returned no data for {alias} (exit={exit_code})")
        except Exception as e:
            logger.warning(f"Failed to get throughput for {alias}: {e}")

        # If bandwidth gave no data, try prometheus metrics for ops/s rates
        if result["throughput"]["rx_bytes_per_sec"] == 0 and result["throughput"]["tx_bytes_per_sec"] == 0:
            prom = await _get_throughput_from_prometheus(mc_shell, alias, demo_id)
            if prom:
                result["throughput"].update(prom)

        return result

    # Run all cluster stats and host stats in parallel
    tasks = [get_cluster_stats(alias) for alias in aliases]
    cluster_results, host_stats = await asyncio.gather(
        asyncio.gather(*tasks, return_exceptions=True),
        _get_host_stats(demo_id),
    )

    clusters = []
    for alias, r in zip(aliases, cluster_results):
        if isinstance(r, Exception):
            logger.warning(f"Cockpit error for {alias}: {r}")
            clusters.append({"alias": alias, "buckets": [], "throughput": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0}})
        elif isinstance(r, dict):
            clusters.append(r)

    return {"demo_id": demo_id, "clusters": clusters, "host_stats": host_stats}


@router.get("/api/demos/{demo_id}/cockpit/health")
async def get_cockpit_health(demo_id: str):
    """Return mc admin info output for each cluster alias in the demo."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    if "mc-shell" not in running.containers:
        return {"demo_id": demo_id, "clusters": [], "error": "mc-shell not available"}

    mc_shell = f"demoforge-{demo_id}-mc-shell"

    # List configured aliases
    try:
        exit_code, stdout, _ = await exec_in_container(mc_shell, "mc alias list --json")
    except Exception:
        return {"demo_id": demo_id, "clusters": [], "error": "mc-shell not reachable"}

    aliases = []
    if exit_code == 0:
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                alias_name = obj.get("alias", "")
                url = obj.get("URL", "")
                skip_aliases = {"play", "local", "gcs", "s3"}
                if alias_name and "demoforge" in url and alias_name not in skip_aliases:
                    aliases.append(alias_name)
            except json.JSONDecodeError:
                continue

    async def get_admin_info(alias: str) -> dict:
        try:
            exit_code, stdout, _ = await exec_in_container(
                mc_shell, f"mc admin info {alias} --json"
            )
            if exit_code == 0 and stdout.strip():
                try:
                    raw = json.loads(stdout.strip())
                    # mc admin info --json wraps data under an "info" key;
                    # fall back to raw if the wrapper is absent.
                    info = raw.get("info", raw)
                    backend = info.get("backend") or {}
                    online = backend.get("onlineDisks", 0) or 0
                    offline = backend.get("offlineDisks", 0) or 0
                    total = online + offline
                    if total == 0:
                        status = "starting"
                    elif offline == 0:
                        status = "healthy"
                    else:
                        status = "degraded"
                    return {"alias": alias, "info": info, "status": status}
                except json.JSONDecodeError:
                    return {"alias": alias, "raw": stdout.strip(), "info": None, "status": "unreachable"}
            else:
                return {"alias": alias, "info": None, "status": "unreachable", "error": f"mc exit {exit_code}"}
        except Exception as e:
            logger.warning(f"mc admin info failed for {alias}: {e}")
        return {"alias": alias, "info": None, "status": "unreachable"}

    results = await asyncio.gather(*[get_admin_info(a) for a in aliases], return_exceptions=True)
    clusters = []
    for alias, r in zip(aliases, results):
        if isinstance(r, Exception):
            logger.warning(f"Health fetch error for {alias}: {r}")
            clusters.append({"alias": alias, "info": None, "status": "unreachable", "error": str(r)})
        elif isinstance(r, dict):
            clusters.append(r)
    return {"demo_id": demo_id, "clusters": clusters}
