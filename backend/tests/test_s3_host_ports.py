"""S3 host port allocation for MinIO clusters."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.engine.compose_generator.generate import generate_compose
from app.engine.s3_host_ports import (
    assign_minio_cluster_s3_host_ports,
    collect_s3_host_port_claims,
    parse_port_range,
)
from app.models.demo import DemoCluster, DemoDefinition, DemoServerPool, NodePosition
from app.registry.loader import load_registry


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def test_parse_port_range_default() -> None:
    start, end = parse_port_range("19000-19005")
    assert start == 19000
    assert end == 19005


def test_assign_unique_ports_per_cluster(tmp_path: Path, monkeypatch) -> None:
    demos_dir = tmp_path / "demos"
    demos_dir.mkdir()
    monkeypatch.setenv("DEMOFORGE_S3_HOST_PORT_RANGE", "19000-19002")
    monkeypatch.setenv("DEMOFORGE_DEMOS_DIR", str(demos_dir))

    demo = DemoDefinition(
        id="d1",
        name="one",
        clusters=[
            DemoCluster(
                id="c1",
                component="minio",
                label="A",
                position=_pos(),
                server_pools=[DemoServerPool(node_count=2, drives_per_node=1, ec_parity=0)],
            ),
            DemoCluster(
                id="c2",
                component="minio",
                label="B",
                position=_pos(),
                server_pools=[DemoServerPool(node_count=2, drives_per_node=1, ec_parity=0)],
            ),
        ],
        nodes=[],
        edges=[],
    )
    assign_minio_cluster_s3_host_ports(demo)
    p1 = int(demo.clusters[0].config["S3_HOST_PORT"])
    p2 = int(demo.clusters[1].config["S3_HOST_PORT"])
    assert p1 != p2
    assert 19000 <= p1 <= 19002
    assert 19000 <= p2 <= 19002


def test_compose_publishes_lb_s3_port(tmp_path: Path, monkeypatch) -> None:
    demos_dir = tmp_path / "demos"
    demos_dir.mkdir()
    monkeypatch.setenv("DEMOFORGE_S3_HOST_PORT_RANGE", "19100-19110")
    monkeypatch.setenv("DEMOFORGE_DEMOS_DIR", str(demos_dir))

    repo_root = Path(__file__).resolve().parents[2]
    load_registry(str(repo_root / "components"))

    demo = DemoDefinition(
        id="portdemo",
        name="ports",
        clusters=[
            DemoCluster(
                id="mc",
                component="minio",
                label="Lake",
                position=_pos(),
                credentials={"root_user": "u", "root_password": "p"},
                server_pools=[DemoServerPool(node_count=2, drives_per_node=1, ec_parity=0)],
            ),
        ],
        nodes=[],
        edges=[],
    )
    compose_path, expanded = generate_compose(demo, str(tmp_path / "data"), str(repo_root / "components"))
    with open(compose_path) as f:
        compose = yaml.safe_load(f)

    lb = compose["services"]["mc-lb"]
    host_port = int(expanded.clusters[0].config["S3_HOST_PORT"])
    assert f"{host_port}:80" in lb["ports"]
    assert lb["labels"]["demoforge.s3_host_port"] == str(host_port)


def test_collect_claims_from_other_demos(tmp_path: Path, monkeypatch) -> None:
    demos_dir = tmp_path / "demos"
    demos_dir.mkdir()
    monkeypatch.setenv("DEMOFORGE_DEMOS_DIR", str(demos_dir))

    other = DemoDefinition(
        id="other",
        name="other",
        clusters=[
            DemoCluster(
                id="mc",
                component="minio",
                label="X",
                position=_pos(),
                config={"S3_HOST_PORT": "19050"},
            ),
        ],
        nodes=[],
        edges=[],
    )
    with open(demos_dir / "other.yaml", "w") as f:
        yaml.dump(other.model_dump(), f)

    claims = collect_s3_host_port_claims(exclude_demo_id="new")
    assert claims[19050] == ("other", "mc")
