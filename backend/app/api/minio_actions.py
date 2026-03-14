"""MinIO bucket/IAM action endpoints for running demos.

Phase 4 features:
  4.3 - Bucket policy presets
  4.5 - Versioning toggle per bucket
  4.6 - IAM setup (pre-create demo users)
"""
import shlex
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..state.store import state
from ..engine.docker_manager import exec_in_container
from .demos import _load_demo

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_POLICIES = {"none", "public", "download", "upload"}


def _cluster_alias(cluster) -> str:
    """Derive the mc alias name for a cluster (matches compose_generator logic)."""
    return cluster.label.replace(" ", "_").replace("-", "_")


def _find_cluster_in_demo(demo, cluster_id: str):
    """Find a DemoCluster by ID."""
    return next((c for c in demo.clusters if c.id == cluster_id), None)


# ---------------------------------------------------------------------------
# 4.3 Bucket Policy Presets
# ---------------------------------------------------------------------------

class BucketPolicyRequest(BaseModel):
    bucket: str
    policy: str  # "none" | "public" | "download" | "upload"


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/policy")
async def set_bucket_policy(demo_id: str, cluster_id: str, req: BucketPolicyRequest):
    """Set anonymous bucket policy via mc anonymous set."""
    if req.policy not in VALID_POLICIES:
        raise HTTPException(400, f"Invalid policy '{req.policy}'. Must be one of: {sorted(VALID_POLICIES)}")

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found — redeploy the demo")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found in demo")

    alias = _cluster_alias(cluster)
    bucket = shlex.quote(req.bucket)
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    cmd = f"mc anonymous set {req.policy} {alias}/{req.bucket}"
    try:
        exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in mc-shell: {e}")

    if exit_code != 0:
        logger.warning(f"set_bucket_policy failed for {demo_id}/{cluster_id}/{req.bucket}: {stderr[:200]}")
        raise HTTPException(500, f"mc command failed: {stderr[:200]}")

    return {"status": "ok", "cluster_id": cluster_id, "bucket": req.bucket, "policy": req.policy}


# ---------------------------------------------------------------------------
# 4.5 Versioning Toggle per Bucket
# ---------------------------------------------------------------------------

class BucketVersioningRequest(BaseModel):
    bucket: str
    enabled: bool


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/versioning")
async def set_bucket_versioning(demo_id: str, cluster_id: str, req: BucketVersioningRequest):
    """Enable or suspend bucket versioning via mc version enable/suspend."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found — redeploy the demo")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found in demo")

    alias = _cluster_alias(cluster)
    action = "enable" if req.enabled else "suspend"
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    cmd = f"mc version {action} {alias}/{req.bucket}"
    try:
        exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in mc-shell: {e}")

    if exit_code != 0:
        logger.warning(f"set_bucket_versioning failed for {demo_id}/{cluster_id}/{req.bucket}: {stderr[:200]}")
        raise HTTPException(500, f"mc command failed: {stderr[:200]}")

    return {"status": "ok", "cluster_id": cluster_id, "bucket": req.bucket, "versioning": req.enabled}


# ---------------------------------------------------------------------------
# 4.6 IAM Setup — Pre-create demo users
# ---------------------------------------------------------------------------

class IAMSetupRequest(BaseModel):
    username: str
    password: str
    policy: str  # e.g. "readonly", "readwrite", "writeonly", "diagnostics"


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/iam")
async def setup_iam_user(demo_id: str, cluster_id: str, req: IAMSetupRequest):
    """Create a MinIO user and attach a policy via mc admin."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found — redeploy the demo")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found in demo")

    alias = _cluster_alias(cluster)
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    username = shlex.quote(req.username)
    password = shlex.quote(req.password)
    policy = shlex.quote(req.policy)

    cmd = (
        f"mc admin user add {alias} {req.username} {req.password} && "
        f"mc admin policy attach {alias} {req.policy} --user {req.username}"
    )
    try:
        exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in mc-shell: {e}")

    if exit_code != 0:
        logger.warning(f"setup_iam_user failed for {demo_id}/{cluster_id}/{req.username}: {stderr[:200]}")
        raise HTTPException(500, f"mc command failed: {stderr[:200]}")

    return {"status": "ok", "cluster_id": cluster_id, "username": req.username, "policy": req.policy}
