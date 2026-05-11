"""
csv_writer.py — Write batches as CSV files and upload to MinIO/S3.

Flat layout: bucket/<timestamp_ms>.csv
Header row included. Timestamps formatted as ISO 8601 strings.
"""

import csv
import datetime
import io

import boto3


def _serialize_value(val):
    """Convert non-string-serializable types for CSV."""
    if isinstance(val, datetime.datetime):
        return val.isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    if isinstance(val, bool):
        return str(val).lower()
    return val


def write_batch(
    rows: list,
    columns: list,
    partition_cfg,  # accepted but ignored — CSV is always flat
    s3_client,
    bucket: str,
    key_prefix: str = "",
) -> str:
    """
    Serialize rows as CSV (with header) and upload to S3.

    Returns the S3 key of the uploaded file.
    """
    if not rows:
        return ""

    fieldnames = [col["name"] for col in columns]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()

    for row in rows:
        rec = {k: _serialize_value(v) for k, v in row.items()}
        # Ensure only declared columns are included
        filtered = {f: rec.get(f, "") for f in fieldnames}
        writer.writerow(filtered)

    data = buf.getvalue().encode("utf-8")

    ts_ms = int(datetime.datetime.utcnow().timestamp() * 1000)
    key = f"{key_prefix}{ts_ms}.csv"

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
