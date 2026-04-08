# Claude Code — MinIO Cluster: Erasure Coding, Cockpit Status & Drive Failure Simulation

**Status:** DONE — Phases 1–3 implemented 2026-04-08. Phase 4 (validation) pending FA testing.

---

## Context

The MinIO cluster component in DemoForge currently supports configuring nodes and drives per node. This instruction file extends it with:

1. Erasure coding (EC) parity configuration in the cluster properties panel
2. Disk size per node + derived usable capacity (info-only display)
3. Cockpit cluster health panel using real `mc admin` commands
4. Drive/node failure simulation to demo MinIO resilience

All changes must integrate with the existing component manifest schema, canvas properties panel, Docker Compose generation, and cockpit infrastructure.

---

## Phase 0 — Codebase Investigation

**Do not write any code in this phase.** Read the codebase and produce a summary for the architect to review before proceeding.

### 0.1 Investigate the MinIO cluster component

```
1. Find the minio-cluster component manifest YAML
   - Where are `nodes` and `drives_per_node` defined?
   - What are their current options and defaults?
   - What other config fields exist (root user/pass, console port, etc.)?

2. Find the cluster properties panel in the React frontend
   - Which component renders the nodes/drives selectors?
   - How do config field changes propagate to the store (Zustand)?
   - Is there an existing pattern for derived/computed read-only fields?
   - Is there an existing pattern for info-only display sections in the panel?

3. Find the Docker Compose generation code
   - Where does the `server http://minio{1...N}/data{1...D}` command get built?
   - Where are environment variables for minio containers assembled?
   - How are volumes generated (one per node × drive)?
   - Is there already a `MINIO_STORAGE_CLASS_STANDARD` env var being set?

4. Find the cockpit infrastructure
   - Does a cockpit panel exist for the minio-cluster component?
   - Is there an existing API route pattern for component-specific endpoints?
   - Is there an mc (minio-client) sidecar container already in the compose output?
   - How does the cockpit poll for live data (WebSocket, SSE, polling interval)?

5. Check the mc-client sidecar
   - Is `mc` available in any container in the current compose output?
   - If a dedicated mc sidecar exists, what alias is configured?
   - If not, where should it be added?

6. Check failure simulation precedent
   - Is there any existing mechanism for runtime container manipulation (exec, stop, start)?
   - Does the backend have Docker SDK or subprocess-based Docker access?
   - Are there any existing "action" buttons in the cockpit that modify running containers?
```

### 0.2 Produce investigation summary

Write a summary covering:

- File paths for each item above
- Current manifest field schema (copy the relevant YAML section)
- Current compose generation logic (copy the relevant function/method)
- Gaps: what exists vs what needs to be built
- Any conflicts or constraints discovered

**Stop here. Present the summary for architect review before proceeding to Phase 1.**

---

## Phase 1 — Erasure Coding Configuration in Cluster Properties

### 1.1 Add fields to the component manifest

Add these fields to the minio-cluster manifest, in the same `config` section as `nodes` and `drives_per_node`.

**First, extend the existing fields:**

- `nodes` options: add `6` → final options: `[4, 6, 8, 16]`
- `drives_per_node` options: add `6` → final options: `[4, 6, 8, 12, 16]`

The 6-node option is important because it produces 12-drive erasure sets (with 4 or 6 drives per node), giving a symmetric EC:6 config (6 data + 6 parity). This is a common real-world deployment topology.

**Then add these new fields:**

**`ec_parity`** — Erasure coding parity level:
- Type: select
- Label: "EC parity"
- Options: dynamically computed from erasure set size (see 1.2)
- Default: auto-set to MinIO default for the erasure set size (see 1.3)
- Description: "Number of parity shards per erasure set. Higher = more fault tolerance, less usable capacity."

**`ec_parity_upgrade_policy`** — Behavior when writing to degraded erasure sets:
- Type: select
- Label: "Parity upgrade policy"
- Options: `["upgrade", "ignore"]`
- Default: `"upgrade"`
- Description: "upgrade: auto-increase parity when drives are offline. ignore: keep configured parity."

**`disk_size_tb`** — Size of each disk (info/planning only):
- Type: select
- Label: "Disk size per node"
- Options: `[1, 2, 4, 8, 16, 32]` (in TB)
- Default: 8
- Description: "Simulated disk capacity for capacity planning display. Does not affect the actual demo containers."

### 1.2 Dynamic EC parity options

The valid EC parity range depends on the erasure set size. MinIO computes erasure set size as the largest divisor of total drives that falls between 2 and 16.

Implement a utility function:

```
function computeErasureSetSize(totalDrives: number): number
  // Find the largest divisor of totalDrives where 2 <= divisor <= 16
  // For our configs this almost always returns 16 or the totalDrives itself

function computeECOptions(erasureSetSize: number): { value: number, label: string, isDefault: boolean }[]
  // Valid parity: EC:2 through EC:(erasureSetSize / 2)
  // MinIO defaults:
  //   set size <= 5:  EC:2
  //   set size 6-7:   EC:3
  //   set size >= 8:  EC:4
  // Mark the default with "(recommended)" in the label
```

Reference table for validation:

| Nodes | Drives/Node | Total | Erasure Set Size | EC Range     | Default | Notes |
|-------|-------------|-------|------------------|--------------|---------|-------|
| 4     | 4           | 16    | 16               | EC:2 – EC:8  | EC:4    | |
| 4     | 6           | 24    | 12               | EC:2 – EC:6  | EC:4    | 12-drive set |
| 4     | 8           | 32    | 16               | EC:2 – EC:8  | EC:4    | |
| 4     | 12          | 48    | 16               | EC:2 – EC:8  | EC:4    | |
| 4     | 16          | 64    | 16               | EC:2 – EC:8  | EC:4    | |
| 6     | 4           | 24    | 12               | EC:2 – EC:6  | EC:4    | 12-drive set |
| 6     | 6           | 36    | 12               | EC:2 – EC:6  | EC:4    | 12-drive set, 3 sets |
| 6     | 8           | 48    | 16               | EC:2 – EC:8  | EC:4    | |
| 6     | 12          | 72    | 12               | EC:2 – EC:6  | EC:4    | 12-drive set, 6 sets |
| 6     | 16          | 96    | 16               | EC:2 – EC:8  | EC:4    | |
| 8     | 4           | 32    | 16               | EC:2 – EC:8  | EC:4    | |
| 8     | 6           | 48    | 16               | EC:2 – EC:8  | EC:4    | |
| 8     | 8           | 64    | 16               | EC:2 – EC:8  | EC:4    | |
| 8     | 12          | 96    | 16               | EC:2 – EC:8  | EC:4    | |
| 8     | 16          | 128   | 16               | EC:2 – EC:8  | EC:4    | |
| 16    | 4           | 64    | 16               | EC:2 – EC:8  | EC:4    | |
| 16    | 6           | 96    | 16               | EC:2 – EC:8  | EC:4    | |
| 16    | 8           | 128   | 16               | EC:2 – EC:8  | EC:4    | |
| 16    | 12          | 192   | 16               | EC:2 – EC:8  | EC:4    | |
| 16    | 16          | 256   | 16               | EC:2 – EC:8  | EC:4    | |

**Important — 12-drive erasure sets:** Configs where total drives are divisible by 12 but not by 16 (e.g., 6×4=24, 6×6=36, 6×12=72) produce 12-drive erasure sets. These have a max parity of EC:6 (6 data + 6 parity = 50/50 symmetric split). The EC dropdown must reflect this — if a user switches from 8 nodes (16-drive sets, EC:8 available) to 6 nodes with 4 drives (12-drive sets), and EC:8 was selected, reset to EC:4 (the default).

When `nodes` or `drives_per_node` changes:
1. Recompute erasure set size
2. Recompute valid EC options
3. If current `ec_parity` is outside the new valid range, reset to the default
4. Recompute all derived values (see 1.3)

### 1.3 Derived capacity display (info-only panel section)

Add a read-only info section below the config fields in the cluster properties panel. This section is **display only** — not editable, not stored in the manifest. It recalculates live as the user changes any config field.

Calculations:

```
total_drives       = nodes × drives_per_node
erasure_set_size   = computeErasureSetSize(total_drives)
num_erasure_sets   = total_drives / erasure_set_size
data_shards        = erasure_set_size - ec_parity
usable_ratio       = data_shards / erasure_set_size
raw_capacity_tb    = total_drives × disk_size_tb
usable_capacity_tb = raw_capacity_tb × usable_ratio
drive_tolerance    = ec_parity        // drives that can fail per erasure set
read_quorum        = data_shards      // = erasure_set_size - ec_parity
write_quorum       = data_shards      // +1 if ec_parity == erasure_set_size / 2
```

Display format — render as a compact info card with subtle styling (match existing info patterns in the properties panel):

```
┌─ Capacity & resilience ──────────────────────┐
│ Erasure sets       2 × 16 drives             │
│ Usable ratio       75% (12 data + 4 parity)  │
│ Raw capacity       128 TB                     │
│ Usable capacity    96 TB                      │
│ Drive tolerance    4 per erasure set          │
│ Read quorum        12 drives                  │
│ Write quorum       12 drives                  │
└──────────────────────────────────────────────┘
```

Follow whatever info/summary pattern already exists in the codebase. If none exists, use a muted background card (`bg-zinc-900/50` or similar in the zinc dark theme) with `text-sm text-zinc-400` labels and `text-zinc-200` values.

### 1.4 Docker Compose generation changes

In the compose generation code, add these environment variables to every MinIO container:

```yaml
environment:
  MINIO_STORAGE_CLASS_STANDARD: "EC:${ec_parity}"
  MINIO_STORAGE_CLASS_RRS: "EC:1"
  MINIO_STORAGE_CLASS_OPTIMIZE: "${ec_parity_upgrade_policy}"
```

These go alongside the existing `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, etc.

The server command already uses the ellipsis notation (`http://minio{1...N}/data{1...D}`) — this does not change. The EC config is purely via environment variables, which is how real MinIO clusters are configured.

### Validation — Phase 1

```
1. Change nodes to 4, drives to 4 — verify EC options show EC:2 through EC:8, default EC:4
2. Change nodes to 8, drives to 8 — verify same EC options (erasure set stays 16)
3. Change nodes to 6, drives to 4 — verify EC options show EC:2 through EC:6 (12-drive set)
4. Change nodes to 6, drives to 6 — verify EC:2 through EC:6, default EC:4
5. With 6×6 config, select EC:6 — verify derived display shows:
   - Usable ratio: 50% (6 data + 6 parity) — symmetric split
   - Drive tolerance: 6 per erasure set
6. Switch from 6×4 (EC:6 selected) to 8×4 — verify EC:6 is still valid (now 16-drive set, max EC:8)
7. Switch from 8×4 (EC:8 selected) to 6×4 — verify EC:8 is OUT OF RANGE (max EC:6), resets to EC:4
8. Change disk_size_tb to 16 with 6×6 config and EC:6 — verify:
   - Raw: 576 TB, Usable: 288 TB (50%)
9. Generate Docker Compose — verify MINIO_STORAGE_CLASS_STANDARD=EC:6 appears
   on all 6 minio service definitions
10. Deploy the generated compose — verify `mc admin info` shows EC:6
```

**Stop here. Confirm Phase 1 is working before proceeding to Phase 2.**

---

## Phase 2 — Cockpit Cluster Health Panel

### 2.1 mc sidecar container

If an `mc` sidecar container does not already exist in the compose output for minio-cluster, add one:

```yaml
mc:
  image: quay.io/minio/mc:latest
  entrypoint: /bin/sh
  command: >
    -c "
    mc alias set local http://minio1:9000 minioadmin minioadmin --api S3v4;
    while true; do sleep 3600; done
    "
  depends_on:
    - minio1
```

This container stays alive and is used by the backend to execute `mc admin` commands via `docker exec`.

### 2.2 Backend API endpoints

Add these endpoints to the FastAPI backend. Follow the existing router pattern discovered in Phase 0.

**GET `/api/cluster/{component_id}/health`**
- Executes: `docker exec {mc_container} mc admin info local --json`
- Returns: parsed JSON with per-node status, drive health, EC config, capacity
- Poll interval: frontend calls every 5 seconds

**GET `/api/cluster/{component_id}/healing`**
- Executes: `docker exec {mc_container} mc admin heal local --recursive --dry-run --json`
- Returns: healing summary (objects total, healed, remaining, estimated time)
- Only called when drives are offline or healing is active

**GET `/api/cluster/{component_id}/health/quick`**
- Executes: `curl -s -o /dev/null -w "%{http_code}" http://minio1:9000/minio/health/cluster`
- Returns: `{ "healthy": true/false, "http_code": 200/503 }`
- Lightweight check, can poll more frequently

### 2.3 Key mc commands reference

These are the real MinIO commands the backend wraps:

| Command | What it returns | Use in cockpit |
|---------|----------------|----------------|
| `mc admin info ALIAS --json` | Per-node uptime, version, network, drives, pool, EC config | Main dashboard |
| `mc admin heal ALIAS --recursive --dry-run --json` | Healing status: objects needing heal, progress | Healing progress |
| `mc admin object info ALIAS BUCKET/KEY` | Per-object shard status across drives | Object detail view |
| `curl :9000/minio/health/cluster` | HTTP 200 if write quorum, 503 if not | Quick health check |
| `curl :9000/minio/health/cluster?maintenance=true` | Checks if cluster survives losing this node | Pre-failure check |
| `curl :9000/minio/v2/metrics/cluster` | Prometheus metrics | Grafana integration |

JSON output structure from `mc admin info --json`:

```
response.info.servers[]              → node cards (endpoint, state, uptime)
response.info.servers[].drives[]     → per-drive status (path, state, totalSpace, usedSpace)
response.info.servers[].network      → peer reachability
response.info.erasure                → EC config (standardSCParity, rrsSCParity, sets[])
```

Drive states: `"ok"`, `"offline"`, `"healing"` — map to green, red, amber indicators.

### 2.4 Frontend cockpit panel

Add a "Cluster health" section to the minio-cluster cockpit. Key elements:

**Header bar:**
- EC badge: `EC:4` styled as a pill
- Drive count: `15/16 online` (green if all online, amber if degraded, red if below write quorum)
- Cluster status: `Healthy` / `Degraded` / `Write quorum lost`

**Node cards** (one per minio container, arranged in a row or grid):
- Node hostname (e.g., `minio1`)
- Uptime
- Drive indicators: small circles per drive — green=ok, red=offline, amber=healing
- Network: `4/4 peers`

**Erasure set summary** (below node cards):
- "2 erasure sets × 16 drives, EC:4"
- Capacity bar: used / total
- Fault tolerance: "Can lose 4 more drives per set"

**Healing panel** (conditionally rendered when healing is active):
- Progress bar with objects healed / remaining
- Estimated completion time
- Auto-refreshes while active

### Validation — Phase 2

```
1. Deploy a 4-node EC:4 cluster
2. Open the cockpit — verify the health panel shows:
   - EC:4 badge
   - 16/16 drives online (all green)
   - 4 node cards with correct hostnames
   - Capacity info
3. Manually fail a drive: docker exec minio1 chmod 000 /data3
4. Wait 10-15 seconds — verify the cockpit updates:
   - 15/16 drives
   - minio1 card shows 3/4 drives, one red indicator
   - Status changes to "Degraded"
5. Restore: docker exec minio1 chmod 755 /data3
6. Verify healing panel appears and shows progress
7. Verify cockpit returns to 16/16 once healing completes
```

**Stop here. Confirm Phase 2 is working before proceeding to Phase 3.**

---

## Phase 3 — Drive Failure Simulation

### 3.1 Why no CSI drivers are needed

MinIO treats each `/dataN` path as a separate drive. In our Docker setup these are Docker volumes mounted into the container. Drive failure can be simulated without any special infrastructure:

- `chmod 000 /dataN` inside the container → MinIO marks drive as offline (I/O error)
- `mv /dataN /dataN.offline` → MinIO sees path as gone
- `docker stop` → kills entire node, all its drives go offline

MinIO detects all of these within ~30 seconds, serves from remaining shards, and auto-heals on restore.

### 3.2 Backend simulation endpoints

Add these endpoints. They use `docker exec` and `docker stop/start` — confirm in Phase 0 that the backend has access to the Docker socket or equivalent.

**POST `/api/cluster/{component_id}/simulate/fail-drive`**
- Body: `{ "node": "minio1", "drive": "data3" }`
- Action: `docker exec {node_container} chmod 000 /{drive}`
- Returns: `{ "status": "drive_failed", "node": "minio1", "drive": "data3" }`

**POST `/api/cluster/{component_id}/simulate/restore-drive`**
- Body: `{ "node": "minio1", "drive": "data3" }`
- Action: `docker exec {node_container} chmod 755 /{drive}`
- Returns: `{ "status": "drive_restored", "node": "minio1", "drive": "data3" }`

**POST `/api/cluster/{component_id}/simulate/fail-node`**
- Body: `{ "node": "minio3" }`
- Action: `docker stop {node_container}`
- Returns: `{ "status": "node_stopped", "node": "minio3" }`

**POST `/api/cluster/{component_id}/simulate/restore-node`**
- Body: `{ "node": "minio3" }`
- Action: `docker start {node_container}`
- Returns: `{ "status": "node_started", "node": "minio3" }`

**POST `/api/cluster/{component_id}/simulate/restore-all`**
- Action: restores all currently failed drives and nodes
- Returns: list of all restored items

All failure endpoints should validate quorum impact before executing. Return a warning if the action would cause quorum loss:
```json
{ "warning": "This will cause write quorum loss. The cluster will become read-only.", "proceed": false }
```
The frontend should show a confirmation dialog when `warning` is present. If the FA confirms, re-call with `{ "force": true }`.

### 3.3 Frontend simulation controls

Add failure simulation controls to the cockpit. Place them as action buttons on the node cards:

Each node card gets:
- "Fail drive" button → opens a mini-dropdown listing the node's drives → triggers fail-drive
- "Fail node" button → confirmation → triggers fail-node
- When drives/node are failed: the button text changes to "Restore drive" / "Restore node"

Additionally, add a global "Restore all" button in the header bar (visible only when anything is failed).

Track simulated failures in frontend state so the UI can show which failures are user-simulated vs organic.

### 3.4 Safety guardrails

- Before executing a failure, compute: `currently_offline_drives + drives_being_failed` vs `ec_parity`
- If crossing the parity threshold, show confirmation: "This will exceed EC:4 tolerance. The cluster will lose write quorum but reads will still work. Continue?"
- Allow crossing (it's educational for the demo) but require explicit confirmation
- "Restore all" is always available and prominent when anything is failed
- Never allow failing ALL drives — always leave at least read quorum

### 3.5 Intended FA demo narrative

This is the story FAs will tell customers:

1. **Deploy** a 4-node cluster with EC:4 → cockpit shows 16/16 drives green
2. **Upload** test data → show files are accessible
3. **Fail 1 drive** → cockpit: 15/16, one amber. Data still readable/writable. "We lost a drive. Nothing happened."
4. **Fail 2 more drives** → 13/16. Still operational. "We've now lost 3 drives. MinIO keeps serving."
5. **Fail 4th drive** → 12/16. At EC limit. Writes still work. "We're at our configured tolerance. Still fully operational."
6. **Fail 5th drive** (with confirmation) → writes fail, reads work. "Now we've exceeded tolerance. Writes are blocked but all data is still readable."
7. **Restore all** → watch healing in real-time. "MinIO auto-heals. Every shard reconstructed."

### Validation — Phase 3

```
1. Deploy 4-node EC:4 cluster, upload test data via mc
2. Use cockpit "Fail a drive" on minio1/data3
   - Verify cockpit updates within 15 seconds (15/16 drives)
   - Verify test data is still readable
3. Fail 3 more drives (total 4 failed, at EC limit)
   - Verify cockpit shows 12/16 drives
   - Verify data still readable AND writable
4. Attempt to fail a 5th drive
   - Verify warning dialog appears about quorum loss
   - Proceed — verify writes fail but reads still work
5. Click "Restore all"
   - Verify all drives come back online
   - Verify healing panel appears
   - Verify all data intact after healing completes
6. Use "Fail a node" on minio3
   - Verify cockpit shows minio3 as unreachable
   - Verify data still accessible
7. Restore the node — verify it rejoins and heals
```

**Stop here. Confirm Phase 3 is working before proceeding to Phase 4.**

---

## Phase 4 — Review & Test

### 4.1 Code review checklist

- [ ] EC parity options correctly recalculate when nodes/drives change
- [ ] Derived capacity values are mathematically correct for all node × drive × ec × disk combinations
- [ ] Docker Compose includes `MINIO_STORAGE_CLASS_STANDARD` on ALL minio services
- [ ] mc sidecar container is included and correctly aliased
- [ ] Health endpoint parses `mc admin info --json` output correctly
- [ ] Healing endpoint only returns data when healing is active
- [ ] Failure simulation endpoints validate quorum before executing
- [ ] Restore endpoints work for both drive-level and node-level failures
- [ ] Frontend polling doesn't leak intervals (cleanup on unmount)
- [ ] Node cards update reactively when health data changes
- [ ] Info-only capacity section updates immediately on any config change (no save required)
- [ ] `disk_size_tb` is clearly marked as planning-only and does NOT affect container volumes
- [ ] All new fields have sensible defaults (EC:4, upgrade, 8 TB)

### 4.2 Integration test scenarios

**Scenario A — Fresh deploy with 6-node symmetric EC:**
1. Place minio-cluster on canvas
2. Set: 6 nodes, 6 drives, EC:6, disk size 16 TB
3. Verify info panel: usable ratio 50%, raw 576 TB, usable 288 TB, 3 erasure sets × 12 drives
4. Deploy → verify `mc admin info` shows EC:6 and 36 drives online
5. Upload 10 files → verify accessible

**Scenario B — Progressive failure and recovery:**
1. Deploy 4×4 EC:4
2. Fail drives one at a time (1, 2, 3, 4)
3. At each step verify: cockpit updates, data accessible, write quorum status correct
4. Fail 5th drive → verify write quorum lost, reads still work
5. Restore all → verify healing completes, all data intact

**Scenario C — Node failure (4-node):**
1. Deploy 4×4 EC:4
2. Stop minio3 (kills 4 drives at once = exactly at EC limit)
3. Verify cluster stays up, data accessible
4. Start minio3 → verify rejoin and heal

**Scenario E — Node failure (6-node symmetric):**
1. Deploy 6×4 EC:6 (12-drive erasure sets)
2. Stop minio5 (kills 4 drives in one node)
3. Verify cluster stays up — only 4 drives lost per set, well within EC:6 tolerance
4. Additionally stop minio6 — now 8 drives offline across 2 erasure sets
5. Verify cluster still operational (each set lost at most 4 drives, EC:6 tolerates 6)
6. Restore both → verify healing completes

**Scenario D — Config change and redeploy:**
1. Deploy 4×4 EC:4
2. Change to EC:2, redeploy
3. Verify `mc admin info` shows EC:2
4. Verify old objects retain EC:4 (MinIO only applies new EC to new writes)
5. Upload new file → verify new object has EC:2

### 4.3 Edge cases to verify

- Minimum config: 4 nodes × 4 drives (total=16, set=16, EC:2–EC:8) — should work
- 6-node symmetric: 6 nodes × 6 drives (total=36, set=12, EC:2–EC:6) — verify 3 erasure sets
- 6-node with 8 drives: 6×8=48, set=16 (not 12) — verify EC range is EC:2–EC:8
- EC:8 on 16-drive set: write quorum = K+1 = 9 (special split-brain prevention) — verify
- EC:6 on 12-drive set: write quorum = K+1 = 7 (same split-brain rule applies at 50/50) — verify
- Switching from 8×4 (EC:8 selected) to 6×4: EC:8 exceeds max EC:6 → must reset to EC:4
- Switching from 6×4 (EC:6 selected) to 8×4: EC:6 is within EC:2–EC:8 → should keep selection
- Disk size changes should ONLY update the info panel, never regenerate compose
- Rapid polling (5s) should not overwhelm the mc sidecar — verify no command stacking
- 6-node failure simulation: failing 1 full node = 6 drives offline. With EC:6 on 12-drive set, that's exactly at tolerance — verify cluster survives
