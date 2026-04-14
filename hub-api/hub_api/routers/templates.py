"""Template proxy — serves and accepts templates via GCS. The gateway is the GCS write path."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
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


def _update_seed_manifest(bucket: storage.Bucket, filename: str, updated_at: str) -> None:
    """Merge one entry into .seed-manifest.json. Best-effort."""
    manifest_blob = bucket.blob(f"{settings.templates_prefix}.seed-manifest.json")
    try:
        manifest = json.loads(manifest_blob.download_as_text())
    except Exception:
        manifest = {}
    manifest[filename] = {"updated_at": updated_at}
    manifest_blob.upload_from_string(
        json.dumps(manifest, indent=2, sort_keys=True),
        content_type="application/json",
    )


@router.put("/{filename}")
async def upload_template(filename: str, request: Request):
    """Upload a template YAML to GCS. Accepts admin key or FA with template_publish permission."""
    if "/" in filename or not filename.endswith(".yaml"):
        raise HTTPException(400, "Invalid template filename")

    # Auth: admin key takes precedence; fallback to FA with template_publish permission
    admin_key = request.headers.get("X-Hub-Admin-Key")
    publisher_id: str
    if admin_key:
        if admin_key != settings.admin_api_key:
            raise HTTPException(403, "Invalid admin key")
        publisher_id = "admin"
    else:
        from ..database import get_db
        db_gen = get_db()
        db = await db_gen.__anext__()
        try:
            fa = await get_current_fa(request, db)
        finally:
            try:
                await db_gen.aclose()
            except Exception:
                pass
        if not fa["permissions"].get("template_publish"):
            raise HTTPException(403, "template_publish permission required")
        publisher_id = fa["fa_id"]

    content = await request.body()
    if not content:
        raise HTTPException(400, "Empty request body")

    # Parse updated_at from YAML for manifest (best-effort)
    updated_at = ""
    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(content) or {}
        updated_at = data.get("_template", {}).get("updated_at", "") or ""
    except Exception:
        pass

    blob_name = f"{settings.templates_prefix}{filename}"

    def _upload():
        bucket = _gcs().bucket(settings.templates_bucket)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(content, content_type="application/x-yaml")
        try:
            _update_seed_manifest(bucket, filename, updated_at)
        except Exception as e:
            logger.warning("Manifest update failed for %s: %s", filename, e)
        return blob.etag or ""

    try:
        etag = await asyncio.get_event_loop().run_in_executor(None, _upload)
        logger.info("Template uploaded: %s by %s", filename, publisher_id)
        return {"uploaded": filename, "etag": etag}
    except Exception as e:
        logger.error("Template upload failed for %s: %s", filename, e)
        raise HTTPException(503, f"Failed to upload template: {e}")


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
