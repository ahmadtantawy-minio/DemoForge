"""
PySpark driver: read CSV or JSON from S3A (MinIO) and create/replace an Iceberg table via REST catalog.

Environment (injected by DemoForge compose):
  SPARK_MASTER_URL, INPUT_S3A_URI, ICEBERG_REST_URI, ICEBERG_WAREHOUSE,
  ICEBERG_TARGET_NAMESPACE, ICEBERG_TARGET_TABLE,
  RAW_INPUT_FORMAT (csv | json), JSON_MULTILINE (true|false for JSON),
  S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT,
  RAW_LANDING_BUCKET, WAREHOUSE_BUCKET, INPUT_OBJECT_PREFIX (for log context)
  ICEBERG_SPARK_CATALOG_NAME — Spark catalog name for REST Iceberg (default iceberg; from MinIO/cluster or job override).
  RAW_TO_ICEBERG_ARCHIVE_PREFIX — key prefix in the same raw bucket to move processed objects after success (empty = off).
  RAW_TO_ICEBERG_VERBOSE_DIAG — set true/1/yes to print every java.class.path entry that mentions hadoop-aws / iceberg / aws-sdk.
  RAW_INPUT_GLOB_RECURSIVE — set true/1/yes to list/read CSV/JSON under subdirectories (pathGlobFilter + recursive listing).
  RAW_TO_ICEBERG_PROGRESS_SEC — heartbeat interval in seconds during inventory/read/write (default 30; set 0 to disable).
  RAW_TO_ICEBERG_SPARK_LOG_LEVEL — e.g. INFO during long phases only (then restored); empty keeps prior driver level.
  RAW_TO_ICEBERG_COALESCE — partitions before Iceberg write (default 8; set 0/false/off to skip). Reduces tiny output files / driver chatter for many small CSVs.
  SPARK_SQL_FILES_MAX_PARTITION_BYTES / SPARK_SQL_FILES_OPEN_COST_BYTES — tune how Spark groups small files when scanning (defaults set for small-file batches).
"""
from __future__ import annotations

import fnmatch
import os
import re
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
    "/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar",
    "/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar",
)


def _diag_verbose() -> bool:
    return os.environ.get("RAW_TO_ICEBERG_VERBOSE_DIAG", "").strip().lower() in ("1", "true", "yes")


def _progress_interval_sec() -> float:
    raw = (os.environ.get("RAW_TO_ICEBERG_PROGRESS_SEC") or "30").strip()
    try:
        return float(raw)
    except ValueError:
        return 30.0


@contextmanager
def _progress_heartbeat(label: str):
    """Emit [raw_to_iceberg] PROGRESS lines on a timer while the driver blocks on Spark/Hadoop work."""
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
                f"[raw_to_iceberg] PROGRESS ({wall}) {label} … still running ({elapsed:.0f}s elapsed)",
                flush=True,
            )

    th = threading.Thread(target=_loop, daemon=True, name="demoforge-etl-progress")
    th.start()
    try:
        yield
    finally:
        stop.set()
        th.join(timeout=min(interval, 10.0) + 2.0)


def _spark_file_scan_conf_from_env() -> dict[str, str]:
    """Prefer fewer / larger scan partitions when many small objects share a prefix."""
    return {
        "spark.sql.files.maxPartitionBytes": (
            os.environ.get("SPARK_SQL_FILES_MAX_PARTITION_BYTES") or "134217728"
        ).strip(),
        "spark.sql.files.openCostInBytes": (
            os.environ.get("SPARK_SQL_FILES_OPEN_COST_BYTES") or "16777216"
        ).strip(),
    }


def _ensure_iceberg_namespace(spark: SparkSession, catalog: str, ns: str) -> None:
    """AIStor / REST catalogs require the namespace to exist before CTAS or DataFrameWriter createOrReplace."""
    try:
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS `{catalog}`.`{ns}`")
        print(f"[raw_to_iceberg] CREATE NAMESPACE IF NOT EXISTS {catalog}.{ns} (ok)", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[raw_to_iceberg] WARN namespace ensure failed for {catalog}.{ns}: {exc!r}", flush=True)


def _log_spark_executor_snapshot(spark: SparkSession, phase: str) -> None:
    """Surface WAITING apps (0 workers) — common when Spark runs master-only."""
    try:
        sc = spark.sparkContext
        _st = getattr(sc, "statusTracker", None)
        tracker = _st() if callable(_st) else _st
        infos = tracker.getExecutorInfos()
        dp = sc.defaultParallelism
        print(
            f"[raw_to_iceberg] Spark cluster snapshot ({phase}): "
            f"executor_count={len(infos)} defaultParallelism={dp}",
            flush=True,
        )
        if len(infos) == 0:
            print(
                "[raw_to_iceberg] WARN executor_count=0 — standalone jobs need ≥1 worker registered with the master. "
                "If Spark Master UI shows Workers: 0, apps stay WAITING until you fix the Spark container (master+worker start).",
                flush=True,
            )
        else:
            for i, inf in enumerate(infos[:16]):
                print(f"[raw_to_iceberg]   executor[{i}] {inf!r}", flush=True)
            if len(infos) > 16:
                print(f"[raw_to_iceberg]   … {len(infos) - 16} more executors", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[raw_to_iceberg] WARN could not read executor snapshot ({phase}): {e!r}", flush=True)


def _apply_coalesce_before_write(df, n_matched: int):
    """Merge partitions before Iceberg write so many small files don't explode driver/commit work."""
    raw = (os.environ.get("RAW_TO_ICEBERG_COALESCE") or "8").strip().lower()
    if raw in ("0", "", "false", "no", "off"):
        print("[raw_to_iceberg] coalesce skipped (RAW_TO_ICEBERG_COALESCE disabled)", flush=True)
        return df
    try:
        cap = int(raw)
    except ValueError:
        cap = 8
    if cap <= 0:
        return df
    use = min(cap, max(1, n_matched)) if n_matched > 0 else cap
    print(
        f"[raw_to_iceberg] coalesce({use}) before Iceberg write "
        f"(RAW_TO_ICEBERG_COALESCE={raw!r}; merges partitions, not separate jobs per file)",
        flush=True,
    )
    return df.coalesce(use)


@contextmanager
def _spark_driver_log_level_for_long_phases(spark: SparkSession):
    """Optionally raise Spark driver log verbosity during blocking actions (schema inference, shuffle, commit)."""
    raw = (os.environ.get("RAW_TO_ICEBERG_SPARK_LOG_LEVEL") or "").strip()
    if not raw:
        yield
        return
    level = raw.upper()
    sc = spark.sparkContext
    prev = sc.getLogLevel()
    sc.setLogLevel(level)
    print(f"[raw_to_iceberg] Spark driver log level -> {level} (was {prev}) for long phases", flush=True)
    try:
        yield
    finally:
        sc.setLogLevel(prev)


def _spark_env_classloader(spark: SparkSession):
    """SparkEnv.classLoader (MutableURLClassLoader); parent chain must still see hadoop-common et al."""
    jvm = spark.sparkContext._jvm
    try:
        return spark.sparkContext._jsc.sc().env().classLoader()
    except Exception:
        pass
    try:
        env = jvm.org.apache.spark.SparkEnv.get()
        if env is not None:
            return env.classLoader()
    except Exception:
        pass
    return jvm.org.apache.spark.util.Utils.getContextOrSparkClassLoader()


def _hadoop_configuration_loader_with_demoforge_jars(spark: SparkSession, parent):
    """
    Hadoop Configuration.getClass uses Configuration.classLoader, not only TCCL.
    Child URLClassLoader lists our S3A/Iceberg jars explicitly so S3AFileSystem resolves reliably under PySpark.
    """
    jvm = spark.sparkContext._jvm
    gw = spark.sparkContext._gateway
    URL = jvm.java.net.URL
    urls = gw.new_array(URL, len(_DF_EXPECTED_JARS))
    for i, path in enumerate(_DF_EXPECTED_JARS):
        urls[i] = jvm.java.io.File(path).toURI().toURL()
    return jvm.java.net.URLClassLoader.newInstance(urls, parent)


def _patch_spark_hadoop_configuration_classloader(spark: SparkSession) -> None:
    parent = _spark_env_classloader(spark)
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    loader = _hadoop_configuration_loader_with_demoforge_jars(spark, parent)
    conf.setClassLoader(loader)
    print(
        "[raw_to_iceberg] DIAG Hadoop Configuration.setClassLoader(URLClassLoader demoforge jars "
        f"+ parent={parent.getClass().getName()})",
        flush=True,
    )
    try:
        cn = conf.getClassByName("org.apache.hadoop.fs.s3a.S3AFileSystem")
        print(f"[raw_to_iceberg] DIAG post-patch Configuration resolves S3AFileSystem -> {cn.getName()}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[raw_to_iceberg] DIAG post-patch Configuration.getClassByName(S3AFileSystem) FAIL: {e!r}", flush=True)


def _align_pyspark_thread_context_classloader(spark: SparkSession) -> None:
    """Best-effort: Py4J RPC thread TCCL; Hadoop FS also needs Configuration.setClassLoader (see _patch_spark_hadoop_configuration_classloader)."""
    jvm = spark.sparkContext._jvm
    jl = jvm.java.lang
    try:
        spark_cl = _spark_env_classloader(spark)
    except Exception as e:
        print(f"[raw_to_iceberg] WARN could not resolve Spark classloader for TCCL fix: {e!r}", flush=True)
        return
    try:
        old = jl.Thread.currentThread().getContextClassLoader()
        jl.Thread.currentThread().setContextClassLoader(spark_cl)
        old_n = old.getClass().getName() if old else "null"
        new_n = spark_cl.getClass().getName()
        same = jl.System.identityHashCode(old) == jl.System.identityHashCode(spark_cl)
        print(
            "[raw_to_iceberg] DIAG Py4J thread TCCL -> Spark env loader "
            f"({old_n} -> {new_n}, same_instance={same})",
            flush=True,
        )
    except Exception as e:
        print(f"[raw_to_iceberg] WARN TCCL alignment failed: {e!r}", flush=True)


def _log_python_and_host_jars() -> None:
    print(
        f"[raw_to_iceberg] DIAG python={sys.version.split()[0]} exe={sys.executable} pid={os.getpid()}",
        flush=True,
    )
    for p in _DF_EXPECTED_JARS:
        try:
            st = os.stat(p)
            print(f"[raw_to_iceberg] DIAG host jar OK path={p} size={st.st_size}", flush=True)
        except OSError as e:
            print(f"[raw_to_iceberg] DIAG host jar MISSING path={p} err={e}", flush=True)


def _log_spark_conf_driver_hints(spark: SparkSession) -> None:
    needles = ("classpath", "jar", "ivy", "packages", "submit", "driver", "executor", "repl")
    for k, v in sorted(spark.sparkContext.getConf().getAll(), key=lambda item: item[0]):
        kl = k.lower()
        if any(n in kl for n in needles):
            print(f"[raw_to_iceberg] DIAG SparkConf {k}={v}", flush=True)


def _log_java_classpath_and_loaders(spark: SparkSession) -> None:
    jvm = spark.sparkContext._jvm
    jl = jvm.java.lang
    sys_prop = jl.System.getProperty
    print(f"[raw_to_iceberg] DIAG java.version={sys_prop('java.version')}", flush=True)
    print(f"[raw_to_iceberg] DIAG java.vendor={sys_prop('java.vendor')}", flush=True)
    cp = sys_prop("java.class.path") or ""
    sep = str(jvm.java.io.File.pathSeparator)
    parts = [x for x in cp.split(sep) if x]
    print(f"[raw_to_iceberg] DIAG java.class.path entries={len(parts)} total_chars={len(cp)}", flush=True)
    hits = ("hadoop-aws", "iceberg", "aws-java-sdk", "aws-bundle")
    for part in parts:
        low = part.lower()
        if any(h in low for h in hits):
            print(f"[raw_to_iceberg] DIAG java.class.path hit: {part}", flush=True)
    if _diag_verbose():
        print("[raw_to_iceberg] DIAG java.class.path FULL (verbose):", flush=True)
        for part in parts:
            print(f"[raw_to_iceberg] DIAG   {part}", flush=True)


def _try_jvm_resolve_classes(spark: SparkSession, *class_names: str) -> None:
    jvm = spark.sparkContext._jvm
    jl = jvm.java.lang
    for name in class_names:
        try:
            jl.Class.forName(name)
            print(f"[raw_to_iceberg] DIAG JVM Class.forName({name!r}) OK", flush=True)
        except Exception as e:  # noqa: BLE001 — diagnostics
            print(f"[raw_to_iceberg] DIAG JVM Class.forName({name!r}) FAIL: {e!r}", flush=True)
        try:
            cl = jl.Thread.currentThread().getContextClassLoader()
            jl.Class.forName(name, True, cl)
            print(f"[raw_to_iceberg] DIAG JVM TCCL Class.forName({name!r},true,tccl) OK", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[raw_to_iceberg] DIAG JVM TCCL Class.forName({name!r}) FAIL: {e!r}", flush=True)


def _log_hadoop_s3a_config_snapshot(spark: SparkSession) -> None:
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    keys = (
        "fs.s3a.impl",
        "fs.s3.impl",
        "fs.s3a.endpoint",
        "fs.s3a.path.style.access",
        "fs.s3a.connection.ssl.enabled",
    )
    for key in keys:
        try:
            v = conf.get(key)
            print(f"[raw_to_iceberg] DIAG Hadoop Configuration {key}={v!r}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[raw_to_iceberg] DIAG Hadoop Configuration {key} unreadable: {e!r}", flush=True)


def _log_driver_diagnostics(spark: SparkSession) -> None:
    print("[raw_to_iceberg] DIAG — Spark driver classpath / loader probes (copy below if CNFE persists)", flush=True)
    _log_spark_conf_driver_hints(spark)
    _log_java_classpath_and_loaders(spark)
    _try_jvm_resolve_classes(
        spark,
        "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    )
    _log_hadoop_s3a_config_snapshot(spark)


def _parse_s3a_uri(uri: str) -> tuple[str, str]:
    """Return (bucket, key_or_prefix_with_glob) from s3a://bucket/path…"""
    p = urlparse(uri)
    if p.scheme not in ("s3a", "s3", "s3n"):
        return ("", "")
    bucket = (p.netloc or "").strip()
    path = (p.path or "").lstrip("/")
    return (bucket, path)


def _resolved_spark_catalog_name() -> str:
    raw = (
        os.environ.get("ICEBERG_SPARK_CATALOG_NAME")
        or os.environ.get("ICEBERG_CATALOG_NAME")
        or "iceberg"
    ).strip()
    if re.match(r"^[A-Za-z][A-Za-z0-9_]*$", raw):
        return raw
    print(f"[raw_to_iceberg] WARN invalid ICEBERG_SPARK_CATALOG_NAME={raw!r} — using 'iceberg'", flush=True)
    return "iceberg"


def _dest_s3a_archive_path(src_s3a: str, archive_prefix: str) -> str:
    bucket, _ = _parse_s3a_uri(src_s3a)
    if not bucket:
        raise ValueError(f"cannot parse bucket from {src_s3a!r}")
    p = urlparse(src_s3a)
    key = (p.path or "").lstrip("/")
    base = key.split("/")[-1] if key else ""
    ap = archive_prefix.strip().strip("/")
    new_key = f"{ap}/{base}" if ap else base
    return f"s3a://{bucket}/{new_key}"


def _s3a_move_copy_delete(spark: SparkSession, src_s3a: str, dst_s3a: str) -> None:
    """Copy object to dst then delete src (S3A: copy + delete)."""
    _align_pyspark_thread_context_classloader(spark)
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    Path = jvm.org.apache.hadoop.fs.Path
    FileUtil = jvm.org.apache.hadoop.fs.FileUtil
    FileSystem = jvm.org.apache.hadoop.fs.FileSystem
    p_src = Path(src_s3a)
    p_dst = Path(dst_s3a)
    fs = FileSystem.get(p_src.toUri(), conf)
    parent = p_dst.getParent()
    if parent is not None and not fs.exists(parent):
        fs.mkdirs(parent)
    ok = FileUtil.copy(fs, p_src, fs, p_dst, True, True, conf)
    if not ok:
        raise RuntimeError(f"S3A FileUtil.copy failed {src_s3a} -> {dst_s3a}")


def _archive_processed_sources(spark: SparkSession, paths: list[str], archive_prefix: str) -> int:
    if not archive_prefix.strip() or not paths:
        return 0
    n_ok = 0
    for src in paths:
        dst = _dest_s3a_archive_path(src, archive_prefix)
        try:
            _s3a_move_copy_delete(spark, src, dst)
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[raw_to_iceberg] WARN archive move failed {src!r} -> {dst!r}: {exc!r}", flush=True)
    return n_ok


def _split_input_uri_and_glob(uri: str) -> tuple[str, str]:
    """
    Split a filesystem URI into (directory_base_with_trailing_slash, glob_suffix).
    If there is no '*', returns (uri, "") so the path is treated as a single object or directory.
    Example: s3a://raw/ecommerce-orders/*.csv -> (s3a://raw/ecommerce-orders/, *.csv)
    """
    p = urlparse(uri)
    path = p.path or ""
    if "*" not in path:
        return uri, ""
    idx = path.index("*")
    dir_rel = path[:idx].rstrip("/")
    glob_rest = path[idx:]
    auth = f"{p.scheme}://{(p.netloc or '').strip()}"
    base = f"{auth}/{dir_rel}/" if dir_rel else f"{auth}/"
    return base, glob_rest


def _env_glob_recursive() -> bool:
    return os.environ.get("RAW_INPUT_GLOB_RECURSIVE", "").strip().lower() in ("1", "true", "yes")


def _use_recursive_glob(glob_pat: str) -> bool:
    if _env_glob_recursive():
        return True
    return "**" in glob_pat


def _log_input_inventory(spark: SparkSession, input_uri: str, max_list: int = 200) -> tuple[int, list[str]]:
    """
    List objects matching INPUT_S3A_URI via Hadoop S3A.
    S3A's globStatus(wildcard path) is unreliable (often returns one object); we list the parent
    prefix and fnmatch the leaf pattern instead — aligned with Spark pathGlobFilter reads.
    Returns (match_count, matched_s3a_paths) for optional archive-after-success.
    """
    _align_pyspark_thread_context_classloader(spark)
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    HPath = jvm.org.apache.hadoop.fs.Path
    try:
        impl = conf.get("fs.s3a.impl") or ""
        print(f"[raw_to_iceberg] DIAG FileSystem inventory uri={input_uri!r} fs.s3a.impl={impl!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[raw_to_iceberg] DIAG could not read fs.s3a.impl: {e!r}", flush=True)

    base_uri, glob_pat = _split_input_uri_and_glob(input_uri)

    if not glob_pat:
        path = HPath(input_uri)
        fs = jvm.org.apache.hadoop.fs.FileSystem.get(path.toUri(), conf)
        print("[raw_to_iceberg] DIAG inventory: globStatus (no wildcard in path)", flush=True)
        try:
            statuses = fs.globStatus(path)
        except Exception as exc:  # noqa: BLE001
            print(f"[raw_to_iceberg] WARN: globStatus failed ({exc!r})", flush=True)
            return -1, []
        if statuses is None:
            print("[raw_to_iceberg] WARN: globStatus returned None", flush=True)
            return 0, []
        arr = list(statuses)
        n = len(arr)
        paths = [st.getPath().toString() for st in arr if st is not None]
        print(f"[raw_to_iceberg] S3A matched {n} path(s) for: {input_uri}", flush=True)
        for i, st in enumerate(arr[:max_list]):
            ps = st.getPath().toString() if st is not None else "?"
            length = st.getLen() if st is not None else -1
            print(f"[raw_to_iceberg]   [{i + 1}] {ps}  ({length} bytes)", flush=True)
        if n > max_list:
            print(f"[raw_to_iceberg] … and {n - max_list} more (capped at {max_list})", flush=True)
        return n, paths

    parent_path = HPath(base_uri.rstrip("/"))
    recursive = _use_recursive_glob(glob_pat)
    fs = jvm.org.apache.hadoop.fs.FileSystem.get(parent_path.toUri(), conf)
    print(
        f"[raw_to_iceberg] DIAG inventory: listFiles(parent, recursive={recursive}) "
        f"parent={base_uri!r} fnmatch={glob_pat!r}",
        flush=True,
    )
    matched = []
    try:
        it = fs.listFiles(parent_path, recursive)
        while it.hasNext():
            st = it.next()
            if st.isDirectory():
                continue
            name = st.getPath().getName()
            if fnmatch.fnmatch(name, glob_pat):
                matched.append(st)
    except Exception as exc:  # noqa: BLE001
        print(f"[raw_to_iceberg] WARN: listFiles inventory failed ({exc!r})", flush=True)
        return -1, []

    matched.sort(key=lambda s: s.getPath().toString())
    n = len(matched)
    paths = [st.getPath().toString() for st in matched]
    print(f"[raw_to_iceberg] S3A listing matched {n} object(s) for {glob_pat!r} under {base_uri!r}", flush=True)
    for i, st in enumerate(matched[:max_list]):
        ps = st.getPath().toString()
        length = st.getLen()
        print(f"[raw_to_iceberg]   [{i + 1}] {ps}  ({length} bytes)", flush=True)
    if n > max_list:
        print(f"[raw_to_iceberg] … and {n - max_list} more (capped at {max_list})", flush=True)
    return n, paths


def _dataframe_reader_for_raw(spark: SparkSession, raw_fmt: str, json_multiline: bool, input_uri: str):
    """Build a DataFrame reader path aligned with inventory (pathGlobFilter avoids broken S3A URI globs)."""
    base_uri, glob_pat = _split_input_uri_and_glob(input_uri)
    read_path = base_uri if glob_pat else input_uri
    r = spark.read
    if glob_pat:
        r = r.option("pathGlobFilter", glob_pat)
        if _use_recursive_glob(glob_pat):
            r = r.option("recursiveFileLookup", "true")
    print(
        f"[raw_to_iceberg] Read path={read_path!r} pathGlobFilter={glob_pat or '(none)'} "
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
        print(f"[raw_to_iceberg] ERROR {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(1)


def _main_impl(job_t0: float) -> None:
    input_uri = os.environ.get("INPUT_S3A_URI", "")
    rest_uri = os.environ.get("ICEBERG_REST_URI", "")
    warehouse = os.environ.get("ICEBERG_WAREHOUSE", "warehouse")
    ns = os.environ.get("ICEBERG_TARGET_NAMESPACE", "analytics")
    table = os.environ.get("ICEBERG_TARGET_TABLE", "events_from_raw")
    raw_fmt = (os.environ.get("RAW_INPUT_FORMAT") or os.environ.get("INPUT_FORMAT") or "csv").strip().lower()
    json_multiline = (os.environ.get("JSON_MULTILINE", "false").strip().lower() in ("1", "true", "yes"))
    s3_key = os.environ.get("S3_ACCESS_KEY", "minioadmin")
    s3_secret = os.environ.get("S3_SECRET_KEY", "minioadmin")
    s3_endpoint = os.environ.get("S3_ENDPOINT", "http://minio-1:9000")
    iceberg_sigv4 = os.environ.get("ICEBERG_SIGV4", "").strip().lower() in ("true", "1", "yes")
    rest_signing_region = (os.environ.get("ICEBERG_REST_SIGNING_REGION") or "us-east-1").strip()
    rest_signing_name = (os.environ.get("ICEBERG_REST_SIGNING_NAME") or "s3tables").strip()
    raw_bucket_cfg = (os.environ.get("RAW_LANDING_BUCKET") or "").strip()
    wh_bucket_cfg = (os.environ.get("WAREHOUSE_BUCKET") or "").strip()
    input_prefix_cfg = (os.environ.get("INPUT_OBJECT_PREFIX") or "").strip()
    archive_prefix = (os.environ.get("RAW_TO_ICEBERG_ARCHIVE_PREFIX") or "").strip()

    if not input_uri:
        print("[raw_to_iceberg] INPUT_S3A_URI is required", flush=True)
        sys.exit(1)
    if not rest_uri:
        print("[raw_to_iceberg] ICEBERG_REST_URI is required", flush=True)
        sys.exit(1)
    if raw_fmt not in ("csv", "json"):
        print(f"[raw_to_iceberg] Unsupported RAW_INPUT_FORMAT={raw_fmt!r} (use csv or json)", flush=True)
        sys.exit(1)

    bucket_from_uri, key_glob = _parse_s3a_uri(input_uri)

    catalog_name_preview = _resolved_spark_catalog_name()
    print(
        "[raw_to_iceberg] Job config snapshot: "
        f"RAW_INPUT_FORMAT={raw_fmt} JSON_MULTILINE={json_multiline} "
        f"ICEBERG_SPARK_CATALOG_NAME={catalog_name_preview!r} "
        f"ICEBERG_TARGET={ns}.{table} ICEBERG_WAREHOUSE={warehouse!r} "
        f"RAW_TO_ICEBERG_ARCHIVE_PREFIX={archive_prefix or '(off)'}",
        flush=True,
    )
    print(
        "[raw_to_iceberg] Bucket context: "
        f"S3_ENDPOINT={s3_endpoint} "
        f"INPUT_S3A_URI bucket={bucket_from_uri!r} key/glob={key_glob!r} "
        f"RAW_LANDING_BUCKET(env)={raw_bucket_cfg or '(unset)'} "
        f"WAREHOUSE_BUCKET(env)={wh_bucket_cfg or '(unset)'} "
        f"INPUT_OBJECT_PREFIX(env)={input_prefix_cfg or '(unset)'}",
        flush=True,
    )
    print(
        f"[raw_to_iceberg] ICEBERG_REST_URI={rest_uri} ICEBERG_SIGV4={iceberg_sigv4} "
        f"signing_region={rest_signing_region!r} signing_name={rest_signing_name!r}",
        flush=True,
    )

    _log_python_and_host_jars()

    catalog = catalog_name_preview
    ep = s3_endpoint if s3_endpoint.startswith("http") else f"http://{s3_endpoint}"
    # Iceberg aws.s3.S3OutputStream uses AWS SDK v2 on executors — not Hadoop fs.s3a.* keys.
    s3_region = (os.environ.get("ICEBERG_S3_REGION") or rest_signing_region or "us-east-1").strip()
    file_scan = _spark_file_scan_conf_from_env()
    print("[raw_to_iceberg] DIAG SparkSession.getOrCreate() starting…", flush=True)
    try:
        bldr = (
            SparkSession.builder.appName("demoforge-raw-to-iceberg")
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
            # Static S3 creds for Iceberg FileIO on workers (parquet commit / putObject).
            .config(f"spark.sql.catalog.{catalog}.s3.endpoint", ep)
            .config(f"spark.sql.catalog.{catalog}.s3.access-key-id", s3_key)
            .config(f"spark.sql.catalog.{catalog}.s3.secret-access-key", s3_secret)
            .config(f"spark.sql.catalog.{catalog}.s3.path-style-access", "true")
            .config(f"spark.sql.catalog.{catalog}.s3.region", s3_region)
            .config("spark.executorEnv.AWS_ACCESS_KEY_ID", s3_key)
            .config("spark.executorEnv.AWS_SECRET_ACCESS_KEY", s3_secret)
            .config("spark.executorEnv.AWS_DEFAULT_REGION", s3_region)
            .config("spark.sql.files.maxPartitionBytes", file_scan["spark.sql.files.maxPartitionBytes"])
            .config("spark.sql.files.openCostInBytes", file_scan["spark.sql.files.openCostInBytes"])
        )
        # AIStor Tables: REST /config is SigV4-protected (Iceberg HTTPClient rest.sigv4-enabled + AwsProperties keys).
        if iceberg_sigv4:
            bldr = (
                bldr.config(f"spark.sql.catalog.{catalog}.rest.sigv4-enabled", "true")
                .config(f"spark.sql.catalog.{catalog}.rest.signing-region", rest_signing_region)
                .config(f"spark.sql.catalog.{catalog}.rest.signing-name", rest_signing_name)
                .config(f"spark.sql.catalog.{catalog}.rest.access-key-id", s3_key)
                .config(f"spark.sql.catalog.{catalog}.rest.secret-access-key", s3_secret)
            )
        spark = bldr.getOrCreate()
    except Exception as exc:
        print(f"[raw_to_iceberg] DIAG SparkSession.getOrCreate() FAILED: {exc!r}", flush=True)
        raise

    _patch_spark_hadoop_configuration_classloader(spark)
    _align_pyspark_thread_context_classloader(spark)

    spark.sparkContext.setLogLevel("WARN")
    fq = f"{catalog}.{ns}.{table}"
    _log_driver_diagnostics(spark)
    print(
        "[raw_to_iceberg] Spark file-scan grouping: "
        f"maxPartitionBytes={file_scan['spark.sql.files.maxPartitionBytes']} "
        f"openCostInBytes={file_scan['spark.sql.files.openCostInBytes']} "
        "(many small objects → fewer scan partitions than one-task-per-file)",
        flush=True,
    )
    print(f"[raw_to_iceberg] SparkSession ready; listing input matches for {input_uri!r}", flush=True)
    _log_spark_executor_snapshot(spark, "before inventory")
    with _progress_heartbeat("S3 inventory (listFiles + match)"):
        n_matched, matched_paths = _log_input_inventory(spark, input_uri)
    if n_matched == 0:
        print(
            "[raw_to_iceberg] WARN: zero input files matched — read may yield empty DataFrame or fail.",
            flush=True,
        )

    print(
        "[raw_to_iceberg] Reading — Spark builds one Dataset over all glob matches "
        "(scan partitioning is grouped; optional coalesce reduces write partitions).",
        flush=True,
    )
    print(f"[raw_to_iceberg] Reading {raw_fmt} from {input_uri} into DataFrame", flush=True)
    _align_pyspark_thread_context_classloader(spark)
    with _spark_driver_log_level_for_long_phases(spark):
        with _progress_heartbeat("Spark read (CSV/JSON scan; inferSchema runs an extra job on CSV)"):
            spark.sparkContext.setJobDescription("DemoForge: read raw files into DataFrame")
            t0 = time.perf_counter()
            df = _dataframe_reader_for_raw(spark, raw_fmt, json_multiline, input_uri)
            spark.sparkContext.setJobDescription(None)
            print(
                f"[raw_to_iceberg] Read phase finished in {time.perf_counter() - t0:.1f}s; schema:",
                f"{df.schema.simpleString()}",
                flush=True,
            )
        _log_spark_executor_snapshot(spark, "after read")
        df = _apply_coalesce_before_write(df, n_matched)
        with _progress_heartbeat("df.count() before Iceberg commit (full scan)"):
            spark.sparkContext.setJobDescription("DemoForge: row count before commit")
            try:
                nrow = df.count()
            except Exception as exc:  # noqa: BLE001
                print(f"[raw_to_iceberg] WARN: row count failed ({exc!r})", flush=True)
                nrow = -1
            finally:
                spark.sparkContext.setJobDescription(None)
            if nrow >= 0:
                print(f"[raw_to_iceberg] Row count before Iceberg commit: {nrow}", flush=True)

        print(f"[raw_to_iceberg] Writing Iceberg table {fq} (catalog warehouse={warehouse!r})", flush=True)
        _align_pyspark_thread_context_classloader(spark)
        _ensure_iceberg_namespace(spark, catalog, ns)
        with _progress_heartbeat("Iceberg createOrReplace (commit may take minutes)"):
            spark.sparkContext.setJobDescription("DemoForge: Iceberg createOrReplace")
            t1 = time.perf_counter()
            df.writeTo(fq).using("iceberg").createOrReplace()
            spark.sparkContext.setJobDescription(None)
            print(f"[raw_to_iceberg] Write phase finished in {time.perf_counter() - t1:.1f}s", flush=True)
        _log_spark_executor_snapshot(spark, "after write")
        rows_part = f"rows={nrow}" if nrow >= 0 else "rows=(count failed)"
        print(
            f"[raw_to_iceberg] SUCCESS Iceberg load complete {rows_part} table={fq} "
            f"wall_s={time.perf_counter() - job_t0:.1f}",
            flush=True,
        )
        if archive_prefix:
            with _progress_heartbeat("Archive processed raw objects (copy+delete)"):
                n_arch = _archive_processed_sources(spark, matched_paths, archive_prefix)
            print(
                f"[raw_to_iceberg] Archive: moved_ok={n_arch} total_sources={len(matched_paths)} "
                f"prefix={archive_prefix!r}",
                flush=True,
            )
    print(
        f"[raw_to_iceberg] Done (createOrReplace complete). Total wall time {time.perf_counter() - job_t0:.1f}s",
        flush=True,
    )
    spark.stop()


if __name__ == "__main__":
    main()
