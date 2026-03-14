# DemoForge -- Phase 3, 4, and 5 Execution Plan

Produced from a full codebase audit on 2026-03-13.
Covers: reliability hardening, advanced MinIO features, and experience/sharing.

---

## 0. Pre-Phase: Critical Bug Fixes

These must be resolved before any new feature work. They affect deploy reliability and data integrity.

### BUG-1: NGINX template upstream direction is inverted (S)

**File**: `components/nginx/templates/nginx.conf.j2:4-6`
**Problem**: Template checks `edge.target == node.id` for load-balance edges, but in the active-active template the edge goes FROM nginx TO minio (`source: nginx-lb`). The upstream pool will always be empty, falling back to the `127.0.0.1:9000` placeholder.
**Fix**: Change condition to `edge.source == node.id` for outbound connection types (load-balance, http), or check both directions.

### BUG-2: Init script results are discarded, init_status hardcoded (S)

**Files**: `backend/app/engine/docker_manager.py:61`, `backend/app/api/instances.py:87`
**Problem**: `run_init_scripts()` return value is dropped. `init_status` is always `"completed"`.
**Fix**: Store init results in `RunningDemo` or `RunningContainer`. Return actual status in the instances API.

### BUG-3: No state recovery after backend restart (M)

**File**: `backend/app/state/store.py`
**Problem**: Comment claims re-discovery via labels, but no such logic exists. Backend restart orphans all running demos.
**Fix**: On startup, query Docker for containers with `demoforge.*` labels. Rebuild `RunningDemo` entries. Re-join networks.

### BUG-4: Node ID counter resets on page reload (S)

**File**: `frontend/src/components/canvas/DiagramCanvas.tsx:21`
**Problem**: `let nodeCounter = 0` resets on reload, creating ID collisions with existing nodes.
**Fix**: Derive counter from existing node IDs when loading a demo (e.g., `Math.max(...nodes.map(n => parseInt(n.id.split('-').pop()) || 0)) + 1`).

### BUG-5: Grafana secret keys mismatch environment keys (S)

**File**: `components/grafana/manifest.yaml:37-42`
**Problem**: Secrets use `GF_ADMIN_USER`/`GF_ADMIN_PASSWORD` but env uses `GF_SECURITY_ADMIN_USER`/`GF_SECURITY_ADMIN_PASSWORD`. Credential display shows wrong values.
**Fix**: Change secret keys to `GF_SECURITY_ADMIN_USER` and `GF_SECURITY_ADMIN_PASSWORD`.

### BUG-6: Deploy endpoint swallows exceptions without logging (S)

**File**: `backend/app/api/deploy.py:24-28`
**Problem**: All exceptions are caught and returned as a generic error string. No logging, no traceback.
**Fix**: Add `logger.exception()` before returning. Include error category (docker, network, init) in response.

### BUG-7: No cleanup on partial deploy failure (M)

**File**: `backend/app/engine/docker_manager.py:29-64`
**Problem**: If compose up succeeds but network join or init scripts fail, containers are left running in "error" state with no rollback.
**Fix**: Wrap post-compose steps in try/except. On failure, run compose down before re-raising. Set state to "error" with details.

### BUG-8: Terminal panel tab duplication (S)

**File**: `frontend/src/components/terminal/TerminalPanel.tsx:30`
**Problem**: `allTabs` merges `tabs` and `extraTabs` but the useEffect at line 19 already pushes extraTabs into tabs, creating potential duplicates.
**Fix**: Remove the `allTabs` computed variable; use `tabs` directly since the useEffect already handles merging.

**Pre-Phase Effort**: ~3-4 days for all 8 fixes.

---

## Phase 3: Demo Polish and Reliability

**Goal**: Make deployments work reliably end-to-end. An SE should be able to click Deploy, watch it happen, see errors clearly, and trust that the system is in the state it says it is.

**Timeline**: 2-3 weeks
**Parallel Streams**: 2 (Backend reliability, Frontend feedback)

---

### Stream 1: Backend Reliability

#### 3.1 Deploy Event Stream (M)

**What**: Replace the synchronous deploy response with a Server-Sent Events (SSE) or WebSocket stream that reports each deploy step in real-time: pulling images, creating networks, starting containers, running init scripts, final status.
**Files to modify**:
- `backend/app/api/deploy.py` -- add SSE endpoint `/api/demos/{demo_id}/deploy/stream`
- `backend/app/engine/docker_manager.py` -- accept a callback/queue for step reporting
**Dependencies**: None
**Effort**: M (3-4 days)
**Risk**: SSE connection management; need heartbeat to detect dropped clients.

#### 3.2 Container Log Streaming (M)

**What**: Add a WebSocket endpoint that streams `docker logs --follow` output for a given container. Frontend can show live logs in a panel alongside or instead of the terminal.
**Files to modify**:
- New: `backend/app/api/logs.py` -- WebSocket endpoint
- New: `backend/app/engine/log_streamer.py` -- subprocess wrapper for `docker logs -f`
- `backend/app/main.py` -- register router
**Dependencies**: None
**Effort**: M (2-3 days)
**Risk**: Memory if logs are large; need line-count limits and disconnect handling.

#### 3.3 Container Status Polling Hardening (S)

**What**: The health monitor at `backend/app/engine/health_monitor.py` is a bare infinite loop with no error handling. A single Docker API timeout will crash the loop silently.
**Files to modify**:
- `backend/app/engine/health_monitor.py` -- add try/except per container, add logging, add exponential backoff on Docker API errors
- `backend/app/engine/docker_manager.py:88-106` -- add try/except around `docker_client.containers.get()` for transient Docker socket errors
**Dependencies**: None
**Effort**: S (1 day)
**Risk**: Low.

#### 3.4 State Recovery on Startup (M)

**What**: Query Docker on backend startup for containers with `demoforge.*` labels. Rebuild `RunningDemo` entries, re-join networks, resume health monitoring.
**Files to modify**:
- New: `backend/app/engine/state_recovery.py`
- `backend/app/main.py` -- call recovery in lifespan startup
- `backend/app/state/store.py` -- no structural changes needed
**Dependencies**: None (but resolves BUG-3)
**Effort**: M (2-3 days)
**Risk**: Edge case where compose file is deleted but containers remain. Need to handle gracefully.

#### 3.5 Structured Error Responses (S)

**What**: Replace bare string error messages with structured error codes and details. Frontend can show actionable messages ("Docker daemon not reachable" vs "Component minio not found in registry").
**Files to modify**:
- `backend/app/models/api_models.py` -- add `ErrorDetail` model with `code`, `message`, `details`
- `backend/app/api/deploy.py` -- categorize errors
- `backend/app/api/instances.py` -- wrap Docker errors
**Dependencies**: None
**Effort**: S (1 day)
**Risk**: Low.

#### 3.6 Demo Deletion Safety (S)

**What**: `backend/app/api/demos.py:108-113` allows deleting a demo YAML even while it is running. This orphans containers.
**Fix**: Check state store; if demo is running, require stop first (or auto-stop then delete).
**Dependencies**: None
**Effort**: S (0.5 days)
**Risk**: Low.

---

### Stream 2: Frontend Feedback

#### 3.7 Deploy Progress Panel (M)

**What**: Show a deploy progress UI: steps (pulling, starting, init), per-container status, live log lines. Consumes the SSE stream from 3.1.
**Files to modify**:
- New: `frontend/src/components/deploy/DeployProgress.tsx`
- `frontend/src/stores/demoStore.ts` -- add deploy events state
- `frontend/src/api/client.ts` -- add SSE client helper
- `frontend/src/components/toolbar/Toolbar.tsx` -- show progress panel on deploy
**Dependencies**: 3.1 (deploy event stream)
**Effort**: M (3-4 days)
**Risk**: UX complexity; need clear "done" vs "still going" states.

#### 3.8 Log Viewer Panel (M)

**What**: A panel (tab alongside terminal) that shows container stdout/stderr. Uses WebSocket from 3.2.
**Files to modify**:
- New: `frontend/src/components/logs/LogViewer.tsx`
- `frontend/src/components/control-plane/ComponentCard.tsx` -- add "Logs" button
- `frontend/src/api/client.ts` -- add log stream URL helper
**Dependencies**: 3.2 (log streaming endpoint)
**Effort**: M (2-3 days)
**Risk**: Performance with high log volume; need virtual scrolling.

#### 3.9 Toast/Notification System (S)

**What**: Global toast notifications for deploy success/failure, restart confirmations, save errors. Currently errors are silently swallowed (`.catch(() => {})` appears 5+ times in the frontend).
**Files to modify**:
- New: `frontend/src/components/ui/toast.tsx` (shadcn/ui has a toast component)
- `frontend/src/components/toolbar/Toolbar.tsx` -- replace silent catches
- `frontend/src/components/canvas/DiagramCanvas.tsx` -- surface save errors
- `frontend/src/components/control-plane/ControlPlane.tsx` -- surface fetch errors
**Dependencies**: None
**Effort**: S (1-2 days)
**Risk**: Low.

#### 3.10 Resource Usage Display (S)

**What**: The `ContainerInstance` model already has a `resource_usage` field (`backend/app/models/api_models.py:83`) but it is never populated. Add Docker stats collection and display memory/CPU per container in the Control Plane.
**Files to modify**:
- `backend/app/engine/docker_manager.py` -- add `get_container_stats()` using Docker stats API
- `backend/app/api/instances.py` -- populate `resource_usage` in the response
- `frontend/src/components/control-plane/ComponentCard.tsx` -- display stats
**Dependencies**: None
**Effort**: S (1-2 days)
**Risk**: Docker stats API can be slow; consider caching.

#### 3.11 Connection Type Picker on Edge Creation (S)

**What**: When the user draws an edge, there is no way to choose the connection type. It defaults to `"data"` (`frontend/src/stores/diagramStore.ts:32`). Add a dropdown or dialog after edge creation to pick from the valid connection types based on source/target component manifests.
**Files to modify**:
- `frontend/src/stores/diagramStore.ts` -- modify `onConnect` to trigger a type picker
- New: `frontend/src/components/canvas/edges/EdgeTypeDialog.tsx`
- `frontend/src/components/canvas/DiagramCanvas.tsx` -- integrate dialog
**Dependencies**: None
**Effort**: S (1-2 days)
**Risk**: Low.

---

### Phase 3 Dependency Graph

```
[3.1 Deploy SSE]  -->  [3.7 Deploy Progress Panel]
[3.2 Log Stream]  -->  [3.8 Log Viewer Panel]

Independent (can run in parallel):
  3.3 Health polling hardening
  3.4 State recovery
  3.5 Structured errors
  3.6 Deletion safety
  3.9 Toast system
  3.10 Resource usage
  3.11 Connection type picker
```

---

## Phase 4: Advanced MinIO Features

**Goal**: Automate the MinIO SE demo scenarios that matter: site replication, bucket policies, SSE (encryption), versioning, and IAM. An SE should be able to demo these features without manually running mc commands.

**Timeline**: 3-4 weeks
**Parallel Streams**: 2 (Backend automation, Component enhancements)

---

### Stream 1: MinIO Automation Engine

#### 4.1 MinIO Admin Client Library (M)

**What**: A Python wrapper around MinIO's Admin API (or `mc admin` CLI) that can be called from init scripts or on-demand via the API. Handles alias setup, health checks, and credential management.
**Files to add**:
- `backend/app/engine/minio_admin.py` -- wraps `mc` commands via docker exec
- Functions: `setup_alias()`, `get_server_info()`, `add_replication_rule()`, `set_bucket_policy()`, `enable_versioning()`, `configure_sse()`
**Dependencies**: None
**Effort**: M (3-4 days)
**Risk**: mc CLI output parsing is fragile. Consider using the JSON output flag (`--json`).

#### 4.2 Site Replication Setup Automation (L)

**What**: When the user draws a "replication" edge between two MinIO nodes, DemoForge should automatically configure site replication after deploy. Currently the replication-source/replication-target variants exist but do nothing beyond starting MinIO.
**Files to modify**:
- `components/minio/manifest.yaml` -- add init scripts for replication setup using mc
- New: `components/minio/templates/replication-init.sh.j2` -- Jinja2 template that generates the mc commands based on topology
- `backend/app/engine/init_runner.py` -- support init scripts that reference other nodes by hostname
**Dependencies**: 4.1 (MinIO admin library)
**Effort**: L (4-5 days)
**Risk**: Replication setup requires both nodes healthy first. Order-dependent init. Need retry logic. MinIO site replication requires all sites to be added in a single `mc admin replicate add` call.

#### 4.3 Bucket Policy Presets (M)

**What**: Add a "bucket policies" section to the MinIO properties panel. Presets: public-read, write-only, read-write, custom JSON. Applied via mc after deploy.
**Files to modify**:
- `components/minio/manifest.yaml` -- add policy preset definitions
- `backend/app/api/instances.py` or new `backend/app/api/minio_actions.py` -- API endpoint for applying policies
- `frontend/src/components/properties/PropertiesPanel.tsx` -- add bucket policy UI when a MinIO node is selected
**Dependencies**: 4.1
**Effort**: M (2-3 days)
**Risk**: Low.

#### 4.4 SSE (Server-Side Encryption) Configuration (M)

**What**: Add SSE-S3 and SSE-KMS configuration options. For demo purposes, SSE-S3 with auto-encryption is simplest. Add environment variables and init script to enable it.
**Files to modify**:
- `components/minio/manifest.yaml` -- add SSE-related environment variables and init script
- `frontend/src/components/properties/PropertiesPanel.tsx` -- SSE toggle in MinIO properties
**Dependencies**: 4.1
**Effort**: M (2-3 days)
**Risk**: KMS setup requires a separate KES/Vault container. Start with SSE-S3 only. KMS can be Phase 5.

#### 4.5 Versioning Configuration (S)

**What**: Toggle versioning per bucket via the properties panel. Applied via `mc version enable`.
**Files to modify**:
- `backend/app/api/minio_actions.py` -- versioning endpoint
- `frontend/src/components/properties/PropertiesPanel.tsx` -- versioning toggle
**Dependencies**: 4.1
**Effort**: S (1 day)
**Risk**: Low.

#### 4.6 IAM User/Policy Demo Setup (M)

**What**: Pre-create demo IAM users with specific policies (read-only, write-only, admin). SEs frequently demo IAM capabilities.
**Files to modify**:
- `components/minio/manifest.yaml` -- add IAM init scripts
- New: `components/minio/templates/iam-setup.sh.j2`
- `frontend/src/components/control-plane/ComponentCard.tsx` -- show IAM credentials
**Dependencies**: 4.1
**Effort**: M (2-3 days)
**Risk**: Low.

---

### Stream 2: Component Enhancements

#### 4.7 MinIO AIStore Image Support (S)

**What**: Backlog item. Switch from `minio/minio:latest` to the AIStore image. May need different command flags.
**Files to modify**:
- `components/minio/manifest.yaml` -- update image, add AIStore variant
**Dependencies**: None
**Effort**: S (0.5 days)
**Risk**: Need to verify AIStore image compatibility with existing health checks and init scripts.

#### 4.8 KES (Key Encryption Service) Component (M)

**What**: New component manifest for MinIO KES. Required for SSE-KMS demos.
**Files to add**:
- `components/kes/manifest.yaml`
- `components/kes/templates/` -- config templates
**Dependencies**: None (but enables full SSE-KMS in 4.4)
**Effort**: M (2-3 days)
**Risk**: KES configuration is non-trivial; needs TLS certs generated at deploy time.

#### 4.9 mc CLI Sidecar Component (S)

**What**: A lightweight container with mc pre-installed and pre-aliased to all MinIO nodes in the demo. Useful for SEs to show mc commands without SSH-ing into MinIO containers.
**Files to add**:
- `components/mc-client/manifest.yaml`
- `components/mc-client/templates/aliases.sh.j2`
**Dependencies**: None
**Effort**: S (1-2 days)
**Risk**: Low.

#### 4.10 Traffic Generator Component (M)

**What**: A container that generates synthetic S3 traffic (PUTs, GETs, deletes) to demonstrate replication, monitoring dashboards, and load balancing. Configurable rate and object sizes.
**Files to add**:
- `components/traffic-gen/manifest.yaml`
- `components/traffic-gen/Dockerfile` -- simple Python/Go script using boto3/minio-go
- `components/traffic-gen/templates/config.yaml.j2`
**Dependencies**: 4.1 (needs target MinIO endpoints from topology)
**Effort**: M (3-4 days)
**Risk**: Resource usage on laptops; needs configurable rate limits.

---

### Phase 4 Dependency Graph

```
[4.1 MinIO Admin Library] --> [4.2 Site Replication]
                          --> [4.3 Bucket Policies]
                          --> [4.4 SSE Config]
                          --> [4.5 Versioning]
                          --> [4.6 IAM Setup]

Independent:
  4.7 AIStore image
  4.8 KES component
  4.9 mc CLI sidecar
  4.10 Traffic generator
```

---

## Phase 5: Experience and Sharing

**Goal**: Make DemoForge a tool SEs love to use daily. Export/import demos, guided walkthroughs, snapshots, and lightweight collaboration.

**Timeline**: 3-4 weeks
**Parallel Streams**: 3 (Export/Import, Guided Walkthroughs, Platform)

---

### Stream 1: Demo Export/Import

#### 5.1 Demo Export as Portable Archive (M)

**What**: Export a demo as a `.demoforge` archive (ZIP containing the demo YAML, all referenced component manifests, templates, and optionally Docker images as tarballs). Another SE can import it on their laptop.
**Files to add**:
- `backend/app/api/export.py` -- GET `/api/demos/{id}/export` returns ZIP
- `backend/app/engine/archive.py` -- build the archive
**Dependencies**: None
**Effort**: M (3-4 days)
**Risk**: Including Docker images makes archives very large. Default to manifest-only (images pulled on import). Add opt-in `include_images=true`.

#### 5.2 Demo Import (M)

**What**: Upload a `.demoforge` archive, extract, register any new components, create the demo.
**Files to add**:
- `backend/app/api/import_.py` -- POST `/api/demos/import` with file upload
- Frontend upload dialog
**Dependencies**: 5.1
**Effort**: M (2-3 days)
**Risk**: Component version conflicts if imported manifest differs from local registry. Need merge strategy.

#### 5.3 Demo Snapshots (Checkpoint/Restore) (L)

**What**: Save the current state of a running demo (container data volumes, bucket contents) as a named snapshot. Restore to a snapshot to reset demo state between customer calls.
**Files to add**:
- `backend/app/engine/snapshot.py` -- uses `docker commit` or volume backup
- `backend/app/api/snapshots.py` -- CRUD endpoints
- Frontend snapshot management UI
**Dependencies**: None
**Effort**: L (5-7 days)
**Risk**: Volume snapshot is Docker-driver dependent. May need to copy data to a tarball. Large data volumes will be slow.

---

### Stream 2: Guided Walkthroughs

#### 5.4 Demo Template Library (M)

**What**: Expand from 1 template to 5+. Each template targets a specific SE demo scenario.
Templates to create:
1. Single MinIO with monitoring (beginner)
2. Active-active replication (existing, needs fix)
3. Multi-tier: NGINX -> MinIO -> Prometheus -> Grafana
4. SSE-KMS: MinIO + KES with encryption
5. Distributed erasure coding (4-node MinIO cluster)
**Dependencies**: Phase 4 components (KES, traffic-gen)
**Effort**: M (3-4 days for all templates)
**Risk**: Templates must be validated against current component manifests.

#### 5.5 Step-by-Step Walkthrough Engine (L)

**What**: Attach a walkthrough script to a demo template. Each step has: description, expected action (click deploy, open terminal, run command), validation (check health, check bucket exists). The UI highlights the next step and validates completion.
**Files to add**:
- New model: `DemoWalkthrough` with steps
- `backend/app/api/walkthroughs.py`
- `frontend/src/components/walkthrough/WalkthroughPanel.tsx`
- `frontend/src/components/walkthrough/WalkthroughStep.tsx`
**Dependencies**: 5.4 (templates to attach walkthroughs to)
**Effort**: L (5-7 days)
**Risk**: Validation logic is scenario-specific. Start with manual "mark as done" and add auto-validation incrementally.

#### 5.6 Annotated Diagram Mode (M)

**What**: Allow SEs to add text annotations and callout boxes to the diagram canvas. These are visible during demos to explain architecture to customers.
**Files to modify**:
- `frontend/src/stores/diagramStore.ts` -- add annotation nodes
- New: `frontend/src/components/canvas/nodes/AnnotationNode.tsx`
- `backend/app/models/demo.py` -- add annotations field to DemoDefinition
**Dependencies**: None
**Effort**: M (2-3 days)
**Risk**: Low. React Flow supports custom node types natively.

---

### Stream 3: Platform Improvements

#### 5.7 Demo List Dashboard (M)

**What**: Replace the simple dropdown in the toolbar with a proper dashboard page. Show all demos as cards with status, last modified, node count, template origin, and quick actions (deploy, stop, delete, export).
**Files to add**:
- `frontend/src/components/dashboard/DemoDashboard.tsx`
- `frontend/src/components/dashboard/DemoCard.tsx`
**Dependencies**: None
**Effort**: M (2-3 days)
**Risk**: Low.

#### 5.8 Settings/Preferences Page (S)

**What**: Configure: Docker socket path, default resource limits, proxy port, data directory. Currently all config is via environment variables which is unfriendly for SEs.
**Files to add**:
- `backend/app/api/settings.py`
- `frontend/src/components/settings/SettingsPage.tsx`
**Dependencies**: None
**Effort**: S (1-2 days)
**Risk**: Low.

#### 5.9 Offline Mode / Pre-Pull Images (M)

**What**: SEs demo at customer sites with unreliable internet. Add a "pre-pull images" action that downloads all component images ahead of time. Show pull status. Deploy should work fully offline after pre-pull.
**Files to add**:
- `backend/app/api/images.py` -- list required images, pull status, trigger pull
- `frontend/src/components/settings/ImageManager.tsx`
**Dependencies**: None
**Effort**: M (2-3 days)
**Risk**: Pull progress reporting from Docker API is complex (layer-by-layer). Consider polling.

#### 5.10 Multi-Demo Isolation (M)

**What**: Currently the backend can technically track multiple demos but the frontend only shows one at a time with the `activeDemoId` state. Allow multiple demos to be deployed simultaneously with proper network isolation (already supported by the compose project naming) and add a status indicator per demo in the dashboard.
**Files to modify**:
- `frontend/src/stores/demoStore.ts` -- track per-demo status independently
- `frontend/src/components/toolbar/Toolbar.tsx` -- show active/inactive indicators
- `backend/app/engine/network_manager.py` -- verify no network name collisions
**Dependencies**: 5.7 (dashboard)
**Effort**: M (2-3 days)
**Risk**: Laptop resource constraints with multiple demos. Need resource budget warnings.

---

### Phase 5 Dependency Graph

```
[5.1 Export] --> [5.2 Import]
[5.4 Template Library] --> [5.5 Walkthrough Engine]

Independent:
  5.3 Snapshots
  5.6 Annotated diagrams
  5.7 Dashboard
  5.8 Settings
  5.9 Offline mode
  5.10 Multi-demo isolation
```

---

## Effort Summary

| ID | Task | Effort | Phase |
|----|------|--------|-------|
| BUG-1 | NGINX template direction fix | S | Pre |
| BUG-2 | Init script result tracking | S | Pre |
| BUG-3 | State recovery (startup) | M | Pre |
| BUG-4 | Node ID counter fix | S | Pre |
| BUG-5 | Grafana secret key mismatch | S | Pre |
| BUG-6 | Deploy error logging | S | Pre |
| BUG-7 | Partial deploy rollback | M | Pre |
| BUG-8 | Terminal tab duplication | S | Pre |
| 3.1 | Deploy event stream (SSE) | M | 3 |
| 3.2 | Container log streaming | M | 3 |
| 3.3 | Health polling hardening | S | 3 |
| 3.4 | State recovery on startup | M | 3 |
| 3.5 | Structured error responses | S | 3 |
| 3.6 | Demo deletion safety | S | 3 |
| 3.7 | Deploy progress panel (FE) | M | 3 |
| 3.8 | Log viewer panel (FE) | M | 3 |
| 3.9 | Toast notification system | S | 3 |
| 3.10 | Resource usage display | S | 3 |
| 3.11 | Connection type picker | S | 3 |
| 4.1 | MinIO admin client library | M | 4 |
| 4.2 | Site replication automation | L | 4 |
| 4.3 | Bucket policy presets | M | 4 |
| 4.4 | SSE configuration | M | 4 |
| 4.5 | Versioning configuration | S | 4 |
| 4.6 | IAM user/policy setup | M | 4 |
| 4.7 | AIStore image support | S | 4 |
| 4.8 | KES component | M | 4 |
| 4.9 | mc CLI sidecar | S | 4 |
| 4.10 | Traffic generator | M | 4 |
| 5.1 | Demo export | M | 5 |
| 5.2 | Demo import | M | 5 |
| 5.3 | Demo snapshots | L | 5 |
| 5.4 | Template library (5+) | M | 5 |
| 5.5 | Walkthrough engine | L | 5 |
| 5.6 | Annotated diagram mode | M | 5 |
| 5.7 | Demo dashboard | M | 5 |
| 5.8 | Settings page | S | 5 |
| 5.9 | Offline / pre-pull images | M | 5 |
| 5.10 | Multi-demo isolation | M | 5 |

**Effort key**: S = 0.5-2 days, M = 2-4 days, L = 4-7 days

---

## Risk Registry

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Docker socket unavailable on deploy | Deploy fails silently | Medium | Phase 3 structured errors + pre-flight check |
| Laptop resource exhaustion (multi-node demos) | Containers OOM-killed | High | Resource budgets in 3.10; warnings in 5.10 |
| MinIO site replication requires specific ordering | Replication setup fails | High | Retry logic in 4.2; health-gate before replication init |
| Offline demo at customer site | Image pull fails | High | 5.9 pre-pull; fall back to cached images |
| Template drift from manifest changes | Templates break on deploy | Medium | CI validation of templates against manifests |
| Large volume snapshots slow on HDD laptops | Snapshot takes minutes | Medium | Incremental snapshots; warn on large volumes |
| SSE-KMS requires TLS cert generation | Complex setup | Medium | Auto-generate self-signed certs in KES init script |

---

## Recommended Execution Order

1. **Pre-Phase** (week 0): Fix all 8 bugs. Ship a patch release.
2. **Phase 3** (weeks 1-3): Reliability. Two parallel streams. Culminates in "Deploy and it just works."
3. **Phase 4** (weeks 4-7): MinIO features. Start with 4.1 (admin library) as the keystone. 4.7 (AIStore) can ship immediately.
4. **Phase 5** (weeks 8-11): Experience. 5.1/5.2 (export/import) and 5.7 (dashboard) are highest ROI for SE adoption.

Within each phase, items without upstream dependencies can be parallelized freely. The dependency graphs above show the critical paths.
