"""Compose env wiring for spark-etl-job (Iceberg REST + SigV4, compaction mode, catalog naming)."""

from __future__ import annotations

import pytest

from app.engine.compose_generator.generate import (
    _inject_spark_etl_job_env,
    _spark_etl_job_spark_catalog_name_from_peer,
)
from app.engine.compose_generator.helpers import resolve_minio_peer_aistor_catalog_name
from app.models.demo import DemoCluster, DemoDefinition, DemoEdge, DemoNode, NodePosition


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _spark_minio_job_demo(
    *,
    job_mode: str = "iceberg_compaction",
    job_config: dict[str, str] | None = None,
    minio_config: dict[str, str] | None = None,
    tables_enabled: bool = True,
    edge_role: str = "output",
) -> tuple[DemoDefinition, DemoNode]:
    minio_cfg = dict(minio_config or {})
    job_cfg = {"JOB_MODE": job_mode, **(job_config or {})}
    demo = DemoDefinition(
        id="d1",
        name="test",
        nodes=[
            DemoNode(
                id="spark-master",
                component="spark",
                position=_pos(),
            ),
            DemoNode(
                id="minio-1",
                component="minio",
                position=_pos(),
                aistor_tables_enabled=tables_enabled,
                config={
                    "MINIO_ROOT_USER": "minioadmin",
                    "MINIO_ROOT_PASSWORD": "minioadmin",
                    **minio_cfg,
                },
            ),
            DemoNode(
                id="spark-job",
                component="spark-etl-job",
                position=_pos(),
                config=job_cfg,
            ),
        ],
        edges=[
            DemoEdge(
                id="e-submit",
                source="spark-job",
                target="spark-master",
                connection_type="spark-submit",
            ),
            DemoEdge(
                id="e-minio",
                source="spark-job",
                target="minio-1",
                connection_type="aistor-tables",
                connection_config={"spark_sink_role": edge_role},
            ),
        ],
    )
    job = next(n for n in demo.nodes if n.id == "spark-job")
    return demo, job


def test_compaction_env_defaults_and_skips_input_uri() -> None:
    demo, job = _spark_minio_job_demo(
        minio_config={"AISTOR_TABLES_CATALOG_NAME": "datalake"},
    )
    env: dict[str, str] = {}
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")

    assert env["JOB_MODE"] == "iceberg_compaction"
    assert "ICEBERG_TARGET_NAMESPACE" not in env
    assert "ICEBERG_TARGET_TABLE" not in env


def test_compaction_strips_manifest_target_defaults_from_env() -> None:
    """Compose merges manifest env before _inject_spark_etl_job_env; compaction must not inherit load-job targets."""
    demo, job = _spark_minio_job_demo(
        minio_config={"AISTOR_TABLES_CATALOG_NAME": "datalake"},
    )
    env = {
        "ICEBERG_TARGET_NAMESPACE": "analytics",
        "ICEBERG_TARGET_TABLE": "events_from_raw",
        "JOB_MODE": "iceberg_compaction",
    }
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")
    assert "ICEBERG_TARGET_NAMESPACE" not in env
    assert "ICEBERG_TARGET_TABLE" not in env


def test_compaction_honors_optional_scope_filters() -> None:
    demo, job = _spark_minio_job_demo(
        job_config={"ICEBERG_TARGET_NAMESPACE": "ecom", "ICEBERG_TARGET_TABLE": "orders"},
        minio_config={"AISTOR_TABLES_CATALOG_NAME": "datalake"},
    )
    env = {
        "ICEBERG_TARGET_NAMESPACE": "analytics",
        "ICEBERG_TARGET_TABLE": "events_from_raw",
    }
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")
    assert env["ICEBERG_TARGET_NAMESPACE"] == "ecom"
    assert env["ICEBERG_TARGET_TABLE"] == "orders"
    assert env["COMPACTION_REWRITE_DATA_FILES"] == "true"
    assert env["COMPACTION_EXPIRE_SNAPSHOTS"] == "true"
    assert env["COMPACTION_REMOVE_ORPHAN_FILES"] == "true"
    assert env["COMPACTION_EXPIRE_SNAPSHOTS_OLDER_THAN"] == "5d"
    assert "INPUT_S3A_URI" not in env
    assert env["ICEBERG_REST_URI"].endswith("/_iceberg")
    assert env["ICEBERG_SIGV4"] == "true"
    assert env["ICEBERG_REST_SIGNING_NAME"] == "s3tables"
    assert env["SPARK_MASTER_URL"] == "spark://demoforge-d1-spark-master:7077"


def test_catalog_inferred_from_aistor_tables_catalog_name() -> None:
    demo, job = _spark_minio_job_demo(
        minio_config={"AISTOR_TABLES_CATALOG_NAME": "datalake"},
    )
    env: dict[str, str] = {}
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")

    assert env["ICEBERG_SPARK_CATALOG_NAME"] == "datalake"
    assert env["ICEBERG_CATALOG_NAME"] == "datalake"


def test_job_override_wins_over_minio_aistor_catalog() -> None:
    demo, job = _spark_minio_job_demo(
        job_config={
            "ICEBERG_SPARK_CATALOG_NAME": "spark_custom",
            "JOB_MODE": "raw_to_iceberg",
            "RAW_LANDING_BUCKET": "raw",
        },
        minio_config={"AISTOR_TABLES_CATALOG_NAME": "datalake"},
        edge_role="input",
    )
    env: dict[str, str] = {}
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")
    assert env["ICEBERG_SPARK_CATALOG_NAME"] == "spark_custom"


def test_raw_to_iceberg_requires_input_edge() -> None:
    demo = DemoDefinition(
        id="d1",
        name="t",
        nodes=[
            DemoNode(id="spark-master", component="spark", position=_pos()),
            DemoNode(
                id="minio-1",
                component="minio",
                position=_pos(),
                aistor_tables_enabled=True,
                config={"MINIO_ROOT_USER": "a", "MINIO_ROOT_PASSWORD": "b"},
            ),
            DemoNode(
                id="spark-job",
                component="spark-etl-job",
                position=_pos(),
                config={"JOB_MODE": "raw_to_iceberg"},
            ),
        ],
        edges=[
            DemoEdge(
                id="e-submit",
                source="spark-job",
                target="spark-master",
                connection_type="spark-submit",
            ),
            DemoEdge(
                id="e-minio",
                source="spark-job",
                target="minio-1",
                connection_type="aistor-tables",
                connection_config={"spark_sink_role": "output"},
            ),
        ],
    )
    job = next(n for n in demo.nodes if n.id == "spark-job")
    with pytest.raises(ValueError, match="input MinIO edge"):
        _inject_spark_etl_job_env(demo, job, {}, "demoforge-d1")


def test_compaction_requires_aistor_tables_on_peer() -> None:
    demo, job = _spark_minio_job_demo(tables_enabled=False)
    with pytest.raises(ValueError, match="AIStor Tables"):
        _inject_spark_etl_job_env(demo, job, {}, "demoforge-d1")


def test_cluster_lb_peer_catalog_from_aistor_tables_name() -> None:
    demo = DemoDefinition(
        id="d1",
        name="t",
        clusters=[
            DemoCluster(
                id="mc",
                position=_pos(),
                aistor_tables_enabled=True,
                credentials={"root_user": "minioadmin", "root_password": "minioadmin"},
                config={"AISTOR_TABLES_CATALOG_NAME": "cluster_lake"},
            ),
        ],
        nodes=[
            DemoNode(id="spark-master", component="spark", position=_pos()),
            DemoNode(
                id="spark-job",
                component="spark-etl-job",
                position=_pos(),
                config={"JOB_MODE": "iceberg_compaction"},
            ),
        ],
        edges=[
            DemoEdge(
                id="e-submit",
                source="spark-job",
                target="spark-master",
                connection_type="spark-submit",
            ),
            DemoEdge(
                id="e-minio",
                source="spark-job",
                target="mc-lb",
                connection_type="aistor-tables",
                connection_config={"spark_sink_role": "output"},
            ),
        ],
    )
    job = next(n for n in demo.nodes if n.id == "spark-job")
    env: dict[str, str] = {}
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")
    assert env["ICEBERG_SPARK_CATALOG_NAME"] == "cluster_lake"
    assert "mc-pool1-node-1:9000" in env["ICEBERG_REST_URI"] or env["ICEBERG_REST_URI"].endswith("/_iceberg")


def test_spark_catalog_name_helper_matches_resolve_aistor() -> None:
    demo, _ = _spark_minio_job_demo(minio_config={"AISTOR_TABLES_CATALOG_NAME": "lake_prod"})
    assert resolve_minio_peer_aistor_catalog_name(demo, "minio-1") == "lake_prod"
    assert _spark_etl_job_spark_catalog_name_from_peer(demo, "minio-1", {}) == "lake_prod"


def test_reserved_trino_catalog_name_sanitized_for_spark() -> None:
    demo, job = _spark_minio_job_demo(
        minio_config={"AISTOR_TABLES_CATALOG_NAME": "iceberg"},
    )
    env: dict[str, str] = {}
    _inject_spark_etl_job_env(demo, job, env, "demoforge-d1")
    assert env["ICEBERG_SPARK_CATALOG_NAME"] == "aistor"
