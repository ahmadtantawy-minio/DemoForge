"""Read IAM simulation reconcile stats from mc-shell container logs (``DEMOFORGE_IAM_REPORT`` line)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time as time_mod
from typing import Any

import docker
from docker.errors import NotFound
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["iam"])


class IamReconcileReport(BaseModel):
    enabled: bool = True
    policies_expected: int = 0
    policies_provisioned: int = 0
    policies_failed: int = 0
    policies_unprovisioned: int = 0
    users_expected: int = 0
    users_provisioned: int = 0
    users_failed: int = 0
    users_unprovisioned: int = 0
    attaches_expected: int = 0
    attaches_provisioned: int = 0
    attaches_failed: int = 0
    attaches_unprovisioned: int = 0
    errors: list[str] = Field(default_factory=list)


def _parse_kv_report_line(line: str) -> dict[str, str] | None:
    s = line.strip()
    prefix = "DEMOFORGE_IAM_REPORT "
    idx = s.find(prefix)
    if idx < 0:
        return None
    rest = s[idx + len(prefix) :].strip()
    kv: dict[str, str] = {}
    for part in rest.split():
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        kv[k.strip()] = v.strip()
    return kv or None


def _b64_decode_errors(token: str) -> list[str]:
    t = (token or "").strip()
    if not t:
        return []
    pad = (-len(t)) % 4
    if pad:
        t += "=" * pad
    try:
        raw = base64.standard_b64decode(t.encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, OSError) as e:
        logger.debug("IAM report errs b64 decode failed: %s", e)
        return [t] if t else []
    return [x.strip() for x in raw.split("|") if x.strip()]


def parse_mc_shell_logs_for_iam_report(log_bytes: bytes) -> IamReconcileReport | None:
    text = log_bytes.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        kv = _parse_kv_report_line(line)
        if not kv:
            continue
        try:
            pol_exp = int(kv.get("pol_exp", "0"))
            usr_exp = int(kv.get("usr_exp", "0"))
            att_exp = int(kv.get("att_exp", "0"))
        except ValueError:
            continue
        if pol_exp + usr_exp + att_exp <= 0:
            return None

        def _i(key: str) -> int:
            try:
                return int(kv.get(key, "0"))
            except ValueError:
                return 0

        pol_ok, pol_fail = _i("pol_ok"), _i("pol_fail")
        usr_ok, usr_fail = _i("usr_ok"), _i("usr_fail")
        att_ok, att_fail = _i("att_ok"), _i("att_fail")
        errors = _b64_decode_errors(kv.get("errs", ""))

        return IamReconcileReport(
            enabled=True,
            policies_expected=pol_exp,
            policies_provisioned=pol_ok,
            policies_failed=pol_fail,
            policies_unprovisioned=max(0, pol_exp - pol_ok),
            users_expected=usr_exp,
            users_provisioned=usr_ok,
            users_failed=usr_fail,
            users_unprovisioned=max(0, usr_exp - usr_ok),
            attaches_expected=att_exp,
            attaches_provisioned=att_ok,
            attaches_failed=att_fail,
            attaches_unprovisioned=max(0, att_exp - att_ok),
            errors=errors,
        )
    return None


def mc_shell_iam_integration_events_from_logs(log_bytes: bytes, demo_id: str) -> list[dict[str, Any]]:
    """Build integration-log style records from mc-shell stdout/stderr (IAM simulation + report line)."""
    text = log_bytes.decode("utf-8", errors="replace")
    out: list[dict[str, Any]] = []
    base_ms = int(time_mod.time() * 1000)
    seen: set[str] = set()
    for i, raw in enumerate(text.splitlines()):
        s = raw.strip()
        if not s:
            continue
        if "[iam-sim]" not in s and "DEMOFORGE_IAM_REPORT " not in s:
            continue
        if "DEMOFORGE_IAM_REPORT " in s:
            idx = s.find("DEMOFORGE_IAM_REPORT ")
            s = s[idx:].strip()
        key = hashlib.sha256(f"{demo_id}:{s}".encode()).hexdigest()[:28]
        if key in seen:
            continue
        seen.add(key)
        kind = "minio_iam_report" if s.startswith("DEMOFORGE_IAM_REPORT") else "minio_iam_sim"
        lvl = "warn" if ("WARN" in s or "fail" in s.lower()) and kind == "minio_iam_sim" else "info"
        msg = s if len(s) <= 240 else s[:237] + "…"
        out.append(
            {
                "id": f"mc-shell-iam-{key}",
                "ts_ms": base_ms + i,
                "level": lvl,
                "kind": kind,
                "message": msg,
                "details": s,
                "source": "mc-shell",
                "node_id": "mc-shell",
            }
        )
    return out


@router.get("/api/demos/{demo_id}/iam-reconcile-report")
async def get_iam_reconcile_report(demo_id: str) -> dict[str, Any]:
    """Return IAM reconcile statistics when the demo's mc-shell emitted ``DEMOFORGE_IAM_REPORT``."""
    client = docker.from_env()
    name = f"demoforge-{demo_id}-mc-shell"
    try:
        c = await asyncio.to_thread(client.containers.get, name)
    except NotFound:
        return {"enabled": False, "reason": "mc_shell_not_found"}
    except Exception as e:
        logger.warning("iam-reconcile-report: get container %s: %s", name, e)
        return {"enabled": False, "reason": "docker_error"}

    try:
        logs = await asyncio.to_thread(lambda: c.logs(tail=50000))
    except Exception as e:
        logger.warning("iam-reconcile-report: logs %s: %s", name, e)
        return {"enabled": False, "reason": "logs_error"}

    rep = parse_mc_shell_logs_for_iam_report(logs)
    if rep is None:
        return {"enabled": False, "reason": "no_iam_report"}
    return rep.model_dump()
