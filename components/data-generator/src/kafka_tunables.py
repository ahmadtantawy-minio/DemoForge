"""Lean data-tunable transforms for Kafka-mode generation."""

from __future__ import annotations

import datetime
import random


def _clamp_pct(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _timestamp_columns(columns: list) -> list[str]:
    ts_cols = []
    for col in columns:
        col_type = str(col.get("type", "")).lower()
        if "timestamp" in col_type or "datetime" in col_type:
            ts_cols.append(col["name"])
    return ts_cols


def _inject_nulls(rows: list, columns: list, null_rate_pct: float, rng=random) -> None:
    if not rows:
        return
    pct = _clamp_pct(null_rate_pct)
    if pct <= 0:
        return
    excluded = {"id", "order_id", "customer_id", "event_id"}
    nullable_cols = [c["name"] for c in columns if c.get("name") not in excluded]
    if not nullable_cols:
        return
    threshold = pct / 100.0
    for row in rows:
        if rng.random() < threshold:
            row[rng.choice(nullable_cols)] = None


def _inject_late_events(
    rows: list,
    columns: list,
    late_event_rate_pct: float,
    max_lateness_sec: int,
    rng=random,
) -> None:
    if not rows:
        return
    pct = _clamp_pct(late_event_rate_pct)
    if pct <= 0 or max_lateness_sec <= 0:
        return
    ts_cols = _timestamp_columns(columns)
    if not ts_cols:
        return
    threshold = pct / 100.0
    for row in rows:
        if rng.random() >= threshold:
            continue
        col_name = rng.choice(ts_cols)
        value = row.get(col_name)
        if isinstance(value, datetime.datetime):
            row[col_name] = value - datetime.timedelta(seconds=rng.randint(1, max_lateness_sec))


def _with_duplicates(rows: list, duplicate_rate_pct: float, rng=random) -> list:
    if not rows:
        return rows
    pct = _clamp_pct(duplicate_rate_pct)
    if pct <= 0:
        return rows
    dup_count = int(len(rows) * (pct / 100.0))
    if dup_count <= 0:
        return rows
    out = list(rows)
    for _ in range(dup_count):
        out.append(dict(rng.choice(rows)))
    return out


def apply_kafka_tunables(
    rows: list,
    columns: list,
    null_rate_pct: float,
    duplicate_rate_pct: float,
    late_event_rate_pct: float,
    max_lateness_sec: int,
    rng=random,
) -> list:
    if not rows:
        return rows
    _inject_nulls(rows, columns, null_rate_pct, rng=rng)
    _inject_late_events(rows, columns, late_event_rate_pct, max_lateness_sec, rng=rng)
    return _with_duplicates(rows, duplicate_rate_pct, rng=rng)
