"""
json_writer.py — Write batches as NDJSON files and upload to MinIO/S3.

Flat layout: bucket/<timestamp_ms>.ndjson
Timestamps are formatted as ISO 8601 strings.
"""

import datetime
import json

import boto3


def _serialize_value(val):
    """Convert non-JSON-serializable types."""
    if isinstance(val, datetime.datetime):
        return val.isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    return val


def write_batch(
    rows: list,
    columns: list,
    partition_cfg,  # accepted but ignored — JSON is always flat
    s3_client,
    bucket: str,
    key_prefix: str = "",
) -> str:
    """
    Serialize rows as NDJSON and upload to S3.

    Returns the S3 key of the uploaded file.
    """
    if not rows:
        return ""

    lines = []
    for row in rows:
        rec = {k: _serialize_value(v) for k, v in row.items()}
        lines.append(json.dumps(rec, separators=(",", ":")))

    data = ("\n".join(lines) + "\n").encode("utf-8")

    ts_ms = int(datetime.datetime.utcnow().timestamp() * 1000)
    key = f"{key_prefix}{ts_ms}.ndjson"

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
