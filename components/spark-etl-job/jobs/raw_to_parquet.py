"""
PySpark driver: read CSV or JSON from S3A (MinIO) and write Parquet files to an S3 output path.

Environment (injected by DemoForge compose):
  SPARK_MASTER_URL, INPUT_S3A_URI, OUTPUT_S3A_URI,
  RAW_INPUT_FORMAT (csv | json), JSON_MULTILINE (true|false for JSON),
  S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT,
  RAW_LANDING_BUCKET, PARQUET_OUTPUT_BUCKET, INPUT_OBJECT_PREFIX (for log context),
  PARQUET_PARTITION_COLS — comma-separated column names for partitioned output (optional).
  PARQUET_COALESCE — output partitions before write (default 4; 0 to skip).
  RAW_TO_PARQUET_VERBOSE_DIAG — set true/1/yes for extra diagnostics.
  RAW_TO_PARQUET_PROGRESS_SEC — heartbeat interval in seconds (default 30; 0 to disable).
"""
from __future__ import annotations

import fnmatch
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from urllib.parse import urlparse

from pyspark.sql import SparkSession

_DF_EXPECTED_JARS = (
    "/opt/spark/jars/hadoop-aws-3.3.4.jar",
    "/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar",
)


def _diag_verbose() -> bool:
    return os.environ.get("RAW_TO_PARQUET_VERBOSE_DIAG", "").strip().lower() in ("1", "true", "yes")


def _progress_interval_sec() -> float:
    raw = (os.environ.get("RAW_TO_PARQUET_PROGRESS_SEC") or "30").strip()
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
                f"[raw_to_parquet] PROGRESS ({wall}) {label} … still running ({elapsed:.0f}s elapsed)",
                flush=True,
            )

    th = threading.Thread(target=_loop, daemon=True, name="demoforge-etl-progress")
    th.start()
    try:
        yield
    finally:
        stop.set()
        th.join(timeout=min(interval, 10.0) + 2.0)


def _parse_s3a_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def _split_input_uri_and_glob(input_uri: str) -> tuple[str, str]:
    parsed = urlparse(input_uri)
    key = parsed.path.lstrip("/")
    has_glob = any(c in key for c in ("*", "?", "["))
    if has_glob:
        parts = key.rsplit("/", 1)
        if len(parts) == 2:
            return f"s3a://{parsed.netloc}/{parts[0]}/", parts[1]
        return f"s3a://{parsed.netloc}/", parts[0]
    return input_uri, ""


def _use_recursive_glob(glob_pat: str) -> bool:
    return "/" in glob_pat or "**" in glob_pat


def _dataframe_reader_for_raw(spark: SparkSession, raw_fmt: str, json_multiline: bool, input_uri: str):
    base_uri, glob_pat = _split_input_uri_and_glob(input_uri)
    read_path = base_uri if glob_pat else input_uri
    r = spark.read
    if glob_pat:
        r = r.option("pathGlobFilter", glob_pat)
        if _use_recursive_glob(glob_pat):
            r = r.option("recursiveFileLookup", "true")
    print(
        f"[raw_to_parquet] Read path={read_path!r} pathGlobFilter={glob_pat or '(none)'} "
        f"recursiveFileLookup={_use_recursive_glob(glob_pat) if glob_pat else False}",
        flush=True,
    )
    if raw_fmt == "json":
        return r.option("multiLine", str(json_multiline).lower()).json(read_path)
    return r.option("header", "true").option("inferSchema", "true").csv(read_path)


def main() -> None:
    job_t0 = time.perf_counter()
    try:
        _main_impl(job_t0)
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"[raw_to_parquet] ERROR {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(1)


def _main_impl(job_t0: float) -> None:
    input_uri = os.environ.get("INPUT_S3A_URI", "")
    output_uri = os.environ.get("OUTPUT_S3A_URI", "")
    raw_fmt = (os.environ.get("RAW_INPUT_FORMAT") or os.environ.get("INPUT_FORMAT") or "csv").strip().lower()
    json_multiline = os.environ.get("JSON_MULTILINE", "false").strip().lower() in ("1", "true", "yes")
    s3_key = os.environ.get("S3_ACCESS_KEY", "minioadmin")
    s3_secret = os.environ.get("S3_SECRET_KEY", "minioadmin")
    s3_endpoint = os.environ.get("S3_ENDPOINT", "http://minio-1:9000")
    partition_cols_raw = (os.environ.get("PARQUET_PARTITION_COLS") or "").strip()
    partition_cols = [c.strip() for c in partition_cols_raw.split(",") if c.strip()] if partition_cols_raw else []
    coalesce_raw = (os.environ.get("PARQUET_COALESCE") or "4").strip()
    try:
        coalesce_n = int(coalesce_raw) if coalesce_raw.lower() not in ("0", "false", "off", "none") else 0
    except ValueError:
        coalesce_n = 4

    if not input_uri:
        print("[raw_to_parquet] INPUT_S3A_URI is required", flush=True)
        sys.exit(1)
    if not output_uri:
        print("[raw_to_parquet] OUTPUT_S3A_URI is required", flush=True)
        sys.exit(1)
    if raw_fmt not in ("csv", "json"):
        print(f"[raw_to_parquet] Unsupported RAW_INPUT_FORMAT={raw_fmt!r} (use csv or json)", flush=True)
        sys.exit(1)

    print(
        "[raw_to_parquet] Job config snapshot: "
        f"RAW_INPUT_FORMAT={raw_fmt} JSON_MULTILINE={json_multiline} "
        f"INPUT_S3A_URI={input_uri!r} OUTPUT_S3A_URI={output_uri!r} "
        f"PARQUET_PARTITION_COLS={partition_cols or '(none)'} "
        f"PARQUET_COALESCE={coalesce_n}",
        flush=True,
    )
    print(
        "[raw_to_parquet] S3 context: "
        f"S3_ENDPOINT={s3_endpoint} S3_ACCESS_KEY={s3_key[:4]}***",
        flush=True,
    )

    ep = s3_endpoint if s3_endpoint.startswith("http") else f"http://{s3_endpoint}"
    print("[raw_to_parquet] DIAG SparkSession.getOrCreate() starting…", flush=True)
    try:
        spark = (
            SparkSession.builder.appName("demoforge-raw-to-parquet")
            .config("spark.hadoop.fs.s3a.access.key", s3_key)
            .config("spark.hadoop.fs.s3a.secret.key", s3_secret)
            .config("spark.hadoop.fs.s3a.endpoint", ep)
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
            .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
            .config("spark.hadoop.fs.s3a.connection.ssl.enabled", str(ep.startswith("https")).lower())
            .getOrCreate()
        )
    except Exception as exc:
        print(f"[raw_to_parquet] DIAG SparkSession.getOrCreate() FAILED: {exc!r}", flush=True)
        raise

    spark.sparkContext.setLogLevel("WARN")
    print(f"[raw_to_parquet] SparkSession ready; reading {raw_fmt} from {input_uri!r}", flush=True)

    with _progress_heartbeat("Spark read (CSV/JSON scan)"):
        spark.sparkContext.setJobDescription("DemoForge: read raw files into DataFrame")
        t0 = time.perf_counter()
        df = _dataframe_reader_for_raw(spark, raw_fmt, json_multiline, input_uri)
        spark.sparkContext.setJobDescription(None)
        print(
            f"[raw_to_parquet] Read phase finished in {time.perf_counter() - t0:.1f}s; schema: "
            f"{df.schema.simpleString()}",
            flush=True,
        )

    if coalesce_n > 0:
        print(f"[raw_to_parquet] Coalescing to {coalesce_n} partitions before write", flush=True)
        df = df.coalesce(coalesce_n)

    with _progress_heartbeat("df.count() before Parquet write"):
        spark.sparkContext.setJobDescription("DemoForge: row count before Parquet write")
        try:
            nrow = df.count()
        except Exception as exc:
            print(f"[raw_to_parquet] WARN: row count failed ({exc!r})", flush=True)
            nrow = -1
        finally:
            spark.sparkContext.setJobDescription(None)
        if nrow >= 0:
            print(f"[raw_to_parquet] Row count before Parquet write: {nrow}", flush=True)

    print(f"[raw_to_parquet] Writing Parquet to {output_uri!r}", flush=True)
    with _progress_heartbeat("Parquet write"):
        spark.sparkContext.setJobDescription("DemoForge: Parquet write")
        t1 = time.perf_counter()
        writer = df.write.mode("overwrite")
        if partition_cols:
            print(f"[raw_to_parquet] Partitioning by columns: {partition_cols}", flush=True)
            writer = writer.partitionBy(*partition_cols)
        writer.parquet(output_uri)
        spark.sparkContext.setJobDescription(None)
        print(f"[raw_to_parquet] Write phase finished in {time.perf_counter() - t1:.1f}s", flush=True)

    rows_part = f"rows={nrow}" if nrow >= 0 else "rows=(count failed)"
    print(
        f"[raw_to_parquet] SUCCESS Parquet write complete {rows_part} "
        f"output={output_uri!r} wall_s={time.perf_counter() - job_t0:.1f}",
        flush=True,
    )
    spark.stop()


if __name__ == "__main__":
    main()
