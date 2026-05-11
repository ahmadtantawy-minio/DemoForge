"""
run.py — External System scenario engine entrypoint.

Reads scenario YAML from /scenarios/{ES_SCENARIO}.yaml and drives a data
generation pipeline that writes Iceberg tables via PyIceberg REST and MinIO
objects, then provisions Metabase dashboards and saved queries.

When ES_SCENARIO matches a Data Generator dataset id (bundled under
/app/vendor/data-generator/), the container runs the same generate.py scenario
loop as the Data Generator image (identical S3 keys, partitioning, and writers).

Env vars:
  ES_SCENARIO           scenario ID (e.g. "soc-firewall-events")
  ES_SCENARIOS_DIR      scenarios dir (default /app/scenarios)
  ES_STARTUP_DELAY      seconds to sleep before generation (correlation ordering)
  S3_ENDPOINT           MinIO endpoint
  S3_ACCESS_KEY         MinIO access key
  S3_SECRET_KEY         MinIO secret key
  ICEBERG_CATALOG_URI   Iceberg REST catalog URL
  ICEBERG_CATALOG_NAME  PyIceberg RestCatalog client name; for MinIO /_iceberg, set from MinIO AISTOR_TABLES_CATALOG_NAME (compose)
  ICEBERG_WAREHOUSE     warehouse name (default "warehouse")
  ICEBERG_SIGV4         "true" for AIStor SigV4 auth
  TRINO_HOST            Optional Trino host:port (read-only probes, e.g. correlation seeding)
  TRINO_CATALOG         Trino catalog for those probes (default matches AIStor vs Hive catalog)
  METABASE_URL          Metabase URL (default http://metabase:3000)
  METABASE_USER         Metabase user (default admin@demoforge.local)
  METABASE_PASSWORD     Metabase password (default DemoForge123!)
  ES_ON_DEMAND_DIR      Poll this dir for *.json to trigger extra batch generation (default /tmp/es-on-demand)
  ES_ON_DEMAND_POLL_SEC Polling interval for on-demand requests (default 5)
  ES_SINK_MODE          files_and_iceberg (default) or files_only — when files_only, skip Iceberg/mirror writes
"""

import copy
import importlib.util
import io
import json
import os
import re
import sys
import time
import uuid as _uuid_mod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import boto3
from botocore.exceptions import ClientError

from src.schema_loader import load_scenario
from src.generators import generate_batch, generate_row
from src import metabase_client as mc

try:
    from integration_log import append as _integration_log_append
except ImportError:
    _integration_log_append = None


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

ES_SCENARIO = os.environ.get("ES_SCENARIO", "")
ES_SCENARIOS_DIR = os.environ.get("ES_SCENARIOS_DIR", "/app/scenarios")
DG_VENDOR_ROOT = os.environ.get("ES_DG_VENDOR_ROOT", "/app/vendor/data-generator")
ES_STARTUP_DELAY = int(os.environ.get("ES_STARTUP_DELAY", "0") or 0)
ES_ON_DEMAND_DIR = os.environ.get("ES_ON_DEMAND_DIR", "/tmp/es-on-demand")
ES_ON_DEMAND_POLL_SEC = float(os.environ.get("ES_ON_DEMAND_POLL_SEC", "5") or 5)
ES_SINK_MODE_RAW = (os.environ.get("ES_SINK_MODE", "files_and_iceberg") or "files_and_iceberg").strip().lower()
FILES_ONLY = ES_SINK_MODE_RAW == "files_only"

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")

ICEBERG_CATALOG_URI = os.environ.get("ICEBERG_CATALOG_URI", "")
ICEBERG_CATALOG_NAME = (os.environ.get("ICEBERG_CATALOG_NAME") or "").strip()
ICEBERG_WAREHOUSE = os.environ.get("ICEBERG_WAREHOUSE", "warehouse")
ICEBERG_SIGV4 = os.environ.get("ICEBERG_SIGV4", "").lower() in ("true", "1", "yes")

TRINO_HOST = os.environ.get("TRINO_HOST", "")
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "aistor" if ICEBERG_SIGV4 else "iceberg")

METABASE_URL = os.environ.get("METABASE_URL", "")  # only set when dashboard-provision edge exists
METABASE_USER = os.environ.get("METABASE_USER", mc.DEFAULT_USER)
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD", mc.DEFAULT_PASSWORD)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _s3_endpoint_url() -> str:
    return S3_ENDPOINT if S3_ENDPOINT.startswith("http") else f"http://{S3_ENDPOINT}"


def make_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=_s3_endpoint_url(),
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
    )


def wait_for_minio(timeout: int = 180):
    print(f"[external-system] Waiting for MinIO at {S3_ENDPOINT} (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client = make_s3_client()
            client.list_buckets()
            print("[external-system] MinIO is available.")
            return client
        except Exception as exc:
            print(f"[external-system]   not ready: {exc}; retrying...")
            time.sleep(3)
    raise RuntimeError(f"MinIO not available within {timeout}s")


def ensure_bucket(client, bucket: str):
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            print(f"[external-system] Created bucket '{bucket}'.")
        else:
            raise


# ---------------------------------------------------------------------------
# Iceberg table writer (PyIceberg REST — no Trino write path)
# ---------------------------------------------------------------------------

_PYICEBERG_AVAILABLE = False
try:
    import pyiceberg  # noqa: F401
    _PYICEBERG_AVAILABLE = True
except ImportError:
    pass


_ICEBERG_TYPE_MAP_NAMES = {
    "string": "StringType",
    "integer": "IntegerType",
    "int": "IntegerType",
    "int32": "IntegerType",
    "long": "LongType",
    "int64": "LongType",
    "float": "FloatType",
    "double": "DoubleType",
    "float32": "FloatType",
    "float64": "DoubleType",
    "boolean": "BooleanType",
    "timestamp": "TimestampType",
    "date": "DateType",
}


def _pa_type(col_type: str):
    import pyarrow as pa
    mapping = {
        "string": pa.string(),
        "integer": pa.int32(),
        "int": pa.int32(),
        "int32": pa.int32(),
        "long": pa.int64(),
        "int64": pa.int64(),
        "float": pa.float32(),
        "float32": pa.float32(),
        "double": pa.float64(),
        "float64": pa.float64(),
        "boolean": pa.bool_(),
        "timestamp": pa.timestamp("us"),
        "date": pa.date32(),
    }
    return mapping.get(col_type, pa.string())


def _coerce_value(val, col_type: str):
    import datetime as _dt
    if val is None:
        return None
    if col_type in ("integer", "int", "int32", "long", "int64"):
        try:
            return int(val)
        except (TypeError, ValueError):
            return None
    if col_type in ("float", "double", "float32", "float64"):
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    if col_type == "boolean":
        return bool(val)
    if col_type == "timestamp":
        if isinstance(val, _dt.datetime):
            return val
        if isinstance(val, str):
            try:
                return _dt.datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                return None
        return None
    if col_type == "date":
        if isinstance(val, _dt.date) and not isinstance(val, _dt.datetime):
            return val
        if isinstance(val, _dt.datetime):
            return val.date()
        return None
    # string / json
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val)


def _rows_to_arrow(rows, schema):
    import pyarrow as pa
    arrays = {}
    fields = []
    for col in schema:
        name = col["name"]
        t = col.get("type", "string")
        pa_t = _pa_type(t)
        vals = [_coerce_value(r.get(name), t) for r in rows]
        arrays[name] = pa.array(vals, type=pa_t)
        fields.append(pa.field(name, pa_t, nullable=col.get("nullable", True)))
    return pa.table(arrays, schema=pa.schema(fields))


class IcebergTableWriter:
    def __init__(self):
        if not _PYICEBERG_AVAILABLE:
            raise RuntimeError("pyiceberg not installed")
        self._catalog = None
        self._last_iceberg_data_prefix: str = ""

    def last_iceberg_data_prefix(self) -> str:
        """S3 URI prefix for table data (metadata.location) after last successful append."""
        return self._last_iceberg_data_prefix or ""

    def _catalog_handle(self):
        if self._catalog:
            return self._catalog
        from pyiceberg.catalog.rest import RestCatalog
        endpoint = _s3_endpoint_url()
        wh = ICEBERG_WAREHOUSE
        wh_uri = wh if ICEBERG_SIGV4 else (wh if wh.startswith("s3://") else f"s3://{wh}/")
        catalog_uri = ICEBERG_CATALOG_URI.strip()
        if ICEBERG_SIGV4 and "-lb:80" in catalog_uri:
            catalog_uri = catalog_uri.replace("-lb:80", "-pool1-node-1:9000")
            print(f"[iceberg] AIStor SigV4: catalog URI → {catalog_uri}", flush=True)
        props = {
            "uri": catalog_uri,
            "warehouse": wh_uri,
            "s3.endpoint": endpoint,
            "s3.access-key-id": S3_ACCESS_KEY,
            "s3.secret-access-key": S3_SECRET_KEY,
            "s3.path-style-access": "true",
            "s3.region": "us-east-1",
            "py-io-impl": "pyiceberg.io.fsspec.FsspecFileIO",
        }
        if ICEBERG_SIGV4:
            os.environ.setdefault("AWS_ACCESS_KEY_ID", S3_ACCESS_KEY)
            os.environ.setdefault("AWS_SECRET_ACCESS_KEY", S3_SECRET_KEY)
            os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
            props["rest.sigv4-enabled"] = "true"
            props["rest.signing-region"] = "us-east-1"
            props["rest.signing-name"] = "s3tables"
        rest_catalog_name = ICEBERG_CATALOG_NAME or ("aistor" if ICEBERG_SIGV4 else "external-system")
        self._catalog = RestCatalog(name=rest_catalog_name, **props)
        return self._catalog

    def ensure_table(self, namespace: str, table_name: str, schema_fields: list):
        from pyiceberg.schema import Schema
        from pyiceberg.types import (
            StringType, LongType, IntegerType, FloatType, DoubleType,
            BooleanType, TimestampType, DateType, NestedField,
        )
        type_map = {
            "StringType": StringType(),
            "LongType": LongType(),
            "IntegerType": IntegerType(),
            "FloatType": FloatType(),
            "DoubleType": DoubleType(),
            "BooleanType": BooleanType(),
            "TimestampType": TimestampType(),
            "DateType": DateType(),
        }
        catalog = self._catalog_handle()
        full = f"{namespace}.{table_name}"
        try:
            catalog.load_table(full)
            print(f"[iceberg] table exists: {full}", flush=True)
            return
        except Exception:
            pass
        fields = []
        for idx, col in enumerate(schema_fields, start=1):
            tn = _ICEBERG_TYPE_MAP_NAMES.get(col.get("type", "string"), "StringType")
            fields.append(
                NestedField(
                    field_id=idx,
                    name=col["name"],
                    field_type=type_map[tn],
                    required=not col.get("nullable", True),
                )
            )
        try:
            print(f"[iceberg] create_namespace: {namespace}", flush=True)
            catalog.create_namespace(namespace)
            print(f"[iceberg] namespace ok: {namespace}", flush=True)
        except Exception as exc:
            print(f"[iceberg] namespace already exists or failed: {namespace}: {exc}", flush=True)
        print(f"[iceberg] create_table: {full}", flush=True)
        try:
            catalog.create_table(identifier=full, schema=Schema(*fields))
            print(f"[iceberg] table created: {full}", flush=True)
        except Exception as exc:
            print(f"[iceberg] create_table failed: {full}: {exc}", flush=True)
            raise

    def append(self, namespace: str, table_name: str, rows: list, schema: list, *, quiet: bool = False) -> int:
        if not rows:
            return 0
        arrow = _rows_to_arrow(rows, schema)
        ident = f"{namespace}.{table_name}"
        for attempt in range(2):
            try:
                catalog = self._catalog_handle()
                tbl = catalog.load_table(ident)
                tbl.append(arrow)
                # Reload metadata so location reflects the new commit (data files live under this S3 prefix).
                tbl_after = catalog.load_table(ident)
                loc = ""
                try:
                    loc = str(getattr(tbl_after.metadata, "location", "") or "")
                except Exception:
                    loc = ""
                self._last_iceberg_data_prefix = loc
                wh = (ICEBERG_WAREHOUSE or "").strip()
                ep = (S3_ENDPOINT or "").strip()
                if not quiet:
                    print(
                        "[external-system] Iceberg write SUCCESS: "
                        f"{len(rows)} row(s) → table `{ident}` | "
                        f"table_data_prefix={loc or '(unknown)'} | "
                        f"warehouse={wh or '(unset)'} | s3_endpoint={ep or '(unset)'}",
                        flush=True,
                    )
                return len(rows)
            except Exception:
                if attempt == 0:
                    self._catalog = None
                else:
                    raise
        return len(rows)


def _get_table_writer():
    """Return (IcebergTableWriter, 'iceberg') when PyIceberg + ICEBERG_CATALOG_URI; else (None, None)."""
    if not _PYICEBERG_AVAILABLE or not (ICEBERG_CATALOG_URI or "").strip():
        return None, None
    try:
        return IcebergTableWriter(), "iceberg"
    except Exception as exc:
        print(f"[external-system] IcebergTableWriter init failed: {exc}")
        return None, None


# ---------------------------------------------------------------------------
# Object generation
# ---------------------------------------------------------------------------

def _stix_bundle(row: dict) -> dict:
    """Build a minimal STIX 2.1 bundle wrapping the synthesized indicator row."""
    indicator_id = f"indicator--{_uuid_mod.uuid4()}"
    bundle_id = f"bundle--{_uuid_mod.uuid4()}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    pattern_val = row.get("indicator") or row.get("value") or "unknown"
    ioc_type = row.get("ioc_type") or "ipv4-addr"
    stix_pattern_type = {
        "ipv4": "ipv4-addr",
        "ipv6": "ipv6-addr",
        "domain": "domain-name",
        "url": "url",
        "sha256": "file:hashes.'SHA-256'",
        "md5": "file:hashes.MD5",
    }.get(ioc_type, "ipv4-addr")
    stix_pattern = f"[{stix_pattern_type}:value = '{pattern_val}']"
    return {
        "type": "bundle",
        "id": bundle_id,
        "spec_version": "2.1",
        "objects": [
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": indicator_id,
                "created": now,
                "modified": now,
                "pattern": stix_pattern,
                "pattern_type": "stix",
                "valid_from": now,
                "labels": [row.get("tags", "malicious-activity")] if row.get("tags") else ["malicious-activity"],
                "confidence": int(row.get("confidence", 75)),
                "description": row.get("description", ""),
            }
        ],
    }


def write_object_batch(
    client,
    dataset: dict,
    ctx: dict,
    table_writer,
    table_kind: str,
    count: int,
    phase_label: str = "Seeding",
) -> None:
    """Write `count` objects for one dataset (initial seed or on-demand burst)."""
    if count <= 0:
        return
    bucket = dataset["bucket"]
    prefix = dataset.get("prefix", "")
    fmt = dataset.get("object_format", "json")
    schema = dataset.get("schema", [])
    ds_id = dataset["id"]

    ensure_bucket(client, bucket)

    mirror = dataset.get("mirror_to_table")
    mirror_rows = []
    mirror_fields_spec = None
    if mirror:
        names = set(mirror.get("fields", []))
        mirror_fields_spec = [f for f in schema if f["name"] in names]

    print(f"[{ds_id}] {phase_label}: {count} objects → s3://{bucket}/{prefix} ({fmt})")

    import random as _r

    progress_every = max(1, count // 10)
    for i in range(count):
        row = generate_row(schema, ctx)
        key_name = f"{prefix}{row.get('object_id') or _uuid_mod.uuid4().hex}"

        if fmt == "json":
            if ds_id in ("threat_feeds_raw",) or dataset.get("json_style") == "stix":
                body_obj = _stix_bundle(row)
            else:
                body_obj = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
            body = json.dumps(body_obj, indent=2).encode("utf-8")
            key = key_name if key_name.endswith(".json") else f"{key_name}.json"
        elif fmt == "binary":
            size_min = int(dataset.get("object_size_min", 10 * 1024))
            size_max = int(dataset.get("object_size_max", 500 * 1024))
            body = os.urandom(_r.randint(size_min, size_max))
            sha256_val = row.get("sha256")
            if sha256_val:
                key = f"{prefix}{sha256_val}.bin"
            else:
                key = key_name if "." in os.path.basename(key_name) else f"{key_name}.bin"
        else:  # text
            body = (row.get("content") or "lorem ipsum").encode("utf-8")
            key = key_name if key_name.endswith(".txt") else f"{key_name}.txt"

        client.put_object(Bucket=bucket, Key=key, Body=body)
        print(f"[{ds_id}] S3 write SUCCESS: s3://{bucket}/{key}", flush=True)

        also_report = dataset.get("also_write_report")
        if also_report and fmt == "binary" and row.get("sha256"):
            report_prefix = also_report.get("prefix", "reports/")
            report_key = f"{report_prefix}{row['sha256']}.json"
            report_data = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                           for k, v in row.items()}
            report_body = json.dumps(report_data, indent=2).encode("utf-8")
            client.put_object(Bucket=bucket, Key=report_key, Body=report_body,
                              ContentType="application/json",
                              ContentLength=len(report_body))
            print(f"[{ds_id}] S3 write SUCCESS: s3://{bucket}/{report_key}", flush=True)

        if mirror_fields_spec:
            tags = []
            for f in mirror_fields_spec:
                v = row.get(f["name"])
                if v is None:
                    continue
                if hasattr(v, "isoformat"):
                    v = v.isoformat()
                sv = str(v)[:256]
                tags.append({"Key": f["name"], "Value": sv})
            if tags:
                try:
                    client.put_object_tagging(
                        Bucket=bucket, Key=key, Tagging={"TagSet": tags}
                    )
                except Exception as exc:
                    print(f"[{ds_id}] tagging failed for {key}: {exc}")
            mirror_rows.append({f["name"]: row.get(f["name"]) for f in mirror_fields_spec})

        if (i + 1) % progress_every == 0 or (i + 1) == count:
            pct = int(100 * (i + 1) / count)
            done = " — DONE" if (i + 1) == count else ""
            print(f"[{ds_id}] {phase_label}: {i + 1}/{count} objects ({pct}%){done}")

    if mirror and mirror_rows and table_writer and not FILES_ONLY:
        ns = mirror["namespace"]
        tn = mirror["table_name"]
        print(f"[{ds_id}] Mirroring {len(mirror_rows)} rows -> {ns}.{tn}")
        try:
            table_writer.ensure_table(ns, tn, mirror_fields_spec)
            table_writer.append(ns, tn, mirror_rows, mirror_fields_spec)
        except Exception as exc:
            print(f"[{ds_id}] mirror table write failed: {exc}")


def write_object_dataset(client, dataset: dict, ctx: dict, table_writer, table_kind: str):
    gen_cfg = dataset.get("generation", {})
    count = int(gen_cfg.get("seed_count", 100))
    write_object_batch(client, dataset, ctx, table_writer, table_kind, count, phase_label="Seeding")


# ---------------------------------------------------------------------------
# Table generation
# ---------------------------------------------------------------------------

def _parse_rate(rate: str) -> float:
    """'25/s' -> 25.0 rows/sec."""
    if not rate:
        return 1.0
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(s|sec|second|m|min|minute|h|hour)\s*$", rate)
    if not m:
        try:
            return float(rate)
        except Exception:
            return 1.0
    n = float(m.group(1))
    unit = m.group(2)
    if unit.startswith("s"):
        return n
    if unit.startswith("m"):
        return n / 60.0
    if unit.startswith("h"):
        return n / 3600.0
    return n


def _parse_duration(d: str) -> float:
    """'30m' -> seconds; 'forever' -> inf."""
    if not d or d == "forever":
        return float("inf")
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(s|m|h|d)?\s*$", str(d))
    if not m:
        return float("inf")
    n = float(m.group(1))
    u = m.group(2) or "s"
    mul = {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]
    return n * mul


def _write_csv_to_s3(client, bucket: str, key: str, rows: list, schema: list):
    import csv
    import io
    import datetime as _dt
    buf = io.StringIO()
    col_names = [c["name"] for c in schema]
    writer = csv.writer(buf)
    writer.writerow(col_names)
    for row in rows:
        out_row = []
        for c in schema:
            v = row.get(c["name"])
            if isinstance(v, _dt.datetime):
                v = v.isoformat()
            elif isinstance(v, _dt.date):
                v = str(v)
            elif v is None:
                v = ""
            out_row.append(v)
        writer.writerow(out_row)
    data = buf.getvalue().encode("utf-8")
    client.put_object(Bucket=bucket, Key=key, Body=data,
                      ContentType="text/csv", ContentLength=len(data))


def _log_s3_csv_success(ds_id: str, bucket: str, key: str, rows_desc: str) -> None:
    print(
        f"[{ds_id}] S3 write SUCCESS (CSV): {rows_desc} → s3://{bucket}/{key}",
        flush=True,
    )


def _write_table_landing_only(dataset: dict, ctx: dict, client) -> None:
    """CSV raw_landing only — no Iceberg / catalog writes (e.g. vuln scanner → EP builds reports)."""
    ds_id = dataset["id"]
    schema = dataset.get("schema", [])
    gen_cfg = dataset.get("generation", {})
    mode = gen_cfg.get("mode", "batch")
    raw_landing = dataset.get("raw_landing")
    if not raw_landing or not client:
        print(f"[{ds_id}] landing_only requires raw_landing and S3 client — skipping.")
        return None
    if mode not in ("batch",):
        print(f"[{ds_id}] landing_only supports mode=batch only (got {mode}) — skipping.")
        return None

    rl_bucket = raw_landing.get("bucket", "raw-logs")
    rl_prefix = raw_landing.get("prefix", "")
    rl_batch_size = int(raw_landing.get("batch_size", 5000))
    ensure_bucket(client, rl_bucket)

    total = int(gen_cfg.get("seed_rows", 1000))
    CHUNK = 2000
    written = 0
    csv_buf = []
    csv_file_num = 0
    while written < total:
        n = min(CHUNK, total - written)
        rows = generate_batch(schema, n, ctx)
        written += n
        pct = int(100 * written / total)
        done = " — DONE" if written == total else ""
        print(f"[{ds_id}] Raw CSV seeding: {written}/{total} rows ({pct}%){done}")

        csv_buf.extend(rows)
        while len(csv_buf) >= rl_batch_size:
            csv_file_num += 1
            batch = csv_buf[:rl_batch_size]
            csv_buf = csv_buf[rl_batch_size:]
            key = f"{rl_prefix}{ds_id}_{csv_file_num:05d}.csv"
            _write_csv_to_s3(client, rl_bucket, key, batch, schema)
            _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(batch)} rows")

    if csv_buf:
        csv_file_num += 1
        key = f"{rl_prefix}{ds_id}_{csv_file_num:05d}.csv"
        _write_csv_to_s3(client, rl_bucket, key, csv_buf, schema)
        _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(csv_buf)} rows (remainder)")

    print(f"[{ds_id}] landing_only complete — no Iceberg table writes.")
    return None


def write_landing_only_extra_files(
    dataset: dict, ctx: dict, client, num_files: int, rows_per_file: int,
) -> None:
    """Append N CSV files (for landing_only tables) — used by on-demand triggers."""
    ds_id = dataset["id"]
    schema = dataset.get("schema", [])
    raw_landing = dataset.get("raw_landing")
    if not raw_landing or not client or num_files <= 0 or rows_per_file <= 0:
        return
    rl_bucket = raw_landing.get("bucket", "raw-logs")
    rl_prefix = raw_landing.get("prefix", "")
    ensure_bucket(client, rl_bucket)
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    for fi in range(num_files):
        rows = generate_batch(schema, rows_per_file, ctx)
        key = f"{rl_prefix}{ds_id}_ondemand_{ts}_{fi + 1:04d}.csv"
        _write_csv_to_s3(client, rl_bucket, key, rows, schema)
        _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(rows)} rows (on-demand)")


def _cap_on_demand(n: int, mx: int) -> int:
    if n < 0:
        return 0
    return min(n, mx)


def _on_demand_specs(scenario: dict) -> list[tuple[dict, dict]]:
    out = []
    for ds in scenario.get("datasets", []):
        gen = ds.get("generation") or {}
        od = gen.get("on_demand")
        if isinstance(od, dict) and od.get("enabled"):
            out.append((ds, od))
    return out


def _parse_on_demand_counts(
    payload: dict | None, od_specs: list[tuple[dict, dict]],
) -> dict[str, int]:
    """Map dataset id → count (objects, or CSV files for landing_only)."""
    if not od_specs:
        return {}
    id_set = {d["id"] for d, _ in od_specs}
    defaults = {d["id"]: int(od.get("default_count", 1)) for d, od in od_specs}
    maxmap = {d["id"]: int(od.get("max_count", 5000)) for d, od in od_specs}

    if not payload:
        return {i: _cap_on_demand(defaults[i], maxmap[i]) for i in id_set}

    if isinstance(payload.get("generate"), list):
        counts: dict[str, int] = {}
        for item in payload["generate"]:
            if not isinstance(item, dict):
                continue
            dsid = item.get("dataset")
            if dsid in id_set:
                raw = int(item.get("count", defaults.get(dsid, 1)))
                counts[dsid] = _cap_on_demand(raw, maxmap[dsid])
        return counts if counts else {i: _cap_on_demand(defaults[i], maxmap[i]) for i in id_set}

    if "count" in payload and len(od_specs) == 1:
        only_id = od_specs[0][0]["id"]
        return {
            only_id: _cap_on_demand(int(payload["count"]), maxmap[only_id]),
        }

    counts = {}
    for k, v in payload.items():
        if k in ("generate", "scenario", "note"):
            continue
        if k in id_set and isinstance(v, (int, float)):
            counts[k] = _cap_on_demand(int(v), maxmap[k])
    if counts:
        return counts

    return {i: _cap_on_demand(defaults[i], maxmap[i]) for i in id_set}


def _resolve_on_demand_target(ds: dict, scenario: dict) -> dict:
    """If generation.on_demand.inherit_from is set, use that dataset's batch S3 target (bucket/prefix)."""
    gen = ds.get("generation") or {}
    od = gen.get("on_demand") or {}
    ref_id = od.get("inherit_from")
    if not ref_id:
        return ds
    sibling = next((d for d in scenario.get("datasets", []) if d.get("id") == ref_id), None)
    if not sibling:
        print(f"[on-demand] inherit_from dataset '{ref_id}' not found — using configured bucket/prefix")
        return ds
    out = copy.deepcopy(ds)
    st = sibling.get("target")
    if st == "table":
        rl = sibling.get("raw_landing") or {}
        if not rl.get("bucket"):
            print(f"[on-demand] '{ref_id}' has no raw_landing.bucket — cannot inherit; using defaults")
            return ds
        if ds.get("target") == "object":
            out["bucket"] = rl["bucket"]
            out["prefix"] = rl.get("prefix", "")
            print(
                f"[on-demand] '{ds['id']}' writes to s3://{out['bucket']}/{out['prefix']} "
                f"(same target as batch dataset '{ref_id}')",
            )
        elif ds.get("target") == "table" and ds.get("landing_only"):
            out["raw_landing"] = {**(ds.get("raw_landing") or {}), **rl}
            print(
                f"[on-demand] '{ds['id']}' raw_landing aligned with batch dataset '{ref_id}'",
            )
        else:
            print(
                f"[on-demand] inherit_from '{ref_id}' applies to object or landing_only datasets only "
                f"(got target={ds.get('target')}, landing_only={ds.get('landing_only')})",
            )
            return ds
    elif st == "object":
        if not sibling.get("bucket"):
            print(f"[on-demand] '{ref_id}' has no bucket — cannot inherit")
            return ds
        out["bucket"] = sibling["bucket"]
        out["prefix"] = sibling.get("prefix", "")
        print(
            f"[on-demand] '{ds['id']}' writes to s3://{out['bucket']}/{out['prefix']} "
            f"(same target as '{ref_id}')",
        )
    else:
        print(f"[on-demand] inherit_from '{ref_id}' has unsupported target={st}")
        return ds
    return out


def _run_on_demand_trigger(
    ds: dict,
    od_cfg: dict,
    count: int,
    ctx: dict,
    client,
    table_writer,
    table_kind: str,
    scenario: dict,
) -> None:
    ds_eff = _resolve_on_demand_target(ds, scenario)
    target = ds_eff.get("target")
    ds_id = ds["id"]
    if count <= 0:
        print(f"[on-demand] {ds_id}: count=0 — skip.")
        return
    if target == "object":
        write_object_batch(
            client, ds_eff, ctx, table_writer, table_kind, count, phase_label="On-demand",
        )
        return
    if target == "table" and ds_eff.get("landing_only"):
        raw = ds_eff.get("raw_landing") or {}
        rows_pf = int(od_cfg.get("rows_per_csv_file") or raw.get("batch_size", 500))
        max_files = int(od_cfg.get("max_csv_files", 50))
        nfiles = min(count, max_files)
        write_landing_only_extra_files(ds_eff, ctx, client, nfiles, rows_pf)
        return
    if target == "table" and FILES_ONLY and not ds_eff.get("landing_only") and ds_eff.get("raw_landing"):
        raw = ds_eff.get("raw_landing") or {}
        rows_pf = int(od_cfg.get("rows_per_csv_file") or raw.get("batch_size", 500))
        max_files = int(od_cfg.get("max_csv_files", 50))
        nfiles = min(count, max_files)
        write_landing_only_extra_files(ds_eff, ctx, client, nfiles, rows_pf)
        return
    print(
        f"[on-demand] dataset '{ds_id}' (target={target}, landing_only={ds_eff.get('landing_only')}) "
        "does not support on-demand — skip.",
    )


def run_on_demand_loop(
    scenario: dict,
    client,
    ctx: dict,
    table_writer,
    table_kind: str,
) -> None:
    """Poll ES_ON_DEMAND_DIR for *.json request files; generate batches offline (no cloud)."""
    od_specs = _on_demand_specs(scenario)
    if not od_specs:
        return
    poll = max(1.0, ES_ON_DEMAND_POLL_SEC)
    os.makedirs(ES_ON_DEMAND_DIR, exist_ok=True)
    processed = os.path.join(ES_ON_DEMAND_DIR, "processed")
    os.makedirs(processed, exist_ok=True)
    print(
        f"[external-system] On-demand generation enabled — drop *.json in {ES_ON_DEMAND_DIR} "
        f"(poll every {poll:g}s). Datasets: {[d[0]['id'] for d in od_specs]}",
    )
    while True:
        try:
            names = sorted(os.listdir(ES_ON_DEMAND_DIR))
        except OSError:
            time.sleep(poll)
            continue
        for name in names:
            if not name.endswith(".json") or name.startswith("."):
                continue
            path = os.path.join(ES_ON_DEMAND_DIR, name)
            if not os.path.isfile(path):
                continue
            payload = None
            try:
                with open(path, encoding="utf-8") as fh:
                    raw = fh.read().strip()
                payload = json.loads(raw) if raw else {}
            except Exception as exc:
                print(f"[on-demand] invalid JSON in {path}: {exc}")
                try:
                    dest = os.path.join(processed, f"{name}.error")
                    os.replace(path, dest)
                except OSError:
                    pass
                continue
            if not isinstance(payload, dict):
                print(f"[on-demand] expected object in {path}, got {type(payload)}")
                continue
            counts = _parse_on_demand_counts(payload, od_specs)
            print(f"[on-demand] request {name} → {counts}")
            for ds, od_cfg in od_specs:
                n = counts.get(ds["id"], 0)
                if n <= 0:
                    continue
                try:
                    _run_on_demand_trigger(ds, od_cfg, n, ctx, client, table_writer, table_kind, scenario)
                except Exception as exc:
                    print(f"[on-demand] {ds['id']} failed: {exc}")
            try:
                dest = os.path.join(processed, f"{int(time.time())}_{name}")
                os.replace(path, dest)
            except OSError as exc:
                print(f"[on-demand] could not move {path}: {exc}")
        time.sleep(poll)


def write_table_dataset(dataset: dict, ctx: dict, table_writer, table_kind: str, client=None):
    ds_id = dataset["id"]
    if dataset.get("landing_only"):
        return _write_table_landing_only(dataset, ctx, client)

    ns = dataset.get("namespace", "default")
    tn = dataset["table_name"]
    schema = dataset.get("schema", [])
    gen_cfg = dataset.get("generation", {})
    mode = gen_cfg.get("mode", "batch")

    if FILES_ONLY:
        raw_landing = dataset.get("raw_landing")
        if not raw_landing or not client:
            print(
                f"[{ds_id}] ES_SINK_MODE=files_only — table dataset needs raw_landing and S3 client; skipping.",
            )
            return None
        rl_bucket = raw_landing.get("bucket", "raw-logs")
        rl_prefix = raw_landing.get("prefix", "")
        rl_batch_size = int(raw_landing.get("batch_size", 5000))
        ensure_bucket(client, rl_bucket)
        csv_buf: list = []
        csv_file_num = 0
        if mode in ("batch", "batch_then_stream"):
            total = int(gen_cfg.get("seed_rows", 1000))
            CHUNK = 2000
            written = 0
            while written < total:
                n = min(CHUNK, total - written)
                rows = generate_batch(schema, n, ctx)
                written += n
                pct = int(100 * written / total)
                done = " — DONE" if written == total else ""
                print(f"[{ds_id}] Raw CSV seeding (files_only): {written}/{total} rows ({pct}%){done}")
                csv_buf.extend(rows)
                while len(csv_buf) >= rl_batch_size:
                    csv_file_num += 1
                    batch = csv_buf[:rl_batch_size]
                    csv_buf = csv_buf[rl_batch_size:]
                    key = f"{rl_prefix}{ds_id}_{csv_file_num:05d}.csv"
                    _write_csv_to_s3(client, rl_bucket, key, batch, schema)
                    _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(batch)} rows")
            if csv_buf:
                csv_file_num += 1
                key = f"{rl_prefix}{ds_id}_{csv_file_num:05d}.csv"
                _write_csv_to_s3(client, rl_bucket, key, csv_buf, schema)
                _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(csv_buf)} rows (remainder)")
        elif mode == "stream":
            print(f"[{ds_id}] files_only + mode=stream — no batch seed; streaming will write raw CSV only.")
        print(f"[{ds_id}] files_only table path complete — no Iceberg writes.")
        return {"dataset": dataset, "schema": schema, "namespace": ns, "table_name": tn}

    if not table_writer:
        print(f"[{ds_id}] No table writer (set ICEBERG_CATALOG_URI and install pyiceberg). Skipping.")
        return None

    try:
        table_writer.ensure_table(ns, tn, schema, partition_by=dataset.get("partition_by"))
    except TypeError:
        # PyIceberg variant has no partition_by arg
        table_writer.ensure_table(ns, tn, schema)
    except Exception as exc:
        print(f"[{ds_id}] ensure_table failed: {exc}")
        return None

    raw_landing = dataset.get("raw_landing")
    rl_client = client if raw_landing and client else None
    rl_bucket = rl_prefix = None
    rl_batch_size = 5000
    csv_buf = []
    csv_file_num = 0
    if rl_client and raw_landing:
        rl_bucket = raw_landing.get("bucket", "raw-logs")
        rl_prefix = raw_landing.get("prefix", "")
        rl_batch_size = int(raw_landing.get("batch_size", 5000))
        ensure_bucket(rl_client, rl_bucket)

    if mode in ("batch", "batch_then_stream"):
        total = int(gen_cfg.get("seed_rows", 1000))
        CHUNK = 2000
        written = 0
        while written < total:
            n = min(CHUNK, total - written)
            rows = generate_batch(schema, n, ctx)
            try:
                table_writer.append(ns, tn, rows, schema)
            except Exception as exc:
                print(f"[{ds_id}] append failed: {exc}")
                break
            written += n
            pct = int(100 * written / total)
            done = " — DONE" if written == total else ""
            print(f"[{ds_id}] Seeding: {written}/{total} rows ({pct}%){done}")

            # CSV raw landing
            if rl_client:
                csv_buf.extend(rows)
                while len(csv_buf) >= rl_batch_size:
                    csv_file_num += 1
                    batch = csv_buf[:rl_batch_size]
                    csv_buf = csv_buf[rl_batch_size:]
                    key = f"{rl_prefix}{ds_id}_{csv_file_num:05d}.csv"
                    _write_csv_to_s3(rl_client, rl_bucket, key, batch, schema)
                    _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(batch)} rows")

        # Flush remainder
        if rl_client and csv_buf:
            csv_file_num += 1
            key = f"{rl_prefix}{ds_id}_{csv_file_num:05d}.csv"
            _write_csv_to_s3(rl_client, rl_bucket, key, csv_buf, schema)
            _log_s3_csv_success(ds_id, rl_bucket, key, f"{len(csv_buf)} rows (remainder)")
            csv_buf = []

    return {"dataset": dataset, "schema": schema, "namespace": ns, "table_name": tn}


def run_streams(stream_datasets: list, table_writer, ctx: dict, client=None):
    """Round-robin stream generation for batch_then_stream / stream datasets."""
    if not stream_datasets:
        return
    print(f"[external-system] Entering stream mode for {len(stream_datasets)} dataset(s)")
    # Build per-dataset schedulers
    scheds = []
    now = time.time()
    for meta in stream_datasets:
        ds = meta["dataset"]
        gen_cfg = ds.get("generation", {})
        rate = _parse_rate(gen_cfg.get("stream_rate", "1/s"))
        duration = _parse_duration(gen_cfg.get("stream_duration", "forever"))
        scheds.append({
            "meta": meta,
            "interval": 1.0 / rate if rate > 0 else 1.0,
            "next_fire": now,
            "end": now + duration,
            "rows_sent": 0,
            "rate": rate,
        })
        print(f"[{ds['id']}] Streaming: {rate:g} rows/s")

    # Build per-dataset CSV state for raw landing
    for s in scheds:
        ds = s["meta"]["dataset"]
        rl = ds.get("raw_landing")
        if rl and client:
            rl_bucket = rl.get("bucket", "raw-logs")
            ensure_bucket(client, rl_bucket)
            s["csv_state"] = {
                "buf": [],
                "file_num": 0,
                "bucket": rl_bucket,
                "prefix": rl.get("prefix", ""),
                "batch_size": 200,
            }
        else:
            s["csv_state"] = None

    # Combined loop
    while True:
        now = time.time()
        active = [s for s in scheds if now < s["end"]]
        if not active:
            print("[external-system] All streams complete.")
            return
        # Fire any due
        for s in active:
            if now >= s["next_fire"]:
                ds = s["meta"]["dataset"]
                schema = s["meta"]["schema"]
                ns = s["meta"]["namespace"]
                tn = s["meta"]["table_name"]
                row = generate_row(schema, ctx)
                if table_writer and not FILES_ONLY:
                    try:
                        quiet = s["rows_sent"] > 0
                        table_writer.append(ns, tn, [row], schema, quiet=quiet)
                        s["rows_sent"] += 1
                        if s["rows_sent"] % 50 == 0:
                            ib = table_writer.last_iceberg_data_prefix()
                            ibs = f" | iceberg_data_prefix={ib}" if ib else ""
                            print(f"[{ds['id']}] streamed={s['rows_sent']} rate={s['rate']:g}/s{ibs}")
                    except Exception as exc:
                        print(f"[{ds['id']}] stream append failed: {exc}")
                elif FILES_ONLY:
                    s["rows_sent"] += 1
                    if s["rows_sent"] % 50 == 0:
                        print(f"[{ds['id']}] streamed(csv-only)={s['rows_sent']} rate={s['rate']:g}/s")
                if s.get("csv_state") and client:
                    import datetime as _dt
                    cs = s["csv_state"]
                    cs["buf"].append(row)
                    if len(cs["buf"]) >= cs["batch_size"]:
                        cs["file_num"] += 1
                        ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
                        key = f"{cs['prefix']}{ds['id']}_stream_{ts}_{cs['file_num']:05d}.csv"
                        _write_csv_to_s3(client, cs["bucket"], key, cs["buf"], schema)
                        _log_s3_csv_success(ds["id"], cs["bucket"], key, f"{len(cs['buf'])} rows (stream)")
                        cs["buf"] = []
                s["next_fire"] += s["interval"]
        # Sleep until next event
        next_fire = min(s["next_fire"] for s in active)
        sleep = max(0.01, next_fire - time.time())
        time.sleep(min(sleep, 1.0))


# ---------------------------------------------------------------------------
# Metabase provisioning
# ---------------------------------------------------------------------------

INTENTS_DIR = os.environ.get("MB_INTENTS_DIR", "/provision-intents")


def publish_metabase_intent(scenario: dict):
    """Write a provisioning intent file to the shared volume for the Metabase reconciler."""
    dashboards = scenario.get("dashboards", [])
    saved_queries = scenario.get("saved_queries", {})
    qlist = saved_queries.get("queries") or []
    if not dashboards and not qlist:
        print("[external-system] No Metabase dashboards/queries in scenario — skipping intent.")
        if _integration_log_append:
            _integration_log_append(
                "info",
                "dashboard_seed_request",
                f"No Metabase dashboards/queries in scenario {scenario['id']} — intent not written",
                "",
            )
        return

    import json as _json
    intent = {
        "scenario_id": scenario["id"],
        "scenario_name": scenario.get("name", ""),
        "dashboards": dashboards,
        "saved_queries": saved_queries,
    }
    os.makedirs(INTENTS_DIR, exist_ok=True)
    path = os.path.join(INTENTS_DIR, f"{scenario['id']}.json")
    try:
        with open(path, "w") as f:
            _json.dump(intent, f, indent=2)
        print(f"[external-system] Metabase intent written → {path}")
        if _integration_log_append:
            titles = [d.get("title", "?") for d in dashboards]
            _integration_log_append(
                "info",
                "dashboard_seed_request",
                f"Metabase dashboard seed requested for scenario {scenario['id']}",
                f"path={path} dashboard_count={len(dashboards)} dashboard_titles={_json.dumps(titles)} saved_query_count={len(qlist)} await_kind=dashboard_seed_result",
            )
    except Exception as exc:
        print(f"[external-system] Failed to write Metabase intent: {exc}")
        if _integration_log_append:
            _integration_log_append(
                "error",
                "dashboard_seed_request",
                f"Failed to write Metabase intent for scenario {scenario['id']}",
                str(exc)[:500],
            )


# ---------------------------------------------------------------------------
# Cross-scenario correlation (firewall <- threat_iocs + vulnerability_scan)
# ---------------------------------------------------------------------------

def _load_correlation_ips(ctx: dict, scenario: dict):
    """If firewall scenario, try to pull real IPs via Trino from related tables."""
    if scenario["id"] != "soc-firewall-events" or not TRINO_HOST:
        return
    import requests
    host = TRINO_HOST if TRINO_HOST.startswith("http") else f"http://{TRINO_HOST}"
    tries = [
        (f'SELECT indicator FROM "{TRINO_CATALOG}"."soc"."threat_iocs" '
         f"WHERE ioc_type='ipv4' LIMIT 200"),
        (f'SELECT host_ip FROM "{TRINO_CATALOG}"."soc"."vulnerability_scan" LIMIT 200'),
    ]
    ips = []
    for sql in tries:
        try:
            resp = requests.post(
                f"{host}/v1/statement", data=sql,
                headers={"X-Trino-User": "demoforge", "X-Trino-Catalog": TRINO_CATALOG,
                         "Content-Type": "text/plain"},
                timeout=20,
            )
            result = resp.json()
            while "nextUri" in result:
                r2 = requests.get(result["nextUri"], timeout=20)
                result = r2.json()
                for row in result.get("data", []) or []:
                    if row and row[0]:
                        ips.append(str(row[0]))
                if result.get("stats", {}).get("state") in ("FINISHED", "FAILED"):
                    break
        except Exception as exc:
            print(f"[external-system] correlation lookup skipped: {exc}")
    if ips:
        ctx["_known_bad_ips"] = ips
        print(f"[external-system] Loaded {len(ips)} correlated IPs for firewall traffic.")


# ---------------------------------------------------------------------------
# Data Generator scenario bridge (same writers + paths as data-generator image)
# ---------------------------------------------------------------------------

def _dg_dataset_yaml_path(scenario_id: str) -> str:
    return os.path.join(DG_VENDOR_ROOT, "datasets", f"{scenario_id}.yaml")


def _external_system_scenario_yaml_path(scenario_id: str) -> str:
    return os.path.join(ES_SCENARIOS_DIR, f"{scenario_id}.yaml")


def _run_data_generator_scenario_loop() -> None:
    """Execute data-generator/generate.py main_scenario with External System env."""
    dg_gen = os.path.join(DG_VENDOR_ROOT, "generate.py")
    if not os.path.isfile(dg_gen):
        print(f"[external-system] Data Generator bundle missing at {dg_gen}. Rebuild the image.")
        sys.exit(1)

    fmt = (os.environ.get("DG_FORMAT") or os.environ.get("ES_DG_FORMAT") or "parquet").strip().lower()
    if fmt not in ("parquet", "json", "csv"):
        fmt = "parquet"
    profile = (os.environ.get("DG_RATE_PROFILE") or os.environ.get("ES_DG_RATE_PROFILE") or "medium").strip().lower()
    if profile not in ("low", "medium", "high"):
        profile = "medium"

    os.environ["DG_SCENARIO"] = ES_SCENARIO
    os.environ["DG_FORMAT"] = fmt
    os.environ["DG_RATE_PROFILE"] = profile
    os.environ["DG_WRITE_MODE"] = "raw" if FILES_ONLY else os.environ.get("DG_WRITE_MODE", "iceberg")

    if ES_STARTUP_DELAY > 0:
        print(f"[external-system] ES_STARTUP_DELAY={ES_STARTUP_DELAY}s — sleeping before DG scenario loop...")
        time.sleep(ES_STARTUP_DELAY)

    print(
        f"[external-system] Data Generator scenario mode: scenario={ES_SCENARIO} "
        f"format={fmt} rate_profile={profile} DG_WRITE_MODE={os.environ['DG_WRITE_MODE']}"
    )

    # run.py already imported `src.*` from /app/src. Vendored generate.py expects
    # data-generator's `src` tree (value_generators, writers, schema_loader, …).
    # Drop cached `src` modules so imports resolve under DG_VENDOR_ROOT first.
    _saved_src_modules: dict[str, object] = {}
    for _k in list(sys.modules):
        if _k == "src" or _k.startswith("src."):
            _saved_src_modules[_k] = sys.modules.pop(_k)

    sys.path.insert(0, DG_VENDOR_ROOT)
    try:
        spec = importlib.util.spec_from_file_location("_demoforge_dg_generate", dg_gen)
        if spec is None or spec.loader is None:
            print("[external-system] Could not load bundled generate.py")
            sys.exit(1)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main_scenario(ES_SCENARIO, fmt, profile)
    finally:
        for _k, _m in _saved_src_modules.items():
            if _m is not None:
                sys.modules[_k] = _m


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not ES_SCENARIO:
        print("[external-system] ES_SCENARIO env var is required. Exiting.")
        sys.exit(1)

    es_yaml = _external_system_scenario_yaml_path(ES_SCENARIO)
    dg_yaml = _dg_dataset_yaml_path(ES_SCENARIO)
    if os.path.isfile(es_yaml):
        pass  # native external-system scenario
    elif os.path.isfile(dg_yaml):
        _run_data_generator_scenario_loop()
        return
    else:
        print(
            f"[external-system] No scenario file for '{ES_SCENARIO}' under {ES_SCENARIOS_DIR} "
            f"or {os.path.dirname(dg_yaml)}."
        )
        sys.exit(1)

    scenario = load_scenario(ES_SCENARIO, ES_SCENARIOS_DIR)
    print(f"[external-system] Loaded scenario: {scenario['id']} — {scenario['name']}")

    if ES_STARTUP_DELAY > 0:
        print(f"[external-system] ES_STARTUP_DELAY={ES_STARTUP_DELAY}s — sleeping before generation...")
        time.sleep(ES_STARTUP_DELAY)

    # Build generator context
    ctx = {"_counters": {}, "_reference_data": {}, "_known_bad_ips": []}
    for ref in scenario.get("reference_data", []):
        ctx["_reference_data"][ref["id"]] = {
            "columns": ref.get("columns", []),
            "rows": ref.get("rows", []),
        }
    # Seed known_bad_ips from reference_data when present
    kb = ctx["_reference_data"].get("known_c2_ips")
    if kb:
        cols = kb["columns"]
        if "ip" in cols:
            idx = cols.index("ip")
            ctx["_known_bad_ips"].extend([r[idx] for r in kb["rows"]])

    # S3 client
    client = wait_for_minio(timeout=180)

    # Table writer
    table_writer, table_kind = _get_table_writer()
    if FILES_ONLY:
        print("[external-system] ES_SINK_MODE=files_only — catalog/mirror Iceberg writes disabled.")
    if table_writer and not FILES_ONLY:
        print(f"[external-system] Using table writer: {table_kind}")
    elif not FILES_ONLY:
        has_landing_only = any(
            d.get("target") == "table" and d.get("landing_only")
            for d in scenario.get("datasets", [])
        )
        if has_landing_only:
            print("[external-system] No Iceberg writer — landing_only datasets still write raw CSV to S3.")
        else:
            print(
                "[external-system] No PyIceberg writer (missing ICEBERG_CATALOG_URI or pyiceberg) — "
                "table datasets will be skipped."
            )

    # Cross-scenario correlation
    _load_correlation_ips(ctx, scenario)

    # Process datasets sequentially
    stream_metas = []
    for ds in scenario["datasets"]:
        target = ds["target"]
        if target == "object":
            write_object_dataset(client, ds, ctx, table_writer, table_kind)
        elif target == "table":
            meta = write_table_dataset(ds, ctx, table_writer, table_kind, client=client)
            mode = ds.get("generation", {}).get("mode", "batch")
            if meta and mode in ("stream", "batch_then_stream"):
                stream_metas.append(meta)
        else:
            print(f"[external-system] Unknown dataset target '{target}' — skipping.")

    # Publish provisioning intent to shared volume for Metabase reconciler
    publish_metabase_intent(scenario)

    # Stream phase (CSV-only streams allowed when FILES_ONLY + raw_landing)
    if stream_metas and (table_writer or FILES_ONLY):
        run_streams(stream_metas, table_writer, ctx, client=client)

    # On-demand file generation (poll ES_ON_DEMAND_DIR for *.json)
    if _on_demand_specs(scenario):
        run_on_demand_loop(scenario, client, ctx, table_writer, table_kind)
    else:
        print("[external-system] No on-demand datasets — engine idling.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
