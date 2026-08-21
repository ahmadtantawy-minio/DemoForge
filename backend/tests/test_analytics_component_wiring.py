"""Compose wiring tests for ClickHouse, OpenSearch, and HDFS/Hive/Trino dual catalogs."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.engine.compose_generator.generate import generate_compose
from app.models.demo import DemoDefinition, DemoEdge, DemoNode, NodePosition
from app.registry.loader import load_registry


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _load_registry() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_registry(str(repo_root / "components"))


def _env(service: dict) -> dict[str, str]:
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return {str(k): str(v) for k, v in environment.items()}
    out: dict[str, str] = {}
    for item in environment:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            out[k] = v
    return out


def test_clickhouse_s3_env_and_init_sql(tmp_path: Path) -> None:
    _load_registry()
    demo = DemoDefinition(
        id="ch1",
        name="ch-s3",
        nodes=[
            DemoNode(id="minio", component="minio", position=_pos(), config={}),
            DemoNode(id="clickhouse", component="clickhouse", position=_pos(), config={}),
        ],
        edges=[
            DemoEdge(
                id="e1",
                source="minio",
                target="clickhouse",
                connection_type="s3",
                connection_config={"source_bucket": "demo-bucket", "file_pattern": "*.csv"},
            ),
        ],
    )
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(Path(__file__).resolve().parents[2] / "components"),
    )
    services = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))["services"]
    env = _env(services["clickhouse"])
    assert env["S3_ENDPOINT"].startswith("http://demoforge-ch1-minio:")
    assert env["S3_BUCKET"] == "demo-bucket"
    assert env["S3_ACCESS_KEY"] == "minioadmin"

    sql = Path(tmp_path / "demoforge-ch1" / "clickhouse" / "init-s3.sql").read_text(encoding="utf-8")
    assert "CREATE NAMED COLLECTION" in sql
    assert "demoforge_s3_files" in sql
    assert "demo-bucket" in sql

    vols = services["clickhouse"].get("volumes") or []
    vol_str = "\n".join(str(v) for v in vols)
    assert "init-s3.sql" in vol_str
    assert "apply-s3-init.sh" in vol_str


def test_opensearch_s3_snapshot_env(tmp_path: Path) -> None:
    _load_registry()
    demo = DemoDefinition(
        id="os1",
        name="os-s3",
        nodes=[
            DemoNode(id="minio", component="minio", position=_pos(), config={}),
            DemoNode(id="opensearch", component="opensearch", position=_pos(), config={}),
        ],
        edges=[
            DemoEdge(
                id="e1",
                source="minio",
                target="opensearch",
                connection_type="s3",
                connection_config={"snapshot_bucket": "opensearch-snapshots"},
            ),
        ],
    )
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(Path(__file__).resolve().parents[2] / "components"),
    )
    env = _env(yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))["services"]["opensearch"])
    assert env["S3_ENDPOINT"].startswith("http://demoforge-os1-minio:")
    assert env["OPENSEARCH_SNAPSHOT_BUCKET"] == "opensearch-snapshots"


def test_hdfs_hive_trino_dual_catalogs(tmp_path: Path) -> None:
    _load_registry()
    demo = DemoDefinition(
        id="mig1",
        name="dual",
        nodes=[
            DemoNode(id="hdfs", component="hdfs", position=_pos(), config={}, variant="pseudo-distributed"),
            DemoNode(id="hive-ms", component="hive-metastore", position=_pos(), config={}),
            DemoNode(id="minio-1", component="minio", position=_pos(), config={}),
            DemoNode(id="trino", component="trino", position=_pos(), config={}),
        ],
        edges=[
            DemoEdge(
                id="e-hdfs-hive",
                source="hdfs",
                target="hive-ms",
                connection_type="hdfs",
                connection_config={"warehouse_path": "/user/hive/warehouse"},
            ),
            DemoEdge(
                id="e-hive-trino",
                source="hive-ms",
                target="trino",
                connection_type="hive-metastore",
                connection_config={"catalog_name": "legacy"},
            ),
            DemoEdge(
                id="e-minio-trino",
                source="minio-1",
                target="trino",
                connection_type="s3",
                connection_config={"catalog_name": "minio"},
            ),
        ],
    )
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(Path(__file__).resolve().parents[2] / "components"),
    )
    services = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))["services"]
    hive_env = _env(services["hive-ms"])
    assert hive_env["HDFS_NAMENODE"] == "demoforge-mig1-hdfs"
    assert hive_env["HIVE_WAREHOUSE_PATH"] == "/user/hive/warehouse"

    trino_dir = tmp_path / "demoforge-mig1" / "trino"
    legacy = (trino_dir / "legacy-hive-legacy.properties").read_text(encoding="utf-8")
    assert "connector.name=hive" in legacy
    assert "thrift://demoforge-mig1-hive-ms:9083" in legacy

    minio_cat = (trino_dir / "hive-minio.properties").read_text(encoding="utf-8")
    assert "connector.name=hive" in minio_cat
    assert "s3.endpoint=" in minio_cat
    assert "demoforge-mig1-minio-1" in minio_cat

    vols = "\n".join(str(v) for v in (services["trino"].get("volumes") or []))
    assert "/etc/trino/catalog/legacy.properties" in vols
    assert "/etc/trino/catalog/minio.properties" in vols
