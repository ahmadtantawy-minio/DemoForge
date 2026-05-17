"""Unit tests for Raw→Iceberg write-mode helpers (no PySpark)."""

from __future__ import annotations

import sys
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parents[1] / "components" / "spark-etl-job" / "jobs"
sys.path.insert(0, str(JOBS_DIR))

from csv_glob_to_iceberg import (  # noqa: E402
    _is_missing_table_error,
    _resolve_iceberg_write_mode,
)


def test_resolve_iceberg_write_mode_defaults_append(monkeypatch) -> None:
    monkeypatch.delenv("ICEBERG_WRITE_MODE", raising=False)
    assert _resolve_iceberg_write_mode() == "append"


def test_resolve_iceberg_write_mode_replace_aliases(monkeypatch) -> None:
    monkeypatch.setenv("ICEBERG_WRITE_MODE", "createOrReplace")
    assert _resolve_iceberg_write_mode() == "replace"


def test_is_missing_table_error() -> None:
    assert _is_missing_table_error(RuntimeError("Table ecom.orders not found"))
    assert _is_missing_table_error(Exception("NoSuchTableException: ns.tbl"))
    assert not _is_missing_table_error(RuntimeError("Connection refused"))
