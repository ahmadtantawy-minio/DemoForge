"""MinIO S3 peer resolution for compose env injection and mc-shell bucket bootstrap."""

from __future__ import annotations

import re
from typing import Any

from ...models.demo import DemoDefinition

# Edge connection_config keys that carry a bucket name (first path segment used for mc mb).
S3_BUCKET_CONFIG_KEYS = (
    "target_bucket",
    "bucket",
    "sink_bucket",
    "documents_bucket",
    "audit_bucket",
    "snapshot_bucket",
    "artifact_bucket",
    "training_bucket",
    "source_bucket",
    "output_bucket",
    "milvus_bucket",
    "dag_bucket",
    "log_bucket",
)

KAFKA_CONNECT_S3_DEFAULT_BUCKET = "streaming-data"
FILE_PUSH_DEFAULT_BUCKET = "demo-bucket"


def s3_bucket_object_name(raw: str) -> str:
    """Bucket name for mc mb / aws.s3.bucket.name (strip optional key prefix)."""
    return (raw or "").strip().split("/")[0].strip()


def buckets_from_edge_config(
    edge_cfg: dict[str, Any],
    *,
    connection_type: str,
    consumer_component: str | None = None,
) -> list[str]:
    """Collect deduplicated bucket names from an S3-class edge."""
    names: list[str] = []
    for key in S3_BUCKET_CONFIG_KEYS:
        val = edge_cfg.get(key)
        if val:
            b = s3_bucket_object_name(str(val))
            if b and b not in names:
                names.append(b)
    if not names and connection_type == "file-push":
        names.append(FILE_PUSH_DEFAULT_BUCKET)
    if not names and consumer_component == "kafka-connect-s3":
        names.append(KAFKA_CONNECT_S3_DEFAULT_BUCKET)
    return names


def normalize_minio_peer_id(demo: DemoDefinition, peer_id: str) -> str:
    """Route cluster / pool-node peers to the embedded nginx LB service id."""
    if peer_id.endswith("-lb"):
        return peer_id
    cluster = next((c for c in demo.clusters if c.id == peer_id), None)
    if cluster:
        return f"{cluster.id}-lb"
    for cluster in demo.clusters:
        prefix = f"{cluster.id}-"
        if peer_id.startswith(prefix) and peer_id != f"{cluster.id}-lb":
            return f"{cluster.id}-lb"
    return peer_id


def mc_alias_for_minio_peer(demo: DemoDefinition, peer_id: str) -> str | None:
    """Sanitized mc alias for mc-shell init (LB, cluster id, or standalone MinIO node)."""
    peer_id = normalize_minio_peer_id(demo, peer_id)
    if peer_id.endswith("-lb"):
        cluster_id = peer_id[:-3]
        cluster = next((c for c in demo.clusters if c.id == cluster_id), None)
        if cluster:
            return re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
    cluster = next((c for c in demo.clusters if c.id == peer_id), None)
    if cluster:
        return re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
    for cluster in demo.clusters:
        if peer_id.startswith(f"{cluster.id}-"):
            return re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
    standalone = [
        n
        for n in demo.nodes
        if n.component == "minio"
        and not any(n.id.startswith(f"{c.id}-") for c in demo.clusters)
    ]
    node = next((n for n in standalone if n.id == peer_id), None)
    if node:
        return re.sub(r"[^a-zA-Z0-9_]", "_", node.display_name) if node.display_name else node.id
    return None


def resolve_minio_s3_endpoint(
    demo: DemoDefinition,
    peer_id: str,
    project_name: str,
) -> tuple[str, str, str] | None:
    """
    Return (http endpoint URL, access key, secret key) for S3 clients.
    Cluster peers always use the nginx LB on port 80.
    """
    peer_id = normalize_minio_peer_id(demo, peer_id)
    peer_cluster = next((c for c in demo.clusters if c.id == peer_id), None)
    peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
    is_cluster_lb = peer_id.endswith("-lb")

    if is_cluster_lb:
        cluster_id = peer_id[:-3]
        peer_cluster = next((c for c in demo.clusters if c.id == cluster_id), None)
        if not peer_cluster or peer_cluster.component != "minio":
            return None
        svc = f"{project_name}-{peer_id}"
        port = 80
        ak = peer_cluster.credentials.get("root_user", "minioadmin")
        sk = peer_cluster.credentials.get("root_password", "minioadmin")
        return f"http://{svc}:{port}", str(ak), str(sk)

    if peer_cluster and peer_cluster.component == "minio":
        svc = f"{project_name}-{peer_cluster.id}-lb"
        port = 80
        ak = peer_cluster.credentials.get("root_user", "minioadmin")
        sk = peer_cluster.credentials.get("root_password", "minioadmin")
        return f"http://{svc}:{port}", str(ak), str(sk)

    if peer_node and peer_node.component == "minio":
        svc = f"{project_name}-{peer_id}"
        port = 9000
        ak = peer_node.config.get("MINIO_ROOT_USER", "minioadmin")
        sk = peer_node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
        return f"http://{svc}:{port}", str(ak), str(sk)

    if is_cluster_lb:
        # LB node without resolved cluster (should not happen)
        return None

    return None


def collect_mc_buckets_for_edge(
    demo: DemoDefinition,
    edge,
    *,
    consumer_component: str | None = None,
) -> list[tuple[str, str]]:
    """Return list of (mc_alias, bucket) to create for one S3-class edge."""
    cfg = edge.connection_config or {}
    buckets = buckets_from_edge_config(
        cfg,
        connection_type=edge.connection_type,
        consumer_component=consumer_component,
    )
    if not buckets:
        return []

    aliases: list[str] = []
    for node_id in (edge.target, edge.source):
        a = mc_alias_for_minio_peer(demo, node_id)
        if a:
            aliases.append(a)
    for key in ("_target_cluster_id", "_source_cluster_id"):
        cid = cfg.get(key)
        if cid:
            a = mc_alias_for_minio_peer(demo, str(cid))
            if a:
                aliases.append(a)

    target_node = next((n for n in demo.nodes if n.id == edge.target), None)
    if target_node and target_node.component == "nginx":
        for e2 in demo.edges:
            if e2.source == edge.target and e2.connection_type in ("load-balance", "nginx-backend"):
                a = mc_alias_for_minio_peer(demo, e2.target)
                if a:
                    aliases.append(a)

    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for alias in dict.fromkeys(aliases):
        for bucket in buckets:
            key = (alias, bucket)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out
