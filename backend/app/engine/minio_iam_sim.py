"""MinIO IAM simulation for demos — JSON spec parsed at compose time for mc-shell + S3 browser."""

from __future__ import annotations

import json
import logging
import re
import shlex
from typing import Any

logger = logging.getLogger(__name__)


def parse_iam_sim_spec(raw: str | None) -> dict[str, Any] | None:
    """Parse ``MINIO_IAM_SIM_SPEC`` JSON; return None if empty or invalid."""
    if not raw or not str(raw).strip():
        return None
    try:
        spec = json.loads(str(raw))
    except json.JSONDecodeError as e:
        logger.warning("MINIO_IAM_SIM_SPEC is not valid JSON: %s", e)
        return None
    if not isinstance(spec, dict):
        return None
    return spec


def effective_iam_sim_spec(raw: str | None) -> dict[str, Any] | None:
    """Return a parsed IAM sim spec only when it declares at least one policy or user.

    Placeholder values such as ``{}`` or ``{"policies":[],"users":[]}`` must not enable IAM
    reconciliation or S3 browser identity injection — keeps legacy demos unchanged.
    """
    spec = parse_iam_sim_spec(raw)
    if not spec:
        return None
    pols = spec.get("policies")
    usrs = spec.get("users")
    has_policies = isinstance(pols, list) and len(pols) > 0
    has_users = isinstance(usrs, list) and len(usrs) > 0
    if not has_policies and not has_users:
        return None
    return spec


def safe_policy_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)[:200] or "policy"


def safe_shell_single_quoted(s: str) -> str:
    """Wrap *s* for POSIX single-quoted shell literal."""
    return "'" + str(s).replace("'", "'\"'\"'") + "'"


def count_iam_policy_creates(spec: dict[str, Any]) -> int:
    """How many ``mc admin policy create`` attempts will be emitted (valid policy entries only)."""
    n = 0
    for pol in spec.get("policies") or []:
        if not isinstance(pol, dict):
            continue
        name = str(pol.get("name", "")).strip()
        doc = pol.get("document")
        if name and isinstance(doc, dict):
            n += 1
    return n


def count_iam_user_adds(spec: dict[str, Any]) -> int:
    """How many ``mc admin user add`` attempts will be emitted."""
    n = 0
    for user in spec.get("users") or []:
        if not isinstance(user, dict):
            continue
        ak = str(user.get("access_key") or user.get("name") or "").strip()
        sk = str(user.get("secret_key") or user.get("secret") or "").strip()
        if ak and sk:
            n += 1
    return n


def count_iam_policy_attaches(spec: dict[str, Any]) -> int:
    """How many ``mc admin policy attach`` attempts will be emitted."""
    n = 0
    for user in spec.get("users") or []:
        if not isinstance(user, dict):
            continue
        ak = str(user.get("access_key") or user.get("name") or "").strip()
        sk = str(user.get("secret_key") or user.get("secret") or "").strip()
        if not ak or not sk:
            continue
        policies = user.get("policies") or user.get("policy") or []
        if isinstance(policies, str):
            policies = [p.strip() for p in policies.split(",") if p.strip()]
        if not isinstance(policies, list):
            continue
        for pol in policies:
            if str(pol).strip():
                n += 1
    return n


def iam_reconcile_expected_counts(spec: dict[str, Any]) -> tuple[int, int, int]:
    """``(policy_creates, user_adds, policy_attaches)`` matching :func:`mc_shell_iam_lines`."""
    return (
        count_iam_policy_creates(spec),
        count_iam_user_adds(spec),
        count_iam_policy_attaches(spec),
    )


def mc_shell_iam_report_shell_init() -> list[str]:
    """Reset counters before any IAM ``mc`` commands (single block per init.sh)."""
    return [
        "",
        "# --- IAM simulation counters (DemoForge) ---",
        "iam_pol_ok=0; iam_pol_fail=0; iam_usr_ok=0; iam_usr_fail=0; iam_att_ok=0; iam_att_fail=0;",
        "DEMOFORGE_IAM_ERR=",
    ]


def mc_shell_iam_report_shell_finalize() -> list[str]:
    """Emit a single-line machine-readable summary for ``docker logs`` / API parsing."""
    return [
        "DEMOFORGE_IAM_ERR_B64=$(printf '%s' \"$DEMOFORGE_IAM_ERR\" | base64 | tr -d '\\n' 2>/dev/null || true)",
        "echo \"DEMOFORGE_IAM_REPORT v=1 pol_exp=${DEMOFORGE_IAM_EXP_POLICIES:-0} pol_ok=$iam_pol_ok pol_fail=$iam_pol_fail "
        "usr_exp=${DEMOFORGE_IAM_EXP_USERS:-0} usr_ok=$iam_usr_ok usr_fail=$iam_usr_fail "
        "att_exp=${DEMOFORGE_IAM_EXP_ATTACHES:-0} att_ok=$iam_att_ok att_fail=$iam_att_fail errs=${DEMOFORGE_IAM_ERR_B64}\"",
    ]


def _iam_err_shell_token(s: str) -> str:
    """Safe token for shell-embedded error fragments (single-quoted segments)."""
    return re.sub(r"[^a-zA-Z0-9._@-]", "_", str(s))[:120]


def write_policy_files_for_spec(
    spec: dict[str, Any],
    iam_dir: str,
    target_slug: str,
) -> list[tuple[str, str]]:
    """Write policy JSON files under ``iam_dir/target_slug/``.

    Returns list of ``(policy_name, relative_path)`` where relative_path is
    ``iam/{target_slug}/{file}.json`` under the mc-shell mount root.
    """
    import os

    out: list[tuple[str, str]] = []
    pol_dir = os.path.join(iam_dir, target_slug)
    os.makedirs(pol_dir, exist_ok=True)
    for pol in spec.get("policies") or []:
        if not isinstance(pol, dict):
            continue
        name = str(pol.get("name", "")).strip()
        doc = pol.get("document")
        if not name or not isinstance(doc, dict):
            continue
        fn = safe_policy_filename(name) + ".json"
        rel = f"iam/{target_slug}/{fn}"
        path = os.path.join(pol_dir, fn)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
        out.append((name, rel))
    return out


def mc_shell_iam_lines(
    alias: str,
    target_slug: str,
    spec: dict[str, Any],
    policy_pairs: list[tuple[str, str]],
) -> list[str]:
    """Shell lines to reconcile policies + users (run after ``mc alias set``).

    Counts successes/failures for :func:`mc_shell_iam_report_shell_finalize` (``DEMOFORGE_IAM_REPORT`` log line).
    """
    aq = safe_shell_single_quoted(alias)
    lines: list[str] = []
    lines.append(f"echo '[iam-sim] reconciling IAM for alias {alias} ({target_slug})'")

    for pol_name, rel_path in policy_pairs:
        fq = f"/etc/mc-shell/{rel_path}"
        pq = safe_shell_single_quoted(pol_name)
        fqq = safe_shell_single_quoted(fq)
        tok = _iam_err_shell_token(pol_name)
        lines.append(
            f"echo {shlex.quote(f'[iam-sim] cmd: mc admin policy remove {alias} policy={pol_name}')}"
        )
        lines.append(f"mc admin policy remove {aq} {pq} 2>/dev/null || true")
        lines.append(
            f"echo {shlex.quote(f'[iam-sim] cmd: mc admin policy create {alias} policy={pol_name} file={rel_path}')}"
        )
        lines.append(
            f"if mc admin policy create {aq} {pq} {fqq} >/dev/null 2>&1; then "
            f"iam_pol_ok=$((iam_pol_ok+1)); "
            f"else iam_pol_fail=$((iam_pol_fail+1)); "
            f"DEMOFORGE_IAM_ERR=\"${{DEMOFORGE_IAM_ERR}}policy_create:{tok}|\"; "
            f"echo '[iam-sim] WARN: policy {pol_name} create failed' >&2; "
            f"fi"
        )

    for user in spec.get("users") or []:
        if not isinstance(user, dict):
            continue
        ak = str(user.get("access_key") or user.get("name") or "").strip()
        sk = str(user.get("secret_key") or user.get("secret") or "").strip()
        if not ak or not sk:
            logger.warning("[iam-sim] skip user missing access_key/secret_key: %s", user)
            continue
        akq = safe_shell_single_quoted(ak)
        skq = safe_shell_single_quoted(sk)
        akt = _iam_err_shell_token(ak)
        lines.append(
            f"echo {shlex.quote(f'[iam-sim] cmd: mc admin user remove {alias} user={ak}')}"
        )
        lines.append(f"mc admin user remove {aq} {akq} 2>/dev/null || true")
        lines.append(
            f"echo {shlex.quote(f'[iam-sim] cmd: mc admin user add {alias} user={ak} (secret redacted)')}"
        )
        lines.append(
            f"if mc admin user add {aq} {akq} {skq} >/dev/null 2>&1; then "
            f"iam_usr_ok=$((iam_usr_ok+1)); "
            f"else iam_usr_fail=$((iam_usr_fail+1)); "
            f"DEMOFORGE_IAM_ERR=\"${{DEMOFORGE_IAM_ERR}}user_add:{akt}|\"; "
            f"echo '[iam-sim] WARN: user {ak} add failed' >&2; "
            f"fi"
        )
        policies = user.get("policies") or user.get("policy") or []
        if isinstance(policies, str):
            policies = [p.strip() for p in policies.split(",") if p.strip()]
        if not isinstance(policies, list):
            continue
        for pol in policies:
            pn = str(pol).strip()
            if not pn:
                continue
            pnq = safe_shell_single_quoted(pn)
            pnt = _iam_err_shell_token(pn)
            lines.append(
                f"echo {shlex.quote(f'[iam-sim] cmd: mc admin policy attach {alias} {pn} --user {ak}')}"
            )
            lines.append(
                f"if mc admin policy attach {aq} {pnq} --user={akq} >/dev/null 2>&1; then "
                f"iam_att_ok=$((iam_att_ok+1)); "
                f"else iam_att_fail=$((iam_att_fail+1)); "
                f"DEMOFORGE_IAM_ERR=\"${{DEMOFORGE_IAM_ERR}}attach:{pnt}_to_{akt}|\"; "
                f"echo '[iam-sim] WARN: attach {pn} -> {ak} failed' >&2; "
                f"fi"
            )

    lines.append(f"echo '[iam-sim] done for {alias}'")
    return lines


def build_s3_identity_env(
    root_user: str,
    root_password: str,
    spec: dict[str, Any] | None,
    simulated_identity: str,
) -> tuple[str, str, str, str, str]:
    """Build JSON env strings and active S3 access/secret for the file browser.

    Root credentials are keyed as ``__root__`` (and legacy ``""``) in the identity map.
    When ``simulated_identity`` is unset, empty, or unknown, the browser defaults to **root**
    (backward compatible). Use ``__first__`` to opt into the first simulated IAM user, or set
    a user's access key explicitly.

    Returns ``(identity_map_json, identities_public_json, active_ak, active_sk, active_identity_id)``.
    """
    root_entry = {"access_key": root_user, "secret_key": root_password}
    identity_map: dict[str, dict[str, str]] = {
        "": dict(root_entry),
        "__root__": dict(root_entry),
    }
    user_rows: list[tuple[str, str, str, list[str]]] = []
    if spec:
        for user in spec.get("users") or []:
            if not isinstance(user, dict):
                continue
            ak = str(user.get("access_key") or user.get("name") or "").strip()
            sk = str(user.get("secret_key") or user.get("secret") or "").strip()
            if not ak or not sk or ak in ("__root__", "", "__first__"):
                continue
            policies = user.get("policies") or user.get("policy") or []
            if isinstance(policies, str):
                pol_list = [p.strip() for p in policies.split(",") if p.strip()]
            elif isinstance(policies, list):
                pol_list = [str(p).strip() for p in policies if str(p).strip()]
            else:
                pol_list = []
            label = str(user.get("label") or ak).strip() or ak
            user_rows.append((ak, sk, label, pol_list))

    first_sim_ak = user_rows[0][0] if user_rows else ""
    for ak, sk, label, pol_list in user_rows:
        identity_map[ak] = {"access_key": ak, "secret_key": sk}

    if first_sim_ak:
        identity_map["__first__"] = dict(identity_map[first_sim_ak])

    public: list[dict[str, Any]] = [{"id": "__root__", "label": "Root (MinIO administrator)", "policies": []}]
    if user_rows:
        public.append(
            {
                "id": "__first__",
                "label": "First simulated user (IAM)",
                "policies": list(user_rows[0][3]),
            }
        )
    for ak, _sk, label, pol_list in user_rows:
        public.append({"id": ak, "label": label, "policies": pol_list})

    sim = (simulated_identity or "").strip()
    if sim == "__first__":
        active_id = "__first__" if first_sim_ak else "__root__"
    elif sim in ("", "__root__") or not sim:
        active_id = "__root__"
    elif sim in identity_map:
        active_id = sim
    else:
        active_id = "__root__"

    creds = identity_map.get(active_id) or identity_map["__root__"]
    return (
        json.dumps(identity_map, separators=(",", ":")),
        json.dumps(public, separators=(",", ":")),
        creds["access_key"],
        creds["secret_key"],
        active_id,
    )
