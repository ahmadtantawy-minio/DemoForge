# Claude Code Instruction: Inference Simulator UI Overhaul

Read the existing simulation UI code before making changes:
- `components/inference-sim/app/static/index.html` — current visualization
- `components/inference-sim/app/simulation/engine.py` — simulation loop
- `components/inference-sim/app/simulation/kv_block_manager.py` — tier management

---

## Problems to fix

1. **Tier bars are confusing** — colored blocks inside bars don't align with the percentage indicator. The user can't tell what the blocks represent vs what the percentage means vs what the capacity number means.

2. **Metrics are broken** — GPU utilization >100%, cache hit rate >800%, dashes for active blocks and S3 ops. These must be clamped and computed correctly.

3. **"Speed" is unclear** — what does "5x" mean to someone who doesn't know it's a simulation clock?

4. **Single GPU doesn't tell the CMX story** — the shared-context-across-GPUs value of G3.5 is invisible with one GPU.

---

## Task 1: Dual-GPU Architecture

### New visualization layout

Replace the current single-column tier bars with a dual-GPU layout:

```
┌──────────────────────────────────────────────────────────────────┐
│  MEMORY HIERARCHY                                                │
│                                                                  │
│  ┌─── GPU-A ────────────────────┐  ┌─── GPU-B ────────────────┐ │
│  │                              │  │                            │ │
│  │  G1  GPU HBM    ████░░ 65%  │  │  G1  GPU HBM   ███░░ 52% │ │
│  │      6.5 / 10 GB            │  │      5.2 / 10 GB          │ │
│  │                              │  │                            │ │
│  │  G2  CPU DRAM   █████ 80%   │  │  G2  CPU DRAM  ████░ 72%  │ │
│  │      12 / 15 GB             │  │      10.8 / 15 GB         │ │
│  │                              │  │                            │ │
│  │  G3  Local NVMe ██████ 90%  │  │  G3  Local NVMe █████ 85% │ │
│  │      18 / 20 GB             │  │      17 / 20 GB           │ │
│  │                              │  │                            │ │
│  └──────────────────────────────┘  └────────────────────────────┘ │
│                                                                  │
│  ┌─── G3.5  MinIO CMX (shared) ─────────────────────────────────┐│
│  │  █████████████████████████████████████░░░░░░░░░░  72%        ││
│  │  28.8 / 40 GB                                                ││
│  │  ↑↑ blocks from both GPUs land here ↑↑                       ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─── G4  Enterprise Storage ───────────────────────────────────┐│
│  │  ██████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  12%       ││
│  │  12 / 100 GB                                                 ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Key design decisions

**Each GPU has its own G1/G2/G3 column.** These are private to that GPU — a KV block in GPU-A's G1 is NOT accessible by GPU-B without going through G3.5.

**G3.5 and G4 span both columns.** They are shared, pod-level tiers. This is the visual punchline: the MinIO tier is the bridge between isolated GPU memories.

**The tier bars are simple fill bars, not block grids.** One bar per tier, colored fill showing utilization percentage, with used/capacity text to the right. No individual block rectangles inside the bars — those were confusing. Instead, show individual sessions in the separate "Active sessions" section below.

**Block migration animations** happen between the GPU columns and the shared tiers. When a session migrates from GPU-A to GPU-B:
1. Block visually drops from GPU-A's G1 → G3.5 (shared)
2. Block visually rises from G3.5 → GPU-B's G1
3. The animation passes through the shared tier, making it obvious why G3.5 exists

**When CMX is OFF**, the G3.5 row grays out entirely. Blocks skip from G3 straight to G4. Migrations between GPUs require full recomputation (shown as a red flash on the destination GPU).

### Simulation engine changes

File: `components/inference-sim/app/simulation/engine.py`

The simulation engine currently models a single GPU. Extend to dual-GPU:

```python
class SimulationConfig:
    gpu_count: int = 2                    # NEW: 2 GPUs
    g1_capacity_gb_per_gpu: float = 10    # Per GPU
    g2_capacity_gb_per_gpu: float = 15    # Per GPU
    g3_capacity_gb_per_gpu: float = 20    # Per GPU
    g35_capacity_gb: float = 40           # Shared
    g4_capacity_gb: float = 100           # Shared
    cmx_enabled: bool = True
    users: int = 50
    context_tokens: int = 32768
    speed: int = 5
```

```python
class SimulationState:
    gpus: list[GPUState]           # One per GPU
    shared_g35: TierState          # Shared across GPUs
    shared_g4: TierState           # Shared across GPUs
    sessions: list[Session]
    metrics: SimMetrics

class GPUState:
    id: str                        # "gpu-a" or "gpu-b"
    g1: TierState                  # Private G1
    g2: TierState                  # Private G2
    g3: TierState                  # Private G3

class TierState:
    capacity_gb: float
    used_gb: float
    block_count: int

class Session:
    id: str
    gpu_id: str                    # Which GPU currently serves this session
    tier: str                      # Which tier holds the KV cache ("g1", "g2", "g3", "g35", "g4")
    size_gb: float
    active: bool
    idle_ticks: int
```

**Session routing:** New sessions are assigned to the GPU with more available G1 capacity (simple load balancing). This means both GPUs fill up over time.

**Session migration:** When a session returns after being idle and its KV cache has been evicted from its original GPU, the router may assign it to a *different* GPU (the one with more capacity). This triggers the G3.5 → new GPU promotion path.

The migration event types:
- `EVICT_TO_G2` — session goes idle, KV cache drops from G1 to G2 (same GPU)
- `EVICT_TO_G3` — G2 full, drops to G3 (same GPU)
- `EVICT_TO_G35` — G3 full, drops to shared G3.5 (MinIO S3 PUT)
- `EVICT_TO_G4` — G3.5 full or CMX disabled, drops to G4 (MinIO S3 PUT)
- `PROMOTE_SAME_GPU` — session returns, KV cache promoted back to G1 on same GPU
- `PROMOTE_CROSS_GPU` — session returns, routed to different GPU, KV cache pulled from G3.5 to new GPU's G1 (this is the CMX value moment)
- `RECOMPUTE` — no cache available (evicted to G4 or CMX off), GPU recomputes from scratch

**Cross-GPU promotion frequency:** Make ~20-30% of returning sessions route to the other GPU. This happens naturally with load-balanced routing when both GPUs are busy. It ensures the demo shows enough cross-GPU migrations to make the G3.5 value visible.

### WebSocket state format update

Each WebSocket message now includes per-GPU tier states:

```json
{
  "tick": 1234,
  "gpus": [
    {
      "id": "gpu-a",
      "g1": {"capacity_gb": 10, "used_gb": 6.5, "block_count": 12, "pct": 65},
      "g2": {"capacity_gb": 15, "used_gb": 12, "block_count": 8, "pct": 80},
      "g3": {"capacity_gb": 20, "used_gb": 18, "block_count": 15, "pct": 90}
    },
    {
      "id": "gpu-b",
      "g1": {"capacity_gb": 10, "used_gb": 5.2, "block_count": 10, "pct": 52},
      "g2": {"capacity_gb": 15, "used_gb": 10.8, "block_count": 7, "pct": 72},
      "g3": {"capacity_gb": 20, "used_gb": 17, "block_count": 14, "pct": 85}
    }
  ],
  "shared": {
    "g35": {"capacity_gb": 40, "used_gb": 28.8, "block_count": 45, "pct": 72},
    "g4":  {"capacity_gb": 100, "used_gb": 12, "block_count": 20, "pct": 12}
  },
  "metrics": {
    "gpu_a_utilization": 65,
    "gpu_b_utilization": 52,
    "avg_ttft_ms": 85,
    "cache_hit_rate": 92,
    "cross_gpu_migrations": 47,
    "recomputations": 3,
    "s3_ops_per_sec": 24,
    "active_sessions": 48,
    "total_kv_blocks": 131
  },
  "events": [
    {"type": "PROMOTE_CROSS_GPU", "session": "s-abc12", "from_gpu": "gpu-a", "to_gpu": "gpu-b", "via": "g35"},
    {"type": "EVICT_TO_G35", "session": "s-def34", "gpu": "gpu-a"},
    {"type": "RECOMPUTE", "session": "s-ghi56", "gpu": "gpu-b", "reason": "cache_in_g4"}
  ]
}
```

---

## Task 2: Fix tier bar visualization

### Replace block-grid bars with clean fill bars

The current bars show individual colored rectangles (blocks) inside each tier. This is confusing because:
- Block width varies by session size
- Blocks don't fill the bar uniformly even at 100%
- The user can't tell what a single block represents

**Replace with simple fill bars:**

```html
<div class="tier-row">
  <div class="tier-label">
    <div class="tier-name">G1</div>
    <div class="tier-desc">GPU HBM</div>
  </div>
  <div class="tier-bar-track">
    <div class="tier-bar-fill" style="width: 65%; background: var(--color-g1);">
      <span class="tier-pct">65%</span>
    </div>
  </div>
  <div class="tier-capacity">6.5 / 10 GB</div>
</div>
```

**Style rules:**
- Bar track: full width, 32px height, dark background (`rgba(255,255,255,0.05)` on dark theme), rounded corners
- Bar fill: colored per tier, animated width transition (`transition: width 0.4s ease`), percentage text inside
- Fill colors:
  - G1 (GPU HBM): red/coral (`#E85D24` → warm = hot memory)
  - G2 (CPU DRAM): amber/orange (`#EF9F27`)
  - G3 (Local NVMe): blue (`#378ADD`)
  - G3.5 (MinIO CMX): green/teal (`#1D9E75` → the MinIO color, the "good" tier)
  - G4 (Enterprise): gray (`#888780` → cold, slow)
- When a tier is over 90% capacity, the fill bar pulses subtly (CSS animation, `opacity: 0.85 → 1.0`)
- When a tier is at 0% (CMX disabled), show the track with a striped "disabled" pattern

**Capacity text:** Always show `{used} / {capacity} GB` to the right of the bar. This is the authoritative number. The percentage inside the bar is the visual shorthand.

### GPU column layout

```html
<div class="gpu-columns">
  <div class="gpu-column">
    <div class="gpu-header">GPU-A</div>
    <!-- G1 bar -->
    <!-- G2 bar -->
    <!-- G3 bar -->
  </div>
  <div class="gpu-column">
    <div class="gpu-header">GPU-B</div>
    <!-- G1 bar -->
    <!-- G2 bar -->
    <!-- G3 bar -->
  </div>
</div>
<div class="shared-tiers">
  <div class="shared-header">Shared storage (pod-level)</div>
  <!-- G3.5 bar (full width, highlighted border) -->
  <!-- G4 bar (full width) -->
</div>
```

**CSS layout:**

```css
.gpu-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.gpu-column {
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 12px;
}
.gpu-header {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: rgba(255,255,255,0.7);
}
.shared-tiers {
  border: 1px solid rgba(29,158,117,0.3);  /* Green border for MinIO tiers */
  border-radius: 8px;
  padding: 12px;
}
.shared-header {
  font-size: 12px;
  color: rgba(255,255,255,0.5);
  margin-bottom: 8px;
}
```

---

## Task 3: Fix metrics

### Clamp all percentage values

```python
# In simulation/metrics.py or wherever metrics are computed:
def compute_metrics(state: SimulationState) -> dict:
    gpu_a = state.gpus[0]
    gpu_b = state.gpus[1]
    
    # GPU utilization = how much of G1 is being actively used for inference
    # Clamped to 0-100
    gpu_a_util = min(100, round(gpu_a.g1.used_gb / gpu_a.g1.capacity_gb * 100))
    gpu_b_util = min(100, round(gpu_b.g1.used_gb / gpu_b.g1.capacity_gb * 100))
    
    # Cache hit rate = successful cache retrievals / total session returns
    # Must be 0-100, never above
    total_returns = state.cache_hits + state.cache_misses
    cache_hit_rate = round(state.cache_hits / max(total_returns, 1) * 100)
    cache_hit_rate = min(100, max(0, cache_hit_rate))
    
    # TTFT (time to first token) — simulated based on where cache was found
    # G1 hit: ~20ms, G2: ~50ms, G3: ~100ms, G3.5: ~200ms, G4: ~1000ms, recompute: ~2000ms
    ...
    
    return {
        "gpu_a_utilization": gpu_a_util,
        "gpu_b_utilization": gpu_b_util,
        "avg_ttft_ms": round(avg_ttft),
        "cache_hit_rate": cache_hit_rate,
        "cross_gpu_migrations": state.cross_gpu_count,
        "recomputations": state.recomputation_count,
        "s3_ops_per_sec": round(state.s3_ops_in_window / max(state.window_seconds, 1)),
        "active_sessions": len([s for s in state.sessions if s.active]),
        "total_kv_blocks": sum(t.block_count for gpu in state.gpus for t in [gpu.g1, gpu.g2, gpu.g3])
                          + state.shared_g35.block_count + state.shared_g4.block_count,
    }
```

**Rules:**
- No metric can exceed 100% (clamp with `min(100, value)`)
- No metric can be negative (clamp with `max(0, value)`)
- Display integers for percentages (no decimals — "92%" not "92.3%")
- Display integers for milliseconds ("85 ms" not "85.3 ms")
- If a value is 0 and the simulation hasn't started, show "—" (dash), not "0"

### Updated metrics panel layout

Replace the current 6-card grid with a more informative layout:

```
┌─ LIVE METRICS ──────────────────────────────────┐
│                                                  │
│  GPU-A         GPU-B          Combined           │
│  ██ 65%        ██ 52%         ██ 59% avg         │
│  utilization   utilization    utilization         │
│                                                  │
│  Avg TTFT      Cache hits     Cross-GPU          │
│  85 ms         92%            47 migrations      │
│                                                  │
│  S3 ops/sec    Recomputes     Active sessions    │
│  24            3              48                  │
│                                                  │
└──────────────────────────────────────────────────┘
```

The top row shows per-GPU utilization side by side — this immediately shows load distribution. The "Cross-GPU migrations" metric is new and directly shows how often G3.5 is saving the day.

### Metric card color coding

```
GPU utilization:   green (>70%) | amber (40-70%) | red (<40%)
Avg TTFT:          green (<100ms) | amber (100-500ms) | red (>500ms)
Cache hit rate:    green (>80%) | amber (50-80%) | red (<50%)
Cross-GPU:         always teal (neutral — higher = more G3.5 value)
Recomputations:    green (0) | amber (1-10) | red (>10)
S3 ops/sec:        always teal (shows MinIO activity)
```

---

## Task 4: Rename and clarify controls

### "Speed" → "Simulation pace"

Replace the "Speed" control with clearer labeling:

```
Simulation pace    [Slow] [Normal] [Fast]
```

Where:
- **Slow** = 1x real-time (1 tick = 200ms, events happen slowly, easy to follow individual blocks)
- **Normal** = 5x (default, good balance of visibility and demo pacing)
- **Fast** = 20x (rapid, shows aggregate patterns, good for stress tests)

Add a subtle label below: "Controls how fast events occur in the simulation"

### "Users" → "Concurrent sessions"

The "Users" slider is more accurately "concurrent inference sessions" — each session is a multi-turn conversation with its own KV cache.

```
Concurrent sessions    ●────────────── 50
                       10                500
```

### "Context Length" stays the same

32K is clear. But add a subtitle:

```
Context length    [4K] [16K] [32K] [64K] [128K]
Affects KV cache size per session
```

### G3.5 toggle — make it more prominent

The CMX toggle is THE most important control. Make it larger and more visually distinct:

```
┌──────────────────────────────────────────────────┐
│  ● G3.5 Context Memory (MinIO CMX)        [ON]  │
│  Enables KV cache offload to shared               │
│  object storage between GPUs                      │
│                                                   │
│  Toggle OFF to see what happens without          │
│  the context memory tier                          │
└──────────────────────────────────────────────────┘
```

When toggled OFF, show a warning banner at the top of the visualization:

```
⚠ CMX DISABLED — G3.5 tier bypassed. KV cache evicts from G3 directly to G4.
  Cross-GPU cache sharing is unavailable. Sessions may require full recomputation.
```

---

## Task 5: Active sessions section

### Replace the current block-grid with a session table

The current "Active Sessions — KV Cache Location" section shows a grid of colored rectangles. Each represents a session, colored by tier. This is too abstract — the user can't tell which session is where or why.

Replace with a compact session list showing the last 20 sessions:

```
ACTIVE SESSIONS (48 total, showing last 20)

Session    GPU    Tier          Status    Cache size
s-abc12    A      G1 (HBM)     active    0.8 GB
s-def34    B      G3.5 (CMX)   idle      1.2 GB      ← evicted to shared
s-ghi56    A      G2 (DRAM)    idle      0.6 GB
s-jkl78    B      G1 (HBM)     active    0.9 GB
s-mno90    —      G4           idle      1.1 GB      ← cold archive
...
```

Color the tier cell background to match the tier's color. Active sessions get a subtle pulse. Sessions in G3.5 get a MinIO green highlight. Sessions in G4 get a gray "cold" indicator.

When a session migrates cross-GPU (the key CMX moment), briefly highlight that row with a teal flash animation.

---

## Task 6: Event stream

### Replace "Waiting for simulation..." with a live event log

Show the last 10 events as they happen:

```
EVENT STREAM

12:34:05  ↓ EVICT s-abc12 GPU-A G1 → G2 (G1 full)
12:34:05  ↓ EVICT s-def34 GPU-A G3 → G3.5 (S3 PUT 0.8GB)
12:34:06  ↑ PROMOTE s-ghi56 G3.5 → GPU-B G1 (cross-GPU migration!)
12:34:06  ⚡ RECOMPUTE s-jkl78 on GPU-B (cache in G4, too slow)
12:34:07  + NEW s-mno90 → GPU-A G1
12:34:07  ↓ EVICT s-pqr12 GPU-B G2 → G3
```

Event type icons:
- `↓` = eviction (moving down the hierarchy)
- `↑` = promotion (moving up — the good path)
- `⚡` = recomputation (the bad path — highlighted red)
- `+` = new session assigned
- `×` = session terminated

Cross-GPU promotions get highlighted in teal with `(cross-GPU migration!)` suffix.
Recomputations get highlighted in red.

When CMX is OFF and recomputations spike, the event stream fills with red `⚡ RECOMPUTE` entries — a very visual indicator that things are going wrong.

---

## Task 7: Scenario buttons update

Update the pre-built scenarios for dual-GPU:

### "Multi-turn chat burst"
- 100 sessions, 32K context, both GPUs busy
- Lots of idle/return cycles → shows G3.5 absorbing overflow from both GPUs
- ~30% of returns go to the other GPU → shows cross-GPU migration

### "Agentic deep reasoning"
- 10 sessions, 128K context, massive KV caches
- Each session's cache is ~32GB → doesn't fit in any single GPU's G1+G2
- G3.5 holds the overflow → both GPUs can serve these sessions
- Without CMX → G4 is too slow, recomputation dominates

### "GPU migration stress test" (NEW)
- 200 sessions, 16K context, high churn
- Aggressive load balancing → 50% of returns route to the other GPU
- Shows G3.5 as the "shared shelf" between GPUs
- Without CMX → every cross-GPU return requires full recomputation

### "Scale comparison" (NEW)
- Runs two rounds automatically:
  1. First round: CMX OFF, 30 seconds → metrics captured
  2. Second round: CMX ON, 30 seconds → metrics captured
  3. Shows side-by-side comparison at the end

---

## Verification

### Unit tests

```python
def test_dual_gpu_state():
    """Simulation state should have 2 GPUs with separate G1/G2/G3."""
    config = SimulationConfig(gpu_count=2)
    state = SimulationState(config)
    assert len(state.gpus) == 2
    assert state.gpus[0].id == "gpu-a"
    assert state.gpus[1].id == "gpu-b"
    assert state.gpus[0].g1.capacity_gb == config.g1_capacity_gb_per_gpu

def test_shared_tiers():
    """G3.5 and G4 should be shared across GPUs."""
    config = SimulationConfig(gpu_count=2, g35_capacity_gb=40)
    state = SimulationState(config)
    assert state.shared_g35.capacity_gb == 40
    # Both GPUs should write to the same shared tier
    
def test_cross_gpu_migration():
    """Session returning to different GPU should go through G3.5."""
    # Create session on GPU-A, evict to G3.5
    # Session returns, routed to GPU-B
    # Should promote from G3.5 to GPU-B's G1 (not recompute)
    ...

def test_cmx_off_forces_recomputation():
    """With CMX disabled, cross-GPU return should recompute."""
    config = SimulationConfig(cmx_enabled=False)
    # Create session on GPU-A, evict past G3 → goes to G4 (no G3.5)
    # Session returns to GPU-B → must recompute
    ...

def test_metrics_clamped():
    """No metric should exceed 100% or go negative."""
    # Run simulation for 100 ticks
    # Check all percentage metrics: 0 <= value <= 100
    ...

def test_session_routing_balances_gpus():
    """New sessions should route to the GPU with more G1 capacity."""
    # Fill GPU-A's G1 to 90%
    # Next session should go to GPU-B
    ...
```

### Playwright E2E

```typescript
test.describe('Inference Simulator Dual-GPU', () => {
  test.beforeAll(async () => {
    // Deploy STX Experience, open simulation UI
  });

  test('shows two GPU columns', async ({ page }) => {
    await expect(page.locator('[data-testid="gpu-column-a"]')).toBeVisible();
    await expect(page.locator('[data-testid="gpu-column-b"]')).toBeVisible();
    await expect(page.locator('text=GPU-A')).toBeVisible();
    await expect(page.locator('text=GPU-B')).toBeVisible();
  });

  test('shows shared G3.5 and G4 tiers', async ({ page }) => {
    await expect(page.locator('[data-testid="shared-g35"]')).toBeVisible();
    await expect(page.locator('[data-testid="shared-g4"]')).toBeVisible();
    await expect(page.locator('text=Shared storage')).toBeVisible();
  });

  test('tier percentages never exceed 100', async ({ page }) => {
    // Start simulation
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    
    // Check all percentage values
    const pctElements = page.locator('[data-testid^="tier-pct-"]');
    const count = await pctElements.count();
    for (let i = 0; i < count; i++) {
      const text = await pctElements.nth(i).textContent();
      const value = parseInt(text!.replace('%', ''));
      expect(value).toBeLessThanOrEqual(100);
      expect(value).toBeGreaterThanOrEqual(0);
    }
  });

  test('metrics are valid numbers', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    
    // GPU utilization should be 0-100
    const gpuA = await page.locator('[data-testid="metric-gpu-a-util"]').textContent();
    expect(parseInt(gpuA!)).toBeLessThanOrEqual(100);
    
    // Cache hit rate should be 0-100
    const hitRate = await page.locator('[data-testid="metric-cache-hit"]').textContent();
    expect(parseInt(hitRate!)).toBeLessThanOrEqual(100);
    
    // Recomputations should be a non-negative integer
    const recomps = await page.locator('[data-testid="metric-recomps"]').textContent();
    expect(parseInt(recomps!)).toBeGreaterThanOrEqual(0);
  });

  test('toggling CMX off grays out G3.5', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(3000);
    
    // Toggle CMX off
    await page.click('[data-testid="cmx-toggle"]');
    
    // G3.5 bar should be visually disabled
    await expect(page.locator('[data-testid="shared-g35"]')).toHaveClass(/disabled/);
    
    // Warning banner should appear
    await expect(page.locator('[data-testid="cmx-off-warning"]')).toBeVisible();
  });

  test('CMX off increases recomputations', async ({ page }) => {
    // Run with CMX on for 5 seconds
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    const recompsOn = parseInt(await page.locator('[data-testid="metric-recomps"]').textContent() || '0');
    
    // Toggle CMX off, wait 5 more seconds
    await page.click('[data-testid="cmx-toggle"]');
    await page.waitForTimeout(5000);
    const recompsOff = parseInt(await page.locator('[data-testid="metric-recomps"]').textContent() || '0');
    
    // Recomputations should increase after CMX is disabled
    expect(recompsOff).toBeGreaterThan(recompsOn);
  });

  test('event stream shows cross-GPU migrations', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(10000);
    
    // Should see at least one cross-GPU migration event
    await expect(page.locator('text=cross-GPU')).toBeVisible({ timeout: 15000 });
  });

  test('session list shows GPU assignment', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    
    // Session table should show GPU-A and GPU-B assignments
    await expect(page.locator('[data-testid="session-gpu-a"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="session-gpu-b"]').first()).toBeVisible();
  });
});
```

---

## What NOT to do

- Don't show individual KV blocks as rectangles inside tier bars — use simple fill bars. The block-level detail goes in the session list.
- Don't allow metrics to exceed 100% — clamp everything. If the simulation math allows over-capacity (queued evictions), show 100% with a "pressure" indicator instead.
- Don't make the two GPU columns different sizes — they should be identical, side by side, emphasizing symmetry.
- Don't animate block movement with DOM elements flying across the screen — it'll be janky. Instead, show the event in the event stream log and update the bar fills smoothly via CSS transitions.
- Don't add more than 2 GPUs — 2 is enough to demonstrate shared context. More GPUs add complexity without clarity.
- Don't change the MinIO S3 integration — the simulation should still write real objects to MinIO for G3.5 and G4. The dual-GPU change is in the simulation logic and UI, not in the storage backend.
