"""
Config-driven post-processing for MinIO webhook payloads (malware sample → report + Iceberg).
Scenario YAML path: EP_PROCESSING_SCENARIO (basename under /app/scenarios/ or absolute path).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import yaml

logger = logging.getLogger(__name__)

_SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_scenario_path() -> Path:
    raw = os.environ.get("EP_PROCESSING_SCENARIO", "malware-sample-pipeline.yaml").strip()
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return p
    name = raw if raw.endswith(".yaml") else f"{raw}.yaml"
    return _SCENARIOS_DIR / name


def load_processing_config() -> Dict[str, Any]:
    path = _resolve_scenario_path()
    if not path.exists():
        logger.warning("Processing scenario not found: %s — pipeline disabled", path)
        return {}
    try:
        cfg = _load_yaml(path)
        logger.info("Loaded processing scenario: %s", path)
        return cfg
    except Exception as e:
        logger.exception("Failed to load processing scenario %s: %s", path, e)
        return {}


def _extract_s3_from_payload(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """MinIO/S3 notification: Records[0].s3.bucket.name, Records[0].s3.object.key"""
    try:
        records = payload.get("Records") or []
        if not records:
            return None, None
        s3 = (records[0] or {}).get("s3") or {}
        bucket = ((s3.get("bucket") or {}) or {}).get("name")
        key = ((s3.get("object") or {}) or {}).get("key")
        if key and isinstance(key, str):
            key = urllib.parse.unquote_plus(key)
        return bucket, key
    except Exception:
        return None, None


def _match_sha256_from_key(key: str, match_cfg: Dict[str, Any]) -> Optional[str]:
    if not key:
        return None
    prefix = (match_cfg.get("key_prefix") or "").strip()
    suffix = (match_cfg.get("key_suffix") or "").strip()
    hex_len = int(match_cfg.get("sha256_hex_length") or 64)
    if prefix and not key.startswith(prefix):
        return None
    if suffix and not key.endswith(suffix):
        return None
    base = Path(key).name
    if suffix and base.endswith(suffix):
        base = base[: -len(suffix)]
    elif prefix and base.startswith(prefix.rstrip("/").split("/")[-1]):
        pass
    # basename is sha256 or sha256 with noise
    if len(base) != hex_len or not re.fullmatch(r"[0-9a-fA-F]+", base):
        return None
    return base.lower()


def _seed_from_sha256(sha256: str) -> int:
    h = hashlib.sha256(sha256.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _pick(rng: random.Random, seq: List[Any]) -> Any:
    return seq[rng.randrange(0, len(seq))] if seq else None


def _build_synthetic_report(sha256: str, syn: Dict[str, Any]) -> Dict[str, Any]:
    rng = random.Random(_seed_from_sha256(sha256))
    engines = syn.get("sandbox_engines") or ["Sandbox"]
    duration_cfg = syn.get("analysis_duration_sec") or {}
    dmin = int(duration_cfg.get("min", 60))
    dmax = int(duration_cfg.get("max", 300))
    duration = rng.randint(dmin, dmax)
    behavioral = (syn.get("behavioral_pool") or [])[:]
    rng.shuffle(behavioral)
    behavioral = behavioral[: rng.randint(1, min(4, len(behavioral) or 1))]
    mitre = (syn.get("mitre_pool") or [])[:]
    rng.shuffle(mitre)
    mitre = mitre[: rng.randint(1, min(3, len(mitre) or 1))]
    return {
        "sha256": sha256,
        "sandbox_engine": _pick(rng, engines),
        "sandbox_verdict": _pick(rng, syn.get("verdicts") or ["unknown"]),
        "file_type": _pick(rng, syn.get("file_types") or ["unknown"]),
        "analysis_duration_seconds": duration,
        "behavioral_indicators": behavioral,
        "mitre_techniques": mitre,
        "ioc_summary": {
            "domains": [f"evil-{sha256[:6]}.test"],
            "ips": [f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_iceberg_row(sha256: str, report: Dict[str, Any], syn: Dict[str, Any]) -> Dict[str, Any]:
    """Columns aligned with &malware_meta_schema in soc-threat-intel.yaml (malware_metadata_empty)."""
    rng = random.Random(_seed_from_sha256(sha256 + ":row"))
    object_id = str(uuid4())
    now = datetime.now(timezone.utc)
    duration_cfg = syn.get("analysis_duration_sec") or {}
    dmin = int(duration_cfg.get("min", 60))
    dmax = int(duration_cfg.get("max", 300))
    analysis_duration = rng.randint(dmin, dmax)
    behavioral = json.dumps(report.get("behavioral_indicators") or [])
    mitre = json.dumps(report.get("mitre_techniques") or [])
    sandbox_verdict = report.get("sandbox_verdict") or _pick(
        rng, syn.get("verdicts") or ["unknown"]
    )
    file_type = report.get("file_type") or _pick(rng, syn.get("file_types") or ["unknown"])
    threat = _pick(rng, syn.get("threat_actors") or ["Unknown"])
    family = _pick(rng, syn.get("malware_families") or ["unknown"])
    return {
        "object_id": object_id,
        "sha256": sha256,
        "file_type": file_type,
        "sandbox_verdict": sandbox_verdict,
        "threat_actor": threat,
        "file_size_bytes": rng.randint(10_000, 5_000_000),
        "malware_family": family,
        "behavioral_indicators": behavioral,
        "mitre_techniques": mitre,
        "analysis_timestamp": now,
        "sandbox_engine": report.get("sandbox_engine") or "Sandbox",
        "analysis_duration_seconds": report.get("analysis_duration_seconds") or analysis_duration,
    }


def _sql_escape(s: str) -> str:
    return s.replace("'", "''")


def _trino_literal(val: Any, col: str) -> str:
    if val is None:
        return "NULL"
    if col in ("file_size_bytes", "analysis_duration_seconds"):
        return str(int(val))
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, datetime):
        return f"TIMESTAMP '{val.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
    if isinstance(val, str):
        return f"'{_sql_escape(val)}'"
    return f"'{_sql_escape(str(val))}'"


def trino_execute_sql(sql: str, timeout: float = 60.0) -> Tuple[bool, Optional[str]]:
    """POST raw SQL like external-system TrinoTableWriter (text/plain body)."""
    host = os.environ.get("TRINO_HOST", "").strip()
    user = os.environ.get("TRINO_USER", "demoforge").strip() or "demoforge"
    if not host:
        return False, "TRINO_HOST not set"
    base = host if host.startswith("http") else f"http://{host}"
    url = f"{base}/v1/statement"
    body = sql.encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    req.add_header("X-Trino-User", user)
    catalog = os.environ.get("TRINO_CATALOG", "").strip()
    if catalog:
        req.add_header("X-Trino-Catalog", catalog)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        err = data.get("error")
        if err:
            return False, str(err.get("message") or err)
        next_uri = data.get("nextUri")
        while next_uri:
            r2 = urllib.request.Request(next_uri, method="GET")
            r2.add_header("X-Trino-User", user)
            with urllib.request.urlopen(r2, timeout=timeout) as resp2:
                raw2 = resp2.read().decode("utf-8", errors="replace")
            data2 = json.loads(raw2)
            err2 = data2.get("error")
            if err2:
                return False, str(err2.get("message") or err2)
            st = (data2.get("stats") or {}).get("state")
            if st == "FAILED":
                return False, str(data2.get("error") or "FAILED")
            next_uri = data2.get("nextUri")
        return True, None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        return False, f"HTTP {e.code}: {detail[:500]}"
    except Exception as e:
        return False, str(e)


def _insert_malware_metadata(
    catalog: str,
    schema: str,
    table: str,
    row: Dict[str, Any],
    skip_dup: bool,
) -> Tuple[bool, Optional[str]]:
    cols = [
        "object_id",
        "sha256",
        "file_type",
        "sandbox_verdict",
        "threat_actor",
        "file_size_bytes",
        "malware_family",
        "behavioral_indicators",
        "mitre_techniques",
        "analysis_timestamp",
        "sandbox_engine",
        "analysis_duration_seconds",
    ]
    fq = f'"{catalog}"."{schema}"."{table}"'
    if skip_dup:
        del_sql = f'DELETE FROM {fq} WHERE "sha256" = {_trino_literal(row["sha256"], "sha256")}'
        ok, err = trino_execute_sql(del_sql)
        if not ok:
            return False, err
    values = ", ".join(_trino_literal(row[c], c) for c in cols)
    col_list = ", ".join(f'"{c}"' for c in cols)
    sql = f"INSERT INTO {fq} ({col_list}) VALUES ({values})"
    return trino_execute_sql(sql)


def run_malware_pipeline(
    payload: Dict[str, Any],
    cfg: Dict[str, Any],
    s3_client: Any,
) -> Dict[str, Any]:
    """
    Returns dict: matched, sha256, report_key, report_bucket, trino_ok, trino_error,
    skip_generic_audit, error
    """
    out: Dict[str, Any] = {
        "matched": False,
        "sha256": None,
        "report_key": None,
        "report_bucket": None,
        "trino_ok": None,
        "trino_error": None,
        "skip_generic_audit": False,
        "error": None,
    }
    proc = (cfg.get("processing") or {}).get("malware_samples") or {}
    if not proc.get("enabled", True):
        return out

    match_cfg = proc.get("match") or {}
    bucket, key = _extract_s3_from_payload(payload)
    if not key:
        return out

    sha256 = _match_sha256_from_key(key, match_cfg)
    if not sha256:
        return out

    out["matched"] = True
    out["sha256"] = sha256
    syn = proc.get("synthetic") or {}

    report_doc = _build_synthetic_report(sha256, syn)
    report_cfg = proc.get("report") or {}
    key_tpl = (report_cfg.get("key_template") or "reports/{sha256}.json").replace("{sha256}", sha256)

    use_notif_bucket = report_cfg.get("use_notification_bucket", True)
    if use_notif_bucket:
        report_bucket = bucket
    else:
        report_bucket = os.environ.get("EP_REPORT_OUTPUT_BUCKET", "").strip()
    if not report_bucket:
        out["error"] = "report bucket missing (notification bucket or EP_REPORT_OUTPUT_BUCKET)"
        return out
    if not s3_client:
        out["error"] = "S3 client unavailable (S3_ENDPOINT / credentials)"
        return out

    try:
        body = json.dumps(report_doc, indent=2).encode("utf-8")
        extra = {}
        ct = report_cfg.get("content_type")
        if ct:
            extra["ContentType"] = str(ct)
        s3_client.put_object(Bucket=report_bucket, Key=key_tpl, Body=body, **extra)
        out["report_key"] = key_tpl
        out["report_bucket"] = report_bucket
    except Exception as e:
        out["error"] = f"put report: {e}"
        logger.exception("Malware pipeline: failed to write report")
        return out

    trino_cfg = proc.get("trino") or {}
    if trino_cfg.get("enabled", True):
        catalog = os.environ.get("TRINO_CATALOG", "iceberg").strip() or "iceberg"
        schema = str(trino_cfg.get("schema") or "soc")
        table = str(trino_cfg.get("table") or "malware_metadata")
        skip_dup = bool(trino_cfg.get("skip_if_duplicate_sha256", True))
        row = _build_iceberg_row(sha256, report_doc, syn)
        ok, err = _insert_malware_metadata(catalog, schema, table, row, skip_dup)
        out["trino_ok"] = ok
        out["trino_error"] = err
        if not ok:
            logger.warning("Malware pipeline: Trino insert failed: %s", err)

    audit = proc.get("audit") or {}
    if audit.get("skip_generic_audit_when_matched", False) and not out.get("error"):
        out["skip_generic_audit"] = True

    return out
