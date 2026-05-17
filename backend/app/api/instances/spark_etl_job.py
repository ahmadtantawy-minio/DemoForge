"""Apache Spark job (spark-etl-job): compose-aligned preview and per-run history."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import tempfile
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...engine.compose_generator import generate_compose
from ...state.store import state
from ..demos import _load_demo
from .helpers import _resolve_components_dir
from ...engine.docker_manager import exec_in_container

logger = logging.getLogger(__name__)

router = APIRouter()

SPARK_RUN_LOG_PATH = "/tmp/demoforge-spark-runs.ndjson"
SPARK_SUBMIT_LOG_PATH = "/tmp/demoforge-spark-submit-last.log"

_SPARK_JOB_SCRIPTS: dict[str, str] = {
    "raw_to_iceberg": "csv_glob_to_iceberg.py",
    "raw_to_parquet": "raw_to_parquet.py",
    "iceberg_compaction": "iceberg_catalog_compaction.py",
}

def _mask_env_for_preview(env: dict[str, Any]) -> dict[str, str]:
    """Return string env suitable for UI; redact credentials."""
    out: dict[str, str] = {}
    sensitive_substrings = ("SECRET", "PASSWORD", "TOKEN", "ACCESS_KEY", "PRIVATE")
    for k, v in env.items():
        ks = str(k).upper()
        val = "" if v is None else str(v)
        if any(s in ks for s in sensitive_substrings) or k in ("S3_ACCESS_KEY", "S3_SECRET_KEY"):
            if len(val) <= 4:
                out[k] = "****"
            elif "SECRET" in ks or "PASSWORD" in ks or k == "S3_SECRET_KEY":
                out[k] = "****"
            else:
                out[k] = val[:4] + "…" + " (redacted)"
        else:
            out[k] = val
    return out


def _normalize_compose_environment(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if isinstance(item, str) and "=" in item:
                a, b = item.split("=", 1)
                out[a] = b
        return out
    return {}


def _spark_submit_command(job_mode: str) -> str:
    # Matches components/spark-etl-job/entrypoint.sh — --jars + extraClassPath so Hadoop FileSystem sees S3A on driver + executors.
    script = _SPARK_JOB_SCRIPTS.get(job_mode, _SPARK_JOB_SCRIPTS["raw_to_iceberg"])
    jars_csv = ",".join(
        [
            "/opt/spark/jars/hadoop-aws-3.3.4.jar",
            "/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar",
            "/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar",
            "/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar",
        ]
    )
    driver_cp = ":".join(
        [
            "/opt/spark/jars/hadoop-aws-3.3.4.jar",
            "/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar",
            "/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar",
            "/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar",
        ]
    )
    return (
        "/opt/spark/bin/spark-submit \\\n"
        '  --master "${SPARK_MASTER_URL}" \\\n'
        "  --deploy-mode client \\\n"
        f'  --jars "{jars_csv}" \\\n'
        f'  --driver-class-path "{driver_cp}" \\\n'
        f"  --conf spark.executor.extraClassPath={driver_cp} \\\n"
        f"  /opt/demoforge/jobs/{script}"
    )


class SparkEtlJobPreviewResponse(BaseModel):
    node_id: str
    job_script_path: str = "jobs/csv_glob_to_iceberg.py"
    job_script: str
    spark_submit_command: str
    environment: dict[str, str] = Field(default_factory=dict)
    job_schedule: str = "on_deploy_once"
    job_template: str = "raw_to_iceberg"


class SparkEtlJobRunRecord(BaseModel):
    ts: str = ""
    phase: str = ""
    schedule: str = ""
    exit_code: int | None = None
    # ok | error | submitted | idle | unknown (derived for legacy NDJSON without status)
    status: str = ""
    success: bool | None = Field(
        default=None,
        description="True when spark-submit finished with exit 0.",
    )


class SparkEtlJobRunsResponse(BaseModel):
    runs: list[SparkEtlJobRunRecord]
    log_path: str = SPARK_RUN_LOG_PATH
    submit_log_path: str = SPARK_SUBMIT_LOG_PATH
    submit_log_tail: str = ""
    container_running: bool = False
    message: str = ""
    last_finished_exit_code: int | None = None
    last_finished_success: bool | None = None


def _spark_run_record_from_ndjson(obj: dict[str, Any]) -> SparkEtlJobRunRecord:
    phase = str(obj.get("phase") or "")
    ec_raw = obj.get("exit_code")
    ec: int | None
    if ec_raw is None:
        ec = None
    else:
        try:
            ec = int(ec_raw)
        except (TypeError, ValueError):
            ec = None
    status = str(obj.get("status") or "").strip()
    success: bool | None = obj.get("success")
    if isinstance(success, str):
        success = success.strip().lower() in ("1", "true", "yes")
    elif success is not None:
        success = bool(success)
    if phase == "spark_submit_finished" and ec is not None:
        if not status:
            status = "ok" if ec == 0 else "error"
        if success is None:
            success = ec == 0
    elif phase == "spark_submit_start" and not status:
        # Append-only NDJSON: this row is never updated when submit ends — avoid "running" (misread as stuck).
        status = "submitted"
    elif phase == "manual_idle" and not status:
        status = "idle"
    return SparkEtlJobRunRecord(
        ts=str(obj.get("ts") or ""),
        phase=phase,
        schedule=str(obj.get("schedule") or ""),
        exit_code=ec,
        status=status,
        success=success,
    )


def _last_spark_submit_finished_summary(runs: list[SparkEtlJobRunRecord]) -> tuple[int | None, bool | None]:
    for r in reversed(runs):
        if r.phase == "spark_submit_finished" and r.exit_code is not None:
            return r.exit_code, r.exit_code == 0
    return None, None


@router.get(
    "/api/demos/{demo_id}/instances/{node_id}/spark-etl-job/preview",
    response_model=SparkEtlJobPreviewResponse,
)
async def spark_etl_job_preview(demo_id: str, node_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    node = next((n for n in demo.nodes if n.id == node_id), None)
    if not node or node.component != "spark-etl-job":
        raise HTTPException(404, "Not an Apache Spark job node")

    cfg = node.config or {}
    job_mode = str(cfg.get("JOB_MODE") or cfg.get("JOB_TEMPLATE") or "raw_to_iceberg").strip().lower()
    if job_mode == "csv_glob_to_iceberg":
        job_mode = "raw_to_iceberg"
    script_name = _SPARK_JOB_SCRIPTS.get(job_mode, _SPARK_JOB_SCRIPTS["raw_to_iceberg"])

    components_dir = _resolve_components_dir()
    script_fs = os.path.join(components_dir, "spark-etl-job", "jobs", script_name)
    try:
        with open(script_fs, encoding="utf-8") as f:
            job_script = f.read()
    except OSError as e:
        raise HTTPException(500, f"Could not read job script: {e}") from e

    tmp = tempfile.mkdtemp(prefix="df-spark-preview-")
    try:
        try:
            generate_compose(demo, tmp, components_dir)
        except Exception as e:
            logger.warning("spark-etl-job preview compose failed for %s/%s: %s", demo_id, node_id, e)
            raise HTTPException(400, str(e)) from e

        project_name = f"demoforge-{demo.id}"
        compose_path = os.path.join(tmp, f"{project_name}.yml")
        try:
            with open(compose_path, encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except OSError as e:
            raise HTTPException(500, f"Could not read generated compose: {e}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    services = (doc or {}).get("services") or {}
    svc = services.get(node_id)
    if not svc:
        raise HTTPException(500, f"Service {node_id} missing from generated compose")

    raw_env = svc.get("environment")
    env_flat = _normalize_compose_environment(raw_env)
    masked = _mask_env_for_preview(env_flat)
    job_schedule = str(env_flat.get("JOB_SCHEDULE") or cfg.get("JOB_SCHEDULE") or "on_deploy_once")
    tpl = str(env_flat.get("JOB_MODE") or env_flat.get("JOB_TEMPLATE") or cfg.get("JOB_MODE") or cfg.get("JOB_TEMPLATE") or "raw_to_iceberg")
    if tpl == "csv_glob_to_iceberg":
        tpl = "raw_to_iceberg"

    return SparkEtlJobPreviewResponse(
        node_id=node_id,
        job_script_path=f"jobs/{script_name}",
        job_script=job_script,
        spark_submit_command=_spark_submit_command(job_mode),
        environment=masked,
        job_schedule=job_schedule,
        job_template=tpl,
    )


@router.get(
    "/api/demos/{demo_id}/instances/{node_id}/spark-etl-job/runs",
    response_model=SparkEtlJobRunsResponse,
)
async def spark_etl_job_runs(demo_id: str, node_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    node = next((n for n in demo.nodes if n.id == node_id), None)
    if not node or node.component != "spark-etl-job":
        raise HTTPException(404, "Not an Apache Spark job node")

    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        return SparkEtlJobRunsResponse(
            runs=[],
            container_running=False,
            message="Demo is not running or this node has no container.",
            last_finished_exit_code=None,
            last_finished_success=None,
            submit_log_tail="",
        )

    container_name = running.containers[node_id].container_name
    inner = (
        f"test -f {SPARK_RUN_LOG_PATH} && tail -n 500 {SPARK_RUN_LOG_PATH} || true; "
        f"echo '---DF_SUBMIT_LOG---'; "
        f"test -f {SPARK_SUBMIT_LOG_PATH} && tail -n 200 {SPARK_SUBMIT_LOG_PATH} || true"
    )
    cmd = f"sh -c {shlex.quote(inner)}"
    try:
        exit_code, stdout, stderr = await exec_in_container(container_name, cmd)
    except Exception as e:
        logger.warning("spark-etl-job runs read failed: %s", e)
        return SparkEtlJobRunsResponse(
            runs=[],
            container_running=True,
            message=f"Could not read run log: {e}",
            last_finished_exit_code=None,
            last_finished_success=None,
            submit_log_tail="",
        )

    raw_out = (stdout or "") + (stderr or "")
    submit_log_tail = ""
    if "---DF_SUBMIT_LOG---" in raw_out:
        ndjson_part, submit_part = raw_out.split("---DF_SUBMIT_LOG---", 1)
        text = ndjson_part
        submit_log_tail = submit_part.strip()[:120_000]
    else:
        text = raw_out
    runs: list[SparkEtlJobRunRecord] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                runs.append(_spark_run_record_from_ndjson(obj))
        except json.JSONDecodeError:
            continue

    if exit_code != 0 and not runs and (stderr or "").strip():
        return SparkEtlJobRunsResponse(
            runs=[],
            container_running=True,
            message=(stderr or stdout or "").strip()[:500],
            last_finished_exit_code=None,
            last_finished_success=None,
            submit_log_tail=submit_log_tail,
        )

    window = runs[-200:]
    last_ec, last_ok = _last_spark_submit_finished_summary(window)
    return SparkEtlJobRunsResponse(
        runs=window,
        container_running=True,
        message="",
        last_finished_exit_code=last_ec,
        last_finished_success=last_ok,
        submit_log_tail=submit_log_tail,
    )
