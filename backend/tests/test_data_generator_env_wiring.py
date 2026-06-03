"""Compose env wiring coverage for Data Generator Kafka tunables."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.engine.compose_generator.generate import generate_compose
from app.registry.loader import load_registry
from app.models.demo import DemoDefinition, DemoEdge, DemoNode, NodePosition


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


def test_data_generator_kafka_tunables_flow_into_compose_env(tmp_path: Path) -> None:
    demo = DemoDefinition(
        id="d1",
        name="dg-env",
        nodes=[
            DemoNode(
                id="dg1",
                component="data-generator",
                position=_pos(),
                config={
                    "DG_FORMAT": "kafka",
                    "DG_NULL_RATE_PCT": "10",
                    "DG_DUPLICATE_RATE_PCT": "5",
                    "DG_LATE_EVENT_RATE_PCT": "7",
                    "DG_MAX_LATENESS_SEC": "120",
                },
            ),
            DemoNode(
                id="rp1",
                component="redpanda",
                position=_pos(),
            ),
        ],
        edges=[
            DemoEdge(
                id="e-kafka",
                source="dg1",
                target="rp1",
                connection_type="kafka",
                connection_config={"topic": "orders"},
            ),
        ],
    )

    repo_root = Path(__file__).resolve().parents[2]
    load_registry(str(repo_root / "components"))
    compose_path, _ = generate_compose(
        demo=demo,
        output_dir=str(tmp_path),
        components_dir=str(repo_root / "components"),
    )
    compose = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))
    env = _env_as_dict(compose["services"]["dg1"]["environment"])

    assert env["DG_FORMAT"] == "kafka"
    assert env["DG_NULL_RATE_PCT"] == "10"
    assert env["DG_DUPLICATE_RATE_PCT"] == "5"
    assert env["DG_LATE_EVENT_RATE_PCT"] == "7"
    assert env["DG_MAX_LATENESS_SEC"] == "120"
    assert env["KAFKA_TOPIC"] == "orders"
