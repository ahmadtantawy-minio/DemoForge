"""
table_setup.py — One-time setup run before streaming begins.

1. Create MinIO buckets defined in the scenario.
2. Create Iceberg table (if format=iceberg) via IcebergWriter.
3. Register external Trino table (if format=parquet/json/csv).
"""

import os

import boto3
from botocore.exceptions import ClientError


def make_s3_client(endpoint: str, access_key: str, secret_key: str) -> boto3.client:
    url = endpoint if endpoint.startswith("http") else f"http://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


def ensure_bucket(s3_client, bucket_name: str) -> bool:
    """Create a bucket if it doesn't already exist. Returns True if created."""
    if not bucket_name:
        return False
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"[table_setup] Bucket '{bucket_name}' already exists.")
        return False
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            s3_client.create_bucket(Bucket=bucket_name)
            print(f"[table_setup] Created bucket '{bucket_name}'.")
            return True
        raise


def create_buckets(scenario: dict, s3_client) -> None:
    """Create all buckets declared in the scenario's 'buckets' config."""
    buckets = scenario.get("buckets", {})
    for fmt, bucket_name in buckets.items():
        if bucket_name:
            ensure_bucket(s3_client, bucket_name)


def create_iceberg_table(scenario: dict, iceberg_writer) -> None:
    """
    Create the Iceberg table for the scenario if it doesn't exist.
    iceberg_writer is an IcebergWriter instance.
    """
    iceberg_cfg = scenario.get("iceberg")
    if not iceberg_cfg:
        print("[table_setup] No Iceberg config in scenario — skipping table creation.")
        return

    namespace = iceberg_cfg.get("namespace", "demo")
    table_name = iceberg_cfg.get("table", "data")
    partition_spec = iceberg_cfg.get("partition_spec")
    columns = scenario.get("columns", [])

    print(
        f"[table_setup] Ensuring Iceberg table '{namespace}.{table_name}' "
        f"(partition: {partition_spec})"
    )
    iceberg_writer.ensure_table(
        namespace=namespace,
        table_name=table_name,
        columns=columns,
        partition_spec_sql=partition_spec,
    )
    print(f"[table_setup] Iceberg table '{namespace}.{table_name}' ready.")


def _trino_column_defs(columns: list, fmt: str) -> str:
    """Build Trino-compatible column definitions string."""
    type_map = {
        "string": "VARCHAR",
        "int32": "INTEGER",
        "int64": "BIGINT",
        "float32": "REAL",
        "float64": "DOUBLE",
        "boolean": "BOOLEAN",
        "timestamp": "TIMESTAMP",
        "date": "DATE",
    }
    parts = []
    for col in columns:
        trino_type = type_map.get(col.get("type", "string"), "VARCHAR")
        parts.append(f"    {col['name']} {trino_type}")
    return ",\n".join(parts)


def register_external_table(
    scenario: dict,
    fmt: str,
    trino_connection,
    catalog: str,
    namespace: str,
    s3_endpoint: str,
) -> None:
    """
    Execute CREATE TABLE IF NOT EXISTS via Trino to register an external table
    pointing at the scenario's S3 bucket.

    trino_connection: a connection object with a cursor() method (e.g. from trino-python-client).
    """
    bucket = scenario.get("buckets", {}).get(fmt)
    if not bucket:
        print(f"[table_setup] No bucket configured for format '{fmt}' — skipping DDL.")
        return

    iceberg_cfg = scenario.get("iceberg", {}) or {}
    table_name = iceberg_cfg.get("table", scenario.get("id", "data").replace("-", "_"))
    columns = scenario.get("columns", [])

    # Build external location URL
    s3_base = s3_endpoint if s3_endpoint.startswith("s3") else f"s3a://{bucket}/"
    if not s3_base.endswith("/"):
        s3_base += "/"

    fmt_map = {
        "parquet": "PARQUET",
        "json": "JSON",
        "csv": "CSV",
    }
    trino_format = fmt_map.get(fmt, "PARQUET")
    col_defs = _trino_column_defs(columns, fmt)

    ddl = (
        f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table_name} (\n"
        f"{col_defs}\n"
        f") WITH (\n"
        f"    format = '{trino_format}',\n"
        f"    external_location = '{s3_base}'\n"
        f")"
    )

    print(f"[table_setup] Registering external table: {catalog}.{namespace}.{table_name}")
    try:
        cur = trino_connection.cursor()
        cur.execute(ddl)
        cur.fetchall()
        print(f"[table_setup] Table '{catalog}.{namespace}.{table_name}' registered.")
    except Exception as exc:
        print(f"[table_setup] Warning: DDL failed (may already exist): {exc}")


class TrinoRestClient:
    """Lightweight Trino client using the REST API (no extra dependencies)."""

    def __init__(self, host: str, port: int = 8080, user: str = "demoforge"):
        self.base_url = f"http://{host}:{port}"
        self.user = user

    def execute(self, sql: str) -> list:
        import requests, time
        resp = requests.post(
            f"{self.base_url}/v1/statement",
            data=sql.encode("utf-8"),
            headers={"X-Trino-User": self.user, "X-Trino-Source": "demoforge-setup"},
        )
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data", [])

        # Follow nextUri until query completes
        while "nextUri" in data:
            time.sleep(0.5)
            resp = requests.get(data["nextUri"], headers={"X-Trino-User": self.user})
            resp.raise_for_status()
            data = resp.json()
            rows.extend(data.get("data", []))

            state = data.get("stats", {}).get("state", "")
            if state == "FAILED":
                error = data.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Trino query failed: {error}")

        return rows

    def cursor(self):
        """Compatibility shim for register_external_table."""
        return self

    def fetchall(self):
        return self._last_result

    def execute_compat(self, sql):
        self._last_result = self.execute(sql)


def run_setup(
    scenario: dict,
    fmt: str,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    trino_host: str = None,
    iceberg_catalog_uri: str = None,
    trino_catalog: str = "iceberg",
    trino_namespace: str = "demo",
) -> None:
    """
    Full one-time setup for a scenario + format combination.
    """
    s3_client = make_s3_client(s3_endpoint, s3_access_key, s3_secret_key)

    # Step 1: create buckets (including warehouse for Iceberg)
    create_buckets(scenario, s3_client)
    ensure_bucket(s3_client, "warehouse")

    # Step 2: create Iceberg table if format=iceberg
    if fmt == "iceberg" and iceberg_catalog_uri:
        try:
            from src.writers.iceberg_writer import IcebergWriter
            writer = IcebergWriter(
                catalog_uri=iceberg_catalog_uri,
                warehouse=scenario.get("iceberg", {}).get("warehouse", "analytics"),
                s3_endpoint=s3_endpoint,
                access_key=s3_access_key,
                secret_key=s3_secret_key,
            )
            create_iceberg_table(scenario, writer)
        except Exception as exc:
            print(f"[table_setup] Iceberg table setup failed: {exc}")

    # Step 3: register Iceberg table in Trino for file-based formats
    # Skip if ICEBERG_CATALOG_URI is set AND not SigV4 — PyIceberg will create the table.
    # For AIStor (SigV4), PyIceberg can't auth, so Trino must create the table.
    catalog_uri = os.environ.get("ICEBERG_CATALOG_URI", "")
    is_sigv4 = os.environ.get("ICEBERG_SIGV4", "").lower() in ("true", "1", "yes")
    if fmt in ("parquet", "json", "csv") and trino_host and (not catalog_uri or is_sigv4):
        try:
            import time as _time
            # Wait for Trino to be ready (it starts slower than MinIO)
            trino = TrinoRestClient(trino_host)
            for attempt in range(12):
                try:
                    import requests as _req
                    r = _req.get(f"http://{trino_host}:8080/v1/info", timeout=3)
                    if r.status_code == 200:
                        info = r.json()
                        if not info.get("starting", True):
                            print(f"[table_setup] Trino is ready (attempt {attempt+1}).")
                            break
                        print(f"[table_setup] Trino is starting up... (attempt {attempt+1}/12)")
                except Exception:
                    pass
                print(f"[table_setup] Waiting for Trino... (attempt {attempt+1}/12)")
                _time.sleep(10)
            else:
                print(f"[table_setup] Trino not available after 120s — skipping DDL.")
                return
            iceberg_cfg = scenario.get("iceberg", {}) or {}
            table_name = iceberg_cfg.get("table", scenario.get("id", "data").replace("-", "_"))
            bucket = scenario.get("buckets", {}).get(fmt)
            # Use the S3_BUCKET override if available
            bucket_override = os.environ.get("S3_BUCKET", "")
            if bucket_override and bucket_override != "raw-data":
                bucket = bucket_override

            if not bucket:
                print(f"[table_setup] No bucket for format '{fmt}' — skipping DDL.")
                return

            # Create schema
            trino.execute(f"CREATE SCHEMA IF NOT EXISTS {trino_catalog}.{trino_namespace}")
            print(f"[table_setup] Schema '{trino_catalog}.{trino_namespace}' ensured.")

            # Create Iceberg table (Trino manages data lifecycle)
            col_defs = _trino_column_defs(scenario.get("columns", []), fmt)
            ddl = (
                f"CREATE TABLE IF NOT EXISTS {trino_catalog}.{trino_namespace}.{table_name} (\n"
                f"{col_defs}\n"
                f") WITH (format = 'PARQUET')"
            )
            trino.execute(ddl)
            print(f"[table_setup] Iceberg table '{trino_catalog}.{trino_namespace}.{table_name}' ready.")
        except Exception as exc:
            print(f"[table_setup] Trino table registration failed: {exc}")
