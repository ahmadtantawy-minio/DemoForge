"""Template proxy — serves templates from hub MinIO to authenticated FAs."""
import io
import functools
import asyncio
import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..auth import get_current_fa
from ..config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=settings.sync_endpoint,
        aws_access_key_id="demoforge-sync",
        aws_secret_access_key=settings.sync_secret_key,
        region_name="us-east-1",
        config=BotoConfig(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=15,
            retries={"max_attempts": 1},
        ),
    )


def _available():
    return bool(settings.sync_secret_key and settings.sync_endpoint)


@router.get("/")
async def list_templates(_fa: dict = Depends(get_current_fa)):
    if not _available():
        raise HTTPException(503, "Template sync not configured on hub")

    def _list():
        client = _s3()
        resp = client.list_objects_v2(
            Bucket=settings.sync_bucket,
            Prefix=settings.sync_prefix,
            MaxKeys=500,
        )
        results = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            fname = key.removeprefix(settings.sync_prefix).lstrip("/")
            if not fname.endswith(".yaml") or "/" in fname or not fname:
                continue
            results.append({
                "name": fname,
                "etag": obj.get("ETag", "").strip('"'),
                "size": obj.get("Size", 0),
                "last_modified": obj["LastModified"].isoformat(),
            })
        return results

    try:
        templates = await asyncio.get_event_loop().run_in_executor(None, _list)
        return {"templates": templates}
    except Exception as e:
        logger.error(f"Template list failed: {e}")
        raise HTTPException(503, f"Failed to list templates: {e}")


@router.get("/{filename}")
async def get_template(filename: str, _fa: dict = Depends(get_current_fa)):
    if not _available():
        raise HTTPException(503, "Template sync not configured on hub")
    if "/" in filename or not filename.endswith(".yaml"):
        raise HTTPException(400, "Invalid template filename")

    key = f"{settings.sync_prefix}{filename}"

    def _fetch():
        client = _s3()
        try:
            obj = client.get_object(Bucket=settings.sync_bucket, Key=key)
            return obj["Body"].read(), obj.get("ETag", "").strip('"')
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None, None
            raise

    try:
        content, etag = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        if content is None:
            raise HTTPException(404, f"Template '{filename}' not found")
        headers = {}
        if etag:
            headers["ETag"] = etag
        return Response(content=content, media_type="application/x-yaml", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Template fetch failed for {filename}: {e}")
        raise HTTPException(503, f"Failed to fetch template: {e}")
