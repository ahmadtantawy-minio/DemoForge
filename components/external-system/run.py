"""
run.py — External System scenario engine entrypoint.

Reads scenario YAML from /scenarios/{ES_SCENARIO}.yaml and drives a data
generation pipeline that writes Iceberg tables (via PyIceberg or Trino) and
MinIO objects, then provisions Metabase dashboards and saved queries.

Env vars:
  ES_SCENARIO           scenario ID (e.g. "soc-firewall-events")
  ES_SCENARIOS_DIR      scenarios dir (default /app/scenarios)
  ES_STARTUP_DELAY      seconds to sleep before generation (correlation ordering)
  S3_ENDPOINT           MinIO endpoint
  S3_ACCESS_KEY         MinIO access key
  S3_SECRET_KEY         MinIO secret key
  ICEBERG_CATALOG_URI   Iceberg REST catalog URL
  ICEBERG_WAREHOUSE     warehouse name (default "warehouse")
  ICEBERG_SIGV4         "true" for AIStor SigV4 auth
  TRINO_HOST            Trino host:port (fallback / cross-scenario lookups)
  TRINO_CATALOG         Trino catalog name (default "iceberg")
  METABASE_URL          Metabase URL (default http://metabase:3000)
  METABASE_USER         Metabase user (default admin@demoforge.local)
  METABASE_PASSWORD     Metabase password (default DemoForge123!)
"""

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


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

ES_SCENARIO = os.environ.get("ES_SCENARIO", "")
ES_SCENARIOS_DIR = os.environ.get("ES_SCENARIOS_DIR", "/app/scenarios")
ES_STARTUP_DELAY = int(os.environ.get("ES_STARTUP_DELAY", "0") or 0)

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")

ICEBERG_CATALOG_URI = os.environ.get("ICEBERG_CATALOG_URI", "")
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
# Iceberg / Trino table writers
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

    def _catalog_handle(self):
        if self._catalog:
            return self._catalog
        from pyiceberg.catalog.rest import RestCatalog
        endpoint = _s3_endpoint_url()
        wh = ICEBERG_WAREHOUSE
        wh_uri = wh if ICEBERG_SIGV4 else (wh if wh.startswith("s3://") else f"s3://{wh}/")
        catalog_uri = ICEBERG_CATALOG_URI
        if ICEBERG_SIGV4 and "-lb:" in catalog_uri:
            catalog_uri = catalog_uri.replace("-lb:", "-node-1:").replace(":80/", ":9000/")
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
        self._catalog = RestCatalog(name="external-system", **props)
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

    def append(self, namespace: str, table_name: str, rows: list, schema: list) -> int:
        if not rows:
            return 0
        arrow = _rows_to_arrow(rows, schema)
        for attempt in range(2):
            try:
                catalog = self._catalog_handle()
                tbl = catalog.load_table(f"{namespace}.{table_name}")
                tbl.append(arrow)
                return len(rows)
            except Exception:
                if attempt == 0:
                    self._catalog = None
                else:
                    raise
        return len(rows)


class TrinoTableWriter:
    """Fallback writer: CREATE TABLE IF NOT EXISTS + INSERT via Trino HTTP."""

    def __init__(self, trino_host: str, catalog: str):
        self.host = trino_host
        self.catalog = catalog

    def _post_query(self, sql: str):
        import requests
        host = self.host if self.host.startswith("http") else f"http://{self.host}"
        resp = requests.post(
            f"{host}/v1/statement",
            data=sql,
            headers={
                "X-Trino-User": "demoforge",
                "X-Trino-Catalog": self.catalog,
                "Content-Type": "text/plain",
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        # Follow nextUri until done
        while "nextUri" in result:
            r2 = requests.get(result["nextUri"], timeout=60)
            r2.raise_for_status()
            result = r2.json()
            if result.get("stats", {}).get("state") in ("FINISHED", "FAILED"):
                break
        if result.get("error"):
            raise RuntimeError(f"Trino error: {result['error']}")
        return result

    def _trino_type(self, t: str) -> str:
        return {
            "string": "VARCHAR",
            "integer": "INTEGER",
            "int": "INTEGER",
            "int32": "INTEGER",
            "long": "BIGINT",
            "int64": "BIGINT",
            "float": "REAL",
            "float32": "REAL",
            "double": "DOUBLE",
            "float64": "DOUBLE",
            "boolean": "BOOLEAN",
            "timestamp": "TIMESTAMP(6)",
            "date": "DATE",
        }.get(t, "VARCHAR")

    def _wait_for_trino(self, max_wait: int = 300, interval: int = 10):
        """Block until Trino responds, up to max_wait seconds."""
        import requests, time
        host = self.host if self.host.startswith("http") else f"http://{self.host}"
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                r = requests.get(f"{host}/v1/info", timeout=5)
                if r.ok and r.json().get("starting") is False:
                    return
            except Exception:
                pass
            remaining = int(deadline - time.time())
            print(f"[trino] server not ready, retrying in {interval}s (up to {remaining}s remaining)…", flush=True)
            time.sleep(interval)
        raise RuntimeError(f"Trino at {self.host} did not become ready within {max_wait}s")

    def ensure_table(self, namespace: str, table_name: str, schema: list,
                     partition_by: list = None):
        cols = ", ".join(f'"{c["name"]}" {self._trino_type(c.get("type", "string"))}' for c in schema)
        schema_fqn = f'"{self.catalog}"."{namespace}"'
        print(f"[schema] CREATE SCHEMA IF NOT EXISTS {schema_fqn}", flush=True)
        try:
            self._post_query(f'CREATE SCHEMA IF NOT EXISTS {schema_fqn}')
            print(f"[schema] ok: {schema_fqn}", flush=True)
        except Exception as exc:
            if "SERVER_STARTING_UP" in str(exc) or "still initializing" in str(exc):
                print(f"[schema] Trino still initializing — waiting for ready…", flush=True)
                self._wait_for_trino()
                self._post_query(f'CREATE SCHEMA IF NOT EXISTS {schema_fqn}')
                print(f"[schema] ok (after wait): {schema_fqn}", flush=True)
            else:
                print(f"[schema] failed: {schema_fqn}: {exc}", flush=True)
                raise
        with_clause = ""
        if partition_by:
            parts = ", ".join(f"'{p}'" for p in partition_by)
            with_clause = f" WITH (partitioning = ARRAY[{parts}])"
        table_fqn = f'"{self.catalog}"."{namespace}"."{table_name}"'
        print(f"[table] CREATE TABLE IF NOT EXISTS {table_fqn}", flush=True)
        sql = f'CREATE TABLE IF NOT EXISTS {table_fqn} ({cols}){with_clause}'
        try:
            self._post_query(sql)
            print(f"[table] ok: {table_fqn}", flush=True)
        except Exception as exc:
            err_str = str(exc)
            # Trino still booting — wait and retry the full sequence
            if "SERVER_STARTING_UP" in err_str or "still initializing" in err_str:
                print(f"[table] Trino still initializing — waiting…", flush=True)
                self._wait_for_trino()
                self._post_query(sql)
                print(f"[table] ok (after wait): {table_fqn}", flush=True)
                return
            # Some catalogs (Hive, non-Iceberg) don't support the partitioning property.
            # Retry without it so table creation still succeeds.
            if with_clause and "partitioning" in err_str and "does not exist" in err_str:
                print(f"[table] partitioning not supported by catalog, retrying without: {table_fqn}", flush=True)
                sql_no_part = f'CREATE TABLE IF NOT EXISTS {table_fqn} ({cols})'
                try:
                    self._post_query(sql_no_part)
                    print(f"[table] ok (no partitioning): {table_fqn}", flush=True)
                    return
                except Exception as exc2:
                    print(f"[table] failed (no partitioning): {table_fqn}: {exc2}", flush=True)
                    raise exc2
            print(f"[table] failed: {table_fqn}: {exc}", flush=True)
            raise

    def _fmt_literal(self, val, col_type: str) -> str:
        if val is None:
            return "NULL"
        if col_type in ("integer", "int", "int32", "long", "int64", "float", "float32",
                         "double", "float64"):
            return str(val)
        if col_type == "boolean":
            return "TRUE" if val else "FALSE"
        if col_type == "timestamp":
            import datetime as _dt
            if isinstance(val, _dt.datetime):
                return f"TIMESTAMP '{val.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
            return f"TIMESTAMP '{val}'"
        if col_type == "date":
            return f"DATE '{val}'"
        # string / json
        s = val if isinstance(val, str) else json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        s = s.replace("'", "''")
        return f"'{s}'"

    def append(self, namespace: str, table_name: str, rows: list, schema: list) -> int:
        if not rows:
            return 0
        col_names = ", ".join(f'"{c["name"]}"' for c in schema)
        # Chunk inserts to keep statements small
        CHUNK = 500
        total = 0
        for i in range(0, len(rows), CHUNK):
            chunk = rows[i:i + CHUNK]
            values_rows = []
            for r in chunk:
                parts = [self._fmt_literal(r.get(c["name"]), c.get("type", "string")) for c in schema]
                values_rows.append("(" + ", ".join(parts) + ")")
            sql = (
                f'INSERT INTO "{self.catalog}"."{namespace}"."{table_name}" ({col_names}) VALUES '
                + ", ".join(values_rows)
            )
            self._post_query(sql)
            total += len(chunk)
        return total


def _get_table_writer():
    """Return (writer, kind) — PyIceberg if available, else Trino, else None."""
    if _PYICEBERG_AVAILABLE and ICEBERG_CATALOG_URI and not ICEBERG_SIGV4:
        try:
            return IcebergTableWriter(), "iceberg"
        except Exception as exc:
            print(f"[external-system] IcebergTableWriter init failed: {exc}")
    if TRINO_HOST:
        return TrinoTableWriter(TRINO_HOST, TRINO_CATALOG), "trino"
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


def write_object_dataset(client, dataset: dict, ctx: dict, table_writer, table_kind: str):
    bucket = dataset["bucket"]
    prefix = dataset.get("prefix", "")
    fmt = dataset.get("object_format", "json")
    schema = dataset.get("schema", [])
    gen_cfg = dataset.get("generation", {})
    count = int(gen_cfg.get("seed_count", 100))
    ds_id = dataset["id"]

    ensure_bucket(client, bucket)

    mirror = dataset.get("mirror_to_table")
    mirror_rows = []
    mirror_fields_spec = None
    if mirror:
        # Build schema for the mirror table: pick fields from dataset.schema whose names are in mirror.fields
        names = set(mirror.get("fields", []))
        mirror_fields_spec = [f for f in schema if f["name"] in names]

    print(f"[{ds_id}] Writing {count} objects to s3://{bucket}/{prefix} ({fmt})")

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
            body = os.urandom(min(size_max, max(size_min, size_min)))
            # randomize size per object
            import random as _r
            body = os.urandom(_r.randint(size_min, size_max))
            key = key_name if "." in os.path.basename(key_name) else f"{key_name}.bin"
        else:  # text
            body = (row.get("content") or "lorem ipsum").encode("utf-8")
            key = key_name if key_name.endswith(".txt") else f"{key_name}.txt"

        put_kwargs = {"Bucket": bucket, "Key": key, "Body": body}
        client.put_object(**put_kwargs)

        # Tag objects with schema-derived metadata (used for mirror_to_table)
        if mirror_fields_spec:
            tags = []
            for f in mirror_fields_spec:
                v = row.get(f["name"])
                if v is None:
                    continue
                if hasattr(v, "isoformat"):
                    v = v.isoformat()
                # S3 tag values have restrictions; clamp + sanitize
                sv = str(v)[:256]
                tags.append({"Key": f["name"], "Value": sv})
            if tags:
                try:
                    client.put_object_tagging(
                        Bucket=bucket, Key=key, Tagging={"TagSet": tags}
                    )
                except Exception as exc:
                    print(f"[{ds_id}] tagging failed for {key}: {exc}")
            # Mirror row carries just the selected fields
            mirror_rows.append({f["name"]: row.get(f["name"]) for f in mirror_fields_spec})

        if (i + 1) % progress_every == 0 or (i + 1) == count:
            pct = int(100 * (i + 1) / count)
            done = " — DONE" if (i + 1) == count else ""
            print(f"[{ds_id}] Seeding: {i + 1}/{count} objects ({pct}%){done}")

    # Write mirror table
    if mirror and mirror_rows and table_writer:
        ns = mirror["namespace"]
        tn = mirror["table_name"]
        print(f"[{ds_id}] Mirroring {len(mirror_rows)} rows -> {ns}.{tn}")
        try:
            if table_kind == "trino":
                table_writer.ensure_table(ns, tn, mirror_fields_spec)
            else:
                table_writer.ensure_table(ns, tn, mirror_fields_spec)
            table_writer.append(ns, tn, mirror_rows, mirror_fields_spec)
        except Exception as exc:
            print(f"[{ds_id}] mirror table write failed: {exc}")


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


def write_table_dataset(dataset: dict, ctx: dict, table_writer, table_kind: str):
    ds_id = dataset["id"]
    ns = dataset.get("namespace", "default")
    tn = dataset["table_name"]
    schema = dataset.get("schema", [])
    gen_cfg = dataset.get("generation", {})
    mode = gen_cfg.get("mode", "batch")

    if not table_writer:
        print(f"[{ds_id}] No table writer available (no Iceberg catalog, no Trino). Skipping.")
        return None

    try:
        table_writer.ensure_table(ns, tn, schema, partition_by=dataset.get("partition_by"))
    except TypeError:
        # PyIceberg variant has no partition_by arg
        table_writer.ensure_table(ns, tn, schema)
    except Exception as exc:
        print(f"[{ds_id}] ensure_table failed: {exc}")
        return None

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

    return {"dataset": dataset, "schema": schema, "namespace": ns, "table_name": tn}


def run_streams(stream_datasets: list, table_writer, ctx: dict):
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
                try:
                    table_writer.append(ns, tn, [row], schema)
                    s["rows_sent"] += 1
                    if s["rows_sent"] % 50 == 0:
                        print(f"[{ds['id']}] streamed={s['rows_sent']} rate={s['rate']:g}/s")
                except Exception as exc:
                    print(f"[{ds['id']}] stream append failed: {exc}")
                s["next_fire"] += s["interval"]
        # Sleep until next event
        next_fire = min(s["next_fire"] for s in active)
        sleep = max(0.01, next_fire - time.time())
        time.sleep(min(sleep, 1.0))


# ---------------------------------------------------------------------------
# Metabase provisioning
# ---------------------------------------------------------------------------

def provision_metabase(scenario: dict):
    dashboards = scenario.get("dashboards", [])
    saved_queries = scenario.get("saved_queries", {})
    if not dashboards and not saved_queries.get("queries"):
        print("[external-system] No Metabase dashboards/queries to provision.")
        return

    try:
        mc.wait_for_metabase(METABASE_URL, timeout=300)
    except Exception as exc:
        print(f"[external-system] Metabase not ready, skipping provisioning: {exc}")
        return

    try:
        token = mc.get_session_token(METABASE_URL, METABASE_USER, METABASE_PASSWORD)
    except Exception as exc:
        print(f"[external-system] Metabase login failed, skipping: {exc}")
        return

    try:
        db_id = mc.ensure_trino_database(METABASE_URL, token, TRINO_HOST or "trino:8080",
                                         catalog=TRINO_CATALOG)
    except Exception as exc:
        print(f"[external-system] Trino db setup failed, skipping: {exc}")
        return

    # Saved queries
    sq_col_name = saved_queries.get("collection")
    sq_collection_id = None
    if sq_col_name:
        try:
            sq_collection_id = mc.create_collection(METABASE_URL, token, sq_col_name,
                                                    description=f"Queries for {scenario['name']}")
            print(f"[external-system] Collection '{sq_col_name}' ready (id={sq_collection_id})")
        except Exception as exc:
            print(f"[external-system] collection create failed: {exc}")

    queries = sorted(saved_queries.get("queries", []), key=lambda q: q.get("order", 0))
    for q in queries:
        try:
            card_id = mc.create_question(
                METABASE_URL, token,
                collection_id=sq_collection_id,
                title=q["title"],
                sql=q["query"],
                visualization=q.get("visualization", "table"),
                description=q.get("description", ""),
                db_id=db_id,
            )
            print(f"[external-system]   + question: {q['title']} (card={card_id})")
        except Exception as exc:
            print(f"[external-system]   ! question failed {q.get('id')}: {exc}")

    # Dashboards
    for dash in dashboards:
        try:
            dash_id = mc.create_dashboard(METABASE_URL, token, dash["title"],
                                          description=dash.get("description", ""))
            dashcards = []
            for chart in dash.get("charts", []):
                card_id = mc.create_question(
                    METABASE_URL, token,
                    collection_id=sq_collection_id,
                    title=chart["title"],
                    sql=chart["query"],
                    visualization=chart.get("type", "table"),
                    description="",
                    db_id=db_id,
                )
                pos = chart.get("position", {})
                dashcards.append({
                    "card_id": card_id,
                    "row": pos.get("row", 0),
                    "col": pos.get("col", 0),
                    "width": pos.get("width", 6),
                    "height": pos.get("height", 4),
                })
            if dashcards:
                mc.add_cards_to_dashboard(METABASE_URL, token, dash_id, dashcards)
            print(f"[external-system] Dashboard '{dash['title']}' ready (id={dash_id}, {len(dashcards)} cards)")
        except Exception as exc:
            print(f"[external-system] dashboard failed {dash.get('id')}: {exc}")


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
# Main
# ---------------------------------------------------------------------------

def main():
    if not ES_SCENARIO:
        print("[external-system] ES_SCENARIO env var is required. Exiting.")
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
    if table_writer:
        print(f"[external-system] Using table writer: {table_kind}")
    else:
        print("[external-system] No table writer — table datasets will be skipped.")

    # Cross-scenario correlation
    _load_correlation_ips(ctx, scenario)

    # Process datasets sequentially
    stream_metas = []
    for ds in scenario["datasets"]:
        target = ds["target"]
        if target == "object":
            write_object_dataset(client, ds, ctx, table_writer, table_kind)
        elif target == "table":
            meta = write_table_dataset(ds, ctx, table_writer, table_kind)
            mode = ds.get("generation", {}).get("mode", "batch")
            if meta and mode in ("stream", "batch_then_stream"):
                stream_metas.append(meta)
        else:
            print(f"[external-system] Unknown dataset target '{target}' — skipping.")

    # Provision Metabase only when a dashboard-provision edge injected METABASE_URL
    if METABASE_URL:
        provision_metabase(scenario)
    else:
        print("[external-system] No Metabase URL configured — skipping dashboard provisioning.")

    # Stream phase
    if stream_metas and table_writer:
        run_streams(stream_metas, table_writer, ctx)
    else:
        print("[external-system] No streaming datasets — engine idling.")
        # Keep container alive
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
