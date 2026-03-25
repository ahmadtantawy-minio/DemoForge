"""
trino_writer.py — Writes data by INSERTing into an Iceberg table via Trino REST API.

This ensures data is properly managed by Iceberg metadata and immediately
queryable, unlike raw Parquet files on S3 which Iceberg doesn't know about.
"""
import os
import time
import datetime
import requests


TRINO_HOST = os.environ.get("TRINO_HOST", "")
TRINO_CATALOG = "iceberg"
TRINO_NAMESPACE = "demo"


class TrinoInsertWriter:
    def __init__(self, trino_host: str, catalog: str = "iceberg", namespace: str = "demo"):
        self.base_url = f"http://{trino_host}:8080"
        self.catalog = catalog
        self.namespace = namespace
        self.user = "demoforge-generator"

    def _execute(self, sql: str) -> None:
        resp = requests.post(
            f"{self.base_url}/v1/statement",
            data=sql.encode("utf-8"),
            headers={"X-Trino-User": self.user, "X-Trino-Source": "demoforge-gen"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        while "nextUri" in data:
            time.sleep(0.3)
            resp = requests.get(data["nextUri"], headers={"X-Trino-User": self.user}, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            state = data.get("stats", {}).get("state", "")
            if state == "FAILED":
                error = data.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Trino INSERT failed: {error}")


def _sql_value(val, col_type: str) -> str:
    """Convert a Python value to a Trino SQL literal."""
    if val is None:
        return "NULL"
    if col_type in ("string",):
        s = str(val).replace("'", "''")
        return f"'{s}'"
    if col_type == "timestamp":
        if isinstance(val, datetime.datetime):
            return f"TIMESTAMP '{val.strftime('%Y-%m-%d %H:%M:%S')}'"
        return f"TIMESTAMP '{val}'"
    if col_type == "date":
        if isinstance(val, (datetime.date, datetime.datetime)):
            return f"DATE '{val.strftime('%Y-%m-%d')}'"
        return f"DATE '{val}'"
    if col_type == "boolean":
        return "true" if val else "false"
    return str(val)


_writer_instance = None


def write_batch(
    rows: list,
    columns: list,
    partition_cfg,
    s3_client,
    bucket: str,
) -> str:
    """Write a batch of rows by INSERTing into the Iceberg table via Trino."""
    global _writer_instance

    if not TRINO_HOST:
        raise RuntimeError("TRINO_HOST not set — cannot use Trino writer")

    if _writer_instance is None:
        _writer_instance = TrinoInsertWriter(TRINO_HOST)

    table = f"{_writer_instance.catalog}.{_writer_instance.namespace}.orders"

    # Build VALUES clause in chunks to avoid huge SQL strings
    chunk_size = 50
    total_inserted = 0

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        values_parts = []
        for row in chunk:
            vals = []
            for col in columns:
                col_name = col["name"]
                col_type = col.get("type", "string")
                vals.append(_sql_value(row.get(col_name), col_type))
            values_parts.append(f"({', '.join(vals)})")

        col_names = ", ".join(col["name"] for col in columns)
        sql = f"INSERT INTO {table} ({col_names}) VALUES {', '.join(values_parts)}"

        _writer_instance._execute(sql)
        total_inserted += len(chunk)

    ts = int(time.time() * 1000)
    return f"trino-insert/{ts}-{total_inserted}rows"
