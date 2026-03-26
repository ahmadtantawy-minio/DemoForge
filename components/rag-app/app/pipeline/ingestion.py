import io
import json
import logging
import boto3
from botocore.config import Config as BotoConfig
from ..config import settings

logger = logging.getLogger(__name__)


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def ensure_bucket(client, bucket_name: str):
    try:
        client.head_bucket(Bucket=bucket_name)
    except Exception:
        client.create_bucket(Bucket=bucket_name)


def list_objects(client, bucket: str) -> list[str]:
    keys = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
    except Exception as e:
        logger.warning(f"Failed to list objects in {bucket}: {e}")
    return keys


def download_object(client, bucket: str, key: str) -> bytes:
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def upload_object(client, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"):
    ensure_bucket(client, bucket)
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def extract_text(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(data)
    elif lower.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    elif lower.endswith(".json"):
        return _extract_json(data)
    else:
        return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.warning(f"PDF extraction failed: {e}")
        return ""


def _extract_json(data: bytes) -> str:
    try:
        obj = json.loads(data)
        return _collect_strings(obj)
    except Exception:
        return data.decode("utf-8", errors="replace")


def _collect_strings(obj, parts=None) -> str:
    if parts is None:
        parts = []
    if isinstance(obj, str):
        parts.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, parts)
    elif isinstance(obj, list):
        for item in obj:
            _collect_strings(item, parts)
    return " ".join(parts)
