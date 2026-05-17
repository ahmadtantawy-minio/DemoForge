"""
PySpark driver: discover Iceberg tables in the REST catalog and run maintenance where needed.

Scans the linked MinIO AIStor Tables catalog (SigV4 /_iceberg). Optional filters:
  ICEBERG_TARGET_NAMESPACE / ICEBERG_TARGET_TABLE — limit scope (omit to scan all tables).

Per table (Iceberg metadata):
  rewrite_data_files when data file count >= COMPACTION_MIN_INPUT_FILES
  expire_snapshots when snapshots exist older than COMPACTION_EXPIRE_SNAPSHOTS_OLDER_THAN
  remove_orphan_files after rewrite/expire on that table
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass

from pyspark.sql import SparkSession

from iceberg_compaction_util import TableRef, filter_tables, parse_scope_filters

_LOG = "[iceberg_compaction]"


@dataclass(frozen=True)
class TableMaintenancePlan:
    rewrite: bool
    expire: bool
    orphans: bool
    data_file_count: int = -1
    expirable_snapshot_count: int = -1


def _truthy(key: str, default: str = "true") -> bool:
    return (os.environ.get(key) or default).strip().lower() in ("1", "true", "yes")


def _progress_interval_sec() -> float:
    raw = (os.environ.get("COMPACTION_PROGRESS_SEC") or "30").strip()
    try:
        return float(raw)
    except ValueError:
        return 30.0


@contextmanager
def _progress_heartbeat(label: str):
    interval = _progress_interval_sec()
    if interval <= 0:
        yield
        return
    stop = threading.Event()

    def _loop() -> None:
        t0 = time.monotonic()
        while not stop.wait(timeout=interval):
            elapsed = time.monotonic() - t0
            wall = time.strftime("%H:%M:%S", time.localtime())
            print(
                f"{_LOG} PROGRESS ({wall}) {label} … still running ({elapsed:.0f}s elapsed)",
                flush=True,
            )

    th = threading.Thread(target=_loop, daemon=True, name="demoforge-compaction-progress")
    th.start()
    try:
        yield
    finally:
        stop.set()
        th.join(timeout=min(interval, 10.0) + 2.0)


def _resolved_spark_catalog_name() -> str:
    raw = (
        os.environ.get("ICEBERG_SPARK_CATALOG_NAME")
        or os.environ.get("ICEBERG_CATALOG_NAME")
        or "iceberg"
    ).strip()
    return raw or "iceberg"


def _optional_scope_filters() -> tuple[str | None, str | None]:
    return parse_scope_filters(
        os.environ.get("ICEBERG_TARGET_NAMESPACE", ""),
        os.environ.get("ICEBERG_TARGET_TABLE", ""),
        os.environ.get("COMPACTION_NAMESPACE_FILTER", ""),
        os.environ.get("COMPACTION_TABLE_FILTER", ""),
    )


def _expire_snapshots_timestamp_literal() -> str:
    raw = (os.environ.get("COMPACTION_EXPIRE_SNAPSHOTS_OLDER_THAN") or "5d").strip()
    if raw.upper().startswith("TIMESTAMP"):
        return raw
    mult = {"d": 86400, "h": 3600, "m": 60}
    try:
        unit = raw[-1].lower()
        num = int(raw[:-1])
        if unit in mult:
            secs = num * mult[unit]
        else:
            secs = int(raw)
    except ValueError:
        secs = 5 * 86400
    ts = time.gmtime(time.time() - secs)
    return time.strftime("TIMESTAMP '%Y-%m-%d %H:%M:%S.000'", ts)


def _build_spark() -> tuple[SparkSession, str]:
    rest_uri = os.environ.get("ICEBERG_REST_URI", "")
    warehouse = os.environ.get("ICEBERG_WAREHOUSE", "warehouse")
    s3_key = os.environ.get("S3_ACCESS_KEY", "minioadmin")
    s3_secret = os.environ.get("S3_SECRET_KEY", "minioadmin")
    s3_endpoint = os.environ.get("S3_ENDPOINT", "http://minio-1:9000")
    iceberg_sigv4 = _truthy("ICEBERG_SIGV4", "true")
    rest_signing_region = (os.environ.get("ICEBERG_REST_SIGNING_REGION") or "us-east-1").strip()
    rest_signing_name = (os.environ.get("ICEBERG_REST_SIGNING_NAME") or "s3tables").strip()
    s3_region = (os.environ.get("ICEBERG_S3_REGION") or rest_signing_region or "us-east-1").strip()

    if not rest_uri:
        print(f"{_LOG} ICEBERG_REST_URI is required", flush=True)
        sys.exit(1)

    catalog = _resolved_spark_catalog_name()
    ep = s3_endpoint if s3_endpoint.startswith("http") else f"http://{s3_endpoint}"
    print(
        f"{_LOG} REST catalog uri={rest_uri} catalog={catalog} warehouse={warehouse!r} "
        f"ICEBERG_SIGV4={iceberg_sigv4}",
        flush=True,
    )

    bldr = (
        SparkSession.builder.appName("demoforge-iceberg-catalog-compaction")
        .config("spark.hadoop.fs.s3a.access.key", s3_key)
        .config("spark.hadoop.fs.s3a.secret.key", s3_secret)
        .config("spark.hadoop.fs.s3a.endpoint", ep)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", str(ep.startswith("https")).lower())
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .config(f"spark.sql.catalog.{catalog}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{catalog}.catalog-impl", "org.apache.iceberg.rest.RESTCatalog")
        .config(f"spark.sql.catalog.{catalog}.uri", rest_uri)
        .config(f"spark.sql.catalog.{catalog}.warehouse", warehouse)
        .config(f"spark.sql.catalog.{catalog}.s3.endpoint", ep)
        .config(f"spark.sql.catalog.{catalog}.s3.access-key-id", s3_key)
        .config(f"spark.sql.catalog.{catalog}.s3.secret-access-key", s3_secret)
        .config(f"spark.sql.catalog.{catalog}.s3.path-style-access", "true")
        .config(f"spark.sql.catalog.{catalog}.s3.region", s3_region)
        .config("spark.executorEnv.AWS_ACCESS_KEY_ID", s3_key)
        .config("spark.executorEnv.AWS_SECRET_ACCESS_KEY", s3_secret)
        .config("spark.executorEnv.AWS_DEFAULT_REGION", s3_region)
    )
    if iceberg_sigv4:
        bldr = (
            bldr.config(f"spark.sql.catalog.{catalog}.rest.sigv4-enabled", "true")
            .config(f"spark.sql.catalog.{catalog}.rest.signing-region", rest_signing_region)
            .config(f"spark.sql.catalog.{catalog}.rest.signing-name", rest_signing_name)
            .config(f"spark.sql.catalog.{catalog}.rest.access-key-id", s3_key)
            .config(f"spark.sql.catalog.{catalog}.rest.secret-access-key", s3_secret)
        )
    spark = bldr.getOrCreate()
    return spark, catalog


def _row_field(row, *names: str, index: int = 0) -> str | None:
    for name in names:
        if hasattr(row, name):
            val = getattr(row, name)
            if val is not None:
                return str(val)
    if len(row) > index:
        return str(row[index])
    return None


def discover_iceberg_tables(spark: SparkSession, catalog: str) -> list[TableRef]:
    """List Iceberg tables from the REST catalog (all namespaces)."""
    found: list[TableRef] = []
    seen: set[tuple[str, str]] = set()

    def _add(ns: str | None, tbl: str | None) -> None:
        if not ns or not tbl:
            return
        if tbl.startswith("_") or ns.startswith("_"):
            return
        key = (ns, tbl)
        if key in seen:
            return
        seen.add(key)
        found.append(TableRef(namespace=ns, name=tbl))

    try:
        rows = spark.sql(f"SHOW TABLES IN `{catalog}`").collect()
        for row in rows:
            ns = _row_field(row, "namespace", "tableNamespace", index=0)
            tbl = _row_field(row, "tableName", "table", index=1)
            _add(ns, tbl)
        if found:
            return sorted(found, key=lambda t: (t.namespace, t.name))
    except Exception as exc:
        print(f"{_LOG} SHOW TABLES IN catalog failed ({exc!r}); trying per-namespace", flush=True)

    try:
        ns_rows = spark.sql(f"SHOW NAMESPACES IN `{catalog}`").collect()
    except Exception as exc:
        print(f"{_LOG} FATAL could not list namespaces in catalog {catalog!r}: {exc}", flush=True)
        return []

    for nrow in ns_rows:
        ns = _row_field(nrow, "namespace", "namespaceName", index=0)
        if not ns:
            continue
        try:
            trows = spark.sql(f"SHOW TABLES IN `{catalog}`.`{ns}`").collect()
        except Exception as exc:
            print(f"{_LOG} WARN skip namespace {ns}: {exc}", flush=True)
            continue
        for trow in trows:
            tbl = _row_field(trow, "tableName", "table", index=1) or _row_field(trow, index=0)
            _add(ns, tbl)

    return sorted(found, key=lambda t: (t.namespace, t.name))


def _count_data_files(spark: SparkSession, catalog: str, table: TableRef) -> int | None:
    fq = f"`{catalog}`.`{table.namespace}`.`{table.name}`"
    try:
        row = spark.sql(
            f"SELECT COUNT(*) AS c FROM {fq}.files WHERE content = 'DATA'"
        ).collect()[0]
        return int(row.c)
    except Exception:
        pass
    try:
        row = spark.sql(f"SELECT COUNT(*) AS c FROM {fq}.files").collect()[0]
        return int(row.c)
    except Exception:
        return None


def _count_expirable_snapshots(
    spark: SparkSession, catalog: str, table: TableRef, older_than_literal: str
) -> int | None:
    fq = f"`{catalog}`.`{table.namespace}`.`{table.name}`"
    try:
        row = spark.sql(
            f"SELECT COUNT(*) AS c FROM {fq}.snapshots "
            f"WHERE committed_at < {older_than_literal}"
        ).collect()[0]
        return int(row.c)
    except Exception:
        return None


def _table_is_readable(spark: SparkSession, catalog: str, table: TableRef) -> bool:
    try:
        spark.table(f"{catalog}.{table.namespace}.{table.name}").limit(1).count()
        return True
    except Exception:
        return False


def plan_table_maintenance(
    spark: SparkSession,
    catalog: str,
    table: TableRef,
    *,
    do_rewrite: bool,
    do_expire: bool,
    do_orphans: bool,
    min_input_files: int,
    older_than_literal: str,
) -> TableMaintenancePlan:
    data_files = _count_data_files(spark, catalog, table)
    expirable = _count_expirable_snapshots(spark, catalog, table, older_than_literal) if do_expire else 0

    needs_rewrite = False
    if do_rewrite:
        if data_files is not None:
            needs_rewrite = data_files >= min_input_files
        else:
            needs_rewrite = _table_is_readable(spark, catalog, table)

    needs_expire = False
    if do_expire:
        if expirable is not None:
            needs_expire = expirable > 0
        else:
            needs_expire = _table_is_readable(spark, catalog, table)

    needs_orphans = do_orphans and (needs_rewrite or needs_expire)

    return TableMaintenancePlan(
        rewrite=needs_rewrite,
        expire=needs_expire,
        orphans=needs_orphans,
        data_file_count=data_files if data_files is not None else -1,
        expirable_snapshot_count=expirable if expirable is not None else -1,
    )


def _call_procedure(spark: SparkSession, sql: str) -> None:
    print(f"{_LOG} SQL: {sql}", flush=True)
    with _progress_heartbeat(sql[:80]):
        df = spark.sql(sql)
        try:
            df.show(truncate=False)
        except Exception:
            pass


def _compact_table(
    spark: SparkSession,
    catalog: str,
    table: TableRef,
    plan: TableMaintenancePlan,
    *,
    target_bytes: str,
    min_input: str,
    older_than_literal: str,
) -> None:
    ref = table.dotted
    if not plan.rewrite and not plan.expire and not plan.orphans:
        print(
            f"{_LOG} SKIP {ref} (data_files={plan.data_file_count} "
            f"expirable_snapshots={plan.expirable_snapshot_count})",
            flush=True,
        )
        return

    print(
        f"{_LOG} MAINTAIN {ref} rewrite={plan.rewrite} expire={plan.expire} "
        f"orphans={plan.orphans} data_files={plan.data_file_count} "
        f"expirable_snapshots={plan.expirable_snapshot_count}",
        flush=True,
    )

    if plan.rewrite:
        _call_procedure(
            spark,
            "CALL system.rewrite_data_files("
            f"table => '{ref}', "
            f"options => map("
            f"'target-file-size-bytes', '{target_bytes}', "
            f"'min-input-files', '{min_input}'"
            f")"
            ")",
        )

    if plan.expire:
        _call_procedure(
            spark,
            f"CALL system.expire_snapshots(table => '{ref}', older_than => {older_than_literal})",
        )

    if plan.orphans:
        _call_procedure(spark, f"CALL system.remove_orphan_files(table => '{ref}')")


def main() -> None:
    job_t0 = time.perf_counter()
    try:
        _main_impl(job_t0)
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"{_LOG} ERROR {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(1)


def _main_impl(job_t0: float) -> None:
    target_bytes = (os.environ.get("COMPACTION_TARGET_FILE_SIZE_BYTES") or "134217728").strip()
    min_input = int((os.environ.get("COMPACTION_MIN_INPUT_FILES") or "5").strip() or "5")

    do_rewrite = _truthy("COMPACTION_REWRITE_DATA_FILES", "true")
    do_expire = _truthy("COMPACTION_EXPIRE_SNAPSHOTS", "true")
    do_orphans = _truthy("COMPACTION_REMOVE_ORPHAN_FILES", "true")
    older_than = _expire_snapshots_timestamp_literal()

    ns_filter, tbl_filter = _optional_scope_filters()

    print(
        f"{_LOG} Catalog scan mode: rewrite={do_rewrite} expire={do_expire} "
        f"remove_orphans={do_orphans} min_input_files={min_input} "
        f"namespace_filter={ns_filter!r} table_filter={tbl_filter!r}",
        flush=True,
    )

    spark, catalog = _build_spark()
    spark.sql(f"USE `{catalog}`")

    all_tables = discover_iceberg_tables(spark, catalog)
    tables = filter_tables(all_tables, ns_filter, tbl_filter)

    if not tables:
        print(
            f"{_LOG} No Iceberg tables found in catalog {catalog!r}"
            + (f" (filter ns={ns_filter!r} table={tbl_filter!r})" if ns_filter or tbl_filter else "")
            + ". Run a Raw→Iceberg load job first or adjust optional namespace/table filters.",
            flush=True,
        )
        if all_tables:
            print(f"{_LOG} Tables in catalog (unfiltered):", flush=True)
            for t in all_tables:
                print(f"{_LOG}   {t.namespace}.{t.name}", flush=True)
        sys.exit(0)

    print(f"{_LOG} Discovered {len(tables)} table(s) to evaluate:", flush=True)
    for t in tables:
        print(f"{_LOG}   {t.namespace}.{t.name}", flush=True)

    failures: list[str] = []
    maintained = 0
    skipped = 0

    for table in tables:
        try:
            plan = plan_table_maintenance(
                spark,
                catalog,
                table,
                do_rewrite=do_rewrite,
                do_expire=do_expire,
                do_orphans=do_orphans,
                min_input_files=min_input,
                older_than_literal=older_than,
            )
            if not plan.rewrite and not plan.expire and not plan.orphans:
                skipped += 1
            else:
                _compact_table(
                    spark,
                    catalog,
                    table,
                    plan,
                    target_bytes=target_bytes,
                    min_input=str(min_input),
                    older_than_literal=older_than,
                )
                maintained += 1
        except Exception as exc:
            msg = f"{table.dotted}: {type(exc).__name__}: {exc}"
            print(f"{_LOG} ERROR {msg}", flush=True)
            failures.append(msg)

    elapsed = time.perf_counter() - job_t0
    print(
        f"{_LOG} Finished in {elapsed:.1f}s: maintained={maintained} skipped={skipped} "
        f"failed={len(failures)}",
        flush=True,
    )
    if failures:
        for f in failures:
            print(f"{_LOG}   {f}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
