"""Unit tests for data-generator Kafka tunable transforms."""

from __future__ import annotations

import datetime
import importlib
import sys
from pathlib import Path


def _load_kafka_tunables_module():
    root = Path(__file__).resolve().parents[2]
    src_path = root / "components" / "data-generator" / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    return importlib.import_module("kafka_tunables")


def _columns():
    return [
        {"name": "order_id", "type": "int"},
        {"name": "order_date", "type": "timestamp"},
        {"name": "region", "type": "string"},
        {"name": "value", "type": "float"},
    ]


def _rows():
    now = datetime.datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"order_id": 1, "order_date": now, "region": "US", "value": 10.0},
        {"order_id": 2, "order_date": now, "region": "EU", "value": 20.0},
    ]


def test_apply_kafka_tunables_noop_when_all_zero() -> None:
    mod = _load_kafka_tunables_module()
    rows = _rows()
    out = mod.apply_kafka_tunables(
        rows=rows,
        columns=_columns(),
        null_rate_pct=0,
        duplicate_rate_pct=0,
        late_event_rate_pct=0,
        max_lateness_sec=300,
    )
    assert out == rows
    assert len(out) == 2


def test_apply_kafka_tunables_duplicate_rows_added() -> None:
    mod = _load_kafka_tunables_module()
    rows = _rows()
    out = mod.apply_kafka_tunables(
        rows=rows,
        columns=_columns(),
        null_rate_pct=0,
        duplicate_rate_pct=100,
        late_event_rate_pct=0,
        max_lateness_sec=300,
    )
    assert len(out) == 4
    assert out[0]["order_id"] in (1, 2)
    assert out[3]["order_id"] in (1, 2)


def test_apply_kafka_tunables_late_events_within_bound() -> None:
    mod = _load_kafka_tunables_module()
    rows = _rows()
    original = [r["order_date"] for r in rows]
    out = mod.apply_kafka_tunables(
        rows=rows,
        columns=_columns(),
        null_rate_pct=0,
        duplicate_rate_pct=0,
        late_event_rate_pct=100,
        max_lateness_sec=120,
    )
    for idx, row in enumerate(out):
        shifted = row["order_date"]
        assert isinstance(shifted, datetime.datetime)
        assert shifted <= original[idx]
        delta = (original[idx] - shifted).total_seconds()
        assert 1 <= delta <= 120


def test_apply_kafka_tunables_null_injection_does_not_touch_order_id() -> None:
    mod = _load_kafka_tunables_module()
    rows = _rows()
    out = mod.apply_kafka_tunables(
        rows=rows,
        columns=_columns(),
        null_rate_pct=100,
        duplicate_rate_pct=0,
        late_event_rate_pct=0,
        max_lateness_sec=300,
    )
    assert out[0]["order_id"] == 1
    assert out[1]["order_id"] == 2
    # At least one non-identifier field should be nulled at 100% injection.
    assert any(r["region"] is None or r["value"] is None or r["order_date"] is None for r in out)
