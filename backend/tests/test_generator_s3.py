"""Compose S3 sink wiring for data-generator / external-system."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.engine.compose_generator.generate import generate_compose
from app.models.demo import DemoCluster, DemoDefinition, DemoEdge, DemoNode, DemoServerPool, NodePosition
from app.registry.loader import load_registry


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _env_as_dict(environment) -> dict[str, str]:
    if isinstance(environment, dict):
        return {str(k): str(v) for k, v in environment.items()}
    out: dict[str, str] = {}
    for item in environment or []:
        if isinstance(item, str) and "=" in item:
            key, val = item.split("=", 1)
            out[key] = val
    return out


def _load_registry(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_registry(str(repo_root / "components"))


def test_single_s3_sink_keeps_legacy_env_without_dg_s3_sinks(tmp_path: Path) -> None:
    demo = DemoDefinition(
        id="d1",
        name="single-sink",
        nodes=[
            DemoNode(
                id="dg1",
                component="data-generator",
                position=_pos(),
                config={"DG_PARQUET_COMPRESSION": "snappy"},
            ),
            DemoNode(id="m1", component="minio", position=_pos(), config={"MINIO_ROOT_USER": "u", "MINIO_ROOT_PASSWORD": "p"}),
        ],
        edges=[
            DemoEdge(
                id="e1",
                source="dg1",
                target="m1",
                connection_type="s3",
                connection_config={"target_bucket": "data-lake", "format": "parquet"},
            ),
        ],
    )
    _load_registry(tmp_path)
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(Path(__file__).resolve().parents[2] / "components"),
    )
    env = _env_as_dict(yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))["services"]["dg1"]["environment"])
    assert env["S3_BUCKET"] == "data-lake"
    assert env["DG_PARQUET_COMPRESSION"] == "snappy"
    assert "DG_S3_SINKS" not in env


def test_multi_s3_sink_sets_dg_s3_sinks_json(tmp_path: Path) -> None:
    demo = DemoDefinition(
        id="d2",
        name="multi-sink",
        clusters=[
            DemoCluster(
                id="c-off",
                component="minio",
                position=_pos(),
                label="Off",
                config={"MINIO_EDITION": "aistor", "MINIO_COMPRESSION_ENABLE": "off"},
                credentials={"root_user": "minioadmin", "root_password": "minioadmin"},
                server_pools=[DemoServerPool(id="pool-1", node_count=1, drives_per_node=1, ec_parity=0)],
            ),
            DemoCluster(
                id="c-on",
                component="minio",
                position=_pos(),
                label="On",
                config={"MINIO_EDITION": "aistor", "MINIO_COMPRESSION_ENABLE": "on"},
                credentials={"root_user": "minioadmin", "root_password": "minioadmin"},
                server_pools=[DemoServerPool(id="pool-1", node_count=1, drives_per_node=1, ec_parity=0)],
            ),
        ],
        nodes=[
            DemoNode(
                id="es1",
                component="external-system",
                position=_pos(),
                config={"ES_SCENARIO": "ecommerce-orders", "DG_PARQUET_COMPRESSION": "none"},
            ),
        ],
        edges=[
            DemoEdge(
                id="e-off",
                source="es1",
                target="c-off",
                connection_type="s3",
                connection_config={"target_bucket": "parquet-raw"},
            ),
            DemoEdge(
                id="e-on",
                source="es1",
                target="c-on",
                connection_type="s3",
                connection_config={"target_bucket": "parquet-snappy"},
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
    es_env = _env_as_dict(compose["services"]["es1"]["environment"])
    assert es_env["DG_PARQUET_COMPRESSION"] == "none"
    assert "DG_S3_SINKS" in es_env
    sinks = json.loads(es_env["DG_S3_SINKS"])
    assert len(sinks) == 2
    buckets = {s["bucket"] for s in sinks}
    assert buckets == {"parquet-raw", "parquet-snappy"}

    # Cluster compression stays on component config, not stripped for AIStor
    minio_service = next(k for k in compose["services"] if k.startswith("c-off"))
    minio_env = _env_as_dict(compose["services"][minio_service]["environment"])
    assert minio_env.get("MINIO_COMPRESSION_ENABLE") == "off"


def test_ce_minio_strips_compression_env(tmp_path: Path) -> None:
    demo = DemoDefinition(
        id="d3",
        name="ce-strip",
        nodes=[
            DemoNode(
                id="m1",
                component="minio",
                position=_pos(),
                config={
                    "MINIO_EDITION": "ce",
                    "MINIO_COMPRESSION_ENABLE": "on",
                    "MINIO_COMPRESSION_EXTENSIONS": ".parquet",
                },
            ),
        ],
        edges=[],
    )
    _load_registry(tmp_path)
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(Path(__file__).resolve().parents[2] / "components"),
    )
    env = _env_as_dict(yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))["services"]["m1"]["environment"])
    assert "MINIO_COMPRESSION_ENABLE" not in env
    assert "MINIO_COMPRESSION_EXTENSIONS" not in env
