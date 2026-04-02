# DemoForge: NVIDIA Simulation Scenario Expansion

## Objective

Expand the NVIDIA STX inference simulation from a single G3.5 tier comparison (Accelerated/Standard/Disabled) to a three-scenario progression that tells the MinIO value story:

1. **File/POSIX Storage** — Customer's painful baseline (traditional NFS/WEKA/Lustre as G4)
2. **MinIO Object Store** — Drop-in S3 replacement for G4 (no hardware change)
3. **MinIO Object + RDMA** — Full vision with G3.5 NVMe-oF/RDMA via BlueField-4

The demo must produce dramatically different metrics at default settings (100 users, 32K context, 2 GPUs) without any parameter tweaking by the Field Architect.

---

## Context: Current Architecture

The simulation lives entirely inside `components/inference-sim/`:

```
components/inference-sim/
├── manifest.yaml                          # Component manifest
├── app/
│   ├── main.py                            # FastAPI server
│   ├── config.py                          # All defaults and env config
│   ├── static/
│   │   └── index.html                     # Full UI (2313 lines, vanilla HTML/JS)
│   └── simulation/
│       ├── engine.py                      # Primary engine (693 lines)
│       ├── kv_block_manager.py            # Tier management, eviction, latency ticks
│       ├── session_manager.py             # Session lifecycle
│       └── request_generator.py           # Request spawning
```

The demo template is `demo-templates/experience-stx-inference.yaml` wiring:
- `inference-client` → `sim-1` (inference-sim) → `minio-g35` (RDMA) + `minio-g4` (TCP) → `prometheus-1`

---

## Phase 1: Engine Changes

### 1.1 Replace `g35_mode` with `scenario`

**Files:** `engine.py`, `config.py`

The current engine uses a `g35_mode` parameter with values `accelerated`, `standard`, `disabled`. Replace this with a `scenario` parameter accepting: `file-g4`, `minio-g4`, `minio-full`.

In `config.py`, add:
```python
SIM_DEFAULT_SCENARIO = os.getenv("SIM_DEFAULT_SCENARIO", "file-g4")
```

Default to `file-g4` so the demo starts on the painful baseline. The Field Architect upgrades live during the demo.

Remove or deprecate `g35_mode`. If backward compatibility is needed briefly, map:
- `disabled` → `file-g4`
- `standard` → `minio-g4`
- `accelerated` → `minio-full`

### 1.2 Scenario Parameter Constants

**File:** `engine.py` (or a new `scenarios.py` if cleaner)

Define the scenario parameters as a dictionary. These values are grounded in published benchmarks from NVIDIA, Pure Storage, VAST Data, WEKA, and industry storage analyses (NVMe-oF specs, MLPerf Storage, vLLM KV cache benchmarks).

```python
SCENARIO_PARAMS = {
    "file-g4": {
        # G4 tier: Traditional NFS/POSIX file storage
        # Rationale: POSIX metadata bottlenecks, kernel overhead, lock convoys
        # under concurrent GPU access. NFS adds milliseconds of latency through
        # software stacks. Lock contention causes non-linear degradation.
        # Sources: NVIDIA tech blog (G4 = "millisecond-level latency"),
        # Introl 2025 ("traditional storage protocols add milliseconds"),
        # WEKA ("metadata bottlenecks, kernel overhead, limited parallelism")
        "g4_base_ticks": 50,            # ~500ms effective at tick=0.2s
        "g4_jitter_pct": 0.50,          # ±50% variance (metadata lock jitter)
        "g4_parallel_factor": 1,        # Serial: POSIX locks serialize readers
        "g4_label": "File / POSIX",

        # G3.5 tier: Disabled (doesn't exist in this scenario)
        "g35_enabled": False,
        "g35_ticks": None,

        # Cross-GPU migration: Devastating without G3.5
        # Must go through slow file G4 or recompute entirely
        "cross_gpu_recompute_chance": 0.35,  # 35% give up on slow file read
        "cross_gpu_restore_ticks": 55,       # When it does try: slow + jittery
        "cross_gpu_restore_jitter_pct": 0.30,

        # Concurrency collapse: POSIX degrades non-linearly
        # Beyond 2 concurrent G4 reads, metadata lock contention kicks in
        "concurrency_collapse_enabled": True,
    },
    "minio-g4": {
        # G4 tier: MinIO S3 object storage over TCP
        # Rationale: S3 GET is stateless — no locks, no metadata server
        # bottleneck, parallel reads scale gracefully. Pure KVA benchmarks
        # show 6x faster inference with S3-backed KV cache vs recomputation.
        # Sources: Pure Storage KVA ("6x faster with S3"), VAST Data
        # ("50-200ms per S3 read"), MinIO AIStor specs
        "g4_base_ticks": 12,            # ~120ms effective (S3 GET over TCP)
        "g4_jitter_pct": 0.20,          # ±20% (consistent, no lock contention)
        "g4_parallel_factor": 4,        # 4 concurrent reads before degradation
        "g4_label": "MinIO S3",

        # G3.5 tier: Still disabled
        "g35_enabled": False,
        "g35_ticks": None,

        # Cross-GPU migration: Viable via G4 S3 restore
        # Fast enough that engine rarely gives up and recomputes
        "cross_gpu_recompute_chance": 0.05,  # 5% recompute fallback
        "cross_gpu_restore_ticks": 14,       # S3 restore is reliable
        "cross_gpu_restore_jitter_pct": 0.15,

        # No concurrency collapse: S3 is stateless
        "concurrency_collapse_enabled": False,
    },
    "minio-full": {
        # G4 tier: Same MinIO S3 as minio-g4
        "g4_base_ticks": 12,
        "g4_jitter_pct": 0.20,
        "g4_parallel_factor": 4,
        "g4_label": "MinIO S3",

        # G3.5 tier: MinIO NVMe-oF/RDMA via BlueField-4
        # Rationale: NVIDIA STX/CMX spec. NVMe-oF RDMA delivers 10-20μs
        # latency. BlueField-4 terminates NVMe-oF and object/RDMA protocols.
        # NVIDIA claims 5x sustained TPS, WEKA demonstrated 41x TTFT
        # improvement at 128K context.
        # Sources: NVIDIA BF-4 tech blog, DataCore NVMe-oF benchmarks
        # ("10-20 microseconds"), VentureBeat STX coverage ("5x TPS")
        "g35_enabled": True,
        "g35_ticks": 2,                 # ~20μs class (RDMA)
        "g35_label": "MinIO RDMA",

        # Cross-GPU migration: Cheap via G3.5 RDMA
        # KV cache blocks promote through shared G3.5 tier at microsecond speed
        "cross_gpu_recompute_chance": 0.005,  # <1% recompute
        "cross_gpu_restore_ticks": 3,         # RDMA promotion
        "cross_gpu_restore_jitter_pct": 0.10,

        # No concurrency collapse
        "concurrency_collapse_enabled": False,
    },
}
```

### 1.3 Concurrency Collapse Model

**File:** `kv_block_manager.py` or `engine.py`

Add a function that models POSIX non-linear degradation under concurrent access. This is the key differentiator that makes file/POSIX visibly break at 100 users.

```python
def effective_g4_ticks(base_ticks, n_concurrent_reads, scenario_params):
    """
    Calculate effective G4 latency ticks accounting for concurrency.

    For File/POSIX: Non-linear degradation due to metadata lock contention.
    For MinIO S3: Graceful scaling up to parallel_factor, gentle degradation after.
    """
    parallel_factor = scenario_params["g4_parallel_factor"]

    if scenario_params.get("concurrency_collapse_enabled", False):
        # POSIX concurrency collapse model
        # Grounded in: NFS metadata server serialization, POSIX lock convoys,
        # kernel context-switch overhead under concurrent access
        if n_concurrent_reads <= 2:
            multiplier = 1.0
        elif n_concurrent_reads <= 5:
            # Linear degradation: each additional reader adds ~40% latency
            multiplier = 1.0 + 0.4 * (n_concurrent_reads - 2)
        else:
            # Non-linear collapse: lock convoy forms
            multiplier = 1.0 + 0.4 * 3 + 0.8 * (n_concurrent_reads - 5)
        return int(base_ticks * multiplier)
    else:
        # S3 parallel model: graceful up to parallel_factor
        excess = max(0, n_concurrent_reads - parallel_factor)
        multiplier = 1.0 + 0.1 * excess
        return int(base_ticks * multiplier)
```

This function must be called wherever the engine currently calculates G4 access latency ticks. The `n_concurrent_reads` value is the number of sessions performing G4 reads in the current tick.

### 1.4 Update G4 Latency Tick Calculation

**File:** `kv_block_manager.py`

The current static latency tick map:
```python
# CURRENT (lines ~157-162)
LATENCY_TICKS = {"G1": 0, "G2": 0, "G3": 1, "G3.5": 2, "G4": 10}
```

Replace with scenario-aware lookup:
```python
def get_tier_ticks(tier, scenario_params):
    """Get latency ticks for a tier based on active scenario."""
    STATIC_TICKS = {"G1": 0, "G2": 0, "G3": 1}

    if tier in STATIC_TICKS:
        return STATIC_TICKS[tier]
    elif tier == "G3.5":
        if not scenario_params["g35_enabled"]:
            return None  # Tier doesn't exist — skip in eviction cascade
        return scenario_params["g35_ticks"]
    elif tier == "G4":
        return scenario_params["g4_base_ticks"]
    return 0
```

### 1.5 Update Eviction Cascade

**File:** `kv_block_manager.py`

The current eviction cascade is: G1 → G2 → G3 → G3.5 → G4.

When G3.5 is disabled (`file-g4` and `minio-g4` scenarios), the cascade must skip G3.5:
- G1 → G2 → G3 → G4 (skip G3.5)

Find the eviction logic that walks the tier list and add a check:
```python
# When building the eviction tier order:
tier_order = ["G1", "G2", "G3"]
if scenario_params["g35_enabled"]:
    tier_order.append("G3.5")
tier_order.append("G4")
```

### 1.6 Update Cross-GPU Migration Logic

**File:** `engine.py` (currently lines ~576-588)

Replace the current `g35_mode` switch:

```python
# CURRENT CODE (replace this):
if g35_mode == "standard":
    ticks = max(ticks, 15)    # S3/TCP ~5-10ms
elif g35_mode == "accelerated":
    ticks = max(ticks, 3)     # RDMA ~500μs
else:
    ticks = 50                # full recomputation

# NEW CODE:
import random

params = SCENARIO_PARAMS[self.scenario]

if random.random() < params["cross_gpu_recompute_chance"]:
    # Engine gives up on G4/G3.5 restore, recomputes from scratch
    # file-g4: 35% chance (file read too slow, not worth waiting)
    # minio-g4: 5% chance (rare, S3 is usually fast enough)
    # minio-full: <1% chance (RDMA almost never fails)
    ticks = 50  # Full recomputation penalty (existing value)
else:
    base_restore = params["cross_gpu_restore_ticks"]
    jitter_range = int(base_restore * params["cross_gpu_restore_jitter_pct"])
    jitter = random.randint(-jitter_range, jitter_range) if jitter_range > 0 else 0
    ticks = max(ticks, base_restore + jitter)
```

### 1.7 Apply G4 Jitter to All G4 Accesses

**File:** `engine.py`

Wherever a G4 access latency is applied (not just cross-GPU, but regular eviction reads/writes), apply jitter from the scenario params:

```python
def jittered_g4_ticks(self):
    """Get G4 ticks with scenario-appropriate jitter."""
    params = SCENARIO_PARAMS[self.scenario]
    base = params["g4_base_ticks"]
    jitter_range = int(base * params["g4_jitter_pct"])
    jitter = random.randint(-jitter_range, jitter_range)
    return max(1, base + jitter)  # Never less than 1 tick
```

Use this everywhere `G4` tick values are referenced for actual I/O operations.

---

## Phase 2: API Contract Changes

### 2.1 POST /sim/config

**File:** `main.py` (FastAPI routes)

Update the config endpoint to accept `scenario` instead of `g35_mode`:

```python
# Request body schema:
{
    "scenario": "file-g4" | "minio-g4" | "minio-full",  # NEW
    "num_users": 100,
    "context_tokens": 32768,
    "speed_factor": 1.0
}
```

If the engine currently reads `g35_mode` from the config payload and passes it to the simulation, change all references to use `scenario` instead. The engine should look up `SCENARIO_PARAMS[scenario]` and apply the full parameter bundle.

### 2.2 GET /sim/state

**File:** `main.py`

Add scenario metadata to the state response so the UI can react:

```python
# Add to response:
{
    "scenario": "file-g4",
    "scenario_label": "File / POSIX Storage",
    "g4_type": "file-posix",      # or "minio-s3"
    "g35_enabled": false,
    "g35_label": null,             # or "MinIO RDMA"
    # ... existing fields unchanged
}
```

### 2.3 GET /sim/scenarios (NEW endpoint)

Add a new endpoint that returns available scenarios with their metadata. The UI can use this to build the scenario selector dynamically:

```python
@app.get("/sim/scenarios")
async def get_scenarios():
    return {
        "scenarios": [
            {
                "id": "file-g4",
                "label": "File / POSIX Storage",
                "subtitle": "Traditional NFS/WEKA — today's baseline",
                "g4_label": "File / POSIX",
                "g35_label": None,
                "accent": "destructive",  # red/amber
                "expectations": {
                    "gpu_util": "<50%",
                    "recompute": "High",
                    "ttft": "300-800ms"
                }
            },
            {
                "id": "minio-g4",
                "label": "MinIO Object Store",
                "subtitle": "S3-native G4 memory tier",
                "g4_label": "MinIO S3",
                "g35_label": None,
                "accent": "warning",  # amber/green
                "expectations": {
                    "gpu_util": "55-70%",
                    "recompute": "Moderate",
                    "ttft": "80-200ms"
                }
            },
            {
                "id": "minio-full",
                "label": "MinIO Object + RDMA",
                "subtitle": "G4 Object Store + G3.5 NVMe-oF/RDMA",
                "g4_label": "MinIO S3",
                "g35_label": "MinIO RDMA (BlueField-4)",
                "accent": "success",  # green
                "expectations": {
                    "gpu_util": "82-92%",
                    "recompute": "Rare",
                    "ttft": "30-60ms"
                }
            }
        ]
    }
```

---

## Phase 3: UI Changes

All UI changes are in `components/inference-sim/app/static/index.html`.

### 3.1 Replace G3.5 Tier Selector with Scenario Selector

**Find** the current G3.5 tier selector (lines ~481-489) which renders three radio buttons: Accelerated / Standard / Disabled.

**Replace** with a scenario selector — three large radio-card buttons. Each card should contain:
- The scenario label (bold)
- The subtitle (smaller text)
- A colored accent bar (red → amber → green)

```html
<!-- Scenario Selector — replaces G3.5 tier selector -->
<div class="scenario-selector" id="scenarioSelector">
    <div class="scenario-card active destructive" data-scenario="file-g4"
         onclick="setScenario('file-g4')">
        <div class="scenario-accent"></div>
        <div class="scenario-content">
            <div class="scenario-label">File / POSIX Storage</div>
            <div class="scenario-subtitle">Traditional NFS/WEKA — today's baseline</div>
        </div>
    </div>
    <div class="scenario-card warning" data-scenario="minio-g4"
         onclick="setScenario('minio-g4')">
        <div class="scenario-accent"></div>
        <div class="scenario-content">
            <div class="scenario-label">MinIO Object Store</div>
            <div class="scenario-subtitle">S3-native G4 memory tier</div>
        </div>
    </div>
    <div class="scenario-card success" data-scenario="minio-full"
         onclick="setScenario('minio-full')">
        <div class="scenario-accent"></div>
        <div class="scenario-content">
            <div class="scenario-label">MinIO Object + RDMA</div>
            <div class="scenario-subtitle">G4 Object Store + G3.5 NVMe-oF/RDMA</div>
        </div>
    </div>
</div>
```

Style the cards so they are visually distinct and large enough to be tap targets in a demo setting. The active card should be prominently highlighted. The accent colors:
- `destructive`: red/warm tones (file-g4)
- `warning`: amber/orange tones (minio-g4)
- `success`: green tones (minio-full)

### 3.2 Add "What Changes" Summary Strip

Below the scenario selector, add a summary strip that updates when the scenario changes:

```html
<div class="scenario-summary" id="scenarioSummary">
    <div class="summary-item">
        <span class="summary-label">G4 Archive:</span>
        <span class="summary-value" id="summaryG4">File / POSIX</span>
    </div>
    <div class="summary-divider">│</div>
    <div class="summary-item">
        <span class="summary-label">G3.5 Cross-GPU:</span>
        <span class="summary-value" id="summaryG35">Disabled</span>
    </div>
    <div class="summary-divider">│</div>
    <div class="summary-item">
        <span class="summary-label">Expected:</span>
        <span class="summary-value" id="summaryExpect">&lt;50% GPU util · High recompute · Slow TTFT</span>
    </div>
</div>
```

JavaScript to update it:
```javascript
function updateScenarioSummary(scenario) {
    const summaries = {
        'file-g4': {
            g4: 'File / POSIX',
            g35: 'Disabled',
            expect: '<50% GPU util · High recompute · Slow TTFT'
        },
        'minio-g4': {
            g4: 'MinIO S3 (TCP)',
            g35: 'Disabled',
            expect: '55-70% GPU util · Moderate recompute · Faster TTFT'
        },
        'minio-full': {
            g4: 'MinIO S3 (TCP)',
            g35: 'MinIO RDMA (BlueField-4)',
            expect: '82-92% GPU util · Rare recompute · Lowest TTFT'
        }
    };
    const s = summaries[scenario];
    document.getElementById('summaryG4').textContent = s.g4;
    document.getElementById('summaryG35').textContent = s.g35;
    document.getElementById('summaryExpect').textContent = s.expect;
}
```

### 3.3 Update setScenario() Function

The current code likely has a function that sends the G3.5 mode to the backend via POST /sim/config. Replace it:

```javascript
function setScenario(scenario) {
    // Update UI
    document.querySelectorAll('.scenario-card').forEach(card => {
        card.classList.remove('active');
    });
    document.querySelector(`[data-scenario="${scenario}"]`).classList.add('active');

    updateScenarioSummary(scenario);

    // Send to backend
    fetch('/sim/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            scenario: scenario,
            num_users: currentUsers,        // existing variable
            context_tokens: currentContext,  // existing variable
            speed_factor: currentSpeed       // existing variable
        })
    });
}
```

### 3.4 Update Mode Comparison Strip

**Find** the existing 3-column comparison strip (Accelerated / Standard / Disabled).

**Relabel** the columns:
- Column 1: "File / POSIX" (was "Disabled")
- Column 2: "MinIO Object" (was "Standard")
- Column 3: "MinIO + RDMA" (was "Accelerated")

Keep the same structure — each column shows live metric values for the active scenario (real-time updates) and last-known/projected values for the other two. The column order should match the narrative progression (bad → good → best, left to right).

### 3.5 Update Tier Fill Bars

**Find** the tier fill bars section that shows G1/G2/G3 per-GPU + shared G3.5/G4.

Add conditional visibility for G3.5 based on scenario:

```javascript
function updateTierBars(state) {
    // ... existing G1/G2/G3 bar updates ...

    const g35Bar = document.getElementById('tierBarG35');
    const g35Container = g35Bar.closest('.tier-bar-container');  // or parent element

    if (state.g35_enabled) {
        g35Container.style.display = '';
        // Update G3.5 bar with label from scenario
        document.getElementById('g35Label').textContent = state.g35_label || 'G3.5';
    } else {
        g35Container.style.display = 'none';
    }

    // Update G4 bar label based on scenario
    const g4Label = document.getElementById('g4Label');
    if (state.g4_type === 'file-posix') {
        g4Label.textContent = 'G4 (File/POSIX)';
    } else {
        g4Label.textContent = 'G4 (MinIO S3)';
    }
}
```

### 3.6 Update Cross-GPU Path Diagram

**Find** the cross-GPU path diagram (`GPU-A → [G3.5 or G4] → GPU-B`).

It needs three visual states based on scenario:

```javascript
function updateCrossGpuDiagram(scenario, migrationResult) {
    const middleNode = document.getElementById('crossGpuMiddle');
    const latencyLabel = document.getElementById('crossGpuLatency');
    const resultBadge = document.getElementById('crossGpuResult');

    const configs = {
        'file-g4': {
            label: 'File / NFS',
            color: 'var(--color-destructive)',  // red
            typicalLatency: '500ms+',
            recomputeFrequent: true
        },
        'minio-g4': {
            label: 'MinIO S3',
            color: 'var(--color-warning)',       // amber
            typicalLatency: '~120ms',
            recomputeFrequent: false
        },
        'minio-full': {
            label: 'MinIO RDMA',
            color: 'var(--color-success)',        // green
            typicalLatency: '~20μs',
            recomputeFrequent: false
        }
    };

    const config = configs[scenario];
    middleNode.textContent = config.label;
    middleNode.style.borderColor = config.color;
    latencyLabel.textContent = config.typicalLatency;
    latencyLabel.style.color = config.color;

    // Result badge updates from actual migration events
    if (migrationResult === 'recompute') {
        resultBadge.textContent = 'RECOMPUTE';
        resultBadge.className = 'badge badge-destructive';
    } else if (migrationResult === 'restored') {
        resultBadge.textContent = 'RESTORED';
        resultBadge.className = 'badge badge-warning';
    } else if (migrationResult === 'promoted') {
        resultBadge.textContent = 'PROMOTED';
        resultBadge.className = 'badge badge-success';
    }
}
```

### 3.7 Event Stream Labels

**Find** the event stream/feed section (max 15 events).

Update event labels to reflect the scenario context. When a G4 access occurs, the event should say:
- `file-g4`: "Restored from File/NFS (847ms)" or "RECOMPUTE — file read timeout"
- `minio-g4`: "Restored from MinIO S3 (142ms)"
- `minio-full`: "Promoted via MinIO RDMA (0.02ms)"

---

## Phase 4: Manifest and Template Changes

### 4.1 Manifest Update

**File:** `components/inference-sim/manifest.yaml`

Add the default scenario env var:
```yaml
env:
  # ... existing env vars ...
  SIM_DEFAULT_SCENARIO: "file-g4"
```

Update connections to reflect optional G3.5:
```yaml
connections:
  accepts:
    - type: s3
      tier_role: g4-archive
      optional: true         # Not connected in file-g4 scenario
    - type: s3
      tier_role: g35-rdma
      optional: true         # Only connected in minio-full scenario
```

### 4.2 Template Update

**File:** `demo-templates/experience-stx-inference.yaml`

No structural changes needed — the template still wires both MinIO clusters. The simulation engine internally decides which ones are active based on the scenario. The MinIO containers are always running; the scenario controls whether the engine routes I/O through them or simulates file-based latency.

If the template has any metadata or description fields, update them:
```yaml
name: "NVIDIA STX Inference — Storage Tier Comparison"
description: "Three-scenario demo: File/POSIX baseline → MinIO Object Store → MinIO Object + RDMA. Demonstrates GPU utilization improvements from storage modernization."
```

---

## Phase 5: Tuning Targets

After implementation, run all three scenarios at default settings (100 users, 32K context, 2 GPUs, 1x speed) and verify the metrics converge to these benchmark-grounded ranges within 30-60 seconds of simulation time:

```
                           file-g4       minio-g4      minio-full
                           ───────       ────────      ──────────
GPU Active Inference %      25–40%        55–70%        82–92%
GPU IO Stall %              30–45%        15–25%         3–7%
GPU Recompute %             15–25%         5–12%         1–3%
GPU Idle %                   5–10%         5–8%          2–5%

TTFT avg (ms)              300–800       80–200         30–60
TTFT p99 (ms)             1500–3000     300–600         80–150

Cache Hit Rate              35–50%        60–75%        85–95%
Recomputations/min          40–60         10–20          <5
Concurrent Active Sessions  25–45         55–85         90–120
S3 Ops/sec                   0            20–40         40–80
```

### Benchmark Sources for These Targets

The above targets are derived from:

- **GPU utilization 2-3x improvement** from storage optimization: NVIDIA STX/CMX announcement (5x TPS claim), Introl 2025 analysis ("2 to 3 times in I/O bound configurations")
- **TTFT reduction 6-20x** with S3/NFS KV cache: Pure Storage KVA benchmarks (20x NFS, 6x S3), VAST Data testing (11s → 1.5s, ~7x)
- **TTFT reduction 41x** with RDMA at 128K context: WEKA Augmented Memory Grid benchmarks
- **File/POSIX latency characteristics**: NVIDIA tech blog ("millisecond-level latency" for G4), WEKA ("metadata bottlenecks, kernel overhead, limited parallelism"), Introl ("traditional storage protocols add milliseconds through software stacks")
- **RDMA latency 10-20μs**: DataCore NVMe-oF analysis, NVIDIA BlueField-4 specs
- **S3 read latency 50-200ms**: Three-tier storage architecture analysis, confirmed by VAST and Pure Storage production data
- **Concurrency collapse under POSIX**: WEKA analysis of legacy NAS under AI workloads, HPCwire Future of Storage series

### Tuning Adjustments

If metrics don't hit the target ranges, adjust in this order:

1. **G4 base ticks** (primary lever for file-g4 pain): Increase `g4_base_ticks` for file-g4 if GPU utilization is too high. The target is dramatic visual difference.
2. **Concurrency collapse multipliers** (secondary lever): Adjust the `0.4` and `0.8` coefficients in `effective_g4_ticks()` to make the non-linear degradation more or less aggressive.
3. **Cross-GPU recompute chance** (controls recompute bar): Adjust `cross_gpu_recompute_chance` if the recompute % doesn't match targets.
4. **G4 jitter percentage** (controls p99 tail): Increase `g4_jitter_pct` for file-g4 if p99 TTFT isn't high enough.

Do NOT adjust G1/G2/G3 parameters, session lifecycle probabilities, or request generation rates. These should remain unchanged — only the G4 and G3.5 behavior changes between scenarios.

---

## Phase 6: Verification Checklist

After implementation, verify each item:

- [ ] `POST /sim/config` with `{"scenario": "file-g4"}` is accepted and applied
- [ ] `POST /sim/config` with `{"scenario": "minio-g4"}` is accepted and applied
- [ ] `POST /sim/config` with `{"scenario": "minio-full"}` is accepted and applied
- [ ] `GET /sim/state` returns `scenario`, `g4_type`, `g35_enabled` fields
- [ ] `GET /sim/scenarios` returns all three scenarios with metadata
- [ ] Default startup scenario is `file-g4`
- [ ] Switching from `file-g4` to `minio-g4` produces visible GPU utilization improvement within 15-20 seconds
- [ ] Switching from `minio-g4` to `minio-full` produces visible recompute reduction within 15-20 seconds
- [ ] Tier fill bars hide G3.5 in `file-g4` and `minio-g4` scenarios
- [ ] Tier fill bars show G3.5 with "MinIO RDMA" label in `minio-full`
- [ ] G4 tier bar shows "File/POSIX" label in `file-g4` and "MinIO S3" in others
- [ ] Cross-GPU diagram updates label, color, and latency for each scenario
- [ ] Event stream shows scenario-appropriate labels (File/NFS, MinIO S3, MinIO RDMA)
- [ ] Mode comparison strip shows three columns: File/POSIX, MinIO Object, MinIO + RDMA
- [ ] Scenario summary strip updates on scenario change
- [ ] At 100 users / 32K context: file-g4 shows <50% GPU active inference
- [ ] At 100 users / 32K context: minio-g4 shows 55-70% GPU active inference
- [ ] At 100 users / 32K context: minio-full shows 82-92% GPU active inference
- [ ] TTFT values are in the target ranges for each scenario
- [ ] No errors in browser console when switching scenarios rapidly
- [ ] Speed controls (0.5x/1x/2x/4x) still work correctly with new scenarios
- [ ] User slider and context token selector still work correctly

---

## Implementation Order

1. **Engine constants** — Add `SCENARIO_PARAMS` dict and `effective_g4_ticks()` function
2. **Engine logic** — Replace `g35_mode` with `scenario` throughout engine.py
3. **KV block manager** — Scenario-aware tick lookups, eviction cascade skip
4. **Cross-GPU migration** — New scenario-driven logic with recompute chance
5. **API endpoints** — Update `/sim/config`, `/sim/state`, add `/sim/scenarios`
6. **UI: Scenario selector** — Replace G3.5 tier selector with 3-card scenario picker
7. **UI: Summary strip** — Add "what changes" strip below selector
8. **UI: Tier bars** — Conditional G3.5 visibility, G4 label updates
9. **UI: Cross-GPU diagram** — Three visual states
10. **UI: Comparison strip** — Relabel columns
11. **UI: Event stream** — Scenario-aware event labels
12. **Manifest + Template** — Update env defaults and descriptions
13. **Tuning pass** — Run all three scenarios, adjust parameters to hit target ranges
