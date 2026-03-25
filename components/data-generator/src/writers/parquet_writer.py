"""
parquet_writer.py — Write batches as Parquet files and upload to MinIO/S3.

Applies scenario partitioning: creates the partition path
e.g. region=US-East/year=2026/month=03/day=24/<timestamp_ms>.parquet
"""

import io
import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import boto3
from botocore.exceptions import ClientError


# PyArrow type mapping from scenario column type strings
_PA_TYPES = {
    "string": pa.string(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "boolean": pa.bool_(),
    "timestamp": pa.timestamp("us"),
    "date": pa.date32(),
}


def _build_pa_schema(columns: list) -> pa.Schema:
    fields = []
    for col in columns:
        pa_type = _PA_TYPES.get(col.get("type", "string"), pa.string())
        fields.append(pa.field(col["name"], pa_type))
    return pa.schema(fields)


def _coerce_row(row: dict, columns: list) -> dict:
    """Coerce row values to match PyArrow expected Python types."""
    out = {}
    for col in columns:
        name = col["name"]
        val = row.get(name)
        col_type = col.get("type", "string")
        if col_type == "timestamp" and isinstance(val, datetime.datetime):
            out[name] = val
        elif col_type in ("int32", "int64") and val is not None:
            out[name] = int(val)
        elif col_type in ("float32", "float64") and val is not None:
            out[name] = float(val)
        elif col_type == "boolean" and val is not None:
            out[name] = bool(val)
        else:
            out[name] = str(val) if val is not None else None
    return out


def _build_partition_path(partition_cfg: dict, sample_row: dict) -> str:
    """
    Build the S3 prefix path for a partitioned Parquet write.

    partition_cfg example:
      {keys: [region], time_column: order_ts, time_granularity: day}
    """
    if not partition_cfg or partition_cfg == "flat":
        return ""

    parts = []

    # Key-based partitioning (e.g. region=US-East)
    for key in partition_cfg.get("keys", []):
        val = sample_row.get(key, "unknown")
        parts.append(f"{key}={val}")

    # Time-based partitioning
    time_col = partition_cfg.get("time_column")
    granularity = partition_cfg.get("time_granularity", "day")
    if time_col and time_col in sample_row:
        ts = sample_row[time_col]
        if isinstance(ts, datetime.datetime):
            parts.append(f"year={ts.year}")
            parts.append(f"month={ts.month:02d}")
            parts.append(f"day={ts.day:02d}")
            if granularity == "hour":
                parts.append(f"hour={ts.hour:02d}")

    return "/".join(parts) + "/" if parts else ""


def write_batch(
    rows: list,
    columns: list,
    partition_cfg,
    s3_client,
    bucket: str,
) -> str:
    """
    Serialize rows to Parquet and upload to S3.

    Returns the S3 key of the uploaded file.
    """
    if not rows:
        return ""

    schema = _build_pa_schema(columns)
    coerced = [_coerce_row(r, columns) for r in rows]

    arrays = {}
    for col in columns:
        name = col["name"]
        pa_type = _PA_TYPES.get(col.get("type", "string"), pa.string())
        arrays[name] = pa.array([r[name] for r in coerced], type=pa_type)

    table = pa.table(arrays, schema=schema)

    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="snappy",
        row_group_size=min(len(rows), 10000),
        write_statistics=True,
    )
    buf.seek(0)
    data = buf.read()

    # Build S3 key
    ts_ms = int(datetime.datetime.utcnow().timestamp() * 1000)
    partition_path = _build_partition_path(partition_cfg, rows[0])
    key = f"{partition_path}{ts_ms}.parquet"

    s3_client.put_object(Bucket=bucket, Key=key, Body=data)
    return key


def make_s3_client(endpoint: str, access_key: str, secret_key: str) -> boto3.client:
    url = endpoint if endpoint.startswith("http") else f"http://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
