"""
table_setup.py — One-time setup run before streaming begins.

1. Create MinIO buckets defined in the scenario.
2. Create Iceberg table (if format=iceberg) via IcebergWriter when a catalog URI is passed in.
3. Ensure Iceberg table for parquet/json/csv via PyIceberg when ICEBERG_CATALOG_URI is set (no Trino DDL).
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


def _bucket_from_env_or_scenario(bucket_override: str, scenario_fmt_bucket: str) -> str:
    """First path segment only (supports bucket/prefix in S3_BUCKET)."""
    raw = (bucket_override or "").strip()
    if raw and raw != "raw-data":
        return raw.split("/", 1)[0].strip()
    raw = (scenario_fmt_bucket or "").strip()
    return raw.split("/", 1)[0].strip() if raw else ""


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

    # Step 3: ensure Iceberg table for file-based formats via PyIceberg (same path as generator streaming)
    catalog_uri = (os.environ.get("ICEBERG_CATALOG_URI", "") or "").strip()
    is_sigv4 = os.environ.get("ICEBERG_SIGV4", "").lower() in ("true", "1", "yes")
    if fmt in ("parquet", "json", "csv") and catalog_uri:
        try:
            from src.writers.iceberg_writer import IcebergWriter

            wh = os.environ.get(
                "ICEBERG_WAREHOUSE",
                (scenario.get("iceberg", {}) or {}).get("warehouse", "warehouse"),
            )
            wh_uri = wh if is_sigv4 else (wh if wh.startswith("s3://") else f"s3://{wh}/")
            uri = catalog_uri
            if is_sigv4 and "-lb:80" in uri:
                uri = uri.replace("-lb:80", "-pool1-node-1:9000")
                print(f"[table_setup] AIStor SigV4: catalog URI → {uri}")
            endpoint = s3_endpoint if s3_endpoint.startswith("http") else f"http://{s3_endpoint}"
            writer = IcebergWriter(
                catalog_uri=uri,
                warehouse=wh_uri,
                s3_endpoint=endpoint,
                access_key=s3_access_key,
                secret_key=s3_secret_key,
                sigv4=is_sigv4,
            )
            iceberg_cfg = scenario.get("iceberg", {}) or {}
            table_name = iceberg_cfg.get("table", scenario.get("id", "data").replace("-", "_"))
            bucket = _bucket_from_env_or_scenario(
                os.environ.get("S3_BUCKET", ""),
                scenario.get("buckets", {}).get(fmt, ""),
            )
            if not bucket:
                print(f"[table_setup] No bucket for format '{fmt}' — skipping Iceberg DDL.")
                return
            prefix = ""
            sb = (os.environ.get("S3_BUCKET", "") or "").strip()
            if sb and sb != "raw-data" and "/" in sb:
                prefix = sb.split("/", 1)[1].strip().rstrip("/")
                if prefix:
                    prefix += "/"
            mid = f"{prefix}{table_name}/" if prefix else f"{table_name}/"
            table_location = f"s3://{bucket}/{mid}"
            columns = scenario.get("columns", [])
            writer.ensure_table(trino_namespace, table_name, columns, location=table_location)
            print(
                f"[table_setup] Iceberg table '{trino_namespace}.{table_name}' ready "
                f"(PyIceberg, location={table_location})."
            )
        except Exception as exc:
            print(f"[table_setup] PyIceberg table setup failed: {exc}")
