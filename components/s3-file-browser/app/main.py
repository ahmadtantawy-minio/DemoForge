"""S3 File Browser — DemoForge component.

Web-based S3 browser with load-balance visualization and cluster health
validation scenarios. Shows which MinIO node serves each request when
behind an NGINX load balancer.
"""

import io
import json
import os
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from minio import Minio
from minio.error import S3Error

app = FastAPI()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load config from /app/config.json, fall back to env vars."""
    cfg = {
        "endpoint": "",
        "via_loadbalancer": False,
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "connection_type": "none",
        "source_component": "",
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
    return cfg


CONFIG = load_config()

# ---------------------------------------------------------------------------
# S3 client (minio SDK)
# ---------------------------------------------------------------------------

def get_s3_client() -> Minio:
    parsed = urlparse(CONFIG["endpoint"])
    host = parsed.netloc or parsed.path  # handle with/without scheme
    secure = parsed.scheme == "https"
    return Minio(
        host,
        access_key=CONFIG["access_key"],
        secret_key=CONFIG["secret_key"],
        secure=secure,
    )


s3 = get_s3_client()

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
        s3.list_buckets()
        return {"status": "ok", "endpoint": CONFIG["endpoint"]}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_bucket(b):
    return {"name": b.name, "created": b.creation_date.isoformat() if b.creation_date else ""}

def _format_object(o):
    return {
        "key": o.object_name,
        "size": o.size or 0,
        "last_modified": o.last_modified.isoformat() if o.last_modified else "",
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    return CONFIG


# ---------------------------------------------------------------------------
# Bucket operations
# ---------------------------------------------------------------------------

@app.get("/api/buckets")
def list_buckets():
    served_by = track(probe_upstream())
    try:
        buckets = [_format_bucket(b) for b in s3.list_buckets()]
        return {"buckets": buckets, "served_by": served_by}
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


# ---------------------------------------------------------------------------
# Object operations
# ---------------------------------------------------------------------------

@app.get("/api/objects")
def list_objects(bucket: str, prefix: str = ""):
    served_by = track(probe_upstream())
    try:
        objects_iter = s3.list_objects(bucket, prefix=prefix or None, recursive=False)
        prefixes = []
        objects = []
        for obj in objects_iter:
            if obj.is_dir:
                prefixes.append({"prefix": obj.object_name})
            else:
                objects.append(_format_object(obj))
        return {"prefixes": prefixes, "objects": objects, "served_by": served_by}
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


@app.post("/api/upload")
async def upload_file(bucket: str, key: str, file: UploadFile = File(...)):
    served_by = track(probe_upstream())
    try:
        data = await file.read()
        s3.put_object(bucket, key, io.BytesIO(data), length=len(data))
        return {"message": f"Uploaded {key}", "size": len(data), "served_by": served_by}
    except Exception as e:
        return JSONResponse({"error": str(e), "served_by": served_by}, status_code=500)


@app.get("/api/download")
def download_file(bucket: str, key: str):
    try:
        resp = s3.get_object(bucket, key)
        filename = key.split("/")[-1]
        return StreamingResponse(
            resp,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/delete")
def delete_object(bucket: str, key: str):
    served_by = track(probe_upstream())
    try:
        s3.remove_object(bucket, key)
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
        for obj in s3.list_objects(bucket, recursive=True):
            if obj.is_dir:
                continue
            served_by = track(probe_upstream())
            try:
                resp = s3.get_object(bucket, obj.object_name)
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
            s3.put_object(bucket, key, io.BytesIO(data), length=len(data))
        except Exception as e:
            errors.append({"key": key, "phase": "write", "error": str(e), "served_by": served_by_write})
            continue

        served_by_read = track(probe_upstream())
        try:
            resp = s3.get_object(bucket, key)
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
            s3.remove_object(bucket, key)
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
        s3.put_object(bucket, probe_key, io.BytesIO(data), length=len(data))
    except Exception as e:
        return JSONResponse({"error": f"Failed to create probe object: {e}"}, status_code=500)

    measurements = []
    for _ in range(iterations):
        served_by = track(probe_upstream())
        start = time.monotonic()
        try:
            s3.stat_object(bucket, probe_key)
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
        s3.remove_object(bucket, probe_key)
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
            keys = sorted(o.object_name for o in s3.list_objects(bucket, recursive=True) if not o.is_dir)
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
