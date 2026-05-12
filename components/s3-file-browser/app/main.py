"""S3 File Browser — DemoForge component.

Web-based S3 browser with load-balance visualization and cluster health
validation scenarios. Shows which MinIO node serves each request when
behind an NGINX load balancer.
"""

import copy
import io
import json
import logging
import mimetypes
import os
import threading
import time
import uuid
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from collections import defaultdict

from pydantic import BaseModel

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from minio import Minio

from iam_sim_bootstrap import build_s3_identity_env, effective_iam_sim_spec

logger = logging.getLogger(__name__)

app = FastAPI()


class IdentityCredentialError(Exception):
    """IAM simulation map is loaded but active identity / keys cannot be resolved."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _json_safe_api_detail(detail: object) -> object:
    """Coerce ``HTTPException.detail`` (str, list, or dict) for JSON responses."""
    if detail is None:
        return ""
    if isinstance(detail, (str, int, float, bool)):
        return detail
    if isinstance(detail, list):
        out_list: list[object] = []
        for x in detail:
            if isinstance(x, dict) and "msg" in x:
                out_list.append(x.get("msg"))
            else:
                out_list.append(str(x))
        return out_list
    if isinstance(detail, dict):
        return {str(k): _json_safe_api_detail(v) for k, v in detail.items()}
    return str(detail)


def _redact_access_key_id(ak: str) -> str:
    s = str(ak or "").strip()
    if not s:
        return "(empty)"
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}…{s[-4:]}"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _endpoint_looks_like_cluster_lb(url: str) -> bool:
    """Compose uses http://{project}-{clusterId}-lb:80 for distributed MinIO; only that path gets X-Upstream-Server."""
    try:
        p = urlparse(url)
        port = p.port or (80 if p.scheme == "http" else 443)
        host = p.hostname or ""
        return port == 80 and host.endswith("-lb")
    except Exception:
        return False


def load_config() -> dict:
    """Load config from /app/config.json, fall back to env vars."""
    cfg = {
        "endpoint": "",
        "via_loadbalancer": False,
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "connection_type": "none",
        "source_component": "",
        "identities": [],
    }
    config_path = Path("/app/config.json")
    if config_path.exists():
        try:
            with open(config_path) as f:
                loaded = json.load(f)
            cfg.update({k: v for k, v in loaded.items() if v})
        except Exception:
            pass
    # Env-var fallback
    if not cfg["endpoint"]:
        cfg["endpoint"] = os.getenv("S3_ENDPOINT", "http://localhost:9000")
        cfg["access_key"] = os.getenv("S3_ACCESS_KEY", "minioadmin")
        cfg["secret_key"] = os.getenv("S3_SECRET_KEY", "minioadmin")
    elif os.getenv("S3_ENDPOINT"):
        # When compose injects LB URL but an older config.json still pointed at :9000, prefer the live env.
        env_ep = os.getenv("S3_ENDPOINT", "").strip()
        if env_ep and env_ep != cfg.get("endpoint") and _endpoint_looks_like_cluster_lb(env_ep):
            cfg["endpoint"] = env_ep
            if os.getenv("S3_ACCESS_KEY"):
                cfg["access_key"] = os.getenv("S3_ACCESS_KEY", "minioadmin")
            if os.getenv("S3_SECRET_KEY"):
                cfg["secret_key"] = os.getenv("S3_SECRET_KEY", "minioadmin")
    if cfg.get("endpoint") and _endpoint_looks_like_cluster_lb(cfg["endpoint"]):
        cfg["via_loadbalancer"] = True
    idents_raw = os.getenv("S3_BROWSER_IDENTITIES_JSON", "").strip()
    if idents_raw:
        try:
            parsed = json.loads(idents_raw)
            if isinstance(parsed, list):
                cfg["identities"] = parsed
        except json.JSONDecodeError:
            pass
    if not cfg.get("identities"):
        cfg["identities"] = [{"id": "__root__", "label": "Root (MinIO administrator)", "policies": []}]
    # Generated config.json always carries MinIO root keys; compose injects simulated-user keys via env.
    # Prefer env whenever set (with or without S3_IDENTITY_MAP_JSON) so CONFIG matches real S3 credentials.
    env_ak = os.getenv("S3_ACCESS_KEY", "").strip()
    env_sk = os.getenv("S3_SECRET_KEY", "").strip()
    if env_ak:
        cfg["access_key"] = env_ak
    if env_sk:
        cfg["secret_key"] = env_sk
    return cfg


CONFIG = load_config()


def _parse_identity_map() -> dict[str, dict[str, str]]:
    raw = os.getenv("S3_IDENTITY_MAP_JSON", "").strip()
    if not raw:
        return {}
    try:
        m = json.loads(raw)
        if not isinstance(m, dict):
            logger.error("S3_IDENTITY_MAP_JSON parsed to non-object type=%s", type(m).__name__)
            return {}
        return m
    except json.JSONDecodeError as e:
        logger.error("S3_IDENTITY_MAP_JSON is invalid JSON: %s", e)
        return {}


def _bootstrap_identity_map_from_minio_iam_spec_env() -> None:
    """When ``S3_IDENTITY_MAP_JSON`` is missing but ``MINIO_IAM_SIM_SPEC`` is set, build the same map as compose.

    Mirrors :func:`backend.app.engine.compose_generator.generate._apply_s3_file_browser_iam_simulation` output
    and writes ``S3_IDENTITY_MAP_JSON`` / ``S3_BROWSER_IDENTITIES_JSON`` into ``os.environ`` so reload works.
    """
    global ACTIVE_IDENTITY
    if IDENTITY_MAP:
        return
    raw = os.getenv("MINIO_IAM_SIM_SPEC", "").strip()
    if not raw:
        return
    spec = effective_iam_sim_spec(raw)
    if not spec:
        return
    root_u = (
        str(os.getenv("S3_ROOT_ACCESS_KEY", "") or "").strip()
        or str(CONFIG.get("access_key") or "minioadmin").strip()
    )
    root_p = (
        str(os.getenv("S3_ROOT_SECRET_KEY", "") or "").strip()
        or str(CONFIG.get("secret_key") or "minioadmin").strip()
    )
    sim = (ACTIVE_IDENTITY or "").strip() or str(os.getenv("S3_ACTIVE_IDENTITY", "") or "").strip()
    try:
        imap_json, pub_json, ak, sk, active_id = build_s3_identity_env(root_u, root_p, spec, sim)
        new_map = json.loads(imap_json)
        if not isinstance(new_map, dict) or not new_map:
            return
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
        logger.warning("IAM bootstrap from MINIO_IAM_SIM_SPEC failed: %s", e)
        return
    except Exception as e:
        logger.warning("IAM bootstrap from MINIO_IAM_SIM_SPEC failed: %s", e)
        return

    IDENTITY_MAP.clear()
    IDENTITY_MAP.update(new_map)
    try:
        pub = json.loads(pub_json)
        if isinstance(pub, list) and pub:
            CONFIG["identities"] = pub
    except json.JSONDecodeError:
        pass
    CONFIG["access_key"] = ak
    CONFIG["secret_key"] = sk
    ACTIVE_IDENTITY = active_id
    os.environ["S3_IDENTITY_MAP_JSON"] = imap_json
    os.environ["S3_BROWSER_IDENTITIES_JSON"] = pub_json
    os.environ["S3_ACCESS_KEY"] = ak
    os.environ["S3_SECRET_KEY"] = sk
    os.environ["S3_ACTIVE_IDENTITY"] = active_id
    logger.info(
        "S3 IAM bootstrap: identity map built from MINIO_IAM_SIM_SPEC (map_keys=%r active=%r)",
        list(IDENTITY_MAP.keys()),
        ACTIVE_IDENTITY,
    )


IDENTITY_MAP: dict[str, dict[str, str]] = _parse_identity_map()
ACTIVE_IDENTITY: str = os.getenv("S3_ACTIVE_IDENTITY", "").strip()
_bootstrap_identity_map_from_minio_iam_spec_env()
_s3_holder: dict[str, object | None] = {"client": None, "cache_key": None}
_SESSION_EPOCH = 0

# Root is keyed ``__root__`` in the identity map (legacy ``""`` may still exist).
_ROOT_KEYS = frozenset({"", "__root__"})


def _default_root_map_key() -> str | None:
    """Prefer ``__root__`` in the map, then legacy empty-string root."""
    if "__root__" in IDENTITY_MAP:
        return "__root__"
    if "" in IDENTITY_MAP:
        return ""
    return None


def _infer_active_identity_from_credentials() -> None:
    """If compose omits ``S3_ACTIVE_IDENTITY``, derive it from ``CONFIG`` keys + ``IDENTITY_MAP``."""
    global ACTIVE_IDENTITY
    cur = (ACTIVE_IDENTITY or "").strip()
    if cur == "__first__":
        logger.info(
            "S3 identity bootstrap: S3_ACTIVE_IDENTITY=__first__ (explicit); map_keys=%s",
            list(IDENTITY_MAP.keys()) if IDENTITY_MAP else [],
        )
        return
    if cur and cur not in _ROOT_KEYS:
        logger.info(
            "S3 identity bootstrap: S3_ACTIVE_IDENTITY=%r (explicit simulated user); map_loaded=%s",
            cur,
            bool(IDENTITY_MAP),
        )
        return
    if cur == "__root__":
        logger.info("S3 identity bootstrap: S3_ACTIVE_IDENTITY=__root__ (explicit root)")
        return
    ak = str(CONFIG.get("access_key") or "").strip()
    if not IDENTITY_MAP:
        return
    if not ak:
        if not (ACTIVE_IDENTITY or "").strip():
            dk = _default_root_map_key()
            if dk is not None:
                ACTIVE_IDENTITY = dk
                logger.info(
                    "S3 identity bootstrap: CONFIG access_key empty — defaulted ACTIVE_IDENTITY to %r",
                    dk,
                )
        else:
            logger.warning(
                "S3 identity bootstrap: identity map is loaded but CONFIG access_key is empty — leaving ACTIVE_IDENTITY as set",
            )
        return
    root_ent = IDENTITY_MAP.get("__root__") or IDENTITY_MAP.get("") or {}
    root_ak = str(root_ent.get("access_key", "")).strip() if isinstance(root_ent, dict) else ""
    if root_ak and ak == root_ak:
        ACTIVE_IDENTITY = "__root__" if "__root__" in IDENTITY_MAP else ""
        logger.info(
            "S3 identity bootstrap: inferred ACTIVE_IDENTITY=%r from CONFIG access_key matching map root (%s)",
            ACTIVE_IDENTITY,
            _redact_access_key_id(ak),
        )
        return
    for key, ent in IDENTITY_MAP.items():
        if key in _ROOT_KEYS or key == "__first__":
            continue
        if isinstance(ent, dict) and str(ent.get("access_key", "")).strip() == ak:
            ACTIVE_IDENTITY = key
            logger.info(
                "S3 identity bootstrap: inferred ACTIVE_IDENTITY=%r from CONFIG access_key matching map entry %r (%s)",
                ACTIVE_IDENTITY,
                key,
                _redact_access_key_id(ak),
            )
            return
    if "__first__" in IDENTITY_MAP:
        ent_f = IDENTITY_MAP["__first__"]
        if isinstance(ent_f, dict) and str(ent_f.get("access_key", "")).strip() == ak:
            ACTIVE_IDENTITY = "__first__"
            logger.info(
                "S3 identity bootstrap: inferred ACTIVE_IDENTITY=__first__ from CONFIG access_key (%s)",
                _redact_access_key_id(ak),
            )
            return
    logger.info(
        "S3 identity bootstrap: S3_ACTIVE_IDENTITY unset and CONFIG access_key %s did not match a unique map entry (map keys=%r) — will default to root if applicable",
        _redact_access_key_id(ak),
        list(IDENTITY_MAP.keys()),
    )
    if not (ACTIVE_IDENTITY or "").strip() and IDENTITY_MAP:
        dk = _default_root_map_key()
        if dk is not None:
            ACTIVE_IDENTITY = dk
            logger.info(
                "S3 identity bootstrap: defaulted ACTIVE_IDENTITY to %r (single-browser root default)",
                dk,
            )


_infer_active_identity_from_credentials()


def _map_config_access_key_to_identity_key(ak_cfg: str) -> str | None:
    """Map CONFIG access_key to a single identity-map key, or None if ambiguous / no match."""
    if not ak_cfg or not IDENTITY_MAP:
        return None
    root_ent = IDENTITY_MAP.get("__root__") or IDENTITY_MAP.get("") or {}
    root_ak = str(root_ent.get("access_key", "")).strip() if isinstance(root_ent, dict) else ""
    if root_ak and ak_cfg == root_ak:
        if "__root__" in IDENTITY_MAP:
            return "__root__"
        if "" in IDENTITY_MAP:
            return ""
        return None
    sim_keys: list[str] = []
    for k, ent in IDENTITY_MAP.items():
        if k in _ROOT_KEYS or k == "__first__":
            continue
        if isinstance(ent, dict) and str(ent.get("access_key", "")).strip() == ak_cfg:
            sim_keys.append(k)
    if len(sim_keys) > 1:
        logger.error(
            "S3 credential resolution: CONFIG access_key matches multiple map keys %r — refusing ambiguous root fallback",
            sim_keys,
        )
        return None
    if len(sim_keys) == 1:
        return sim_keys[0]
    if "__first__" in IDENTITY_MAP:
        ent_f = IDENTITY_MAP["__first__"]
        if isinstance(ent_f, dict) and str(ent_f.get("access_key", "")).strip() == ak_cfg:
            return "__first__"
    return None


def _endpoint_secure_host() -> tuple[str, bool]:
    parsed = urlparse(CONFIG["endpoint"])
    host = parsed.netloc or parsed.path
    secure = parsed.scheme == "https"
    return host, secure


def _resolve_s3_credentials() -> tuple[str, str]:
    """Return (access_key, secret_key) for the active simulated identity.

    When ``S3_IDENTITY_MAP_JSON`` is loaded, **root is never used as a silent fallback** for an unknown
    or unset simulated user — resolution fails with :class:`IdentityCredentialError` instead.

    MinIO evaluates IAM policies server-side for every S3 call made with these keys
    (including presigned URLs produced by this process). Root keys bypass simulation scope only
    when explicitly selected (map key ``__root__`` or ``""``).
    """
    if not IDENTITY_MAP:
        ak = str(CONFIG.get("access_key", "")).strip()
        sk = str(CONFIG.get("secret_key", "")).strip()
        if not ak or not sk:
            raise IdentityCredentialError(
                "S3 credentials are missing: set S3_ACCESS_KEY and S3_SECRET_KEY (or populate config.json). "
                "No identity map is loaded — both access key and secret key are required."
            )
        return ak, sk

    raw = (ACTIVE_IDENTITY or "").strip()
    key: str | None = None

    if raw == "__first__":
        if "__first__" not in IDENTITY_MAP:
            raise IdentityCredentialError(
                "S3_ACTIVE_IDENTITY is __first__ but __first__ is not present in S3_IDENTITY_MAP_JSON."
            )
        key = "__first__"
    elif raw in _ROOT_KEYS:
        if "__root__" in IDENTITY_MAP:
            key = "__root__"
        elif "" in IDENTITY_MAP:
            key = ""
        else:
            raise IdentityCredentialError(
                "Root was requested but S3_IDENTITY_MAP_JSON has no __root__ or empty-string root entry."
            )
    elif raw:
        if raw not in IDENTITY_MAP:
            raise IdentityCredentialError(
                f"S3_ACTIVE_IDENTITY={raw!r} is not a key in S3_IDENTITY_MAP_JSON. "
                f"Valid keys: {sorted(IDENTITY_MAP.keys())!r}"
            )
        key = raw
    else:
        ak_cfg = str(CONFIG.get("access_key", "")).strip()
        key = _map_config_access_key_to_identity_key(ak_cfg)
        if key is None:
            dk = _default_root_map_key()
            if dk is None:
                raise IdentityCredentialError(
                    "IAM simulation map is loaded but has no root entry (__root__ or empty key) and "
                    "S3_ACCESS_KEY did not match exactly one simulated user."
                )
            key = dk

    ent = IDENTITY_MAP.get(key)  # type: ignore[arg-type]
    if not isinstance(ent, dict):
        raise IdentityCredentialError(f"S3_IDENTITY_MAP_JSON entry for key {key!r} is not an object.")
    ak = str(ent.get("access_key", "")).strip()
    sk = str(ent.get("secret_key", "")).strip()
    if not ak or not sk:
        raise IdentityCredentialError(
            f"S3_IDENTITY_MAP_JSON entry for key {key!r} is missing access_key or secret_key — check compose injection."
        )
    return ak, sk


def _credentials_resolution_preview() -> tuple[bool, str | None]:
    try:
        _resolve_s3_credentials()
        return True, None
    except IdentityCredentialError as e:
        return False, e.message


def _log_bootstrap_summary() -> None:
    idents = CONFIG.get("identities") or []
    logger.info(
        "S3 file browser startup: endpoint=%r via_lb=%s identity_map=%s active_identity=%r identities_rows=%s config_access_key_id=%s",
        CONFIG.get("endpoint"),
        CONFIG.get("via_loadbalancer"),
        "loaded" if IDENTITY_MAP else "absent",
        ACTIVE_IDENTITY,
        len(idents) if isinstance(idents, list) else 0,
        _redact_access_key_id(str(CONFIG.get("access_key") or "")),
    )
    try:
        _resolve_s3_credentials()
    except IdentityCredentialError as e:
        logger.error(
            "S3 file browser startup: credential resolution FAILED — S3 API will return 503 until fixed: %s",
            e.message,
        )
    else:
        logger.info("S3 file browser startup: credential resolution check passed.")


def get_s3() -> Minio:
    """Return a MinIO client for the current ``ACTIVE_IDENTITY`` (cached)."""
    try:
        ak, sk = _resolve_s3_credentials()
    except IdentityCredentialError as e:
        logger.error("S3 credential resolution failed: %s", e.message)
        raise HTTPException(status_code=503, detail=e.message) from e
    host, secure = _endpoint_secure_host()
    cache_key = (ACTIVE_IDENTITY, ak, sk, host, secure)
    if _s3_holder.get("cache_key") != cache_key or _s3_holder.get("client") is None:
        logger.info(
            "S3 MinIO client (re)built: active_identity=%r host=%s secure=%s access_key_id=%s",
            ACTIVE_IDENTITY,
            host,
            secure,
            _redact_access_key_id(ak),
        )
        _s3_holder["client"] = Minio(host, access_key=ak, secret_key=sk, secure=secure)
        _s3_holder["cache_key"] = cache_key
    return _s3_holder["client"]  # type: ignore[return-value]


_log_bootstrap_summary()

# ---------------------------------------------------------------------------
# Upstream tracking (for load-balance visualization)
# ---------------------------------------------------------------------------

node_hits: dict[str, int] = {}


def probe_upstream() -> str:
    """Make a lightweight HEAD request to capture X-Upstream-Server header."""
    try:
        req = urllib.request.Request(CONFIG["endpoint"], method="HEAD")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.headers.get("X-Upstream-Server", "")
    except Exception:
        return ""


def track(served_by: str) -> str:
    if served_by:
        node_hits[served_by] = node_hits.get(served_by, 0) + 1
    return served_by


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    try:
        get_s3().list_buckets()
        return {"status": "ok", "endpoint": CONFIG["endpoint"]}
    except HTTPException as e:
        return JSONResponse({"status": "error", "detail": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_bucket(b):
    return {"name": b.name, "created": b.creation_date.isoformat() if b.creation_date else ""}

def _normalize_user_metadata(meta) -> dict[str, str]:
    """Turn SDK metadata mapping into JSON-safe ``str -> str``."""
    out: dict[str, str] = {}
    if not meta:
        return out
    try:
        items = meta.items()
    except AttributeError:
        return out
    for k, v in items:
        kk = k.decode() if isinstance(k, bytes) else str(k)
        if v is None:
            out[kk] = ""
        elif isinstance(v, bytes):
            out[kk] = v.decode(errors="replace")
        else:
            out[kk] = str(v)
    return out


def _normalize_object_tags(tags) -> dict[str, str]:
    """S3 object tags (``mc cp --tags``, PutObjectTagging) as JSON-safe ``str -> str``."""
    if not tags:
        return {}
    try:
        return {str(k): "" if v is None else str(v) for k, v in tags.items()}
    except Exception:
        return {}


def _format_object(o, *, extended: bool = False) -> dict:
    base: dict = {
        "key": o.object_name,
        "size": o.size or 0,
        "last_modified": o.last_modified.isoformat() if o.last_modified else "",
    }
    if not extended:
        return base
    etag = getattr(o, "etag", None) or ""
    if isinstance(etag, bytes):
        etag = etag.decode(errors="replace")
    base["etag"] = etag
    base["content_type"] = getattr(o, "content_type", None) or ""
    base["storage_class"] = getattr(o, "storage_class", None) or ""
    base["metadata"] = _normalize_user_metadata(getattr(o, "metadata", None))
    base["object_tags"] = _normalize_object_tags(getattr(o, "tags", None))
    vid = getattr(o, "version_id", None)
    if vid:
        base["version_id"] = str(vid)
    return base


# ~16 MiB — MinIO / S3 default multipart threshold; put_object shards beyond this.
_MULTIPART_PART_SIZE = 16 * 1024 * 1024

# Presigned URL expiry bounds (seconds)
_PRESIGN_MIN_SEC = 60
_PRESIGN_MAX_SEC = 7 * 24 * 60 * 60  # 7 days (SDK default window)

# In-process version history for the file-detail UI. Survives PUTs when bucket versioning is off
# (MinIO replaces the object); we keep prior snapshots here for demo storytelling. Cleared on restart.
_VERSION_LEDGER_LOCK = threading.Lock()
_VERSION_LEDGER: dict[tuple[str, str], list[dict]] = {}

_ILM_VERSION_DISPLAY_HINT = (
    "Synthetic Last Modified (Update File with an age preset) affects this UI and the in-app ledger only; "
    "MinIO ILM still uses the real object write time from the server."
)


def _stat_to_version_row(st, *, source: str, is_latest: bool) -> dict:
    etag = getattr(st, "etag", None) or ""
    if isinstance(etag, bytes):
        etag = etag.decode(errors="replace")
    vid = getattr(st, "version_id", None)
    return {
        "version_id": str(vid) if vid else "null",
        "is_latest": bool(is_latest),
        "last_modified": st.last_modified.isoformat() if st.last_modified else "",
        "size": int(st.size or 0),
        "etag": etag,
        "content_type": getattr(st, "content_type", None) or "",
        "metadata": _normalize_user_metadata(getattr(st, "metadata", None)),
        "object_tags": _normalize_object_tags(getattr(st, "tags", None)),
        "source": source,
    }


def _parse_age_days_from_payload(payload: object) -> float:
    """Optional ``age_days`` from JSON body for simulated version display (ledger only)."""
    if not isinstance(payload, dict):
        return 0.0
    v = payload.get("age_days")
    if v is None:
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(x, 3650.0))


def _synthetic_last_modified_iso(age_days: float) -> str:
    """UTC timestamp for (now − age_days), for in-app version table / sorting only."""
    dt = datetime.now(timezone.utc) - timedelta(days=float(age_days))
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ledger_key(bucket: str, key: str) -> tuple[str, str]:
    return (bucket, key)


def _versions_ensure_initialized(client: Minio, bucket: str, key: str) -> bool:
    """Return True if the object exists and the ledger has at least one row."""
    lk = _ledger_key(bucket, key)
    with _VERSION_LEDGER_LOCK:
        if lk in _VERSION_LEDGER and _VERSION_LEDGER[lk]:
            return True
    try:
        st = client.stat_object(bucket, key)
    except Exception:
        return False
    row = _stat_to_version_row(st, source="live", is_latest=True)
    with _VERSION_LEDGER_LOCK:
        if lk not in _VERSION_LEDGER or not _VERSION_LEDGER[lk]:
            _VERSION_LEDGER[lk] = [row]
    return True


def _merge_native_versions_if_available(client: Minio, bucket: str, key: str) -> list[dict] | None:
    """If the MinIO SDK exposes native list-object-versions, return formatted rows (newest first)."""
    fn = getattr(client, "list_object_versions", None)
    if not callable(fn):
        return None
    try:
        raw = fn(bucket, key)
    except Exception as e:
        logger.info("list_object_versions unavailable for %s/%s: %s", bucket, key, e)
        return None
    rows: list[dict] = []
    try:
        iterable = list(raw) if not isinstance(raw, list) else raw
    except Exception:
        return None
    for item in iterable:
        try:
            is_latest = bool(getattr(item, "is_latest", False))
            lm = getattr(item, "last_modified", None)
            etag = getattr(item, "etag", None) or ""
            if isinstance(etag, bytes):
                etag = etag.decode(errors="replace")
            vid = getattr(item, "version_id", None)
            rows.append(
                {
                    "version_id": str(vid) if vid else "null",
                    "is_latest": is_latest,
                    "last_modified": lm.isoformat() if lm else "",
                    "size": int(getattr(item, "size", 0) or 0),
                    "etag": etag,
                    "content_type": getattr(item, "content_type", None) or "",
                    "metadata": _normalize_user_metadata(getattr(item, "metadata", None)),
                    "object_tags": _normalize_object_tags(getattr(item, "tags", None)),
                    "source": "native",
                }
            )
        except Exception:
            continue
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("last_modified") or "", reverse=True)
    return rows


def _versions_select_and_sort(client: Minio, bucket: str, key: str) -> tuple[list[dict], str]:
    """Prefer native multi-version listing when it beats the in-memory ledger row count."""
    lk = _ledger_key(bucket, key)
    native = _merge_native_versions_if_available(client, bucket, key)
    with _VERSION_LEDGER_LOCK:
        ledger = copy.deepcopy(_VERSION_LEDGER.get(lk, []))
    if native is not None and len(native) > len(ledger):
        rows = copy.deepcopy(native)
        mode = "native"
    else:
        rows = ledger
        mode = "ledger"
    rows.sort(key=lambda r: r.get("last_modified") or "", reverse=True)
    for i, r in enumerate(rows):
        r["is_latest"] = i == 0
    return rows, mode


def _simulate_put_new_version(client: Minio, bucket: str, key: str, note: str, age_days: float = 0.0) -> dict:
    """PUT a small JSON object as a new revision; extend native version list or in-process ledger."""
    lk = _ledger_key(bucket, key)
    if not _versions_ensure_initialized(client, bucket, key):
        raise LookupError(key)
    sim_id = str(uuid.uuid4())[:10]
    age_days = max(0.0, min(float(age_days or 0.0), 3650.0))
    payload_obj = {
        "demoforge_simulated_put": True,
        "ts": time.time(),
        "id": sim_id,
        "note": (note or "").strip()[:512],
        "age_days": age_days,
    }
    raw = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
    meta = {"Demoforge-Sim-Id": sim_id}
    if age_days > 0:
        meta["Demoforge-Display-Age-Days"] = f"{age_days:g}"
    client.put_object(
        bucket,
        key,
        io.BytesIO(raw),
        length=len(raw),
        content_type="application/json; charset=utf-8",
        metadata=meta,
    )
    native = _merge_native_versions_if_available(client, bucket, key)
    display_age_applied = False
    display_age_note = ""
    if native is not None and len(native) > 1:
        if age_days > 0:
            display_age_note = (
                "age_days is ignored while native multi-version listing is in use; "
                "synthetic dates apply only to the in-app ledger (single current version on the server)."
            )
        with _VERSION_LEDGER_LOCK:
            _VERSION_LEDGER[lk] = copy.deepcopy(native)
    else:
        st = client.stat_object(bucket, key)
        new_row = _stat_to_version_row(st, source="simulated_put", is_latest=True)
        if age_days > 0:
            real_lm = new_row.get("last_modified") or ""
            new_row["server_last_modified"] = real_lm
            new_row["last_modified"] = _synthetic_last_modified_iso(age_days)
            new_row["demoforge_display_age_days"] = float(age_days)
            display_age_applied = True
        with _VERSION_LEDGER_LOCK:
            hist = list(_VERSION_LEDGER.get(lk, []))
            if hist and hist[-1].get("etag") == new_row.get("etag") and hist[-1].get("size") == new_row.get("size"):
                for j, r in enumerate(hist):
                    r["is_latest"] = j == len(hist) - 1
            else:
                for r in hist:
                    r["is_latest"] = False
                hist.append(new_row)
                _VERSION_LEDGER[lk] = hist
    rows, mode = _versions_select_and_sort(client, bucket, key)
    out: dict = {"versions": rows, "history_mode": mode, "sim_id": sim_id, "display_age_applied": display_age_applied}
    if display_age_note:
        out["display_age_note"] = display_age_note
    return out


def _finalize_presigned_url(raw: object) -> str:
    """Normalize SDK output to a single absolute http(s) URL string; raise on truncation or bad values."""
    if raw is None:
        raise ValueError("S3 SDK returned no presigned URL (None).")
    if isinstance(raw, (bytes, bytearray)):
        u = raw.decode("utf-8", errors="replace").strip()
    else:
        u = str(raw).strip()
    if not u:
        raise ValueError("S3 SDK returned an empty presigned URL.")
    if u.startswith("=") or u.startswith("&") or (u.startswith("X-Amz-") and "?" not in u):
        raise ValueError(
            "Presigned URL looks truncated (starts like a query fragment without host/path). "
            "Check S3_ENDPOINT / MinIO connectivity and SDK version."
        )
    base = str(CONFIG.get("endpoint") or "").strip().rstrip("/")
    if base and not (u.startswith("http://") or u.startswith("https://")):
        if u.startswith("/"):
            u = base + u
        elif u.startswith("?"):
            raise ValueError(
                "Presigned URL is query-only; MinIO client endpoint is likely misconfigured "
                f"(CONFIG.endpoint preview: {base[:120]!r})."
            )
        else:
            u = base + "/" + u.lstrip("/")
    if not (u.startswith("http://") or u.startswith("https://")):
        raise ValueError(f"Presigned URL is not absolute http(s) after normalization (preview: {u[:200]!r}).")
    if "?" not in u:
        logger.warning("Presigned URL has no '?' query string (unusual): len=%s preview=%s", len(u), u[:160])
    return u


def _content_type_for_key(key: str) -> str:
    mt, _ = mimetypes.guess_type(key)
    return mt or "application/octet-stream"


def _is_video_content_type(ct: str) -> bool:
    return bool(ct and ct.startswith("video/"))


def _filename_from_key(key: str) -> str:
    return key.rstrip("/").split("/")[-1] or "object"


def _parse_range_header(range_hdr: str | None, total: int) -> tuple[int, int] | None:
    """Parse single ``Range: bytes=…`` into inclusive (start, end). ``None`` if not a range request."""
    if not range_hdr or not range_hdr.startswith("bytes="):
        return None
    spec = range_hdr.split("=", 1)[1].strip()
    if "," in spec:
        spec = spec.split(",", 1)[0].strip()
    try:
        if spec.startswith("-"):
            suffix = int(spec[1:])
            if suffix <= 0 or total <= 0:
                return None
            start = max(0, total - suffix)
            end = total - 1
            return start, end
        if "-" not in spec:
            return None
        left, right = spec.split("-", 1)
        start = int(left) if left.strip() else 0
        end = int(right) if right.strip() else total - 1
        if total > 0:
            end = min(end, total - 1)
        if start > end or start < 0:
            return None
        return start, end
    except ValueError:
        return None


def _stream_minio_response(resp):
    """Yield chunks from urllib3 response and always release the connection."""
    try:
        # urllib3 HTTPResponse
        if hasattr(resp, "stream"):
            for chunk in resp.stream(amt=1024 * 1024):
                if chunk:
                    yield chunk
        else:
            data = resp.read()
            if data:
                yield data
    finally:
        try:
            resp.close()
        except Exception:
            pass
        try:
            resp.release_conn()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class SessionBody(BaseModel):
    """Switch simulated IAM user (access key) or ``__root__`` for MinIO administrator."""

    identity: str = ""


def _normalize_session_identity(raw: str) -> str:
    """Map legacy empty / ``__root__`` to the canonical root key present in ``IDENTITY_MAP``."""
    r = (raw or "").strip()
    if r in _ROOT_KEYS:
        if "__root__" in IDENTITY_MAP:
            return "__root__"
        return "" if "" in IDENTITY_MAP else r
    return r


def _identity_switch_options() -> list[dict[str, str]]:
    """Dropdown rows: root first, then ``__first__`` (if present), then simulated users — all ``IDENTITY_MAP`` keys.

    Labels come from ``CONFIG.identities`` / ``S3_BROWSER_IDENTITIES_JSON`` when present; otherwise sensible defaults.
    Building from the map guarantees users appear even when only a single default root row was injected in config.
    """
    if not IDENTITY_MAP:
        return []
    rows = [x for x in (CONFIG.get("identities") or []) if isinstance(x, dict)]
    label_for: dict[str, str] = {}
    for row in rows:
        rid = row.get("id")
        if rid is None:
            continue
        sid = str(rid)
        lab = str(row.get("label") or sid).strip() or sid
        if sid in IDENTITY_MAP:
            label_for[sid] = lab
        nk = _normalize_session_identity(sid)
        if nk in IDENTITY_MAP:
            label_for.setdefault(nk, lab)

    out: list[dict[str, str]] = []
    added: set[str] = set()

    def add(map_key: str, default_label: str) -> None:
        if map_key not in IDENTITY_MAP or map_key in added:
            return
        added.add(map_key)
        out.append({"id": map_key, "label": label_for.get(map_key, default_label)})

    dk = _default_root_map_key()
    if dk is not None:
        add(dk, label_for.get(dk, "Root (MinIO administrator)"))
    if "__first__" in IDENTITY_MAP:
        add("__first__", label_for.get("__first__", "First simulated user (IAM)"))
    for mk in sorted(k for k in IDENTITY_MAP if k not in _ROOT_KEYS and k != "__first__"):
        add(mk, label_for.get(mk, mk))
    return out


def _coerce_identity_map_from_env_object(m: dict) -> dict[str, dict[str, str]]:
    """Normalize parsed ``S3_IDENTITY_MAP_JSON`` into credential entries; raise if none usable."""
    out: dict[str, dict[str, str]] = {}
    for k, v in m.items():
        if not isinstance(v, dict):
            continue
        ak = str(v.get("access_key", "")).strip()
        sk = str(v.get("secret_key", "")).strip()
        if not ak or not sk:
            continue
        out[str(k)] = {"access_key": ak, "secret_key": sk}
    if not out:
        raise ValueError(
            "Reloaded S3_IDENTITY_MAP_JSON has no principals with non-empty access_key and secret_key."
        )
    return out


def _reload_browser_identities_from_env_into_config() -> None:
    """Update ``CONFIG["identities"]`` from ``S3_BROWSER_IDENTITIES_JSON`` (strict for reload)."""
    raw = os.getenv("S3_BROWSER_IDENTITIES_JSON", "").strip()
    if not raw:
        CONFIG["identities"] = [{"id": "__root__", "label": "Root (MinIO administrator)", "policies": []}]
        return
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"S3_BROWSER_IDENTITIES_JSON is invalid JSON: {e}") from e
    if not isinstance(parsed, list):
        raise ValueError("S3_BROWSER_IDENTITIES_JSON must be a JSON array.")
    if len(parsed) == 0:
        CONFIG["identities"] = [{"id": "__root__", "label": "Root (MinIO administrator)", "policies": []}]
        return
    CONFIG["identities"] = parsed


def _ensure_active_identity_valid_after_map_reload() -> None:
    """If the active principal is missing from the new map, fall back to root or infer from CONFIG."""
    global ACTIVE_IDENTITY
    if not IDENTITY_MAP:
        return
    cur = (ACTIVE_IDENTITY or "").strip()
    if not cur:
        _infer_active_identity_from_credentials()
        return
    nk = _normalize_session_identity(cur)
    chosen = nk if nk in IDENTITY_MAP else cur
    if chosen in IDENTITY_MAP:
        ACTIVE_IDENTITY = chosen
        return
    dk = _default_root_map_key()
    if dk is not None:
        ACTIVE_IDENTITY = dk
        logger.warning(
            "IAM reload: active identity %r not present in reloaded map — defaulted to %r",
            cur,
            dk,
        )


def reload_iam_identity_state_from_environment() -> None:
    """Re-read identity map + public labels from the process environment (e.g. after mc-shell updates env)."""
    global IDENTITY_MAP
    raw = os.getenv("S3_IDENTITY_MAP_JSON", "").strip()
    if not raw:
        raise ValueError("S3_IDENTITY_MAP_JSON is empty — nothing to reload from the environment.")
    try:
        m = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"S3_IDENTITY_MAP_JSON is invalid JSON: {e}") from e
    if not isinstance(m, dict):
        raise ValueError("S3_IDENTITY_MAP_JSON must be a JSON object.")
    IDENTITY_MAP = _coerce_identity_map_from_env_object(m)
    _reload_browser_identities_from_env_into_config()
    env_ak = os.getenv("S3_ACCESS_KEY", "").strip()
    env_sk = os.getenv("S3_SECRET_KEY", "").strip()
    if env_ak:
        CONFIG["access_key"] = env_ak
    if env_sk:
        CONFIG["secret_key"] = env_sk
    _ensure_active_identity_valid_after_map_reload()


def _restore_iam_snapshot(
    snap_map: dict[str, dict[str, str]],
    snap_active: str,
    snap_idents: list,
    snap_ak: object,
    snap_sk: object,
) -> None:
    """Rollback identity map, active principal, and CONFIG fields after a failed reload / re-auth."""
    global IDENTITY_MAP, ACTIVE_IDENTITY
    IDENTITY_MAP = snap_map
    ACTIVE_IDENTITY = snap_active
    CONFIG["identities"] = snap_idents
    CONFIG["access_key"] = snap_ak
    CONFIG["secret_key"] = snap_sk
    _s3_holder["client"] = None
    _s3_holder["cache_key"] = None


def _policy_list_from_identity_row(row: dict) -> list[str]:
    pols = row.get("policies") or row.get("policy") or []
    if isinstance(pols, str):
        return [x.strip() for x in pols.split(",") if x.strip()]
    if isinstance(pols, list):
        return [str(x).strip() for x in pols if str(x).strip()]
    return []


def _active_identity_policies_label(active: str, identities: list) -> tuple[str, list[str], bool, str]:
    """Human label, attached policy names, is_root, one-line header summary for the UI."""
    idents_list = [x for x in (identities or []) if isinstance(x, dict)]
    root_summary = (
        "MinIO root — all S3 APIs use administrator credentials "
        "(full access; not limited by IAM simulation policies)."
    )
    not_loaded_summary = (
        "S3 calls use deployment access keys (IAM simulation identity map not loaded)."
    )

    def _from_public_row(row: dict, label_hint: str, *, weak_map: bool) -> tuple[str, list[str], bool, str]:
        pol_list = _policy_list_from_identity_row(row)
        label = str(row.get("label") or label_hint).strip() or str(label_hint)
        pol_disp = ", ".join(pol_list) if pol_list else "(none listed in IAM spec)"
        extra = (
            " (Identity map not loaded in this container — switch identity is unavailable.)"
            if weak_map
            else ""
        )
        summary = (
            "Browse, upload, delete, presigned GET/PUT, and health-check S3 calls all use this user's access key — "
            f"MinIO evaluates attached policies on every call. Identity: {label}. Policies: {pol_disp}.{extra}"
        )
        return (label, pol_list, False, summary)

    if not IDENTITY_MAP:
        a_strip = (active or "").strip()
        if a_strip in _ROOT_KEYS:
            return ("Root (MinIO administrator)", [], True, root_summary)
        lookup = a_strip or str(CONFIG.get("access_key") or "").strip()
        if lookup in _ROOT_KEYS:
            return ("Root (MinIO administrator)", [], True, root_summary)
        if lookup == "__first__":
            row = next((r for r in idents_list if str(r.get("id")) == "__first__"), None)
            if row is None:
                row = next(
                    (
                        r
                        for r in idents_list
                        if str(r.get("id")) not in _ROOT_KEYS and str(r.get("id")) != "__first__"
                    ),
                    None,
                )
            if row:
                return _from_public_row(row, lookup, weak_map=True)
        for row in idents_list:
            rid = row.get("id")
            if rid is None:
                continue
            rs = str(rid)
            if rs in _ROOT_KEYS or rs == "__first__":
                continue
            if rs == lookup:
                return _from_public_row(row, lookup, weak_map=True)
        if lookup and lookup not in _ROOT_KEYS:
            disp = lookup if len(lookup) <= 28 else f"{lookup[:10]}…{lookup[-6:]}"
            summary = (
                "Browse, upload, delete, presigned GET/PUT, and health-check S3 calls use this deployment access key — "
                "MinIO enforces IAM for this principal. "
                "(Identity map not loaded in this container; policy names may be omitted.)"
            )
            return (disp, [], False, summary)
        return ("", [], True, not_loaded_summary)

    a_strip = (active or "").strip()
    norm = _normalize_session_identity(a_strip)
    if a_strip in _ROOT_KEYS or norm in _ROOT_KEYS:
        summary = (
            "MinIO root — all S3 APIs use administrator credentials "
            "(full access; not limited by IAM simulation policies)."
        )
        return ("Root (MinIO administrator)", [], True, summary)

    for row in idents_list:
        rid = row.get("id")
        if rid is None:
            continue
        rs = str(rid)
        if rs != a_strip and rs != norm:
            continue
        return _from_public_row(row, str(active), weak_map=False)

    summary = "All S3 calls use this access key; MinIO enforces IAM for this principal on the server."
    return (str(active), [], False, summary)


@app.get("/api/config")
def get_config():
    idents = CONFIG.get("identities") or []
    label, pols, is_root, iam_summary = _active_identity_policies_label(ACTIVE_IDENTITY, idents)
    cred_ok, cred_err = _credentials_resolution_preview()
    switch_opts = _identity_switch_options()
    out = {
        **CONFIG,
        "active_identity": ACTIVE_IDENTITY,
        "active_identity_label": label,
        "active_identity_policies": pols,
        "iam_policy_scope_summary": iam_summary,
        "iam_effective_root": bool(is_root),
        "s3_credentials_ready": cred_ok,
        "s3_credentials_error": cred_err,
        "identity_switch_options": switch_opts,
        "identity_switch_enabled": len(switch_opts) > 1,
        "session_epoch": _SESSION_EPOCH,
        "iam_env_reload_available": bool(os.getenv("S3_IDENTITY_MAP_JSON", "").strip()) or bool(IDENTITY_MAP),
    }
    return out


@app.post("/api/iam/reload")
def reload_iam_from_environment():
    """Re-read ``S3_IDENTITY_MAP_JSON`` / ``S3_BROWSER_IDENTITIES_JSON`` from the environment and re-verify MinIO.

    Use when mc-shell or another process refreshed IAM-related env vars in this container without restarting
    the browser process. Rolls back on parse errors or failed ``list_buckets`` re-authentication.
    """
    global _SESSION_EPOCH
    if not os.getenv("S3_IDENTITY_MAP_JSON", "").strip() and not IDENTITY_MAP:
        return JSONResponse(
            {
                "error": "Reload unavailable: no IAM identity map is loaded and S3_IDENTITY_MAP_JSON is not set.",
                "detail": "Configure MINIO_IAM_SIM_SPEC on the MinIO peer (or S3_IDENTITY_MAP_JSON on this container) and redeploy, or run with compose that injects IAM simulation env.",
            },
            status_code=400,
        )

    if not os.getenv("S3_IDENTITY_MAP_JSON", "").strip() and IDENTITY_MAP:
        os.environ["S3_IDENTITY_MAP_JSON"] = json.dumps(IDENTITY_MAP, separators=(",", ":"))

    snap_map = dict(IDENTITY_MAP)
    snap_active = ACTIVE_IDENTITY
    snap_idents = copy.deepcopy(CONFIG.get("identities") or [])
    snap_ak = CONFIG.get("access_key")
    snap_sk = CONFIG.get("secret_key")

    try:
        reload_iam_identity_state_from_environment()
    except ValueError as e:
        _restore_iam_snapshot(snap_map, snap_active, snap_idents, snap_ak, snap_sk)
        return JSONResponse({"error": str(e), "detail": str(e)}, status_code=400)
    except Exception as e:
        _restore_iam_snapshot(snap_map, snap_active, snap_idents, snap_ak, snap_sk)
        logger.exception("IAM reload: failed while re-reading environment")
        return JSONResponse(
            {"error": "Failed to re-read IAM configuration from the environment.", "detail": str(e)},
            status_code=500,
        )

    _s3_holder["client"] = None
    _s3_holder["cache_key"] = None
    served_by = track(probe_upstream())
    try:
        get_s3().list_buckets()
    except HTTPException as e:
        _restore_iam_snapshot(snap_map, snap_active, snap_idents, snap_ak, snap_sk)
        logger.warning(
            "IAM reload: MinIO re-authentication failed after env re-read (rolled back): status=%s detail=%s",
            e.status_code,
            e.detail,
        )
        return JSONResponse(
            {
                "error": "MinIO rejected credentials after reloading IAM from the environment (state was rolled back).",
                "detail": _json_safe_api_detail(e.detail),
            },
            status_code=e.status_code,
        )
    except Exception as e:
        _restore_iam_snapshot(snap_map, snap_active, snap_idents, snap_ak, snap_sk)
        logger.warning("IAM reload: MinIO re-authentication failed after env re-read (rolled back): %s", e)
        return JSONResponse(
            {
                "error": "Could not reach MinIO after reloading IAM from the environment (state was rolled back).",
                "detail": str(e),
            },
            status_code=503,
        )

    node_hits.clear()
    _SESSION_EPOCH += 1
    logger.info(
        "IAM reload: success map_keys=%r session_epoch=%s served_by=%r",
        list(IDENTITY_MAP.keys()),
        _SESSION_EPOCH,
        served_by,
    )
    out = get_config()
    out["iam_reload"] = {
        "ok": True,
        "message": "User list re-read from container environment; MinIO session verified.",
        "served_by": served_by,
    }
    return out


@app.post("/api/session")
def set_session(body: SessionBody):
    """Switch active S3 credentials when ``S3_IDENTITY_MAP_JSON`` was deployed (IAM simulation)."""
    global ACTIVE_IDENTITY, _SESSION_EPOCH
    if not IDENTITY_MAP:
        if body.identity:
            return JSONResponse(
                {"error": "IAM simulation not configured (no identities map)."},
                status_code=400,
            )
        return {"active_identity": "", "identities": CONFIG.get("identities", [])}
    key = _normalize_session_identity(body.identity)
    if key not in IDENTITY_MAP:
        return JSONResponse(
            {"error": f"Unknown identity {body.identity!r}. Valid: {list(IDENTITY_MAP.keys())!r}"},
            status_code=400,
        )
    prev_identity = ACTIVE_IDENTITY
    prev_epoch = _SESSION_EPOCH
    ACTIVE_IDENTITY = key
    _s3_holder["client"] = None
    _s3_holder["cache_key"] = None
    served_by = track(probe_upstream())
    try:
        get_s3().list_buckets()
    except HTTPException as e:
        ACTIVE_IDENTITY = prev_identity
        _SESSION_EPOCH = prev_epoch
        _s3_holder["client"] = None
        _s3_holder["cache_key"] = None
        logger.warning(
            "S3 session switch re-authentication failed (rolled back to previous identity): status=%s detail=%s",
            e.status_code,
            e.detail,
        )
        return JSONResponse(
            {
                "error": "Re-authentication against the cluster failed after switching user.",
                "detail": _json_safe_api_detail(e.detail),
            },
            status_code=e.status_code,
        )
    except Exception as e:
        ACTIVE_IDENTITY = prev_identity
        _SESSION_EPOCH = prev_epoch
        _s3_holder["client"] = None
        _s3_holder["cache_key"] = None
        logger.warning("S3 session switch re-authentication failed (rolled back): %s", e)
        return JSONResponse(
            {
                "error": "Re-authentication against the cluster failed after switching user.",
                "detail": str(e),
            },
            status_code=503,
        )

    _SESSION_EPOCH = prev_epoch + 1
    node_hits.clear()
    logger.info(
        "S3 session switch: active_identity=%r map_key=%r session_epoch=%s cluster_reauthenticated=1 served_by=%r",
        ACTIVE_IDENTITY,
        key,
        _SESSION_EPOCH,
        served_by,
    )
    idents = CONFIG.get("identities") or []
    _label, _pols, _root, iam_summary = _active_identity_policies_label(ACTIVE_IDENTITY, idents)
    return {
        "active_identity": ACTIVE_IDENTITY,
        "identities": idents,
        "active_identity_label": _label,
        "active_identity_policies": _pols,
        "iam_policy_scope_summary": iam_summary,
        "iam_effective_root": bool(_root),
        "session_epoch": _SESSION_EPOCH,
        "served_by": served_by,
        "cluster_reauthenticated": True,
    }


# ---------------------------------------------------------------------------
# Bucket operations
# ---------------------------------------------------------------------------

@app.get("/api/buckets")
def list_buckets():
    served_by = track(probe_upstream())
    try:
        buckets = [_format_bucket(b) for b in get_s3().list_buckets()]
        return {"buckets": buckets, "served_by": served_by}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


# Cap per-bucket walk so very large buckets do not hang the UI thread unbounded.
_DEFAULT_OVERVIEW_MAX = 200_000


def _bucket_overview_row(
    client: Minio,
    bucket_name: str,
    created: str,
    max_objects: int,
    *,
    group_by_storage_class: bool = False,
) -> dict:
    """Count objects (non-dir) and summed size under bucket; may truncate at max_objects."""
    row: dict = {
        "name": bucket_name,
        "created": created,
        "object_count": 0,
        "total_size_bytes": 0,
        "count_truncated": False,
        "error": None,
        "by_storage_class": None,
    }
    try:
        if not group_by_storage_class:
            n = 0
            total = 0
            for obj in client.list_objects(bucket_name, recursive=True):
                if getattr(obj, "is_dir", False):
                    continue
                n += 1
                total += int(obj.size or 0)
                if n >= max_objects:
                    row["count_truncated"] = True
                    break
            row["object_count"] = n
            row["total_size_bytes"] = total
            return row

        groups: dict[str, dict[str, int]] = defaultdict(lambda: {"object_count": 0, "total_size_bytes": 0})
        n = 0
        for obj in client.list_objects(bucket_name, recursive=True):
            if getattr(obj, "is_dir", False):
                continue
            sc = getattr(obj, "storage_class", None) or ""
            sc_key = str(sc)
            g = groups[sc_key]
            g["object_count"] += 1
            g["total_size_bytes"] += int(obj.size or 0)
            n += 1
            if n >= max_objects:
                row["count_truncated"] = True
                break
        row["object_count"] = n
        row["total_size_bytes"] = sum(int(x["total_size_bytes"]) for x in groups.values())
        breakdown: list[dict] = []
        for sc_key in sorted(groups.keys(), key=lambda k: (-groups[k]["object_count"], k)):
            breakdown.append(
                {
                    "storage_class": sc_key,
                    "display_class": sc_key if sc_key else "(default / unset)",
                    "object_count": groups[sc_key]["object_count"],
                    "total_size_bytes": groups[sc_key]["total_size_bytes"],
                }
            )
        row["by_storage_class"] = breakdown
    except Exception as e:
        row["error"] = str(e)
    return row


@app.get("/api/buckets/overview")
async def buckets_overview(
    max_objects_per_bucket: int = Query(
        _DEFAULT_OVERVIEW_MAX,
        ge=1,
        le=2_000_000,
        description="Stop counting after this many objects per bucket (high-level scan cap).",
    ),
    group_by_storage_class: bool = Query(
        False,
        description="When true, each bucket includes ``by_storage_class`` counts (uses list object metadata).",
    ),
):
    """High-level list: every bucket with object count and total size (best-effort; may truncate)."""
    served_by = track(probe_upstream())

    def _work() -> dict:
        client = get_s3()
        rows: list[dict] = []
        raw = client.list_buckets()
        for b in raw:
            created = b.creation_date.isoformat() if b.creation_date else ""
            rows.append(
                _bucket_overview_row(
                    client,
                    b.name,
                    created,
                    max_objects_per_bucket,
                    group_by_storage_class=group_by_storage_class,
                )
            )
        total_objects = sum(r["object_count"] for r in rows if not r.get("error"))
        total_bytes = sum(int(r.get("total_size_bytes") or 0) for r in rows if not r.get("error"))
        return {
            "buckets": rows,
            "summary": {
                "bucket_count": len(rows),
                "total_objects_counted": total_objects,
                "total_bytes_counted": total_bytes,
                "max_objects_per_bucket": max_objects_per_bucket,
                "group_by_storage_class": group_by_storage_class,
            },
        }

    try:
        data = await run_in_threadpool(_work)
        data["served_by"] = served_by
        return data
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


# ---------------------------------------------------------------------------
# Object operations
# ---------------------------------------------------------------------------

@app.get("/api/objects")
def list_objects(
    bucket: str,
    prefix: str = "",
    extended: bool = Query(
        False,
        description="Include etag, content_type, storage_class, user metadata, and object tags (MinIO: list with metadata=true).",
    ),
):
    served_by = track(probe_upstream())
    try:
        # MinIO: ``include_user_meta`` adds ``metadata=true`` so listings include
        # UserMetadata (x-amz-meta-*) and UserTags (``mc cp --tags`` / object tagging).
        try:
            objects_iter = get_s3().list_objects(
                bucket,
                prefix=prefix or None,
                recursive=False,
                include_user_meta=extended,
            )
        except HTTPException:
            raise
        except Exception as e:
            if extended:
                logger.warning("list_objects with metadata failed (%s); retrying without", e)
                objects_iter = get_s3().list_objects(bucket, prefix=prefix or None, recursive=False)
            else:
                raise
        prefixes = []
        objects = []
        for obj in objects_iter:
            if obj.is_dir:
                prefixes.append({"prefix": obj.object_name})
            else:
                objects.append(_format_object(obj, extended=extended))
        return {"prefixes": prefixes, "objects": objects, "extended": extended, "served_by": served_by}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


@app.get("/api/object/versions")
def get_object_versions(bucket: str, key: str):
    """Version-oriented view for a single object (native list when available, else in-process ledger)."""
    served_by = track(probe_upstream())
    key = (key or "").strip()
    if not key or key.endswith("/"):
        return JSONResponse({"error": "Invalid object key"}, status_code=400)
    try:
        client = get_s3()
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)
    if not _versions_ensure_initialized(client, bucket, key):
        return JSONResponse({"error": "Object not found", "served_by": served_by}, status_code=404)
    rows, mode = _versions_select_and_sort(client, bucket, key)
    if not rows:
        return JSONResponse({"error": "Object not found", "served_by": served_by}, status_code=404)
    return {
        "bucket": bucket,
        "key": key,
        "versions": rows,
        "history_mode": mode,
        "served_by": served_by,
        "ilm_display_hint": _ILM_VERSION_DISPLAY_HINT,
    }


@app.post("/api/object/simulate-new-version")
def simulate_new_object_version(
    bucket: str = Query(..., min_length=1),
    key: str = Query(..., min_length=1),
    payload: dict | None = Body(default=None),
):
    """Simulate a client PUT of a new revision.

    JSON body (optional): ``note`` (str), ``age_days`` (number) — when versioning uses the
    in-app ledger, ``age_days`` sets the displayed ``last_modified`` for that new row (ILM on
    MinIO still uses the real write time).
    """
    served_by = track(probe_upstream())
    key = key.strip()
    if not key or key.endswith("/"):
        return JSONResponse({"error": "Invalid object key"}, status_code=400)
    note = ""
    age_days = 0.0
    if isinstance(payload, dict):
        note = str(payload.get("note") or "")[:512]
        age_days = _parse_age_days_from_payload(payload)
    try:
        client = get_s3()
        out = _simulate_put_new_version(client, bucket, key, note, age_days)
    except LookupError:
        return JSONResponse({"error": "Object not found", "served_by": served_by}, status_code=404)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)
    out["bucket"] = bucket
    out["key"] = key
    out["served_by"] = served_by
    out["ilm_display_hint"] = _ILM_VERSION_DISPLAY_HINT
    return out


@app.post("/api/upload")
async def upload_file(bucket: str, key: str, file: UploadFile = File(...)):
    """Upload object; large streams use multipart uploads inside the MinIO SDK (see part_size)."""
    served_by = track(probe_upstream())
    ct = file.content_type or "application/octet-stream"

    def _put():
        try:
            file.file.seek(0)
        except Exception:
            pass
        sz = getattr(file, "size", None)
        if sz is not None:
            return get_s3().put_object(
                bucket,
                key,
                file.file,
                sz,
                content_type=ct,
                part_size=_MULTIPART_PART_SIZE,
            )
        data = file.file.read()
        return get_s3().put_object(
            bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=ct,
            part_size=_MULTIPART_PART_SIZE,
        )

    try:
        await file.seek(0)
        result = await run_in_threadpool(_put)
        etag = getattr(result, "etag", "") or ""
        sz = getattr(file, "size", None)
        if sz is None:
            try:
                file.file.seek(0, os.SEEK_END)
                sz = file.file.tell()
            except Exception:
                sz = None
        return {
            "message": f"Uploaded {key}",
            "size": sz,
            "etag": etag,
            "multipart": bool(sz and sz >= _MULTIPART_PART_SIZE),
            "served_by": served_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


@app.get("/api/download")
def download_file(bucket: str, key: str, request: Request):
    """Download object. Supports ``Range`` for large files and video seeking (HTTP 206)."""
    served_by = track(probe_upstream())
    filename = _filename_from_key(key)
    content_type = _content_type_for_key(key)
    video = _is_video_content_type(content_type)

    try:
        stat = get_s3().stat_object(bucket, key)
        total = int(stat.size or 0)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    range_pair = _parse_range_header(request.headers.get("range"), total)

    if range_pair is not None:
        start, end = range_pair
        if total <= 0 or start >= total:
            return Response(
                status_code=416,
                headers={
                    "Content-Range": f"bytes */{total}",
                    "Accept-Ranges": "bytes",
                },
            )
        end = min(end, total - 1)
        length = end - start + 1
        try:
            resp = get_s3().get_object(bucket, key, offset=start, length=length)
        except HTTPException:
            raise
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

        disp = (
            f'inline; filename="{filename}"'
            if video
            else f'attachment; filename="{filename}"'
        )
        headers = {
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
            "Content-Disposition": disp,
            "X-Served-By-Upstream": served_by or "",
        }
        return StreamingResponse(
            _stream_minio_response(resp),
            status_code=206,
            media_type=content_type,
            headers=headers,
        )

    try:
        resp = get_s3().get_object(bucket, key)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    disp = (
        f'inline; filename="{filename}"'
        if video
        else f'attachment; filename="{filename}"'
    )
    headers = {
        "Content-Length": str(total) if total > 0 else None,
        "Accept-Ranges": "bytes",
        "Content-Disposition": disp,
        "Content-Type": content_type,
        "X-Served-By-Upstream": served_by or "",
    }
    headers = {k: v for k, v in headers.items() if v is not None}

    return StreamingResponse(
        _stream_minio_response(resp),
        media_type=content_type,
        headers=headers,
    )


@app.get("/api/presign/get")
def presign_get(
    bucket: str = Query(...),
    key: str = Query(...),
    expires_sec: int = Query(
        3600,
        ge=_PRESIGN_MIN_SEC,
        le=_PRESIGN_MAX_SEC,
        description="URL lifetime in seconds",
    ),
    inline: bool = Query(
        False,
        description="If true, set response-content-disposition to inline (e.g. media in browser)",
    ),
):
    """Return a time-limited presigned **GET** URL (download / open in browser)."""
    served_by = track(probe_upstream())
    try:
        exp = timedelta(seconds=expires_sec)
        ct = _content_type_for_key(key)
        fn = _filename_from_key(key)
        disp = (
            f'inline; filename="{fn}"'
            if inline
            else f'attachment; filename="{fn}"'
        )
        response_headers = {
            "response-content-type": ct,
            "response-content-disposition": disp,
        }
        raw_url = get_s3().presigned_get_object(
            bucket,
            key,
            expires=exp,
            response_headers=response_headers,
        )
        url = _finalize_presigned_url(raw_url)
        return {
            "url": url,
            "method": "GET",
            "expires_seconds": expires_sec,
            "bucket": bucket,
            "key": key,
            "inline": inline,
            "served_by": served_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "presign_get failed bucket=%r key=%r expires_sec=%s inline=%s",
            bucket,
            key,
            expires_sec,
            inline,
        )
        return JSONResponse(
            {"error": str(e), "detail": str(e), "served_by": served_by},
            status_code=500,
        )


@app.get("/api/presign/put")
def presign_put(
    bucket: str = Query(...),
    key: str = Query(...),
    expires_sec: int = Query(
        3600,
        ge=_PRESIGN_MIN_SEC,
        le=_PRESIGN_MAX_SEC,
        description="URL lifetime in seconds",
    ),
):
    """Return a time-limited presigned **PUT** URL (upload bytes with HTTP PUT)."""
    served_by = track(probe_upstream())
    try:
        exp = timedelta(seconds=expires_sec)
        raw_url = get_s3().presigned_put_object(bucket, key, expires=exp)
        url = _finalize_presigned_url(raw_url)
        return {
            "url": url,
            "method": "PUT",
            "expires_seconds": expires_sec,
            "bucket": bucket,
            "key": key,
            "usage_note": "HTTP PUT the file bytes as the request body (e.g. curl -T my.dat <url>).",
            "served_by": served_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "presign_put failed bucket=%r key=%r expires_sec=%s",
            bucket,
            key,
            expires_sec,
        )
        return JSONResponse(
            {"error": str(e), "detail": str(e), "served_by": served_by},
            status_code=500,
        )


@app.delete("/api/delete")
def delete_object(bucket: str, key: str):
    served_by = track(probe_upstream())
    try:
        get_s3().remove_object(bucket, key)
        return {"message": f"Deleted {key}", "served_by": served_by}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


# ---------------------------------------------------------------------------
# Stats (node distribution histogram)
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def get_stats():
    total = sum(node_hits.values()) or 1
    return {
        "node_hits": node_hits,
        "total": sum(node_hits.values()),
        "percentages": {k: round(v / total * 100, 1) for k, v in node_hits.items()},
    }


@app.post("/api/stats/reset")
def reset_stats():
    node_hits.clear()
    return {"message": "Stats reset"}


# ---------------------------------------------------------------------------
# Cluster Health Validation Scenarios
# ---------------------------------------------------------------------------

@app.post("/api/health-check/read-all")
def health_read_all(bucket: str = "demo-bucket"):
    """Read every object in a bucket to validate all nodes can serve reads.

    When load-balanced, this exercises all cluster nodes and reports which
    node served each read plus any failures — useful for detecting unhealthy
    nodes or replication lag.
    """
    results = []
    errors = []
    try:
        for obj in get_s3().list_objects(bucket, recursive=True):
            if obj.is_dir:
                continue
            served_by = track(probe_upstream())
            try:
                resp = get_s3().get_object(bucket, obj.object_name)
                resp.read()
                resp.close()
                resp.release_conn()
                results.append({
                    "key": obj.object_name,
                    "size": obj.size or 0,
                    "served_by": served_by,
                    "status": "ok",
                })
            except Exception as e:
                errors.append({
                    "key": obj.object_name,
                    "served_by": served_by,
                    "status": "error",
                    "error": str(e),
                })
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return {
        "bucket": bucket,
        "total_objects": len(results) + len(errors),
        "successful_reads": len(results),
        "failed_reads": len(errors),
        "healthy": len(errors) == 0,
        "results": results,
        "errors": errors,
        "node_distribution": dict(node_hits),
    }


@app.post("/api/health-check/write-read-verify")
def health_write_read_verify(bucket: str = "demo-bucket", count: int = Query(default=10, ge=1, le=100)):
    """Write test objects, read them back, verify integrity.

    Creates N small test objects with known content, reads each back
    (potentially from different nodes behind LB), and verifies the
    content matches. Detects data corruption or replication lag.
    """
    results = []
    errors = []
    test_prefix = f"_health-check/{int(time.time())}/"

    for i in range(count):
        key = f"{test_prefix}test-{i:04d}.txt"
        expected = f"health-check-payload-{i}-{time.time()}"
        served_by_write = track(probe_upstream())

        try:
            data = expected.encode()
            get_s3().put_object(bucket, key, io.BytesIO(data), length=len(data))
        except HTTPException:
            raise
        except Exception as e:
            errors.append({"key": key, "phase": "write", "error": str(e), "served_by": served_by_write})
            continue

        served_by_read = track(probe_upstream())
        try:
            resp = get_s3().get_object(bucket, key)
            actual = resp.read().decode()
            resp.close()
            resp.release_conn()
            match = actual == expected
            results.append({
                "key": key,
                "write_served_by": served_by_write,
                "read_served_by": served_by_read,
                "integrity": "ok" if match else "MISMATCH",
            })
            if not match:
                errors.append({"key": key, "phase": "verify", "error": "Content mismatch"})
        except HTTPException:
            raise
        except Exception as e:
            errors.append({"key": key, "phase": "read", "error": str(e), "served_by": served_by_read})

    # Cleanup test files
    for i in range(count):
        key = f"{test_prefix}test-{i:04d}.txt"
        try:
            get_s3().remove_object(bucket, key)
        except Exception:
            pass

    return {
        "bucket": bucket,
        "test_count": count,
        "successful": len(results),
        "failed": len(errors),
        "healthy": len(errors) == 0,
        "results": results,
        "errors": errors,
        "node_distribution": dict(node_hits),
    }


@app.post("/api/health-check/latency-probe")
def health_latency_probe(bucket: str = "demo-bucket", iterations: int = Query(default=20, ge=1, le=100)):
    """Measure per-node latency by issuing repeated HEAD requests.

    Sends N HEAD requests to a known object (creates one if needed),
    tracks which node served each and the latency. Useful for
    detecting slow nodes or uneven latency distribution.
    """
    probe_key = "_health-check/latency-probe.txt"
    try:
        data = b"latency-probe"
        get_s3().put_object(bucket, probe_key, io.BytesIO(data), length=len(data))
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": f"Failed to create probe object: {e}"}, status_code=500)

    measurements = []
    for _ in range(iterations):
        served_by = track(probe_upstream())
        start = time.monotonic()
        try:
            get_s3().stat_object(bucket, probe_key)
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            measurements.append({"served_by": served_by, "latency_ms": latency_ms, "status": "ok"})
        except HTTPException:
            raise
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            measurements.append({"served_by": served_by, "latency_ms": latency_ms, "status": "error", "error": str(e)})

    # Aggregate per-node
    per_node: dict[str, list[float]] = {}
    for m in measurements:
        node = m["served_by"] or "unknown"
        per_node.setdefault(node, []).append(m["latency_ms"])

    summary = {}
    for node, latencies in per_node.items():
        summary[node] = {
            "count": len(latencies),
            "avg_ms": round(sum(latencies) / len(latencies), 2),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
        }

    # Cleanup
    try:
        get_s3().remove_object(bucket, probe_key)
    except Exception:
        pass

    return {
        "bucket": bucket,
        "iterations": iterations,
        "per_node_summary": summary,
        "measurements": measurements,
        "node_distribution": dict(node_hits),
    }


@app.post("/api/health-check/consistency")
def health_consistency_check(bucket: str = "demo-bucket"):
    """List objects from multiple requests and compare results.

    Issues several LIST requests (which may hit different nodes behind LB)
    and compares the object listings. Inconsistencies indicate replication
    lag or split-brain conditions.
    """
    listings = []
    for _ in range(5):
        served_by = track(probe_upstream())
        try:
            keys = sorted(o.object_name for o in get_s3().list_objects(bucket, recursive=True) if not o.is_dir)
            listings.append({"served_by": served_by, "object_count": len(keys), "keys": keys, "status": "ok"})
        except HTTPException:
            raise
        except Exception as e:
            listings.append({"served_by": served_by, "object_count": 0, "keys": [], "status": "error", "error": str(e)})

    # Compare all listings to first successful one
    ok_listings = [l for l in listings if l["status"] == "ok"]
    consistent = True
    if len(ok_listings) > 1:
        reference = ok_listings[0]["keys"]
        for l in ok_listings[1:]:
            if l["keys"] != reference:
                consistent = False
                break

    return {
        "bucket": bucket,
        "requests": len(listings),
        "consistent": consistent,
        "healthy": consistent and all(l["status"] == "ok" for l in listings),
        "listings": listings,
        "node_distribution": dict(node_hits),
    }


# ---------------------------------------------------------------------------
# Static files — must be last
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
