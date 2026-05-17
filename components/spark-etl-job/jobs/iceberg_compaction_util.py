"""Pure helpers for iceberg catalog compaction (no PySpark dependency)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableRef:
    namespace: str
    name: str

    @property
    def dotted(self) -> str:
        return f"{self.namespace}.{self.name}"


def filter_tables(
    tables: list[TableRef],
    namespace_filter: str | None,
    table_filter: str | None,
) -> list[TableRef]:
    out = tables
    if namespace_filter:
        out = [t for t in out if t.namespace == namespace_filter]
    if table_filter:
        out = [t for t in out if t.name == table_filter]
    return out


def parse_scope_filters(
    namespace: str = "",
    table: str = "",
    namespace_alt: str = "",
    table_alt: str = "",
) -> tuple[str | None, str | None]:
    """Map env-style strings to optional filters (empty = scan all)."""
    ns = (namespace or namespace_alt or "").strip() or None
    tbl = (table or table_alt or "").strip() or None
    return ns, tbl
