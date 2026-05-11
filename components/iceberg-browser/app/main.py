"""Iceberg Browser — DemoForge component.

REST catalog navigation (namespaces, tables, snapshots) plus PyIceberg-backed
row preview and sample column statistics. Supports AIStor SigV4 catalogs.
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
import threading
import time
from typing import Any
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Iceberg Browser")

_catalog_lock = threading.Lock()
_catalog_cache: tuple[float, Any] | None = None
_CATALOG_TTL_SEC = 30.0


def _env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _rest_uri() -> str:
    raw = (os.environ.get("ICEBERG_REST_URI") or os.environ.get("ICEBERG_CATALOG_URI") or "").strip()
    return raw


def _warehouse() -> str:
    raw = (os.environ.get("ICEBERG_WAREHOUSE") or "warehouse").strip()
    sigv4 = _env_bool("ICEBERG_SIGV4", False)
    if sigv4:
        return raw
    if raw.startswith("s3://"):
        return raw
    return f"s3://{raw}/" if raw else "s3://warehouse/"


def _s3_endpoint() -> str:
    ep = (os.environ.get("S3_ENDPOINT") or "http://localhost:9000").strip()
    return ep if ep.startswith("http") else f"http://{ep}"


def _preview_limit() -> int:
    try:
        n = int(os.environ.get("ICEBERG_PREVIEW_ROW_LIMIT", "200"))
    except ValueError:
        n = 200
    return max(1, min(n, 5000))


def _stats_sample_limit() -> int:
    try:
        n = int(os.environ.get("ICEBERG_STATS_SAMPLE_LIMIT", "5000"))
    except ValueError:
        n = 5000
    return max(100, min(n, 100_000))


def _query_timeout_sec() -> float:
    try:
        return float(os.environ.get("ICEBERG_QUERY_TIMEOUT_SEC", "90"))
    except ValueError:
        return 90.0


def _summary_long(summary: dict[str, Any], key: str) -> int | None:
    v = summary.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(str(v)))
        except (TypeError, ValueError):
            return None


def _iso_utc_from_ms(ts_ms: int | None) -> str | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


def _humanize_gap_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    ms = abs(ms)
    sec = ms // 1000
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    if sec < 86400:
        return f"{sec // 3600}h {(sec % 3600) // 60}m"
    d = sec // 86400
    return f"{d}d"


def _relative_commit_label(ts_ms: int | None) -> str | None:
    """Human-readable age of snapshot commit (matches UI snapshot dropdown style)."""
    if ts_ms is None:
        return None
    sec = int((time.time() * 1000 - ts_ms) / 1000)
    if sec < 0:
        return "from now"
    if sec < 60:
        return f"{sec}s ago"
    if sec < 3600:
        return f"{sec // 60}m ago"
    if sec < 86400:
        return f"{sec // 3600}h ago"
    return f"{sec // 86400}d ago"


def _compact_scan_stats(tbl: Any, sid: int | None, sl: int, deadline: float) -> dict[str, Any]:
    """Aggregate null density over a bounded scan (same semantics as Column stats tab)."""
    scan = _data_scan(tbl, sid, sl)
    arrow = scan.to_arrow()
    if time.monotonic() > deadline:
        raise TimeoutError("snapshot compare stats scan timeout")
    n = arrow.num_rows
    cols = arrow.column_names
    null_cells = 0
    cells = n * len(cols) if cols else 0
    for name in cols:
        col = arrow.column(name)
        for i in range(n):
            if col[i].as_py() is None:
                null_cells += 1
    return {
        "sample_rows_scanned": n,
        "columns_in_sample": len(cols),
        "approx_null_cell_rate": round(null_cells / cells, 6) if cells else 0.0,
    }


def _trino_catalog_name() -> str:
    """Trino / AIStor catalog id (compose derives from MinIO ``AISTOR_TABLES_CATALOG_NAME``, not the edge)."""
    return (os.environ.get("TRINO_CATALOG") or "").strip()


def _get_pyiceberg_catalog():
    """Build a PyIceberg RestCatalog (cached briefly)."""
    global _catalog_cache
    uri = _rest_uri()
    if not uri:
        raise RuntimeError("ICEBERG_REST_URI (or ICEBERG_CATALOG_URI) is not set")
    sigv4 = _env_bool("ICEBERG_SIGV4", False)
    if sigv4 and "-lb:80" in uri:
        uri = uri.replace("-lb:80", "-pool1-node-1:9000")
    wh = _warehouse()
    ep = _s3_endpoint()
    ak = os.environ.get("S3_ACCESS_KEY", "minioadmin")
    sk = os.environ.get("S3_SECRET_KEY", "minioadmin")
    region = (os.environ.get("ICEBERG_REST_SIGNING_REGION") or "us-east-1").strip()
    signing_name = (os.environ.get("ICEBERG_REST_SIGNING_NAME") or "s3tables").strip()

    now = time.monotonic()
    with _catalog_lock:
        if _catalog_cache and now - _catalog_cache[0] < _CATALOG_TTL_SEC:
            return _catalog_cache[1]

    from pyiceberg.catalog.rest import RestCatalog

    props: dict[str, str] = {
        "uri": uri,
        "warehouse": wh,
        "s3.endpoint": ep,
        "s3.access-key-id": ak,
        "s3.secret-access-key": sk,
        "s3.path-style-access": "true",
        "s3.region": region,
        "py-io-impl": "pyiceberg.io.fsspec.FsspecFileIO",
    }
    if sigv4:
        os.environ.setdefault("AWS_ACCESS_KEY_ID", ak)
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", sk)
        os.environ.setdefault("AWS_DEFAULT_REGION", region)
        props["rest.sigv4-enabled"] = "true"
        props["rest.signing-region"] = region
        props["rest.signing-name"] = signing_name

    cat_name = _trino_catalog_name() or "iceberg-browser"
    cat = RestCatalog(name=cat_name, **props)
    with _catalog_lock:
        _catalog_cache = (now, cat)
    return cat


def _invalidate_catalog_cache() -> None:
    global _catalog_cache
    with _catalog_lock:
        _catalog_cache = None


def _ns_tuple_from_param(ns: str) -> tuple[str, ...]:
    """Decode namespace query: use literal \\x1f between parts (also accept %1F or legacy '.')."""
    if not ns or not ns.strip():
        raise HTTPException(400, "namespace (ns) is required")
    raw = unquote(ns.strip())
    if "\x1f" in raw:
        return tuple(p for p in raw.split("\x1f") if p)
    if "\u001f" in raw:
        return tuple(p for p in raw.split("\u001f") if p)
    if "%1F" in raw.upper():
        # normalized lower for split inconsistency — use casefold
        parts = re.split(re.escape("%1F"), raw, flags=re.IGNORECASE)
        return tuple(unquote(p) for p in parts if p)
    if "." in raw and "%1F" not in raw.upper():
        return (raw,)
    return (raw,)


def _load_table(cat, ns: tuple[str, ...], table: str):
    """PyIceberg load_table: str for single-part NS, tuple (*ns, table) for nested namespaces."""
    if len(ns) == 1:
        return cat.load_table(f"{ns[0]}.{table}")
    return cat.load_table((*ns, table))


def _snapshot_id_from_query(raw: str | int | None) -> int | None:
    """Parse snapshot id from query; string avoids JS Number precision loss for large Iceberg ids."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise HTTPException(400, f"invalid snapshot_id: {raw!r}") from None


def _data_scan(tbl, snapshot_id: int | None, limit_rows: int | None):
    """PyIceberg 0.11+: row cap is ``Table.scan(limit=…)``, not ``DataScan.limit()`` — ``limit`` on DataScan is an int field."""
    return tbl.scan(snapshot_id=snapshot_id, limit=limit_rows)


@app.get("/health")
def health():
    try:
        if not _rest_uri():
            return JSONResponse({"status": "degraded", "detail": "ICEBERG_REST_URI not configured"}, status_code=503)
        cat = _get_pyiceberg_catalog()
        cat.list_namespaces()
        return {"status": "ok", "catalog": _rest_uri()[:80]}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)


@app.get("/api/config")
def api_config():
    uri = _rest_uri()
    tc = _trino_catalog_name()
    return {
        "iceberg_rest_uri_configured": bool(uri),
        "iceberg_rest_uri_preview": uri[:120] + ("…" if len(uri) > 120 else "") if uri else "",
        "warehouse": _warehouse(),
        "sigv4": _env_bool("ICEBERG_SIGV4", False),
        "preview_row_limit": _preview_limit(),
        "stats_sample_limit": _stats_sample_limit(),
        "query_timeout_sec": _query_timeout_sec(),
        "trino_web_url": (os.environ.get("TRINO_WEB_URL") or "").strip(),
        "trino_catalog": tc,
    }


@app.get("/api/namespaces")
def list_namespaces(parent: str | None = Query(None, description="Parent namespace segments (same encoding as ns)")):
    try:
        cat = _get_pyiceberg_catalog()
        parent_tuple: tuple[str, ...] | None = None
        if parent and parent.strip():
            parent_tuple = _ns_tuple_from_param(parent)
        try:
            rows = cat.list_namespaces(parent=parent_tuple)
        except TypeError:
            rows = cat.list_namespaces()
        out = [{"segments": list(t)} for t in rows]
        return {"namespaces": out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/tables")
def list_tables(ns: str = Query(..., description="Namespace segments; multi-part joined with \\x1f or %1F")):
    try:
        cat = _get_pyiceberg_catalog()
        nst = _ns_tuple_from_param(ns)
        names = cat.list_tables(nst)
        tables = []
        for ident in names:
            if isinstance(ident, tuple):
                tables.append(ident[-1])
            else:
                tables.append(str(ident))
        return {"namespace": list(nst), "tables": sorted(set(tables))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/table/metadata")
def table_metadata(
    ns: str = Query(...),
    table: str = Query(...),
):
    try:
        cat = _get_pyiceberg_catalog()
        nst = _ns_tuple_from_param(ns)
        tbl = _load_table(cat, nst, table)
        meta = tbl.metadata
        snaps = []
        for s in meta.snapshots:
            summ = {}
            if s.summary is not None and hasattr(s.summary, "additional_properties"):
                summ = dict(s.summary.additional_properties)
            snaps.append(
                {
                    "snapshot_id": s.snapshot_id,
                    # JS Number loses Iceberg ids > 2^53-1; use this for query params / dropdown values.
                    "snapshot_id_str": str(s.snapshot_id),
                    "parent_snapshot_id": getattr(s, "parent_snapshot_id", None),
                    "timestamp_ms": s.timestamp_ms,
                    "manifest_list": getattr(s, "manifest_list", None),
                    "summary": summ,
                }
            )
        refs = {}
        for k, v in (meta.refs or {}).items():
            refs[k] = {"snapshot_id": v.snapshot_id, "type": str(v.snapshot_ref_type)}
        fields = [
            {
                "id": f.field_id,
                "name": f.name,
                "type": str(f.field_type),
                "required": f.required,
            }
            for f in meta.schema().fields
        ]
        schemas_out = []
        try:
            for sid, sc in meta.schemas.items():
                schemas_out.append(
                    {
                        "schema_id": sid,
                        "fields": [{"name": x.name, "type": str(x.field_type)} for x in sc.fields],
                    }
                )
        except Exception:
            pass
        try:
            pspec = str(meta.spec())
        except Exception:
            pspec = ""
        ident_str = f"{nst[0]}.{table}" if len(nst) == 1 else "\x1f".join(nst) + f"\x1f{table}"
        return {
            "identifier": ident_str,
            "format_version": meta.format_version,
            "uuid": str(meta.table_uuid),
            "location": meta.location,
            "schemas": schemas_out,
            "current_schema_id": meta.current_schema_id,
            "fields": fields,
            "partition_spec": pspec,
            "snapshots": snaps,
            "refs": refs,
            "current_snapshot_id": meta.current_snapshot_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/table/snapshots")
def table_snapshots(ns: str = Query(...), table: str = Query(...)):
    """Alias-friendly list for UI dropdown."""
    return table_metadata(ns=ns, table=table)


@app.get("/api/table/preview")
def table_preview(
    ns: str = Query(...),
    table: str = Query(...),
    snapshot_id: str | None = Query(
        None,
        description="Snapshot id as decimal string (recommended for ids larger than JS MAX_SAFE_INTEGER)",
    ),
    limit: int | None = Query(None),
):
    sid = _snapshot_id_from_query(snapshot_id)
    lim = limit if limit is not None else _preview_limit()
    lim = max(1, min(lim, 5000))
    deadline = time.monotonic() + _query_timeout_sec()
    try:
        cat = _get_pyiceberg_catalog()
        nst = _ns_tuple_from_param(ns)
        tbl = _load_table(cat, nst, table)
        scan = _data_scan(tbl, sid, lim)
        if time.monotonic() > deadline:
            raise TimeoutError("deadline before scan")
        arrow = scan.to_arrow()
        if time.monotonic() > deadline:
            raise TimeoutError("deadline after scan")
        cols = arrow.column_names
        rows = []
        for i in range(arrow.num_rows):
            row = {}
            for c in cols:
                v = arrow.column(c)[i].as_py()
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    row[c] = None
                elif hasattr(v, "isoformat"):
                    row[c] = v.isoformat()
                else:
                    row[c] = v
            rows.append(row)
        return {
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "snapshot_id": sid,
            "snapshot_id_str": str(sid) if sid is not None else None,
            "truncated": len(rows) >= lim,
        }
    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(504, str(e)) from e
    except Exception as e:
        _invalidate_catalog_cache()
        raise HTTPException(502, str(e)) from e


@app.get("/api/table/stats")
def table_stats(
    ns: str = Query(...),
    table: str = Query(...),
    snapshot_id: str | None = Query(
        None,
        description="Snapshot id as decimal string (recommended for ids larger than JS MAX_SAFE_INTEGER)",
    ),
    sample_limit: int | None = Query(None),
):
    """Approximate stats from a bounded scan (not full-table statistics)."""
    sid = _snapshot_id_from_query(snapshot_id)
    sl = sample_limit if sample_limit is not None else _stats_sample_limit()
    sl = max(50, min(sl, 100_000))
    deadline = time.monotonic() + _query_timeout_sec()
    try:
        cat = _get_pyiceberg_catalog()
        nst = _ns_tuple_from_param(ns)
        tbl = _load_table(cat, nst, table)
        scan = _data_scan(tbl, sid, sl)
        arrow = scan.to_arrow()
        if time.monotonic() > deadline:
            raise TimeoutError("stats scan timeout")
        n = arrow.num_rows
        columns = []
        for name in arrow.column_names:
            col = arrow.column(name)
            nulls = sum(1 for i in range(n) if col[i].as_py() is None)
            non_null = n - nulls
            stat: dict[str, Any] = {
                "name": name,
                "sample_rows": n,
                "null_count": nulls,
                "non_null_count": non_null,
                "null_rate_approx": round(nulls / n, 6) if n else 0.0,
            }
            # numeric min/max on non-null sample
            nums = []
            for i in range(n):
                v = col[i].as_py()
                if v is None:
                    continue
                if isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                    nums.append(float(v))
            if nums:
                stat["sample_min"] = min(nums)
                stat["sample_max"] = max(nums)
            columns.append(stat)
        return {
            "namespace": list(_ns_tuple_from_param(ns)),
            "table": table,
            "snapshot_id": sid,
            "snapshot_id_str": str(sid) if sid is not None else None,
            "sample_rows": n,
            "columns": columns,
            "note": "Stats are computed from the first N rows of a scan (see sample_rows), not full-table statistics.",
        }
    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(504, str(e)) from e
    except Exception as e:
        raise HTTPException(502, str(e)) from e


_SNAPSHOT_COMPARE_STATS_CAP = 8


@app.get("/api/table/snapshot-compare")
def snapshot_compare(
    ns: str = Query(...),
    table: str = Query(...),
    limit: int = Query(10, ge=1, le=50, description="Last N snapshots by commit time (newest first)"),
    include_sample_stats: bool = Query(
        False,
        description="Run bounded scan per snapshot for approximate null density (slow for many snapshots)",
    ),
    stats_sample_limit: int | None = Query(
        None,
        description="Rows to scan per snapshot when include_sample_stats=true",
    ),
):
    """Compare Iceberg snapshot metadata (and optionally sample scans) for the last ``limit`` commits."""
    deadline_global = time.monotonic() + _query_timeout_sec()
    try:
        cat = _get_pyiceberg_catalog()
        nst = _ns_tuple_from_param(ns)
        tbl = _load_table(cat, nst, table)
        meta = tbl.metadata
        snaps = list(meta.snapshots)
        if not snaps:
            return {
                "namespace": list(nst),
                "table": table,
                "limit_requested": limit,
                "snapshots_compared": 0,
                "window_span_ms": None,
                "window_span_human": None,
                "notes": ["No snapshots in table metadata."],
                "rows": [],
            }
        snaps.sort(key=lambda s: s.timestamp_ms, reverse=True)
        chosen = snaps[:limit]

        sl = stats_sample_limit if stats_sample_limit is not None else _stats_sample_limit()
        sl = max(50, min(sl, 100_000))

        notes: list[str] = []
        if include_sample_stats and len(chosen) > _SNAPSHOT_COMPARE_STATS_CAP:
            notes.append(
                f"Sample stats limited to the {_SNAPSHOT_COMPARE_STATS_CAP} newest snapshots "
                f"(requested {len(chosen)})."
            )

        rows_out: list[dict[str, Any]] = []
        stats_budget = _SNAPSHOT_COMPARE_STATS_CAP if include_sample_stats else 0

        for i, s in enumerate(chosen):
            summ: dict[str, Any] = {}
            if s.summary is not None and hasattr(s.summary, "additional_properties"):
                summ = dict(s.summary.additional_properties)

            ts = s.timestamp_ms
            gap_ms = None
            if i < len(chosen) - 1:
                gap_ms = ts - chosen[i + 1].timestamp_ms

            schema_id = getattr(s, "schema_id", None)
            ncol: int | None = None
            if schema_id is not None:
                try:
                    sch = meta.schemas.get(schema_id)
                    if sch is not None:
                        ncol = len(sch.fields)
                except Exception:
                    ncol = None
            if ncol is None:
                try:
                    ncol = len(meta.schema().fields)
                except Exception:
                    ncol = None

            row: dict[str, Any] = {
                "snapshot_id": s.snapshot_id,
                "snapshot_id_str": str(s.snapshot_id),
                "committed_at_ms": ts,
                "committed_at_iso": _iso_utc_from_ms(ts),
                "relative_commit": _relative_commit_label(ts),
                "gap_ms_to_next_older": gap_ms,
                "gap_human_to_next_older": _humanize_gap_ms(gap_ms),
                "total_records_summary": _summary_long(summ, "total-records"),
                "total_data_files_summary": _summary_long(summ, "total-data-files"),
                "total_delete_files_summary": _summary_long(summ, "total-delete-files"),
                "added_records_summary": _summary_long(summ, "added-records"),
                "deleted_records_summary": _summary_long(summ, "deleted-records"),
                "added_data_files_summary": _summary_long(summ, "added-data-files"),
                "schema_id": schema_id,
                "column_count": ncol,
                "operation": summ.get("operation"),
            }

            if include_sample_stats and i < stats_budget:
                if time.monotonic() > deadline_global:
                    row["sample_scan"] = {"error": "skipped (compare request timeout budget)"}
                else:
                    try:
                        dl = min(deadline_global, time.monotonic() + _query_timeout_sec() * 0.25)
                        row["sample_scan"] = _compact_scan_stats(tbl, s.snapshot_id, sl, dl)
                    except TimeoutError as e:
                        row["sample_scan"] = {"error": str(e)}
                        notes.append(f"Sample scan timed out for snapshot {s.snapshot_id}.")

            rows_out.append(row)

        span_ms = None
        span_h = None
        if len(chosen) >= 2:
            span_ms = chosen[0].timestamp_ms - chosen[-1].timestamp_ms
            span_h = _humanize_gap_ms(span_ms)

        if include_sample_stats:
            notes.append(
                "total-* and added-* come from snapshot summary when the engine wrote them; "
                "sample_scan is a bounded table scan (approximate null density), not full-table stats."
            )

        return {
            "namespace": list(nst),
            "table": table,
            "limit_requested": limit,
            "snapshots_compared": len(rows_out),
            "window_span_ms": span_ms,
            "window_span_human": span_h,
            "notes": notes,
            "rows": rows_out,
        }
    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(504, str(e)) from e
    except Exception as e:
        _invalidate_catalog_cache()
        raise HTTPException(502, str(e)) from e


@app.get("/api/catalog-curl")
def catalog_curl():
    """Shell snippets for REST /v1/config (unsigned). For SigV4, use this UI or AWS CLI with sigv4."""
    uri = _rest_uri()
    if not uri:
        raise HTTPException(400, "ICEBERG_REST_URI not set")
    wh = quote(_warehouse(), safe="")
    base = uri.rstrip("/")
    unsigned = f"curl -sS '{base}/v1/config?warehouse={wh}'"
    sigv4 = _env_bool("ICEBERG_SIGV4", False)
    return {
        "unsigned_config_curl": unsigned,
        "sigv4": sigv4,
        "sigv4_note": (
            "This catalog uses SigV4. Plain curl without AWS signing will fail. "
            "Use the Iceberg Browser UI, PyIceberg, or: aws curl / awscurl with SigV4."
        )
        if sigv4
        else None,
        "list_namespaces_curl": f"curl -sS '{base}/v1/namespaces'",
    }


app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
