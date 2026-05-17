"""Unit tests for iceberg compaction scope helpers (no PySpark)."""

from __future__ import annotations

import sys
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parents[2] / "components" / "spark-etl-job" / "jobs"
sys.path.insert(0, str(JOBS_DIR))

from iceberg_compaction_util import (  # noqa: E402
    TableRef,
    filter_tables,
    parse_scope_filters,
    should_expire_snapshots,
    should_rewrite_data_files,
)


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


def test_should_rewrite_respects_min_input_files() -> None:
    assert should_rewrite_data_files(4, 4, table_readable=False) is True
    assert should_rewrite_data_files(3, 4, table_readable=False) is False


def test_should_expire_when_snapshot_count_exceeds_retain() -> None:
    assert should_expire_snapshots(0, 20, retain_last=5) == (True, True)
    assert should_expire_snapshots(0, 5, retain_last=5) == (False, False)
    assert should_expire_snapshots(2, 5, retain_last=5) == (True, False)
