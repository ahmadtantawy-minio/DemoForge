"""
PySpark driver: Iceberg REST catalog maintenance (rewrite data files, expire snapshots, remove orphans).

Requires a deployed Iceberg table via AIStor Tables (/_iceberg REST catalog v3).

Environment (injected by DemoForge compose):
  SPARK_MASTER_URL, ICEBERG_REST_URI, ICEBERG_WAREHOUSE,
  ICEBERG_TARGET_NAMESPACE, ICEBERG_TARGET_TABLE,
  ICEBERG_SPARK_CATALOG_NAME, S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT,
  ICEBERG_SIGV4, ICEBERG_REST_SIGNING_REGION, ICEBERG_REST_SIGNING_NAME,
  COMPACTION_REWRITE_DATA_FILES (default true),
  COMPACTION_EXPIRE_SNAPSHOTS (default true),
  COMPACTION_EXPIRE_SNAPSHOTS_OLDER_THAN (default 5d),
  COMPACTION_REMOVE_ORPHAN_FILES (default true),
  COMPACTION_TARGET_FILE_SIZE_BYTES (default 134217728),
  COMPACTION_MIN_INPUT_FILES (default 5),
  COMPACTION_PROGRESS_SEC (default 30),
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager

from pyspark.sql import SparkSession

_LOG = "[iceberg_compaction]"


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


def _expire_snapshots_timestamp_literal() -> str:
    """Iceberg procedure older_than: use day offset env like 5d, 24h, or raw TIMESTAMP string."""
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


def _call_procedure(spark: SparkSession, sql: str) -> None:
    print(f"{_LOG} SQL: {sql}", flush=True)
    with _progress_heartbeat(sql[:80]):
        df = spark.sql(sql)
        try:
            df.show(truncate=False)
        except Exception:
            pass


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
    ns = os.environ.get("ICEBERG_TARGET_NAMESPACE", "analytics")
    table = os.environ.get("ICEBERG_TARGET_TABLE", "events_from_raw")
    table_ref = f"{ns}.{table}"
    target_bytes = (os.environ.get("COMPACTION_TARGET_FILE_SIZE_BYTES") or "134217728").strip()
    min_input = (os.environ.get("COMPACTION_MIN_INPUT_FILES") or "5").strip()

    do_rewrite = _truthy("COMPACTION_REWRITE_DATA_FILES", "true")
    do_expire = _truthy("COMPACTION_EXPIRE_SNAPSHOTS", "true")
    do_orphans = _truthy("COMPACTION_REMOVE_ORPHAN_FILES", "true")

    print(
        f"{_LOG} Target table={table_ref} steps: "
        f"rewrite_data_files={do_rewrite} expire_snapshots={do_expire} remove_orphan_files={do_orphans}",
        flush=True,
    )

    spark, catalog = _build_spark()
    spark.sql(f"USE `{catalog}`")

    if do_rewrite:
        _call_procedure(
            spark,
            "CALL system.rewrite_data_files("
            f"table => '{table_ref}', "
            f"options => map("
            f"'target-file-size-bytes', '{target_bytes}', "
            f"'min-input-files', '{min_input}'"
            f")"
            ")",
        )
        print(f"{_LOG} rewrite_data_files completed for {table_ref}", flush=True)

    if do_expire:
        older_than = _expire_snapshots_timestamp_literal()
        _call_procedure(
            spark,
            f"CALL system.expire_snapshots(table => '{table_ref}', older_than => {older_than})",
        )
        print(f"{_LOG} expire_snapshots completed for {table_ref} ({older_than})", flush=True)

    if do_orphans:
        _call_procedure(
            spark,
            f"CALL system.remove_orphan_files(table => '{table_ref}')",
        )
        print(f"{_LOG} remove_orphan_files completed for {table_ref}", flush=True)

    elapsed = time.perf_counter() - job_t0
    print(f"{_LOG} Catalog compaction finished OK in {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
