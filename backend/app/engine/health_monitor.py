"""Background task that polls container health and reconciles state every 5 seconds."""
import asyncio
import json
import logging
import time
import urllib.request
from ..state.store import state
from .docker_manager import get_container_health
from ..models.api_models import ContainerHealthStatus

logger = logging.getLogger(__name__)

# Cache: "{demo_id}:{node_id}" → (checked_at, has_tables)
_trino_table_cache: dict = {}
_TRINO_CHECK_INTERVAL = 15  # seconds between Trino table checks


def _trino_has_user_tables(container_name: str) -> bool:
    """Check whether Trino has any user-created schemas/tables.

    Returns True if at least one user schema exists in a non-system catalog.
    Returns True on any network/timeout error to avoid false-degraded state.
    """
    system_catalogs = {"system", "tpch", "tpcds", "jmx", "memory"}

    def _query(host: str, sql: str, catalog: str | None = None) -> list:
        headers = {"X-Trino-User": "healthcheck", "Content-Type": "text/plain"}
        if catalog:
            headers["X-Trino-Catalog"] = catalog
        req = urllib.request.Request(
            f"http://{host}:8080/v1/statement",
            data=sql.encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
        rows = list(data.get("data") or [])
        next_uri = data.get("nextUri")
        if next_uri:
            with urllib.request.urlopen(
                urllib.request.Request(next_uri, headers={"X-Trino-User": "healthcheck"}),
                timeout=4,
            ) as resp2:
                data2 = json.loads(resp2.read())
            rows += list(data2.get("data") or [])
        return rows

    try:
        host = container_name
        catalog_rows = _query(host, "SHOW CATALOGS")
        user_catalogs = [r[0] for r in catalog_rows if r[0] not in system_catalogs]
        if not user_catalogs:
            return False
        for catalog in user_catalogs[:3]:
            try:
                schema_rows = _query(host, "SHOW SCHEMAS", catalog=catalog)
                user_schemas = [r[0] for r in schema_rows if r[0] != "information_schema"]
                if user_schemas:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return True  # Don't degrade on network/timeout errors


async def health_monitor_loop():
    """Run forever, updating container health and reconciling state."""
    while True:
        try:
            for demo in state.list_demos():
                # Stuck "stopping" (task missed, UI out of sync, or manual docker stop): if every
                # tracked container is stopped/not found, align status to stopped.
                if demo.status == "stopping":
                    if not demo.containers:
                        logger.info(
                            "Health reconciler: demo %s was stopping with no tracked containers — marking stopped",
                            demo.demo_id,
                        )
                        demo.status = "stopped"
                        continue
                    all_stopped_s = True
                    for node_id, container in demo.containers.items():
                        health = await get_container_health(container.container_name)
                        container.health = health
                        if health != ContainerHealthStatus.STOPPED:
                            all_stopped_s = False
                    if all_stopped_s:
                        logger.info(
                            "Health reconciler: demo %s was stopping and all containers are stopped — marking stopped",
                            demo.demo_id,
                        )
                        demo.status = "stopped"
                    continue

                if demo.status not in ("running", "error"):
                    continue

                all_stopped = True

                for node_id, container in demo.containers.items():
                    health = await get_container_health(container.container_name)

                    # For Trino nodes that are healthy, check if user tables exist
                    if health == ContainerHealthStatus.HEALTHY and "trino" in node_id:
                        cache_key = f"{demo.demo_id}:{node_id}"
                        now = time.monotonic()
                        cached = _trino_table_cache.get(cache_key)
                        if cached is None or (now - cached[0]) > _TRINO_CHECK_INTERVAL:
                            has_tables = await asyncio.to_thread(
                                _trino_has_user_tables, container.container_name
                            )
                            _trino_table_cache[cache_key] = (now, has_tables)
                        else:
                            has_tables = cached[1]

                        if not has_tables:
                            health = ContainerHealthStatus.DEGRADED

                    container.health = health
                    if health != ContainerHealthStatus.STOPPED:
                        all_stopped = False

                # If all containers are stopped, mark demo as stopped
                if demo.status == "running" and demo.containers and all_stopped:
                    logger.warning(
                        f"Health reconciler: all containers for demo {demo.demo_id} are stopped — marking demo stopped"
                    )
                    demo.status = "stopped"

        except Exception as e:
            logger.warning(f"Health monitor error: {e}")

        await asyncio.sleep(5)
