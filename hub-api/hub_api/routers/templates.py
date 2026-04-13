"""Template proxy — serves templates from GCS to authenticated FAs."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from google.cloud import storage
from google.api_core.exceptions import NotFound

from ..auth import get_current_fa
from ..config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_gcs_client: storage.Client | None = None


def _gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


@router.get("/")
async def list_templates(_fa: dict = Depends(get_current_fa)):
    def _list():
        bucket = _gcs().bucket(settings.templates_bucket)
        blobs = bucket.list_blobs(prefix=settings.templates_prefix)
        results = []
        for blob in blobs:
            fname = blob.name.removeprefix(settings.templates_prefix).lstrip("/")
            if not fname.endswith(".yaml") or "/" in fname or not fname:
                continue
            results.append({
                "name": fname,
                "etag": blob.etag or "",
                "size": blob.size or 0,
                "last_modified": blob.updated.isoformat() if blob.updated else "",
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
    if "/" in filename or not filename.endswith(".yaml"):
        raise HTTPException(400, "Invalid template filename")

    blob_name = f"{settings.templates_prefix}{filename}"

    def _fetch():
        bucket = _gcs().bucket(settings.templates_bucket)
        blob = bucket.blob(blob_name)
        try:
            content = blob.download_as_bytes()
            return content, blob.etag or ""
        except NotFound:
            return None, None

    try:
        content, etag = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        if content is None:
            raise HTTPException(404, f"Template '{filename}' not found")
        headers = {"ETag": etag} if etag else {}
        return Response(content=content, media_type="application/x-yaml", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Template fetch failed for {filename}: {e}")
        raise HTTPException(503, f"Failed to fetch template: {e}")
