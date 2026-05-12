"""IAM simulation helpers for the S3 file browser container (vendored subset of DemoForge backend logic).

Used when ``MINIO_IAM_SIM_SPEC`` is present in the environment but ``S3_IDENTITY_MAP_JSON`` was not
pre-computed at deploy time (or was omitted), so the browser can still build the same identity map
as compose/mc-shell.
"""

from __future__ import annotations

import json
from typing import Any


def parse_iam_sim_spec(raw: str | None) -> dict[str, Any] | None:
    if not raw or not str(raw).strip():
        return None
    try:
        spec = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(spec, dict):
        return None
    return spec


def effective_iam_sim_spec(raw: str | None) -> dict[str, Any] | None:
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


def build_s3_identity_env(
    root_user: str,
    root_password: str,
    spec: dict[str, Any] | None,
    simulated_identity: str,
) -> tuple[str, str, str, str, str]:
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
    for ak, sk, _label, _pol_list in user_rows:
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
