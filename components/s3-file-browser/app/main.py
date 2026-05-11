"""S3 File Browser — DemoForge component.

Web-based S3 browser with load-balance visualization and cluster health
validation scenarios. Shows which MinIO node serves each request when
behind an NGINX load balancer.
"""

import io
import json
import logging
import mimetypes
import os
import time
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from collections import defaultdict

from pydantic import BaseModel

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from minio import Minio

logger = logging.getLogger(__name__)

app = FastAPI()

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
        return m if isinstance(m, dict) else {}
    except json.JSONDecodeError:
        return {}


IDENTITY_MAP: dict[str, dict[str, str]] = _parse_identity_map()
ACTIVE_IDENTITY: str = os.getenv("S3_ACTIVE_IDENTITY", "").strip()
_s3_holder: dict[str, object | None] = {"client": None, "cache_key": None}

# Root is keyed ``__root__`` in the identity map (legacy ``""`` may still exist).
_ROOT_KEYS = frozenset({"", "__root__"})


def _infer_active_identity_from_credentials() -> None:
    """If compose omits ``S3_ACTIVE_IDENTITY``, derive it from ``CONFIG`` keys + ``IDENTITY_MAP``."""
    global ACTIVE_IDENTITY
    cur = (ACTIVE_IDENTITY or "").strip()
    if cur == "__first__":
        return
    if cur and cur not in _ROOT_KEYS:
        return
    if cur == "__root__":
        return
    ak = str(CONFIG.get("access_key") or "").strip()
    if not ak or not IDENTITY_MAP:
        return
    root_ent = IDENTITY_MAP.get("__root__") or IDENTITY_MAP.get("") or {}
    root_ak = str(root_ent.get("access_key", "")).strip() if isinstance(root_ent, dict) else ""
    if root_ak and ak == root_ak:
        ACTIVE_IDENTITY = "__root__" if "__root__" in IDENTITY_MAP else ""
        return
    for key, ent in IDENTITY_MAP.items():
        if key in _ROOT_KEYS or key == "__first__":
            continue
        if isinstance(ent, dict) and str(ent.get("access_key", "")).strip() == ak:
            ACTIVE_IDENTITY = key
            return


_infer_active_identity_from_credentials()


def _endpoint_secure_host() -> tuple[str, bool]:
    parsed = urlparse(CONFIG["endpoint"])
    host = parsed.netloc or parsed.path
    secure = parsed.scheme == "https"
    return host, secure


def _resolve_s3_credentials() -> tuple[str, str]:
    """Return (access_key, secret_key) for the active simulated identity.

    MinIO evaluates IAM policies server-side for every S3 call made with these keys
    (including presigned URLs produced by this process). Root keys bypass simulation scope.
    """
    if not IDENTITY_MAP:
        return str(CONFIG.get("access_key", "minioadmin")), str(CONFIG.get("secret_key", "minioadmin"))
    raw = (ACTIVE_IDENTITY or "").strip()
    if raw in _ROOT_KEYS:
        key = "__root__" if "__root__" in IDENTITY_MAP else ("" if "" in IDENTITY_MAP else raw)
    else:
        key = raw
    if key not in IDENTITY_MAP:
        for cand in IDENTITY_MAP:
            if cand not in _ROOT_KEYS:
                key = cand
                break
    if key not in IDENTITY_MAP:
        key = "__root__" if "__root__" in IDENTITY_MAP else ""
    ent = IDENTITY_MAP.get(key) or {}
    return str(ent.get("access_key", CONFIG.get("access_key", "minioadmin"))), str(
        ent.get("secret_key", CONFIG.get("secret_key", "minioadmin"))
    )


def get_s3() -> Minio:
    """Return a MinIO client for the current ``ACTIVE_IDENTITY`` (cached)."""
    ak, sk = _resolve_s3_credentials()
    host, secure = _endpoint_secure_host()
    cache_key = (ACTIVE_IDENTITY, ak, sk, host, secure)
    if _s3_holder.get("cache_key") != cache_key or _s3_holder.get("client") is None:
        _s3_holder["client"] = Minio(host, access_key=ak, secret_key=sk, secure=secure)
        _s3_holder["cache_key"] = cache_key
    return _s3_holder["client"]  # type: ignore[return-value]

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
    out = {
        **CONFIG,
        "active_identity": ACTIVE_IDENTITY,
        "active_identity_label": label,
        "active_identity_policies": pols,
        "iam_policy_scope_summary": iam_summary,
        "iam_effective_root": bool(is_root),
    }
    return out


@app.post("/api/session")
def set_session(body: SessionBody):
    """Switch active S3 credentials when ``S3_IDENTITY_MAP_JSON`` was deployed (IAM simulation)."""
    global ACTIVE_IDENTITY
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
    ACTIVE_IDENTITY = key
    _s3_holder["client"] = None
    _s3_holder["cache_key"] = None
    idents = CONFIG.get("identities") or []
    _label, _pols, _root, iam_summary = _active_identity_policies_label(ACTIVE_IDENTITY, idents)
    return {
        "active_identity": ACTIVE_IDENTITY,
        "identities": idents,
        "active_identity_label": _label,
        "active_identity_policies": _pols,
        "iam_policy_scope_summary": iam_summary,
        "iam_effective_root": bool(_root),
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
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


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
        url = get_s3().presigned_get_object(
            bucket,
            key,
            expires=exp,
            response_headers=response_headers,
        )
        return {
            "url": url,
            "method": "GET",
            "expires_seconds": expires_sec,
            "bucket": bucket,
            "key": key,
            "inline": inline,
            "served_by": served_by,
        }
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


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
        url = get_s3().presigned_put_object(bucket, key, expires=exp)
        return {
            "url": url,
            "method": "PUT",
            "expires_seconds": expires_sec,
            "bucket": bucket,
            "key": key,
            "usage_note": "HTTP PUT the file bytes as the request body (e.g. curl -T my.dat <url>).",
            "served_by": served_by,
        }
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


@app.delete("/api/delete")
def delete_object(bucket: str, key: str):
    served_by = track(probe_upstream())
    try:
        get_s3().remove_object(bucket, key)
        return {"message": f"Deleted {key}", "served_by": served_by}
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
