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


def coalesce_data_file_count(
    metadata_files_count: int | None,
    snapshot_summary_count: int | None,
) -> int | None:
    """REST catalogs may return an empty Spark `.files` table; snapshot summary matches the Iceberg browser UI."""
    if metadata_files_count is not None and metadata_files_count > 0:
        return metadata_files_count
    if snapshot_summary_count is not None and snapshot_summary_count >= 0:
        return snapshot_summary_count
    return metadata_files_count if metadata_files_count is not None else snapshot_summary_count


def should_rewrite_data_files(
    data_files: int | None,
    min_input_files: int,
    *,
    table_readable: bool,
) -> bool:
    if data_files is not None:
        return data_files >= min_input_files
    return table_readable


def should_expire_snapshots(
    expirable_count: int | None,
    total_snapshots: int | None,
    *,
    retain_last: int,
) -> tuple[bool, bool]:
    """Return (needs_expire, expire_by_snapshot_count)."""
    if retain_last > 0 and total_snapshots is not None and total_snapshots > retain_last:
        return True, True
    if expirable_count is not None and expirable_count > 0:
        return True, False
    return False, False


def format_maintenance_skip_reason(
    *,
    do_rewrite: bool,
    do_expire: bool,
    rewrite: bool,
    expire: bool,
    orphans: bool,
    data_files: int,
    expirable_snapshots: int,
    total_snapshots: int,
    min_input_files: int,
    retain_last: int,
    expire_older_than: str,
) -> str:
    parts: list[str] = []
    if do_rewrite and not rewrite:
        if data_files >= 0:
            parts.append(f"rewrite: {data_files} data file(s) < min_input_files={min_input_files}")
        else:
            parts.append("rewrite: could not read .files metadata")
    if do_expire and not expire:
        if total_snapshots >= 0 and retain_last > 0:
            parts.append(
                f"expire: {total_snapshots} snapshot(s), none older than {expire_older_than!r} "
                f"(retain_last={retain_last} only triggers when count exceeds retain)"
            )
        elif expirable_snapshots == 0:
            parts.append(f"expire: 0 snapshots older than {expire_older_than!r}")
    if not orphans and (do_rewrite or do_expire):
        parts.append("orphans: only runs after rewrite or expire on this table")
    if not parts:
        return "no maintenance flags enabled"
    return "; ".join(parts)
