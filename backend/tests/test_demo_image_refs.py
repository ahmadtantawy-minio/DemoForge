"""Tests for edition-aware demo image ref collection."""

from __future__ import annotations

from app.engine.docker_manager import collect_demo_image_refs
from app.engine.minio_images import (
    MINIO_AISTOR_IMAGE,
    MINIO_CE_IMAGE,
    MINIO_EDGE_IMAGE,
    minio_image_for_edition,
)
from app.models.demo import DemoCluster, DemoDefinition, DemoNode, NodePosition


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def test_minio_image_for_edition() -> None:
    assert minio_image_for_edition("ce") == MINIO_CE_IMAGE
    assert minio_image_for_edition("aistor") == MINIO_AISTOR_IMAGE
    assert minio_image_for_edition("aistor-edge") == MINIO_EDGE_IMAGE


def test_collect_demo_image_refs_minio_edge_node() -> None:
    demo = DemoDefinition(
        id="d1",
        name="edge",
        nodes=[
            DemoNode(
                id="m1",
                component="minio",
                position=_pos(),
                config={"MINIO_EDITION": "aistor-edge"},
            ),
        ],
    )
    refs = collect_demo_image_refs(demo)
    assert MINIO_EDGE_IMAGE in refs
    assert MINIO_CE_IMAGE not in refs


def test_collect_demo_image_refs_minio_cluster() -> None:
    demo = DemoDefinition(
        id="d2",
        name="cluster",
        clusters=[
            DemoCluster(
                id="c1",
                component="minio",
                position=_pos(),
                config={"MINIO_EDITION": "aistor"},
            ),
        ],
    )
    refs = collect_demo_image_refs(demo)
    assert MINIO_AISTOR_IMAGE in refs
    assert MINIO_EDGE_IMAGE in refs


def test_collect_demo_image_refs_non_minio_unchanged() -> None:
    from app.registry.loader import load_registry
    from pathlib import Path

    load_registry(str(Path(__file__).resolve().parents[2] / "components"))
    demo = DemoDefinition(
        id="d3",
        name="trino",
        nodes=[DemoNode(id="t1", component="trino", position=_pos())],
    )
    refs = collect_demo_image_refs(demo)
    assert MINIO_EDGE_IMAGE not in refs
    assert any("trino" in r for r in refs)
