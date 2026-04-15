# Playwright MCP Test Plan: Cockpit Throughput Validation

## Goal

Validate that the Cockpit Throughput tab displays non-zero `ops/s` (operations per second) and bandwidth metrics while the Sovereign Cyber Data Lake demo is running with raw CSV landing active.

## Context

The external-system engine now writes raw CSV files to MinIO (firewall-events and vuln-scan datasets). This generates write traffic that should be visible in the Cockpit Throughput tab as PUT operations and bandwidth. The test confirms that both MinIO cluster metrics and nginx edge metrics are non-zero during active data generation.

## Prerequisites

1. DemoForge is running locally with the frontend on `http://localhost:5173` (or `http://localhost:80` in production)
2. Sovereign Cyber Data Lake template is deployed and running
3. SOC Firewall Events scenario (or similar raw_landing-enabled scenario) is selected on the External System node
4. Demo status is `running` (seeding phase active or completed, data generation ongoing)
5. Cockpit panel is enabled in the control plane (toggle switch)

## Test Steps

### 1. Navigate to Demo Control Plane

```
Navigate to http://localhost:5173
```

Expected: Template Gallery loads. User should see deployed demos in the list or canvas.

### 2. Select Active Demo and Open Cockpit

```
1. Click on the Sovereign Cyber Data Lake demo in the list or canvas header
2. Verify demo status is "running" (not deploying, not stopped)
3. Ensure Cockpit panel is enabled (toggle switch in Instances panel header)
```

Expected: Cockpit overlay appears in the bottom-right corner of the canvas/designer. Demo should be actively seeding or running.

### 3. Navigate to Throughput Tab

```
Click the "Throughput" tab in the Cockpit header (between Health and Stats tabs)
```

Expected: Cockpit displays the Throughput tab. Initial load may show "No clusters running" or "Loading cluster data..." briefly. After 1–2 seconds, cluster data should appear.

### 4. Verify Cluster Header and Health Badge

```
Assert: 
- Cluster alias is visible (e.g., "minio-cluster-1")
- Health badge is displayed with status (healthy, degraded, starting, or unreachable)
- Status badge should show a color indicator (green for healthy, orange for degraded, amber for starting, red for unreachable)
```

DOM selectors:
- Cluster header: `.text-sm.font-medium.text-foreground` containing the cluster alias
- Health badge: `.flex items-center gap-1` with child `.text-[9px].uppercase.tracking-wider`

### 5. Assert PUT Operations > 0

```
Assert: 
- Text "↑ PUT:" visible in green (class: .text-green-400)
- PUT ops/s value > 0 (e.g., "25.3 ops/s")
```

DOM selector:
- PUT row: `.text-green-400` containing "↑ PUT:" and a numeric value
- Pattern: `↑ PUT: (\d+\.?\d*) ops/s`

**Important**: The throughput may initially show 0 during cluster startup. Poll for up to 120 seconds before asserting > 0. If raw_landing is active and seeding is running, PUT ops should appear within 5–10 seconds of the Throughput tab opening.

### 6. Assert GET Operations (May Be Zero)

```
Assert:
- Text "↓ GET:" visible in blue (class: .text-blue-400)
- GET ops/s value ≥ 0 (may be 0 if no reads are happening)
```

DOM selector:
- GET row: `.text-blue-400` containing "↓ GET:" and a numeric value

**Note**: GET operations are acceptable at 0 if the demo is in seeding phase (write-only). Only PUT operations are guaranteed > 0 when raw_landing is active.

### 7. Assert TX Bandwidth (Write Bandwidth)

```
Assert:
- TX bandwidth shown after PUT ops/s (e.g., "(1.2 MB/s)")
- Value > 0 if PUT ops > 0
- Text color: `.text-muted-foreground` with class `.text-[10px]`
```

DOM selector:
- TX bandwidth: text matching pattern `\([\d.]+ (B|KB|MB|GB)\/s\)` appearing after PUT row

Format examples: `(512.5 KB/s)`, `(1.2 MB/s)`, `(0 B/s)` (acceptable), `(1024 B/s)`

### 8. Assert RX Bandwidth (Read Bandwidth)

```
Assert:
- RX bandwidth shown after GET ops/s (e.g., "(0 B/s)" or "(256 KB/s)")
- May be zero if no active reads
- Text color: `.text-muted-foreground` with class `.text-[10px]`
```

DOM selector:
- RX bandwidth: text matching pattern `\([\d.]+ (B|KB|MB|GB)\/s\)` appearing after GET row

### 9. Assert Nginx Edge Metrics (Sub-row)

```
Assert:
- "Nginx (edge)" label visible (class: `.text-muted-foreground`)
- req/s value displayed (e.g., "245.3 req/s")
- active connections count shown (e.g., "(12 active)")
```

DOM selectors:
- Nginx row: `.flex items-center justify-between` containing "Nginx (edge)"
- Nginx req/s: Pattern `(\d+\.?\d*) req/s` in the same row
- Active connections: Pattern `\((\d+) active\)` in the same row

**Expected range**: For raw_landing with firewall-events (50k/5s), expect 10–100 req/s during active seeding.

### 10. Assert MinIO Direct Metrics (Sub-row)

```
Assert:
- "MinIO (cluster)" label visible (class: `.text-muted-foreground`)
- TX (write) bandwidth displayed (e.g., "↑ 2.1 MB/s")
- RX (read) bandwidth displayed (e.g., "↓ 0 B/s")
```

DOM selectors:
- MinIO row: `.flex items-center justify-between` containing "MinIO (cluster)"
- MinIO TX: Pattern `↑ [\d.]+ (B|KB|MB|GB)\/s`
- MinIO RX: Pattern `↓ [\d.]+ (B|KB|MB|GB)\/s`

**Expected**: MinIO TX should correlate with PUT ops and nginx TX. MinIO RX may be 0 during seeding.

## Pass/Fail Criteria

### PASS Conditions (All Required)

1. **PUT ops/s > 0** within 120 seconds of opening Throughput tab
   - With raw_landing active, firewall-events should generate 5–50 PUT ops/s
   - Vuln-scan should generate 1–10 PUT ops/s

2. **At least one of TX bandwidth or MinIO TX bandwidth > 0**
   - Indicates actual bytes are being written to MinIO
   - Byte rate should be proportional to PUT rate and object size

3. **Nginx (edge) metrics visible and consistent**
   - Nginx req/s matches or slightly exceeds MinIO PUT ops/s (some requests may hit errors or retries)
   - Nginx active connections >= 1 during data generation

4. **Health badge shows a valid state**
   - One of: healthy, degraded, starting, unreachable
   - Should not be unreachable if demo is running and data is being written

5. **Metrics refresh within ~1 second**
   - Click Refresh button (top-right of Cockpit header), observe new values within 1–2 seconds
   - Values should change (not frozen)

### FAIL Conditions (Any Fails the Test)

1. **PUT ops/s = 0** after 120 seconds of demo running with active seeding
   - Indicates raw_landing writes are not being measured

2. **All bandwidth metrics = 0** despite non-zero PUT ops
   - Indicates measurement gap between operation count and byte throughput

3. **Cockpit shows "No clusters running"** when demo is deployed
   - Indicates `/api/demos/{demo_id}/cockpit` endpoint is not returning cluster data

4. **Throughput tab does not load or shows error**
   - Check backend logs for cockpit endpoint failures

5. **Health badge shows "unreachable"** despite other tabs showing valid data
   - Indicates cluster health probe is failing (but cluster is actually running)

6. **Metrics frozen / never refresh**
   - Click Refresh button and confirm values change within 2 seconds

## Test Execution

### Manual Execution (Playwright Inspector)

```bash
# Start DemoForge
cd /Users/ahmadtantawy/Documents/Github.nosync/DemoForge
npm run dev

# In another terminal, start Playwright Inspector
npx playwright inspector

# Execute steps 1–10 manually in the browser, verifying selectors and assertions
```

### Automated Execution (Playwright Test)

```bash
# Create test file: frontend/__tests__/cockpit-throughput.spec.ts
# (See separate implementation spec for full test code)

npm run test -- cockpit-throughput.spec.ts
```

Example test structure:

```typescript
import { test, expect } from "@playwright/test";

test("Cockpit Throughput shows non-zero ops/s and bandwidth with raw_landing", async ({ page }) => {
  // Step 1: Navigate
  await page.goto("http://localhost:5173");

  // Step 2: Deploy demo (if not already running)
  // ... (deploy Sovereign Cyber Data Lake template)

  // Step 3: Open Cockpit → Throughput
  const throughputTab = page.getByRole("button", { name: /throughput/i });
  await throughputTab.click();

  // Step 4–10: Assert metrics
  const putOpsText = page.locator(".text-green-400").filter({ hasText: /↑ PUT:/ });
  await expect(putOpsText).toBeVisible({ timeout: 2000 });
  
  const opsMatch = (await putOpsText.textContent())?.match(/(\d+\.?\d*) ops\/s/);
  const putOps = opsMatch ? parseFloat(opsMatch[1]) : 0;
  
  // Poll for non-zero ops within 120 seconds
  let attempts = 0;
  while (putOps === 0 && attempts < 120) {
    await page.waitForTimeout(1000);
    const newText = await putOpsText.textContent();
    const newMatch = newText?.match(/(\d+\.?\d*) ops\/s/);
    putOps = newMatch ? parseFloat(newMatch[1]) : 0;
    attempts++;
  }
  
  expect(putOps).toBeGreaterThan(0);
});
```

## DOM Landmarks (Playwright Selectors)

### Cockpit Container
```
.fixed.z-50.bg-card/95.backdrop-blur.border.border-border.rounded-lg
```

### Tab Bar
```
[class*="flex"][class*="border-b"][class*="border-border"][class*="bg-muted"]
  > button (contains "throughput")
```

### Cluster Header
```
.text-sm.font-medium.text-foreground (contains cluster alias)
```

### Health Badge
```
.flex.items-center.gap-1.text-\\[9px\\].uppercase.tracking-wider
```

### PUT Operations Row
```
.text-green-400 (contains "↑ PUT:")
.text-green-400 (extracts ops/s via regex: /(\d+\.?\d*) ops\/s/)
```

### GET Operations Row
```
.text-blue-400 (contains "↓ GET:")
```

### Nginx Sub-Row
```
.flex.items-center.justify-between (contains "Nginx (edge)")
```

### MinIO Sub-Row
```
.flex.items-center.justify-between (contains "MinIO (cluster)")
```

### Bandwidth Format Regex
```
Pattern: /[\d.]+ (B|KB|MB|GB)\/s/
Examples: "1.2 MB/s", "512.5 KB/s", "0 B/s"
```

## Timeout & Polling Strategy

- **Initial load**: 2 seconds for Throughput tab to render
- **Metric population**: 5–10 seconds for non-zero values to appear (first poll cycle)
- **Data generation lag**: Raw writes may take 3–5 seconds to reach MinIO metrics (Prometheus scrape cycle)
- **Polling interval**: Frontend polls at **1000ms** when Throughput tab is active (line 188 in CockpitOverlay.tsx)
- **Max wait**: 120 seconds total for PUT ops > 0 (reasonable for slow cluster startup)

If metrics remain 0 after 120 seconds:
1. Check demo status (should be `running`)
2. Verify External System node scenario selection (should include `raw_landing`)
3. Check backend logs: `docker logs demoforge-backend-1 | grep cockpit`
4. Check MinIO cluster health via Health tab (should show online drives)
5. Verify demo seeding is active (data should be flowing)

## Edge Cases & Troubleshooting

### Case 1: Cluster Marked "unreachable" Despite Demo Running
- Health badge shows red "unreachable"
- Likely cause: `mc admin info` timeout or cluster not responding to health probe
- Workaround: Metrics may still be valid via Prometheus; nginx metrics should still appear
- Resolution: Check cluster container logs for startup issues

### Case 2: PUT ops > 0 But All Bandwidth = 0
- Indicates measurement gap between operation count and byte-rate calculation
- Likely cause: Prometheus counter collection or rate calculation bug
- Next step: Check backend `cockpit.py` throughput calculation

### Case 3: Metrics Frozen (Clicking Refresh Shows No Change)
- Values remain identical across multiple refreshes
- Likely cause: Frontend polling stalled or backend endpoint not updating
- Next step: Check browser console for fetch errors; check backend logs

### Case 4: "No clusters running" Despite Demo Deployed
- Throughput tab shows "No clusters running"
- Likely cause: `/api/demos/{demo_id}/cockpit` endpoint error or no cluster data in response
- Next step: Inspect network tab → `cockpit` request → response body

### Case 5: Demo Not Running or Seeding Not Active
- Demo status is `deploying` or `stopped`
- No data generation occurring
- Resolution: Ensure demo is fully deployed and seeding has started; check External System scenario selection

## Related Backend Endpoints

These endpoints are called by the Cockpit panel:

- `GET /api/demos/{demo_id}/cockpit` — Returns cluster throughput metrics (PUT/GET ops/s, bandwidth)
- `GET /api/demos/{demo_id}/cockpit/health` — Returns cluster health status (`mc admin info` result)

Both return:
```json
{
  "demo_id": "...",
  "clusters": [
    {
      "alias": "minio-cluster-1",
      "throughput": {
        "put_ops_per_sec": 25.3,
        "get_ops_per_sec": 0,
        "tx_bytes_per_sec": 1258291.2,
        "rx_bytes_per_sec": 0,
        "minio_tx_bytes_per_sec": 1200000,
        "minio_rx_bytes_per_sec": 0,
        "nginx_req_per_sec": 28.5,
        "nginx_active_connections": 5
      }
    }
  ]
}
```

## Success Indicators

- [x] Cockpit Throughput tab renders without errors
- [x] PUT ops/s > 0 within 120 seconds
- [x] At least one bandwidth metric > 0
- [x] Nginx and MinIO metrics visible and consistent
- [x] Health badge shows valid state (not unreachable during active writes)
- [x] Metrics refresh on demand (Refresh button works)

## Notes for Test Maintainer

1. **Flakiness risk**: Metrics depend on ongoing data generation. If seeding completes before metrics are checked, ops/s drops to 0. Ensure test accounts for demo lifecycle (timing is important).

2. **Environment variability**: Throughput rates depend on:
   - CPU/memory available on host
   - Network latency (if using DinD or remote Docker)
   - MinIO cluster configuration (number of nodes, drives)
   - Scenario data size and rate (firewall-events: 50k/5s, vuln-scan: 3k seed)

3. **Playwright MCP plugin**: This test requires the Playwright MCP browser automation tool.

4. **Backlog ref**: Sprint 1 item "Validation: Cockpit throughput visible with raw file writes (Playwright MCP)" — mark as done upon successful test execution.
