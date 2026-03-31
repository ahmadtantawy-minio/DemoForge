"""Image management API — status, pull, pre-cache."""
import asyncio
import os
import logging
from uuid import uuid4
from typing import Optional
from fastapi import APIRouter, HTTPException
import urllib.request
import urllib.error

from ..registry.loader import get_registry
from ..models.api_models import ImageInfo, PullRequest, PullStatus, PullResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/images", tags=["images"])

# In-memory pull tracking
_pulls: dict[str, PullStatus] = {}

REGISTRY_HOST = os.environ.get("DEMOFORGE_REGISTRY_HOST", "")
# Docker pulls go through the host daemon (via socket), so use localhost
# even though the backend container reaches the registry at host.docker.internal
REGISTRY_PULL_HOST = os.environ.get("DEMOFORGE_REGISTRY_PULL_HOST", "localhost:5000")


@router.get("/registry-health")
async def registry_health():
    """Check if the private registry is reachable (from backend container)."""
    if not REGISTRY_HOST:
        return {"status": "not_configured", "host": ""}
    try:
        url = f"http://{REGISTRY_HOST}/v2/"
        req = urllib.request.Request(url, method="GET")
        try:
            resp = await asyncio.to_thread(
                lambda: urllib.request.urlopen(req, timeout=3)
            )
            code = resp.status
        except urllib.error.HTTPError as he:
            # 401/403 means registry is reachable but needs auth — that's fine
            code = he.code
        if code in (200, 401, 403):
            return {"status": "connected", "host": REGISTRY_HOST, "code": code}
        return {"status": "unreachable", "host": REGISTRY_HOST, "code": code}
    except Exception as e:
        return {"status": "unreachable", "host": REGISTRY_HOST, "error": str(e)}


def _categorise(manifest) -> str:
    """Classify image as vendor, custom, or platform."""
    ref = manifest.image or ""
    if manifest.build_context:
        return "custom"
    if "demoforge/" in ref:
        return "platform"
    return "vendor"


def _pull_source(image_ref: str) -> str:
    """Determine registry from image ref."""
    if "/" not in image_ref or image_ref.startswith("library/"):
        return "docker.io"
    parts = image_ref.split("/")
    if "." in parts[0] or ":" in parts[0]:
        return parts[0]
    return "docker.io"


def _check_image_cached(image_ref: str) -> tuple[bool, Optional[float]]:
    """Check if image is cached locally. Returns (cached, size_mb). BLOCKING — run in thread."""
    try:
        import docker
        client = docker.from_env()
        img = client.images.get(image_ref)
        size_mb = round(img.attrs.get("Size", 0) / 1_000_000, 1)
        client.close()
        return True, size_mb
    except Exception:
        return False, None


# Platform images — DemoForge infrastructure, pulled from private registry
# Each entry: (name, registry_ref, [alt_local_tags]) — alt tags for locally-built images
PLATFORM_IMAGES = [
    ("demoforge-backend", "demoforge/demoforge-backend:latest", ["demoforge-backend:latest"]),
    ("demoforge-frontend", "demoforge/demoforge-frontend:latest", ["demoforge-frontend:latest"]),
    ("hub-connector", "gcr.io/minio-demoforge/demoforge-hub-connector:latest", []),
]


@router.get("/status", response_model=list[ImageInfo])
async def get_image_status():
    """Return status of all component images."""
    results = []
    # Gather all image checks concurrently via threads
    tasks = []
    manifests_with_images = []

    for name, manifest in get_registry().items():
        if not manifest.image:
            continue
        manifests_with_images.append((name, manifest))
        tasks.append(asyncio.to_thread(_check_image_cached, manifest.image))

    cache_results = await asyncio.gather(*tasks, return_exceptions=True)

    for (name, manifest), cache_result in zip(manifests_with_images, cache_results):
        if isinstance(cache_result, Exception):
            cached, local_size = False, None
        else:
            cached, local_size = cache_result

        category = _categorise(manifest)
        manifest_size = manifest.image_size_mb
        effective_size = manifest_size if manifest_size is not None else local_size

        if cached:
            status = "cached"
        else:
            status = "missing"

        # Custom images come from the private registry
        if category in ("custom", "platform") and REGISTRY_HOST:
            pull_source = f"Private Registry ({REGISTRY_HOST})"
        else:
            pull_source = _pull_source(manifest.image)

        results.append(ImageInfo(
            component_name=name,
            image_ref=manifest.image,
            category=category,
            cached=cached,
            local_size_mb=local_size,
            manifest_size_mb=manifest_size,
            effective_size_mb=effective_size,
            pull_source=pull_source,
            status=status,
        ))

    # Add platform images (DemoForge infrastructure)
    # Check registry ref + alternate local tags (locally-built images use shorter names)
    async def _check_platform(pname, pref, alt_tags):
        cached, local_size = await asyncio.to_thread(_check_image_cached, pref)
        if not cached:
            for alt in alt_tags:
                cached, local_size = await asyncio.to_thread(_check_image_cached, alt)
                if cached:
                    break
        return cached, local_size

    platform_tasks = [_check_platform(n, r, a) for n, r, a in PLATFORM_IMAGES]
    platform_results = await asyncio.gather(*platform_tasks, return_exceptions=True)

    for (pname, pref, _alt), presult in zip(PLATFORM_IMAGES, platform_results):
        if isinstance(presult, Exception):
            cached, local_size = False, None
        else:
            cached, local_size = presult

        if pref.startswith("demoforge/") and REGISTRY_HOST:
            psource = f"Private Registry ({REGISTRY_HOST})"
        elif pref.startswith("gcr.io/"):
            psource = "gcr.io"
        else:
            psource = _pull_source(pref)

        results.append(ImageInfo(
            component_name=pname,
            image_ref=pref,
            category="platform",
            cached=cached,
            local_size_mb=local_size,
            manifest_size_mb=None,
            effective_size_mb=local_size,
            pull_source=psource,
            status="cached" if cached else "missing",
        ))

    return results


async def _do_pull(pull_id: str, image_ref: str):
    """Background task to pull a Docker image."""
    try:
        _pulls[pull_id] = PullStatus(
            pull_id=pull_id, image_ref=image_ref,
            status="pulling", progress_pct=0
        )

        def _pull():
            import docker
            client = docker.from_env()
            client.images.pull(image_ref)
            client.close()

        await asyncio.to_thread(_pull)
        _pulls[pull_id] = PullStatus(
            pull_id=pull_id, image_ref=image_ref,
            status="complete", progress_pct=100
        )
    except Exception as e:
        _pulls[pull_id] = PullStatus(
            pull_id=pull_id, image_ref=image_ref,
            status="error", error=str(e)[:500]
        )


def _resolve_pull_ref(image_ref: str) -> str:
    """Resolve the actual pull reference — custom images pull from private registry.
    Uses REGISTRY_PULL_HOST (localhost:5000) since Docker pulls go through the host daemon."""
    if not REGISTRY_PULL_HOST:
        return image_ref
    # Check if this is a custom/platform image (demoforge/ prefix)
    if image_ref.startswith("demoforge/"):
        return f"{REGISTRY_PULL_HOST}/{image_ref}"
    return image_ref


@router.post("/pull", response_model=PullResponse)
async def pull_image(req: PullRequest):
    """Start pulling a Docker image in the background."""
    pull_id = str(uuid4())[:8]
    actual_ref = _resolve_pull_ref(req.image_ref)
    asyncio.create_task(_do_pull(pull_id, actual_ref))
    return PullResponse(pull_id=pull_id)


@router.get("/pull/{pull_id}", response_model=PullStatus)
async def get_pull_status(pull_id: str):
    """Check status of an in-progress pull."""
    if pull_id not in _pulls:
        raise HTTPException(status_code=404, detail="Pull ID not found")
    return _pulls[pull_id]


@router.post("/pull-all-missing")
async def pull_all_missing():
    """Pull all missing images."""
    status = await get_image_status()
    missing = [img for img in status if img.status == "missing"]
    pull_ids = []
    for img in missing:
        pull_id = str(uuid4())[:8]
        actual_ref = _resolve_pull_ref(img.image_ref)
        asyncio.create_task(_do_pull(pull_id, actual_ref))
        pull_ids.append(pull_id)
    return {"pull_ids": pull_ids}


@router.get("/dangling")
async def get_dangling_images():
    def _check():
        import docker
        client = docker.from_env()
        dangling = client.images.list(filters={"dangling": True})
        total_bytes = sum(img.attrs.get("Size", 0) for img in dangling)
        client.close()
        return {"count": len(dangling), "reclaimable_mb": round(total_bytes / 1_000_000, 1)}
    return await asyncio.to_thread(_check)


@router.post("/prune")
async def prune_dangling_images():
    def _prune():
        import docker
        client = docker.from_env()
        result = client.images.prune(filters={"dangling": True})
        reclaimed = result.get("SpaceReclaimed", 0)
        deleted = len(result.get("ImagesDeleted", []) or [])
        client.close()
        return {"removed": deleted, "reclaimed_mb": round(reclaimed / 1_000_000, 1)}
    return await asyncio.to_thread(_prune)
