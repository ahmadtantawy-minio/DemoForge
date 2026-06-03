"""Multi-sink S3 upload helpers (compose sets DG_S3_SINKS or legacy single S3_* env)."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from src.writers.parquet_writer import make_s3_client, resolve_parquet_compression, write_batch


def parse_s3_sinks_from_env() -> list[dict[str, str]]:
    raw = (os.environ.get("DG_S3_SINKS") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [s for s in parsed if isinstance(s, dict) and s.get("endpoint") and s.get("bucket")]
        except json.JSONDecodeError:
            pass
    endpoint = (os.environ.get("S3_ENDPOINT") or "").strip()
    bucket = (os.environ.get("S3_BUCKET") or "").strip()
    if not endpoint or not bucket:
        return []
    return [
        {
            "endpoint": endpoint,
            "bucket": bucket,
            "access_key": os.environ.get("S3_ACCESS_KEY", "minioadmin"),
            "secret_key": os.environ.get("S3_SECRET_KEY", "minioadmin"),
        }
    ]


def write_parquet_batch_to_sinks(
    rows: list,
    columns: list,
    partition_cfg: Any,
    key_prefix: str,
    sinks: list[dict[str, str]] | None = None,
) -> list[str]:
    """Write the same Parquet payload to every configured sink. Returns S3 keys (first sink)."""
    if not rows:
        return []
    sinks = sinks or parse_s3_sinks_from_env()
    if not sinks:
        return []

    compression = resolve_parquet_compression()
    keys: list[str] = []
    for sink in sinks:
        client = make_s3_client(
            sink["endpoint"],
            sink.get("access_key", "minioadmin"),
            sink.get("secret_key", "minioadmin"),
        )
        key = write_batch(
            rows=rows,
            columns=columns,
            partition_cfg=partition_cfg,
            s3_client=client,
            bucket=sink["bucket"],
            key_prefix=key_prefix,
            compression=compression,
        )
        if key:
            keys.append(key)
    return keys
