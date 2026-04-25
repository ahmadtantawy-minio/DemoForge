"""Image management API — status, pull, pre-cache."""
import asyncio
import os
import logging
from uuid import uuid4
from typing import Optional
from fastapi import APIRouter, HTTPException
import urllib.request

from ..registry.loader import get_registry
from ..models.api_models import ImageInfo, PullRequest, PullStatus, PullResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/images", tags=["images"])

# In-memory pull tracking
_pulls: dict[str, PullStatus] = {}

@router.get("/registry-health")
async def registry_health():
    """Check private registry reachability. Returns not_configured when no registry is set."""
    host = os.environ.get("DEMOFORGE_REGISTRY_PUSH_HOST", "").strip()
    if not host:
        return {"status": "not_configured", "host": ""}

    def _ping():
        try:
            req = urllib.request.Request(f"http://{host}/v2/", method="GET")
            resp = urllib.request.urlopen(req, timeout=3)
            return resp.status in (200, 401)  # 401 = auth required but reachable
        except Exception:
            return False

    reachable = await asyncio.to_thread(_ping)
    return {"status": "connected" if reachable else "unreachable", "host": host}


def _categorise(manifest) -> str:
    """Classify image as vendor, custom, or platform."""
    ref = manifest.image or ""
    if manifest.build_context:
        return "custom"
    if "demoforge/" in ref:
        return "platform"
    return "vendor"


def _coerce_built_at(value: object) -> str | None:
    """Docker API may return Created as str; normalize for ImageInfo."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _pull_source(image_ref: str) -> str:
    """Determine registry from image ref."""
    if "/" not in image_ref or image_ref.startswith("library/"):
        return "docker.io"
    parts = image_ref.split("/")
    if "." in parts[0] or ":" in parts[0]:
        return parts[0]
    return "docker.io"


def _check_image_cached(image_ref: str) -> tuple[bool, Optional[float], Optional[str]]:
    """Check if image is cached locally. Returns (cached, size_mb, created_at). BLOCKING — run in thread."""
    try:
        import docker
        client = docker.from_env()
        img = client.images.get(image_ref)
        size_mb = round(img.attrs.get("Size", 0) / 1_000_000, 1)
        created_at = img.attrs.get("Created")
        client.close()
        return True, size_mb, created_at
    except Exception:
        return False, None, None


# Platform images — DemoForge infrastructure, pulled from private registry
# Each entry: (name, registry_ref, [alt_local_tags]) — alt tags for locally-built images
PLATFORM_IMAGES = [
    ("demoforge-backend", "demoforge/demoforge-backend:latest", ["demoforge-backend:latest"]),
    ("demoforge-frontend", "demoforge/demoforge-frontend:latest", ["demoforge-frontend:latest"]),
]


@router.get("/status", response_model=list[ImageInfo])
async def get_image_status():
    """Return status of all component images."""
    try:
        return await _get_image_status_impl()
    except Exception as e:
        logger.exception("get_image_status failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _get_image_status_impl() -> list[ImageInfo]:
    results = []
    # Gather all image checks concurrently via threads
    tasks = []
    manifests_with_images = []

    for name, manifest in get_registry().items():
        if not manifest.image:
            continue
        manifests_with_images.append((name, manifest))
        tasks.append(asyncio.to_thread(_check_image_cached, manifest.image))

    # Collect extra refs alongside primary images
    extra_refs_meta: list[tuple[str, str]] = []  # (component_name, image_ref)
    for name, manifest in manifests_with_images:
        for ref in manifest.image_extra_refs or []:
            extra_refs_meta.append((name, ref))
            tasks.append(asyncio.to_thread(_check_image_cached, ref))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)
    primary_results = all_results[: len(manifests_with_images)]
    extra_results = all_results[len(manifests_with_images) :]

    for (name, manifest), cache_result in zip(manifests_with_images, primary_results):
        if isinstance(cache_result, Exception):
            cached, local_size, built_at = False, None, None
        else:
            cached, local_size, built_at = cache_result

        category = _categorise(manifest)
        manifest_size = manifest.image_size_mb
        effective_size = manifest_size if manifest_size is not None else local_size

        results.append(ImageInfo(
            component_name=name,
            image_ref=manifest.image,
            category=category,
            cached=cached,
            local_size_mb=local_size,
            manifest_size_mb=manifest_size,
            effective_size_mb=effective_size,
            pull_source=_pull_source(manifest.image),
            status="cached" if cached else "missing",
            built_at=_coerce_built_at(built_at),
        ))

    for (name, ref), cache_result in zip(extra_refs_meta, extra_results):
        if isinstance(cache_result, Exception):
            cached, local_size, built_at = False, None, None
        else:
            cached, local_size, built_at = cache_result

        results.append(ImageInfo(
            component_name=name,
            image_ref=ref,
            category="vendor",
            cached=cached,
            local_size_mb=local_size,
            manifest_size_mb=None,
            effective_size_mb=local_size,
            pull_source=_pull_source(ref),
            status="cached" if cached else "missing",
            built_at=_coerce_built_at(built_at),
        ))

    # Add platform images (DemoForge infrastructure)
    # Check registry ref + alternate local tags (locally-built images use shorter names)
    async def _check_platform(pname, pref, alt_tags):
        cached, local_size, built_at = await asyncio.to_thread(_check_image_cached, pref)
        if not cached:
            for alt in alt_tags:
                cached, local_size, built_at = await asyncio.to_thread(_check_image_cached, alt)
                if cached:
                    break
        return cached, local_size, built_at

    platform_tasks = [_check_platform(n, r, a) for n, r, a in PLATFORM_IMAGES]
    platform_results = await asyncio.gather(*platform_tasks, return_exceptions=True)

    for (pname, pref, _alt), presult in zip(PLATFORM_IMAGES, platform_results):
        if isinstance(presult, Exception):
            cached, local_size, built_at = False, None, None
        else:
            cached, local_size, built_at = presult

        if pref.startswith("gcr.io/"):
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
            built_at=_coerce_built_at(built_at),
        ))

    return results


async def _do_pull(pull_id: str, pull_ref: str, manifest_ref: str | None = None):
    """Background task to pull a Docker image. ``manifest_ref`` is tagged after GCR pull when set."""
    display_ref = manifest_ref or pull_ref
    try:
        _pulls[pull_id] = PullStatus(
            pull_id=pull_id, image_ref=display_ref,
            status="pulling", progress_pct=0
        )

        def _pull():
            import docker
            client = docker.from_env()
            try:
                _pull_image_verify(client, pull_ref)
                _maybe_tag_alias(client, pull_ref, manifest_ref)
            finally:
                client.close()

        await asyncio.to_thread(_pull)
        _pulls[pull_id] = PullStatus(
            pull_id=pull_id, image_ref=display_ref,
            status="complete", progress_pct=100
        )
    except Exception as e:
        _pulls[pull_id] = PullStatus(
            pull_id=pull_id, image_ref=display_ref,
            status="error", error=str(e)[:500]
        )


GCR_HOST = os.environ.get("DEMOFORGE_GCR_HOST", "gcr.io/minio-demoforge").strip().rstrip("/")


def _resolve_pull_ref(image_ref: str) -> str:
    """Resolve pull reference — demoforge/ images pull from GCR."""
    if image_ref.startswith("demoforge/"):
        return f"{GCR_HOST}/{image_ref}"
    return image_ref


def _pull_image_verify(client, pull_ref: str) -> None:
    """Pull an image; if the engine reports an error but the ref is already present, succeed.

    Docker Desktop on Windows sometimes surfaces stream/API errors after layers finished;
    deploy and UI pulls should not fail spuriously when ``docker images`` would show the ref.
    """
    try:
        client.images.pull(pull_ref)
    except Exception as e:
        try:
            client.images.get(pull_ref)
        except Exception:
            raise e
        logger.warning(
            "Docker pull reported an error for %s but the image is present locally; treating as success: %s",
            pull_ref,
            e,
        )


def _maybe_tag_alias(client, pull_ref: str, alias_ref: str | None) -> None:
    """After pulling from GCR, tag as manifest ref (e.g. demoforge/...) so /status shows cached."""
    if not alias_ref or alias_ref == pull_ref:
        return
    try:
        img = client.images.get(pull_ref)
        if ":" in alias_ref:
            repo, _, tag = alias_ref.rpartition(":")
            tag = tag or "latest"
        else:
            repo, tag = alias_ref, "latest"
        img.tag(repo, tag=tag)
    except Exception as e:
        logger.debug("Optional tag %s <- %s: %s", alias_ref, pull_ref, e)


@router.post("/pull", response_model=PullResponse)
async def pull_image(req: PullRequest):
    """Start pulling a Docker image in the background."""
    pull_id = str(uuid4())[:8]
    actual_ref = _resolve_pull_ref(req.image_ref)
    alias = req.image_ref if actual_ref != req.image_ref else None
    asyncio.create_task(_do_pull(pull_id, actual_ref, alias))
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
        alias = img.image_ref if actual_ref != img.image_ref else None
        asyncio.create_task(_do_pull(pull_id, actual_ref, alias))
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


@router.post("/hub-push")
async def hub_push_images():
    """Build and push all custom component images to the hub registry. Dev mode only."""
    if os.environ.get("DEMOFORGE_MODE") != "dev":
        raise HTTPException(403, "Hub image push is only available in dev mode.")

    registry = os.environ.get("DEMOFORGE_REGISTRY_PUSH_HOST", "")
    if not registry:
        raise HTTPException(400, "DEMOFORGE_REGISTRY_PUSH_HOST is not configured.")

    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "/app/components")
    host_components_dir = os.environ.get("DEMOFORGE_HOST_COMPONENTS_DIR", "")

    import glob as _glob
    dockerfiles = sorted(_glob.glob(f"{components_dir}/*/Dockerfile"))

    async def _build_and_push(component: str, build_ctx: str) -> dict:
        tag = f"{registry}/demoforge-{component}:latest"
        build = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", tag, build_ctx,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, build_err = await build.communicate()
        if build.returncode != 0:
            return {"component": component, "tag": tag, "status": "build_failed",
                    "error": build_err.decode()[-500:]}

        push = await asyncio.create_subprocess_exec(
            "docker", "push", tag,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, push_err = await push.communicate()
        if push.returncode != 0:
            return {"component": component, "tag": tag, "status": "push_failed",
                    "error": push_err.decode()[-500:]}

        return {"component": component, "tag": tag, "status": "ok"}

    tasks = []
    for df in dockerfiles:
        component = os.path.basename(os.path.dirname(df))
        # Always use container-local path: the Docker CLI runs inside the container
        # and reads the build context from its own filesystem (mounted at /app/components).
        # host_components_dir is irrelevant here — the CLI streams the context to the daemon.
        build_ctx = os.path.dirname(df)
        tasks.append(_build_and_push(component, build_ctx))

    results = await asyncio.gather(*tasks)
    pushed = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] != "ok")
    return {"pushed": pushed, "failed": failed, "results": list(results)}
