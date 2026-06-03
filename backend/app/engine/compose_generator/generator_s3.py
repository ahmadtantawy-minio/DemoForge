"""S3 sink wiring for data-generator and external-system (compose env injection)."""

from __future__ import annotations

import json
import logging
from typing import Any

from ...models.demo import DemoDefinition, DemoNode
from .minio_s3_wiring import (
    buckets_from_edge_config,
    normalize_minio_peer_id,
    resolve_minio_s3_endpoint,
    s3_bucket_object_name,
)

logger = logging.getLogger(__name__)

_S3_EDGE_TYPES = ("s3", "structured-data", "file-push", "aistor-tables")
_EDGE_ENV_MAP = {
    "target_bucket": "S3_BUCKET",
    "bucket": "S3_BUCKET",
    "format": "DG_FORMAT",
    "rows_per_file": "DG_FILE_SIZE_ROWS",
    "rate": "DG_RATE",
    "scenario": "DG_SCENARIO",
    "rate_profile": "DG_RATE_PROFILE",
    "sink_bucket": "S3_BUCKET",
    "sink_format": "S3_SINK_FORMAT",
}


def apply_minio_compression_env_guard(env: dict[str, str], edition: str) -> None:
    """Strip server compression env unless AIStor — CE ignores unknown vars but keeps demos predictable."""
    if edition in ("aistor", "aistor-edge"):
        return
    for key in list(env.keys()):
        if key.startswith("MINIO_COMPRESSION_"):
            env.pop(key, None)


def _resolve_bucket(edge_cfg: dict[str, Any], node_config: dict[str, Any]) -> str:
    names = buckets_from_edge_config(edge_cfg, connection_type="s3")
    if names:
        return names[0]
    return s3_bucket_object_name(str(node_config.get("DG_DEFAULT_TARGET_BUCKET") or ""))


def _resolve_minio_peer(
    demo: DemoDefinition,
    peer_id: str,
    project_name: str,
) -> tuple[str, str, str, str] | None:
    """Return (endpoint_url, access_key, secret_key, service_peer_id) or None if not MinIO."""
    resolved = resolve_minio_s3_endpoint(demo, peer_id, project_name)
    if not resolved:
        return None
    endpoint_url, ak, sk = resolved
    return endpoint_url, ak, sk, normalize_minio_peer_id(demo, peer_id)


def collect_generator_s3_sinks(
    demo: DemoDefinition,
    node: DemoNode,
    project_name: str,
) -> list[dict[str, str]]:
    """Outgoing S3 edges from a generator node → sink descriptors for DG_S3_SINKS."""
    node_cfg = node.config or {}
    sinks: list[dict[str, str]] = []
    for edge in demo.edges:
        if edge.source != node.id or edge.connection_type not in _S3_EDGE_TYPES:
            continue
        peer = _resolve_minio_peer(demo, edge.target, project_name)
        if not peer:
            continue
        endpoint_url, ak, sk, peer_id = peer
        bucket = _resolve_bucket(edge.connection_config or {}, node_cfg)
        if not bucket:
            continue
        sinks.append(
            {
                "endpoint": endpoint_url,
                "bucket": bucket,
                "access_key": ak,
                "secret_key": sk,
                "peer_id": peer_id,
                "edge_id": edge.id,
            }
        )
    return sinks


def inject_generator_s3_from_edges(
    demo: DemoDefinition,
    node: DemoNode,
    env: dict[str, str],
    project_name: str,
) -> None:
    """Wire S3 endpoint(s) for data-generator / external-system from diagram edges."""
    node_cfg = node.config or {}
    parquet_compression = str(node_cfg.get("DG_PARQUET_COMPRESSION") or "snappy").strip().lower()
    if parquet_compression:
        env["DG_PARQUET_COMPRESSION"] = parquet_compression

    sinks = collect_generator_s3_sinks(demo, node, project_name)

    # Apply first-edge generator tuning (format, rate, rows) — unchanged for single- or multi-sink.
    for edge in demo.edges:
        if edge.source != node.id or edge.connection_type not in _S3_EDGE_TYPES:
            continue
        edge_cfg = edge.connection_config or {}
        for cfg_key, env_key in _EDGE_ENV_MAP.items():
            if cfg_key in edge_cfg and edge_cfg[cfg_key]:
                env[env_key] = str(edge_cfg[cfg_key])
        break

    if not sinks:
        return

    if len(sinks) == 1:
        s = sinks[0]
        env["S3_ENDPOINT"] = s["endpoint"]
        env["S3_BUCKET"] = s["bucket"]
        env["S3_ACCESS_KEY"] = s["access_key"]
        env["S3_SECRET_KEY"] = s["secret_key"]
        env.pop("DG_S3_SINKS", None)
        return

    env["DG_S3_SINKS"] = json.dumps(sinks)
    env["S3_ENDPOINT"] = sinks[0]["endpoint"]
    env["S3_BUCKET"] = sinks[0]["bucket"]
    env["S3_ACCESS_KEY"] = sinks[0]["access_key"]
    env["S3_SECRET_KEY"] = sinks[0]["secret_key"]
    logger.info(
        "Generator %s: %d S3 sinks (DG_S3_SINKS)",
        node.id,
        len(sinks),
    )
