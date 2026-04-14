"""License proxy — serves and accepts license keys via GCS. The gateway is the GCS write path."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from google.cloud import storage
from google.api_core.exceptions import NotFound

from ..auth import get_current_fa, require_admin
from ..config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _gcs() -> storage.Client:
    from .templates import _gcs as _templates_gcs
    return _templates_gcs()


@router.get("/")
async def list_licenses(_fa: dict = Depends(get_current_fa)):
    def _list():
        bucket = _gcs().bucket(settings.licenses_bucket)
        blobs = list(bucket.list_blobs())
        results = []
        for blob in blobs:
            if not blob.name.endswith(".json"):
                continue
            lid = blob.name.removesuffix(".json")
            results.append({"license_id": lid, "size": blob.size or 0})
        return results

    try:
        licenses = await asyncio.get_event_loop().run_in_executor(None, _list)
        return {"licenses": licenses}
    except Exception as e:
        logger.error(f"License list failed: {e}")
        raise HTTPException(503, f"Failed to list licenses: {e}")


@router.put("/{license_id}.json", dependencies=[Depends(require_admin)])
async def upload_license(license_id: str, request: Request):
    """Upload a license JSON to GCS. Admin-only — licenses are sensitive credentials."""
    if "/" in license_id or not license_id:
        raise HTTPException(400, "Invalid license ID")

    content = await request.body()
    if not content:
        raise HTTPException(400, "Empty request body")

    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(400, "Request body must be valid JSON")

    blob_name = f"{license_id}.json"

    def _upload():
        bucket = _gcs().bucket(settings.licenses_bucket)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(data), content_type="application/json")
        return blob.etag or ""

    try:
        etag = await asyncio.get_event_loop().run_in_executor(None, _upload)
        logger.info("License uploaded: %s", license_id)
        return {"uploaded": license_id, "etag": etag}
    except Exception as e:
        logger.error("License upload failed for %s: %s", license_id, e)
        raise HTTPException(503, f"Failed to upload license: {e}")


@router.get("/{license_id}.json")
async def get_license(license_id: str, _fa: dict = Depends(get_current_fa)):
    if "/" in license_id or not license_id:
        raise HTTPException(400, "Invalid license ID")

    def _fetch():
        bucket = _gcs().bucket(settings.licenses_bucket)
        blob = bucket.blob(f"{license_id}.json")
        try:
            return json.loads(blob.download_as_bytes())
        except NotFound:
            return None

    try:
        data = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        if data is None:
            raise HTTPException(404, f"License '{license_id}' not found")
        return JSONResponse(content=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"License fetch failed for {license_id}: {e}")
        raise HTTPException(503, f"Failed to fetch license: {e}")
