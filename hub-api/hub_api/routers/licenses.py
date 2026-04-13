"""License proxy — serves license keys from GCS to authenticated FAs."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from google.cloud import storage
from google.api_core.exceptions import NotFound

from ..auth import get_current_fa
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
