"""Unit tests for iceberg compaction scope helpers (no PySpark)."""

from __future__ import annotations

import sys
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parents[2] / "components" / "spark-etl-job" / "jobs"
sys.path.insert(0, str(JOBS_DIR))

from iceberg_compaction_util import TableRef, filter_tables, parse_scope_filters  # noqa: E402


def test_filter_tables_namespace_and_table() -> None:
    tables = [
        TableRef("ecom", "orders"),
        TableRef("ecom", "returns"),
        TableRef("analytics", "events"),
    ]
    assert filter_tables(tables, "ecom", None) == [
        TableRef("ecom", "orders"),
        TableRef("ecom", "returns"),
    ]
    assert filter_tables(tables, "ecom", "orders") == [TableRef("ecom", "orders")]


def test_parse_scope_filters_empty_means_scan_all() -> None:
    assert parse_scope_filters("", "") == (None, None)
    assert parse_scope_filters("ecom", "orders") == ("ecom", "orders")
