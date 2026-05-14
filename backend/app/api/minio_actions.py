"""MinIO bucket/IAM action endpoints for running demos.

Phase 4 features:
  4.3 - Bucket policy presets
  4.5 - Versioning toggle per bucket
  4.6 - IAM setup (pre-create demo users)
  4.7 - SSE-S3 encryption toggle per bucket
"""

from __future__ import annotations

import re
import shlex
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..state.store import state
from ..engine.docker_manager import exec_in_container
from ..engine.integration_audit_log import append_integration_audit_line
from .demos import _load_demo

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_POLICIES = {"none", "public", "download", "upload"}


def _cluster_alias(cluster) -> str:
    """Derive the mc alias name for a cluster (matches compose_generator init.sh logic)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)


def _find_cluster_in_demo(demo, cluster_id: str):
    """Find a DemoCluster by ID."""
    return next((c for c in demo.clusters if c.id == cluster_id), None)


def _audit_bucket_mc(
    demo_id: str,
    kind: str,
    message: str,
    cmd: str,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> None:
    tail = "\n".join(x for x in [stdout or "", stderr or ""] if x).strip()
    append_integration_audit_line(
        demo_id,
        "error" if exit_code != 0 else "info",
        kind,
        message,
        tail[:12000],
        node_id="mc-shell",
        command=cmd,
        exit_code=exit_code,
    )


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

    _audit_bucket_mc(
        demo_id,
        "bucket_policy",
        f"{cluster_id} bucket {req.bucket}: anonymous {req.policy}",
        cmd,
        exit_code,
        stdout,
        stderr,
    )

    if exit_code != 0:
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

    _audit_bucket_mc(
        demo_id,
        "bucket_versioning",
        f"{cluster_id} bucket {req.bucket}: version {action}",
        cmd,
        exit_code,
        stdout,
        stderr,
    )

    if exit_code != 0:
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

    _audit_bucket_mc(
        demo_id,
        "iam_user",
        f"{cluster_id}: user {req.username} policy {req.policy}",
        cmd,
        exit_code,
        stdout,
        stderr,
    )

    if exit_code != 0:
        raise HTTPException(500, f"mc command failed: {stderr[:200]}")

    return {"status": "ok", "cluster_id": cluster_id, "username": req.username, "policy": req.policy}


# ---------------------------------------------------------------------------
# 4.7 SSE-S3 Encryption Toggle per Bucket
# ---------------------------------------------------------------------------

class BucketEncryptionRequest(BaseModel):
    bucket: str
    enabled: bool


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/encryption")
async def set_bucket_encryption(demo_id: str, cluster_id: str, req: BucketEncryptionRequest):
    """Enable or clear SSE-S3 auto-encryption on a bucket via mc encrypt set/clear."""
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

    action = "set sse-s3" if req.enabled else "clear"
    cmd = f"mc encrypt {action} {alias}/{req.bucket}"
    try:
        exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in mc-shell: {e}")

    _audit_bucket_mc(
        demo_id,
        "bucket_encryption",
        f"{cluster_id} bucket {req.bucket}: encrypt {action}",
        cmd,
        exit_code,
        stdout,
        stderr,
    )

    if exit_code != 0:
        raise HTTPException(500, f"mc command failed: {stderr[:200]}")

    return {"status": "ok", "cluster_id": cluster_id, "bucket": req.bucket, "encryption": "sse-s3" if req.enabled else "none"}


@router.get("/api/demos/{demo_id}/minio/{cluster_id}/encryption")
async def get_bucket_encryption(demo_id: str, cluster_id: str, bucket: str):
    """Get SSE-S3 encryption status for a bucket via mc encrypt info."""
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

    cmd = f"mc encrypt info {alias}/{bucket}"
    try:
        exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in mc-shell: {e}")

    _audit_bucket_mc(
        demo_id,
        "bucket_encryption_info",
        f"{cluster_id} bucket {bucket}: mc encrypt info",
        cmd,
        exit_code,
        stdout,
        stderr,
    )

    encryption = "none"
    if exit_code == 0 and "sse-s3" in stdout.lower():
        encryption = "sse-s3"

    return {"cluster_id": cluster_id, "bucket": bucket, "encryption": encryption, "raw": stdout}


# ---------------------------------------------------------------------------
# Generic mc command runner + info queries
# ---------------------------------------------------------------------------

class McCommandRequest(BaseModel):
    command: str  # mc subcommand after the alias, e.g. "ls", "admin info", "version info"


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/mc")
async def run_mc_command(demo_id: str, cluster_id: str, req: McCommandRequest):
    """Run an mc command against a cluster and return the output."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")
    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found")

    alias = _cluster_alias(cluster)
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    # Prepend alias to command if it doesn't already contain it
    cmd = req.command.strip()
    if cmd.startswith("mc "):
        cmd = cmd[3:]  # strip "mc " prefix if user included it

    # Build the full mc command with the alias
    full_cmd = f"mc {cmd}"
    # Replace placeholder ALIAS with actual alias
    if "ALIAS" in full_cmd:
        full_cmd = full_cmd.replace("ALIAS", alias)
    elif not any(full_cmd.startswith(f"mc {sub}") for sub in ["alias", "update", "--version"]):
        # Auto-inject alias for commands that need a target
        parts = cmd.split(None, 1)
        if parts:
            subcmd = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            # Commands that take ALIAS as first arg after subcommand
            if subcmd in ("ls", "du", "stat", "cat", "head", "cp", "mv", "rm", "rb", "mb",
                          "version", "anonymous", "replicate"):
                if rest and not rest.startswith(alias):
                    full_cmd = f"mc {subcmd} {alias}/{rest}"
                elif not rest:
                    full_cmd = f"mc {subcmd} {alias}"
            elif subcmd == "admin":
                admin_parts = rest.split(None, 1)
                if admin_parts:
                    admin_sub = admin_parts[0]
                    admin_rest = admin_parts[1] if len(admin_parts) > 1 else ""
                    if admin_rest and not admin_rest.startswith(alias):
                        full_cmd = f"mc admin {admin_sub} {alias} {admin_rest}"
                    elif not admin_rest:
                        full_cmd = f"mc admin {admin_sub} {alias}"

    try:
        exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(full_cmd)}")
    except Exception as e:
        raise HTTPException(500, f"Failed to exec: {e}")

    _audit_bucket_mc(
        demo_id,
        "mc_api",
        f"cluster {cluster_id}: manual mc",
        full_cmd,
        exit_code,
        stdout,
        stderr,
    )

    return {
        "command": full_cmd,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }


@router.get("/api/demos/{demo_id}/minio/{cluster_id}/info")
async def get_cluster_info(demo_id: str, cluster_id: str):
    """Get comprehensive MinIO cluster info: buckets, policies, versioning, users."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")
    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found")

    alias = _cluster_alias(cluster)
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    async def _run(cmd: str) -> tuple[int, str]:
        try:
            ec, out, _ = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
            return ec, out
        except Exception:
            return 1, ""

    import asyncio

    # Run all info queries in parallel
    results = await asyncio.gather(
        _run(f"mc ls {alias}"),                           # bucket list
        _run(f"mc admin info {alias}"),                   # server info
        _run(f"mc admin user ls {alias}"),                # IAM users
        _run(f"mc admin replicate info {alias}"),         # site-replication status
    )

    # Parse bucket list for per-bucket info
    buckets = []
    if results[0][0] == 0:
        for line in results[0][1].strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                bname = parts[-1].rstrip("/")
                if bname:
                    # Get per-bucket policy and versioning
                    pol_ec, pol_out = await _run(f"mc anonymous get-json {alias}/{bname}")
                    ver_ec, ver_out = await _run(f"mc version info {alias}/{bname}")
                    enc_ec, enc_out = await _run(f"mc encrypt info {alias}/{bname}")
                    policy = "none"
                    if pol_ec == 0 and pol_out.strip():
                        policy = "custom" if pol_out.strip() != "{}" else "none"
                    versioning = "unknown"
                    if ver_ec == 0:
                        if "enabled" in ver_out.lower():
                            versioning = "enabled"
                        elif "suspended" in ver_out.lower():
                            versioning = "suspended"
                        else:
                            versioning = "unversioned"
                    encryption = "none"
                    if enc_ec == 0 and "sse-s3" in enc_out.lower():
                        encryption = "sse-s3"
                    buckets.append({"name": bname, "policy": policy, "versioning": versioning, "encryption": encryption})

    return {
        "cluster_id": cluster_id,
        "alias": alias,
        "server_info": results[1][1] if results[1][0] == 0 else "unavailable",
        "buckets": buckets,
        "users": results[2][1] if results[2][0] == 0 else "unavailable",
        "site_replication": results[3][1] if results[3][0] == 0 else "not configured",
    }
