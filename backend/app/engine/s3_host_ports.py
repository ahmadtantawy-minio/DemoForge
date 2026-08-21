"""Host port allocation for MinIO cluster S3 API (localhost access from the PC)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml

from ..models.demo import DemoCluster, DemoDefinition

logger = logging.getLogger(__name__)

_DEFAULT_RANGE = "19000-19999"
_CONFIG_KEY = "S3_HOST_PORT"


def parse_port_range(raw: str | None = None) -> tuple[int, int]:
    """Parse ``19000-19999`` (inclusive)."""
    text = (raw or os.environ.get("DEMOFORGE_S3_HOST_PORT_RANGE") or _DEFAULT_RANGE).strip()
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if not m:
        raise ValueError(
            f"Invalid DEMOFORGE_S3_HOST_PORT_RANGE {text!r} (expected e.g. 19000-19999)"
        )
    start, end = int(m.group(1)), int(m.group(2))
    if start > end or start < 1 or end > 65535:
        raise ValueError(f"Invalid S3 host port range {start}-{end}")
    return start, end


def _demos_dir() -> Path:
    return Path(os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos"))


def _load_demo_yaml(demo_id: str) -> DemoDefinition | None:
    path = _demos_dir() / f"{demo_id}.yaml"
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            raw = yaml.safe_load(f)
        if not raw:
            return None
        return DemoDefinition(**raw)
    except Exception as exc:
        logger.warning("Failed to load demo %s for S3 port scan: %s", demo_id, exc)
        return None


def collect_s3_host_port_claims(
    *,
    exclude_demo_id: str | None = None,
) -> dict[int, tuple[str, str]]:
    """Map host port → (demo_id, cluster_id) from saved demo YAML."""
    claims: dict[int, tuple[str, str]] = {}
    demos_dir = _demos_dir()
    if not demos_dir.is_dir():
        return claims
    for path in demos_dir.glob("*.yaml"):
        demo_id = path.stem
        if demo_id == exclude_demo_id:
            continue
        demo = _load_demo_yaml(demo_id)
        if not demo:
            continue
        for cluster in demo.clusters or []:
            if cluster.component != "minio":
                continue
            raw = (cluster.config or {}).get(_CONFIG_KEY, "").strip()
            if not raw:
                continue
            try:
                port = int(raw)
            except ValueError:
                continue
            claims[port] = (demo_id, cluster.id)
    return claims


def assign_minio_cluster_s3_host_ports(demo: DemoDefinition) -> None:
    """Ensure each MinIO cluster on *demo* has a unique ``S3_HOST_PORT`` in config."""
    start, end = parse_port_range()
    claims = collect_s3_host_port_claims(exclude_demo_id=demo.id)

    for cluster in demo.clusters or []:
        if cluster.component != "minio":
            continue
        cluster.config = dict(cluster.config or {})
        existing = cluster.config.get(_CONFIG_KEY, "").strip()
        if existing:
            try:
                port = int(existing)
            except ValueError:
                port = 0
            owner = claims.get(port)
            if port and start <= port <= end and (
                owner is None or owner == (demo.id, cluster.id)
            ):
                claims[port] = (demo.id, cluster.id)
                cluster.config[_CONFIG_KEY] = str(port)
                continue
            logger.warning(
                "Demo %s cluster %s: S3_HOST_PORT %s unavailable; reassigning",
                demo.id,
                cluster.id,
                existing,
            )

        port = _next_free_port(start, end, claims)
        cluster.config[_CONFIG_KEY] = str(port)
        claims[port] = (demo.id, cluster.id)


def _next_free_port(
    start: int, end: int, claims: dict[int, tuple[str, str]]
) -> int:
    for port in range(start, end + 1):
        if port not in claims:
            return port
    raise RuntimeError(
        f"No free S3 host ports in range {start}-{end} "
        f"({len(claims)} already assigned across demos)"
    )


def persist_cluster_s3_host_ports(demo_id: str, clusters: list[DemoCluster]) -> None:
    """Write ``S3_HOST_PORT`` from compose expansion back to the saved demo YAML."""
    saved = _load_demo_yaml(demo_id)
    if not saved:
        return
    by_id = {c.id: c for c in clusters if c.component == "minio"}
    changed = False
    for cluster in saved.clusters or []:
        src = by_id.get(cluster.id)
        if not src:
            continue
        port = (src.config or {}).get(_CONFIG_KEY)
        if not port:
            continue
        cluster.config = dict(cluster.config or {})
        if cluster.config.get(_CONFIG_KEY) != port:
            cluster.config[_CONFIG_KEY] = port
            changed = True
    if not changed:
        return
    path = _demos_dir() / f"{demo_id}.yaml"
    with path.open("w") as f:
        yaml.dump(saved.model_dump(), f, default_flow_style=False, sort_keys=False)


def cluster_id_for_lb_node(node_id: str) -> str | None:
    if node_id.endswith("-lb"):
        return node_id[: -len("-lb")]
    return None


def s3_host_port_for_cluster(cluster: DemoCluster) -> int | None:
    raw = (cluster.config or {}).get(_CONFIG_KEY, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def localhost_s3_url(host_port: int) -> str:
    return f"http://localhost:{host_port}"
