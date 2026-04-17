# Investigation: MinIO cluster “ready” lags behind containers running

**Status:** Findings (no code changes required for this doc).  
**Related backlog:** “MinIO cluster shows up slower than individual containers.”

## Summary

The UI treats a cluster as **fully healthy** only after several **independent signals** align. Docker reporting `running` is **necessary but not sufficient** for DemoForge’s “green” path.

## Latency sources (by layer)

### 1. Polling interval (frontend)

- `GET /api/demos/{id}/instances` runs on a **5s** interval while a demo is running (`App.tsx`).
- Any improvement to badges or cluster health appears at most **one poll late** (often 0–5s perceived delay).

### 2. Cluster health vs Docker health (`instances.py`)

- For clustered MinIO, **`GET http://{project}-{cluster}-lb:80/minio/health/cluster`** is treated as **authoritative** when it returns **200** (`_check_cluster_early`).
- If it returns non-200 or errors → `degraded` / `unreachable` even if individual containers are `running`.
- Distributed MinIO may need **extra time** after `docker compose up` before this endpoint returns 200 (formatting, quorum, internal health).

### 3. Docker healthcheck vs MinIO readiness

- Per-container status uses Docker **Health** when defined (`get_container_health` in `docker_manager.py`).
- A container can be **`running`** with health **`starting`** while MinIO is still bootstrapping.
- Cluster override: when **cluster** health is `healthy`, node health is forced **healthy** for pool nodes (`cluster_node_health_override`) — so the **cluster endpoint** is the gating signal, not Docker’s per-container health alone.

### 4. `health_monitor` loop (backend)

- Every **5s**, all demos get per-container checks; **Trino** nodes can be marked **degraded** if user tables are missing (`health_monitor.py` + `_trino_table_cache`).
- Not MinIO-specific, but adds another layer of “not green yet” for mixed demos.

### 5. Cold start inside MinIO / AIStor

- Erasure sets, distributed mode, and license checks can delay **S3 and health** APIs even when processes exist.
- **Expired license** blocks S3 entirely (separate from Docker).

## Optional follow-ups (product)

- Shorter first poll after deploy complete, or **SSE** for instance updates (larger change).
- Distinct UI states: **“Containers up”** vs **“Cluster ready”** to set expectations.
- Cache `/minio/health/cluster` for a few seconds server-side only if rate becomes an issue (not observed as primary bottleneck).
