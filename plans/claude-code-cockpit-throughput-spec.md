# End-to-End Test Results & Cockpit Enhancement Spec

## Test Results Summary

### Lifecycle Test: Deploy → Stop → Start → Destroy

| Step | Action | Result | Status |
|------|--------|--------|--------|
| 1 | Page load (previously deployed) | Shows `● running`, Stop + Destroy buttons, 6 nodes healthy | ✅ PASS |
| 2 | Instances tab | 8 containers visible (6 minio nodes + 1 LB + 1 file-generator), all "Healthy" | ✅ PASS |
| 3 | Click Stop | Status → `● stopping...`, button disabled, instances show "Stopped" | ✅ PASS |
| 4 | Stop completes | Status → `● stopped`, Start + Destroy appear | ✅ PASS |
| 5 | Instances tab (stopped) | Initially empty "No running instances", then after a few seconds shows containers with "Stopped" badges | ⚠️ FLAKY — briefly shows empty state |
| 6 | Click Start | Button shows "Starting..." (amber), status stays `● stopped` | ❌ **FAIL — hangs indefinitely** |
| 7 | Start hangs >30s | Still "Starting...", instances empty | ❌ **CRITICAL — Start broken** |
| 8 | Click Destroy (while Start hanging) | Nothing happens — blocked behind hung Start | ❌ **CRITICAL — UI wedged** |
| 9 | Page refresh | State still `● stopped`, Start + Destroy buttons | ⚠️ Backend still processing |
| 10 | Click Destroy (after refresh) | Still stuck | ❌ **CRITICAL — cannot recover** |

### Critical Lifecycle Bugs

**BUG L1 — `docker compose start` hangs or fails silently (P0)**

The Start button calls the backend start endpoint which runs `docker compose start`. This appears to hang indefinitely — no timeout, no error surfaced to the UI. The FA is stuck with no recovery path except manually killing Docker containers.

Root cause hypotheses:
- `docker compose start` requires the compose file to exist — if it was cleaned up after the previous deploy, start fails
- The containers may have been removed by `docker compose stop` (if stop actually ran `down` instead of `stop`)
- The backend may not be surfacing the subprocess error to the frontend

**Fix:**
1. Add timeout to `docker compose start` (30s max)
2. If start fails, transition back to `stopped` state with error toast
3. Verify that `stop` actually runs `docker compose stop` (NOT `down`) — check `docker ps -a` shows exited containers
4. Add a fallback: if `start` fails, offer "Destroy & Redeploy" as recovery

**BUG L2 — No operation cancellation / concurrent operation guard (P0)**

Clicking Destroy while Start is hanging creates a deadlock. Both operations are queued in the backend with no way to cancel the first. The UI becomes completely stuck.

**Fix:**
1. Disable ALL lifecycle buttons while any operation is in progress
2. Add operation timeout with automatic rollback (e.g., 60s timeout → show error, enable Destroy)
3. Backend: drain guard should detect concurrent operations and reject with 409 (already exists in deploy, but may not exist for start/stop)

**BUG L3 — Instances tab briefly empty after Stop (P1)**

After stopping, the Instances tab shows "No running instances / Deploy the demo to see instances here" for several seconds before the stopped containers appear. The instance polling likely filters for `docker inspect` status = "running" only.

**Fix:**
- Instance polling should query `docker ps -a` (include stopped containers) when demo status is `stopped`
- Show stopped containers immediately with "Stopped" badge, not after a delay
- Change the empty state message: "No running instances" → different message based on demo state:
  - `not_deployed`: "Deploy the demo to see instances here."
  - `stopped`: "All containers are stopped. Click Start to resume."

---

## Cockpit Enhancement Spec

### Current State

The left sidebar has a "Healthcheck" item that shows hub/FA infrastructure connectivity (Local Hub API, GCP Gateway, MinIO/Registry, FA Auth). This is useful for DemoForge setup but has nothing to do with the running demo.

There is no demo-scoped "cockpit" or "dashboard" that shows live cluster status, throughput, or operational health during a running demo.

### Proposed: Demo Cockpit (New Page or Tab)

Add a **Cockpit** view accessible from the Designer page (alongside the Diagram / Instances tabs) that provides live operational visibility into the running demo.

```
[Diagram] [Instances] [Cockpit]     ← new tab, only visible when running/stopped
```

The Cockpit has two sub-tabs: **Cluster Status** and **Throughput**.

---

### Tab 1: Cluster Status

A textual, real-time dashboard showing the health of every cluster in the demo. This is the "ops view" — what `mc admin info` would show, presented visually.

#### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  CLUSTER STATUS                             Last check: 3s  │
│                                             [↻ Refresh]     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  MinIO Cluster (minio-cluster-1)              ● HEALTHY     │
│  ─────────────────────────────────────────────────────────  │
│                                                              │
│  Quorum            Write quorum met on all erasure sets     │
│  Uptime            12m 34s                                  │
│  API endpoint      http://localhost:9000                    │
│  Console           http://localhost:9001                    │
│  Version           RELEASE.2024-12-18T13-15-44Z             │
│                                                              │
│  POOLS                                                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Pool 1 — 6 nodes × 6 drives                 ● ONLINE  │ │
│  │                                                         │ │
│  │  Nodes online       6/6                                │ │
│  │  Drives online      36/36                              │ │
│  │  Drives healing     0                                  │ │
│  │  Erasure sets       3 × 12-drive sets                  │ │
│  │  EC parity          EC:3 (9 data + 3 parity)           │ │
│  │  Drive tolerance    3 per set                          │ │
│  │  Usable capacity    54 TB (75% of 72 TB raw)           │ │
│  │  Disk type          SSD                                │ │
│  │                                                         │ │
│  │  NODES                                                  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │ node-1  ● healthy  6/6 drives   uptime 12m 34s  │  │ │
│  │  │ node-2  ● healthy  6/6 drives   uptime 12m 34s  │  │ │
│  │  │ node-3  ● healthy  6/6 drives   uptime 12m 34s  │  │ │
│  │  │ node-4  ● healthy  4/6 drives   uptime 12m 34s  │  │ │
│  │  │   └─ drive-5: FAILED (simulated)                 │  │ │
│  │  │   └─ drive-6: HEALING (23% complete)             │  │ │
│  │  │ node-5  ● healthy  6/6 drives   uptime 12m 34s  │  │ │
│  │  │ node-6  ● healthy  6/6 drives   uptime 12m 34s  │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  LOAD BALANCER (minio-cluster-1-lb)           ● HEALTHY     │
│  ─────────────────────────────────────────────────────────  │
│  Type              nginx                                    │
│  Upstream nodes    6/6 healthy                              │
│  Active conns      12                                       │
│  Endpoint          http://localhost:9000 (proxied)          │
│                                                              │
│  OTHER COMPONENTS                                            │
│  ─────────────────────────────────────────────────────────  │
│  file-generator-3  ● healthy   steady mode                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

#### Data Sources

| Field | Source | Method |
|-------|--------|--------|
| Cluster quorum / health | `/minio/health/cluster` | HEAD request from backend, 200=healthy, 503=degraded |
| Node online/offline | `/minio/health/live` per node | HEAD request per container hostname |
| Drive status | `mc admin info local --json` | `docker exec` on one node, parse JSON `drives` array |
| Uptime | `mc admin info local --json` | `server.uptime` field |
| Version | `mc admin info local --json` | `server.version` field |
| LB active connections | `nginx -T` or nginx stub_status | Parse from LB container |
| LB upstream health | nginx upstream check | Parse upstream status |

#### Update Delivery — WebSocket

All cockpit data is pushed over a single WebSocket connection per demo:

```
ws://localhost:9210/api/demos/{demo_id}/cockpit/ws
```

The backend maintains the connection and pushes `cluster_status` frames on its own schedule:

- Cluster-level health (HEAD `/minio/health/cluster`): every 5 s — lightweight, emitted immediately on connect
- Per-node/drive detail (`mc admin info --json` via `docker exec`): every 10 s — emitted after first successful collect
- LB stats: every 5 s

Frame format:

```json
{
  "type": "cluster_status",
  "ts": 1712700000,
  "clusters": [
    {
      "cluster_id": "minio-cluster-1",
      "health": "healthy",
      "uptime_s": 754,
      "version": "RELEASE.2024-12-18T13-15-44Z",
      "api_endpoint": "http://localhost:9000",
      "console_endpoint": "http://localhost:9001",
      "pools": [ ... ],
      "lb": { "upstream_total": 6, "upstream_healthy": 6, "active_connections": 12 }
    }
  ]
}
```

The frontend opens the WebSocket once when the Cockpit tab is mounted and closes it on unmount. On reconnect (e.g., network blip), it re-subscribes from the last known `ts`. No polling intervals on the frontend.

#### When Demo is Stopped

Show last known state with a banner: "Demo is stopped. Showing last known state from [timestamp]." All values grayed out. Drive/node details show "offline" across the board.

---

### Tab 2: Throughput & Performance

Live throughput metrics scraped from the NGINX load balancer access logs. Shows real-time PUT/GET bandwidth, request rates, and error rates.

#### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  THROUGHPUT                           Live · Last 5 minutes │
│                                                              │
│  ┌─ BANDWIDTH ─────────────────────────────────────────────┐│
│  │                                                          ││
│  │  PUT throughput     ████████████████░░░░░  45.2 MB/s    ││
│  │  GET throughput     ██████████░░░░░░░░░░░  23.1 MB/s    ││
│  │                                                          ││
│  │  [===== sparkline chart over last 5 min =====]          ││
│  │       ^PUT line (teal)    ^GET line (blue)              ││
│  │                                                          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ REQUEST RATE ──────────────────────────────────────────┐│
│  │                                                          ││
│  │  PUT requests/sec   124 req/s                           ││
│  │  GET requests/sec   87 req/s                            ││
│  │  HEAD requests/sec  12 req/s                            ││
│  │  DELETE req/sec     2 req/s                             ││
│  │  Total req/sec      225 req/s                           ││
│  │                                                          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ ERROR RATE ────────────────────────────────────────────┐│
│  │                                                          ││
│  │  2xx responses      98.2%  ████████████████████░        ││
│  │  4xx responses      1.5%   █░░░░░░░░░░░░░░░░░░░        ││
│  │  5xx responses      0.3%   ░░░░░░░░░░░░░░░░░░░░        ││
│  │                                                          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ LATENCY (P50 / P99) ──────────────────────────────────┐│
│  │                                                          ││
│  │  PUT latency        P50: 12ms    P99: 89ms              ││
│  │  GET latency        P50: 8ms     P99: 45ms              ││
│  │  First byte (TTFB)  P50: 3ms     P99: 22ms             ││
│  │                                                          ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ TOP BUCKETS BY TRAFFIC ────────────────────────────────┐│
│  │                                                          ││
│  │  1. raw-data         32.1 MB/s  PUT  █████████████      ││
│  │  2. processed        12.4 MB/s  GET  ██████             ││
│  │  3. archive          0.7 MB/s   PUT  █                  ││
│  │                                                          ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

#### Data Sources — NGINX Access Log Parsing

The NGINX load balancer is already in front of all MinIO nodes. Its access log contains everything needed.

**Enable structured logging in NGINX config** (add to compose generation):

```nginx
log_format minio_metrics '$time_iso8601 $request_method $uri $status '
                         '$body_bytes_sent $request_time $upstream_response_time '
                         '$http_x_amz_content_sha256';
access_log /var/log/nginx/minio_access.log minio_metrics;
```

**Backend WebSocket endpoint** — single connection delivers all throughput frames:

```
ws://localhost:9210/api/demos/{demo_id}/cockpit/ws
```

The same WebSocket used for Cluster Status also carries `throughput` frames, pushed every 5 s:

```python
# Runs inside the cockpit WebSocket loop (shared with cluster_status frames)
async def _emit_throughput(ws, demo_id: str, window: int = 300):
    lb_container = f"demoforge-{demo_id}-minio-cluster-1-lb"
    result = await run_subprocess([
        "docker", "exec", lb_container,
        # awk filters to last `window` seconds using log timestamps — robust at any req/s
        "awk", f'BEGIN{{t=systime()-{window}}} $1>=t' , "/var/log/nginx/minio_access.log"
    ])
    stats = parse_nginx_metrics(result.stdout, window_seconds=window)
    await ws.send_json({
        "type": "throughput",
        "ts": int(time.time()),
        "window_seconds": window,
        "put_bandwidth_mbps": stats.put_bytes / window / 1_000_000,
        "get_bandwidth_mbps": stats.get_bytes / window / 1_000_000,
        "put_rps": stats.put_count / window,
        "get_rps": stats.get_count / window,
        "head_rps": stats.head_count / window,
        "delete_rps": stats.delete_count / window,
        "status_2xx_pct": stats.status_2xx / max(stats.total, 1) * 100,
        "status_4xx_pct": stats.status_4xx / max(stats.total, 1) * 100,
        "status_5xx_pct": stats.status_5xx / max(stats.total, 1) * 100,
        "put_latency_p50_ms": stats.put_latency_p50,
        "put_latency_p99_ms": stats.put_latency_p99,
        "get_latency_p50_ms": stats.get_latency_p50,
        "get_latency_p99_ms": stats.get_latency_p99,
        "top_buckets": stats.top_buckets,
        "timeseries": stats.timeseries_10s_buckets,   # list of {ts, put_mbps, get_mbps}
    })
```

**Note on log window robustness**: use `awk` with `systime()` to filter log lines by ISO timestamp rather than `tail -n 5000`. This correctly covers the last N seconds at any throughput level.

**NGINX stub_status** — also emit alongside the log-parsed data for active connection count (lightweight):

```nginx
location /nginx_status {
    stub_status on;
    allow 172.0.0.0/8;  # Docker network only
    deny all;
}
```

#### Frontend Implementation

- Open one WebSocket (`ws://.../cockpit/ws`) when Cockpit tab mounts; close on unmount
- Dispatch incoming frames by `type`: `cluster_status` → Cluster Status tab state, `throughput` → Throughput tab state
- On reconnect (backoff: 1 s, 2 s, 4 s, max 30 s), re-subscribe; show "Reconnecting…" banner
- Render sparkline charts using `recharts` (already in dependencies) fed by `timeseries` array
- Bandwidth bars: horizontal progress bars with current value
- Request rate: numeric display with per-method breakdown
- Error rate: percentage bars with color coding (green <1% 5xx / amber 1-5% / red >5%)
- Top buckets: parsed from `top_buckets` array in the frame

#### When Demo is Stopped

Show "Throughput data not available — demo is stopped." with the last known snapshot grayed out.

#### When No Traffic

Show "No traffic detected. Start a data generator or upload files to see throughput metrics."

---

### Cockpit Tab Visibility

| Demo State | Cockpit Tab |
|------------|-------------|
| `not_deployed` | Hidden |
| `running` | Visible, live data |
| `stopped` | Visible, last known state (grayed out with banner) |

---

### Implementation Notes

1. **Single WebSocket endpoint** (`/api/demos/{id}/cockpit/ws`) delivers all cockpit data — cluster status and throughput — in typed frames. The frontend dispatches by `type` field. This eliminates all polling intervals on the frontend and makes the UI non-flaky by design.

2. **Cluster Status tab** can be implemented without any NGINX changes — it only needs MinIO health endpoints and `mc admin info` via `docker exec`. No compose generator changes required.

3. **Throughput tab** requires two compose generator changes:
   - Add `minio_metrics` `log_format` + `access_log` directive to the NGINX LB config
   - Add `stub_status` location to the NGINX LB config (Docker-network-only access)

4. **Log parsing robustness**: use `awk` with `systime()` for time-windowed log reads — not `tail -n N`. `tail -n 5000` is unreliable at high throughput.

5. **Reconnect strategy**: frontend uses exponential backoff (1 s → 2 s → 4 s → max 30 s). Shows a "Reconnecting…" overlay on the cockpit panel. Last received frame data is preserved and shown grayed out during reconnect.

6. **Multi-cluster**: the `cluster_status` frame contains a `clusters` array. Show one section per cluster in the Cluster Status tab, each with its own Pool/Node breakdown and LB stats.

7. **Sparklines**: `recharts` is already in frontend dependencies. Feed `timeseries_10s_buckets` from the throughput frame directly into a `<LineChart>` with two lines (PUT teal, GET blue).

---

## Additional Lifecycle Bugs Found During Testing

**BUG L1 — Start/Stop/Destroy status not tracked (P0) — FIXED**
Root cause: frontend optimistically set status ("running"/"stopped") immediately after receiving 202, then `fetchDemos()` overrode it with the actual backend status ("deploying"), leaving the UI in an amber "Deploying…" state for the full task duration. Fix: all three handlers now poll the task endpoint (`/task/{task_id}`) at 1 s intervals and only update status on confirmed completion, matching how deploy works.

**BUG L2 — No concurrent operation guard on stop/start/destroy (P0) — FIXED**
Root cause: only the `/deploy` endpoint had `is_operation_running` check; `/stop`, `/start`, `/destroy` had none. Fix: 409 guard added to all three endpoints in `deploy.py`.

**BUG L3 — Instances tab skips polling when stopped (P1) — FIXED**
Root cause: `ControlPlane.tsx` had `if (activeDemo?.status === "stopped") return;` based on incorrect assumption that `/instances` returns 404 when stopped. It doesn't — `pause_demo` preserves running state in memory. Fix: polling continues when stopped (at 10 s rate instead of 5 s); only skips when `not_deployed` (destroy path, which actually does remove state). Empty-state message is now context-aware.

**BUG L4 — Save + Save as Template visible during transitions (P1) — FIXED**
Root cause: conditions excluded `running` and `stopped` but not `deploying` or `stopping`. Fix: both conditions extended to also exclude `deploying` and `stopping`.

**BUG L5 — IP addresses disappear after Stop (P2) — OPEN**
Network badges show "default (192.168.117.3)" when running, but just "default" after stop. The live Docker IP lookup fails on exited containers and falls back to static config (which has no IP). Fix: preserve last-known IP in `RunningContainer` state and use it as fallback when live lookup fails.
