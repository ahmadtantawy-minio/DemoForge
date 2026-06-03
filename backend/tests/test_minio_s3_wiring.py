"""MinIO S3 LB wiring, bucket defaults, and mc-shell bootstrap."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.engine.compose_generator.generate import generate_compose
from app.engine.compose_generator.minio_s3_wiring import (
    buckets_from_edge_config,
    collect_mc_buckets_for_edge,
    normalize_minio_peer_id,
    resolve_minio_s3_endpoint,
)
from app.models.demo import (
    DemoCluster,
    DemoDefinition,
    DemoEdge,
    DemoNode,
    DemoServerPool,
    NodePosition,
)
from app.registry.loader import load_registry


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _load_registry(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_registry(str(repo_root / "components"))


def test_normalize_minio_peer_id_routes_cluster_and_pool_nodes_to_lb() -> None:
    demo = DemoDefinition(
        id="d",
        name="c",
        clusters=[
            DemoCluster(
                id="mc",
                component="minio",
                position=_pos(),
                label="Lake",
                credentials={"root_user": "u", "root_password": "p"},
                server_pools=[DemoServerPool(id="pool-1", node_count=2, drives_per_node=1, ec_parity=0)],
            ),
        ],
        nodes=[],
        edges=[],
    )
    assert normalize_minio_peer_id(demo, "mc") == "mc-lb"
    assert normalize_minio_peer_id(demo, "mc-pool1-node-1") == "mc-lb"
    assert normalize_minio_peer_id(demo, "mc-lb") == "mc-lb"


def test_resolve_minio_s3_endpoint_uses_cluster_lb() -> None:
    demo = DemoDefinition(
        id="d",
        name="c",
        clusters=[
            DemoCluster(
                id="mc",
                component="minio",
                position=_pos(),
                label="Lake",
                credentials={"root_user": "u", "root_password": "p"},
                server_pools=[DemoServerPool(id="pool-1", node_count=1, drives_per_node=4, ec_parity=0)],
            ),
        ],
        nodes=[],
        edges=[],
    )
    url, ak, sk = resolve_minio_s3_endpoint(demo, "mc-pool1-node-1", "demoforge-d")  # type: ignore[misc]
    assert url == "http://demoforge-d-mc-lb:80"
    assert ak == "u"
    assert sk == "p"


def test_kafka_connect_default_bucket_and_lb_compose(tmp_path: Path) -> None:
    demo = DemoDefinition(
        id="kc1",
        name="stream",
        clusters=[
            DemoCluster(
                id="minio-cluster",
                component="minio",
                position=_pos(),
                label="MinIO_Cluster",
                credentials={"root_user": "minioadmin", "root_password": "minioadmin"},
                server_pools=[DemoServerPool(id="pool-1", node_count=2, drives_per_node=4, ec_parity=0)],
            ),
        ],
        nodes=[
            DemoNode(id="kafka-connect-1", component="kafka-connect-s3", position=_pos(), config={}),
            DemoNode(id="redpanda-1", component="redpanda", position=_pos(), config={}),
        ],
        edges=[
            DemoEdge(
                id="e-kafka",
                source="kafka-connect-1",
                target="redpanda-1",
                connection_type="kafka",
                connection_config={"topic": "clickstream"},
            ),
            DemoEdge(
                id="e-s3",
                source="kafka-connect-1",
                target="minio-cluster",
                connection_type="s3",
                connection_config={},
            ),
        ],
    )
    _load_registry(tmp_path)
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(Path(__file__).resolve().parents[2] / "components"),
    )
    compose = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))
    kc_env = compose["services"]["kafka-connect-1"]["environment"]
    if isinstance(kc_env, list):
        kc_env = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in kc_env if "=" in p}
    assert kc_env["S3_ENDPOINT"] == "http://demoforge-kc1-minio-cluster-lb:80"
    assert kc_env["S3_BUCKET"] == "streaming-data"
    assert kc_env["KAFKA_TOPIC"] == "clickstream"

    init_sh = Path(tmp_path) / "demoforge-kc1" / "mc-shell" / "init.sh"
    assert init_sh.is_file()
    init_body = init_sh.read_text(encoding="utf-8")
    assert "mc mb 'MinIO_Cluster/streaming-data'" in init_body


def test_buckets_from_edge_config_strips_prefix_path() -> None:
    assert buckets_from_edge_config(
        {"bucket": "lake/kafka"},
        connection_type="s3",
    ) == ["lake"]


def test_collect_mc_buckets_uses_cluster_metadata() -> None:
    demo = DemoDefinition(
        id="d",
        name="n",
        clusters=[
            DemoCluster(
                id="c1",
                component="minio",
                position=_pos(),
                label="Store",
                credentials={"root_user": "a", "root_password": "b"},
                server_pools=[DemoServerPool(id="pool-1", node_count=1, drives_per_node=4, ec_parity=0)],
            ),
        ],
        nodes=[
            DemoNode(id="kc", component="kafka-connect-s3", position=_pos(), config={}),
            DemoNode(id="c1-lb", component="nginx", position=_pos(), config={}),
        ],
        edges=[
            DemoEdge(
                id="e1",
                source="kc",
                target="c1-lb",
                connection_type="s3",
                connection_config={"bucket": "events"},
            ),
        ],
    )
    pairs = collect_mc_buckets_for_edge(demo, demo.edges[0], consumer_component="kafka-connect-s3")
    assert ("Store", "events") in pairs
