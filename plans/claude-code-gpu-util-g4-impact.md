# Claude Code Instruction: GPU Utilization Model & G4 Impact Visualization

Apply AFTER `claude-code-inference-sim-complete.md` (already implemented).

Read before starting:
- `components/inference-sim/app/simulation/engine.py` — simulation engine
- `components/inference-sim/app/simulation/kv_block_manager.py` — block manager
- `components/inference-sim/app/static/index.html` — simulation UI

---

## The core insight this file implements

**A GPU cannot do inference while waiting for KV cache I/O.** Every time a session returns and its KV cache needs to be promoted back to G1 (GPU HBM), the GPU stalls until the transfer completes. The stall duration depends entirely on where the cache is:

| Source tier | I/O latency | GPU stall |
|-------------|------------|-----------|
| G1 (already there) | 0 | None |
| G2 (CPU DRAM) | ~100 ns | Negligible |
| G3 (local NVMe) | ~100 μs | Tiny |
| G3.5 (MinIO, RDMA) | ~500 μs | Small |
| G3.5 (MinIO, S3/TCP) | ~5-10 ms | Noticeable |
| G4 (enterprise) | ~50-200 ms | Significant |
| Recompute (no cache) | ~500-2000 ms | Massive (and wastes compute) |

This means **GPU utilization is a direct function of storage latency**. Faster G3.5 access → less GPU stall time → higher effective utilization → better GPU ROI. This is MinIO's value proposition in one metric.

---

## Task 1: Accurate GPU utilization model

### Replace the current utilization calculation

The current model just tracks G1 fill percentage, which doesn't reflect actual compute efficiency. Replace it with a time-budget model.

File: `components/inference-sim/app/simulation/engine.py`

Add a `GPUTimeTracker` that accumulates time budgets per tick:

```python
from dataclasses import dataclass, field
from collections import deque

@dataclass
class GPUTickBudget:
    """How a single GPU spent one tick of time."""
    active_inference: float = 0.0    # Fraction of tick doing useful decode/prefill
    io_stall: float = 0.0           # Fraction of tick waiting for KV cache I/O
    recompute: float = 0.0          # Fraction of tick recomputing KV cache (wasted work)
    idle: float = 0.0               # Fraction of tick with nothing to do

@dataclass
class GPUTimeTracker:
    """
    Tracks how each GPU spends its time over a rolling window.
    
    Each tick, a GPU's time budget sums to 1.0:
      active_inference + io_stall + recompute + idle = 1.0
    
    Over a 100-tick rolling window, we compute averages.
    """
    window_size: int = 100
    history: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Pending stalls: when a promotion starts, register the stall duration.
    # The GPU is stalled for that many ticks.
    remaining_stall_ticks: int = 0
    remaining_recompute_ticks: int = 0
    
    def record_tick(self, active_sessions: int, max_sessions: int):
        """
        Record one tick of GPU time allocation.
        
        If the GPU is stalled on I/O or recomputing, those take priority.
        Remaining capacity goes to active inference.
        Whatever's left is idle.
        """
        budget = GPUTickBudget()
        
        # I/O stalls take absolute priority — GPU literally can't proceed
        if self.remaining_stall_ticks > 0:
            budget.io_stall = 1.0
            self.remaining_stall_ticks -= 1
            self.history.append(budget)
            return
        
        # Recomputation burns GPU cycles on wasted work
        if self.remaining_recompute_ticks > 0:
            budget.recompute = 1.0
            self.remaining_recompute_ticks -= 1
            self.history.append(budget)
            return
        
        # Normal operation: fraction of capacity used for active inference
        if max_sessions > 0 and active_sessions > 0:
            budget.active_inference = min(1.0, active_sessions / max_sessions)
            budget.idle = 1.0 - budget.active_inference
        else:
            budget.idle = 1.0
        
        self.history.append(budget)
    
    def register_io_stall(self, ticks: int):
        """Called when a KV cache promotion starts — GPU will stall for N ticks."""
        self.remaining_stall_ticks += ticks
    
    def register_recompute(self, ticks: int):
        """Called when a session must be recomputed — GPU burns cycles."""
        self.remaining_recompute_ticks += ticks
    
    def utilization(self) -> dict:
        """
        Compute rolling-window averages.
        Returns percentages that sum to ~100%.
        """
        if not self.history:
            return {"active": 0, "io_stall": 0, "recompute": 0, "idle": 100}
        
        n = len(self.history)
        active = sum(b.active_inference for b in self.history) / n * 100
        io_stall = sum(b.io_stall for b in self.history) / n * 100
        recompute = sum(b.recompute for b in self.history) / n * 100
        idle = sum(b.idle for b in self.history) / n * 100
        
        return {
            "active": min(100, max(0, round(active))),
            "io_stall": min(100, max(0, round(io_stall))),
            "recompute": min(100, max(0, round(recompute))),
            "idle": min(100, max(0, round(idle))),
        }
```

### Integrate the tracker into the engine

Each GPU gets its own `GPUTimeTracker`. When promotions or recomputes happen, register the stall:

```python
class SimulationEngine:
    def __init__(self, config, minio_backend=None):
        # ... existing init ...
        self.gpu_trackers = {
            "gpu-a": GPUTimeTracker(window_size=100),
            "gpu-b": GPUTimeTracker(window_size=100),
        }
    
    def _process_tick(self):
        events = []
        
        # ... existing tick logic (create sessions, idle/active transitions, 
        #     eviction cascade, etc.) ...
        
        # At end of tick: record time budget for each GPU
        for gpu in self.manager.gpus:
            tracker = self.gpu_trackers[gpu.id]
            active_on_gpu = len([
                s for s in self.manager.sessions
                if s.active and s.gpu_id == gpu.id and s.tier == "g1"
            ])
            # Max sessions a GPU can serve simultaneously depends on G1 capacity
            max_sessions = int(gpu.g1.capacity_gb / self.kv_size_gb()) if self.kv_size_gb() > 0 else 10
            tracker.record_tick(active_on_gpu, max_sessions)
        
        return events
```

When a promotion from a remote tier happens, register the I/O stall:

```python
def _handle_session_return(self, session, target_gpu_id):
    # ... existing logic to determine source tier and cross-GPU ...
    
    # Register I/O stall on the TARGET GPU
    stall_ticks = self.manager.compute_promotion_latency(session.tier)
    tracker = self.gpu_trackers[target_gpu_id]
    
    if is_recompute:
        tracker.register_recompute(stall_ticks)  # ~100 ticks for full recompute
    else:
        tracker.register_io_stall(stall_ticks)   # Depends on source tier
    
    # ... rest of promotion logic ...
```

The `compute_promotion_latency` already exists from the previous instruction and returns different tick counts per mode:

```python
def compute_promotion_latency(self, source_tier: str) -> int:
    latency_map = {
        "g1": 0,
        "g2": 1,       # ~100 ns — negligible
        "g3": 2,       # ~100 μs
    }
    if self.config.g35_mode == G35Mode.ACCELERATED:
        latency_map["g35"] = 3     # ~500 μs
    elif self.config.g35_mode == G35Mode.STANDARD:
        latency_map["g35"] = 15    # ~5-10 ms
    else:
        latency_map["g35"] = 999   # shouldn't happen
    
    latency_map["g4"] = 50         # ~50-200 ms
    return latency_map.get(source_tier, 100)  # 100 = recompute
```

### Updated WebSocket state

Add per-GPU utilization breakdown to the state snapshot:

```python
def _build_state_snapshot(self):
    return {
        # ... existing fields ...
        "gpus": [
            {
                "id": gpu.id,
                "g1": _tier_dict(gpu.g1),
                "g2": _tier_dict(gpu.g2),
                "g3": _tier_dict(gpu.g3),
                "utilization": self.gpu_trackers[gpu.id].utilization(),
                # ↑ NEW: { "active": 82, "io_stall": 8, "recompute": 3, "idle": 7 }
            }
            for gpu in self.manager.gpus
        ],
        "metrics": {
            # ... existing metrics ...
            # Replace old flat utilization with combined:
            "gpu_a_utilization": self.gpu_trackers["gpu-a"].utilization(),
            "gpu_b_utilization": self.gpu_trackers["gpu-b"].utilization(),
            "combined_effective_util": self._combined_effective_util(),
        },
    }

def _combined_effective_util(self) -> int:
    """Effective GPU utilization = active inference only (excludes stalls and recompute)."""
    utils = [self.gpu_trackers[gpu.id].utilization() for gpu in self.manager.gpus]
    avg_active = sum(u["active"] for u in utils) / len(utils)
    return min(100, max(0, round(avg_active)))
```

---

## Task 2: GPU utilization visualization — stacked bar

### Replace the simple percentage with a stacked horizontal bar

The current metrics panel shows "GPU-A: 65%" as a single number. Replace with a stacked bar that shows *why* the GPU isn't at 100%.

The four segments in the stacked bar:
- **Green** (`#1D9E75`) = active inference (useful work)
- **Amber** (`#EF9F27`) = I/O stall (waiting for KV cache transfer)
- **Red** (`#E85D24`) = recomputation (wasted work — rebuilding cache that was lost)
- **Gray** (implicit remaining space) = idle (no sessions to serve)

```html
<div class="gpu-util-section">
  <div class="gpu-util-header">GPU UTILIZATION</div>
  
  <div class="gpu-util-row" id="gpu-util-a">
    <div class="gpu-util-label">GPU-A</div>
    <div class="gpu-util-bar-track">
      <div class="gpu-util-segment segment-active" id="gpu-a-active"></div>
      <div class="gpu-util-segment segment-stall" id="gpu-a-stall"></div>
      <div class="gpu-util-segment segment-recompute" id="gpu-a-recompute"></div>
    </div>
    <div class="gpu-util-value" id="gpu-a-effective">—</div>
  </div>
  
  <div class="gpu-util-row" id="gpu-util-b">
    <div class="gpu-util-label">GPU-B</div>
    <div class="gpu-util-bar-track">
      <div class="gpu-util-segment segment-active" id="gpu-b-active"></div>
      <div class="gpu-util-segment segment-stall" id="gpu-b-stall"></div>
      <div class="gpu-util-segment segment-recompute" id="gpu-b-recompute"></div>
    </div>
    <div class="gpu-util-value" id="gpu-b-effective">—</div>
  </div>
  
  <div class="gpu-util-legend">
    <span class="legend-item"><span class="legend-dot dot-active"></span> Inference</span>
    <span class="legend-item"><span class="legend-dot dot-stall"></span> I/O stall</span>
    <span class="legend-item"><span class="legend-dot dot-recompute"></span> Recompute</span>
    <span class="legend-item"><span class="legend-dot dot-idle"></span> Idle</span>
  </div>
  
  <div class="gpu-util-effective">
    Effective utilization: <strong id="combined-effective-value">—</strong>
    <span class="gpu-util-note">(only active inference counts — stalls and recomputation are waste)</span>
  </div>
</div>
```

```css
.gpu-util-section { margin-bottom: 16px; }
.gpu-util-header { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: rgba(255,255,255,0.5); margin-bottom: 10px; }
.gpu-util-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.gpu-util-label { font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.6); width: 42px; flex-shrink: 0; }
.gpu-util-bar-track { flex: 1; height: 20px; background: rgba(255,255,255,0.04); border-radius: 4px; display: flex; overflow: hidden; }
.gpu-util-segment { height: 100%; transition: width 0.5s ease; min-width: 0; }
.segment-active { background: #1D9E75; }
.segment-stall { background: #EF9F27; }
.segment-recompute { background: #E85D24; }
.gpu-util-value { font-size: 13px; font-weight: 700; width: 36px; text-align: right; font-variant-numeric: tabular-nums; }
.gpu-util-legend { display: flex; gap: 12px; margin-top: 6px; margin-bottom: 8px; }
.legend-item { font-size: 9px; color: rgba(255,255,255,0.4); display: flex; align-items: center; gap: 4px; }
.legend-dot { width: 8px; height: 8px; border-radius: 2px; }
.dot-active { background: #1D9E75; } .dot-stall { background: #EF9F27; } .dot-recompute { background: #E85D24; } .dot-idle { background: rgba(255,255,255,0.08); }
.gpu-util-effective { font-size: 11px; color: rgba(255,255,255,0.5); padding: 6px 8px; background: rgba(255,255,255,0.02); border-radius: 4px; }
.gpu-util-note { font-size: 9px; color: rgba(255,255,255,0.3); }
```

Update each tick from WebSocket data:

```javascript
function updateGPUUtilization(gpus) {
  gpus.forEach(gpu => {
    const suffix = gpu.id === 'gpu-a' ? 'a' : 'b';
    const u = gpu.utilization;
    document.getElementById(`gpu-${suffix}-active`).style.width = u.active + '%';
    document.getElementById(`gpu-${suffix}-stall`).style.width = u.io_stall + '%';
    document.getElementById(`gpu-${suffix}-recompute`).style.width = u.recompute + '%';
    const valueEl = document.getElementById(`gpu-${suffix}-effective`);
    valueEl.textContent = u.active + '%';
    valueEl.className = 'gpu-util-value ' + (u.active >= 80 ? 'val-good' : u.active >= 50 ? 'val-warn' : 'val-bad');
  });
  const avg = Math.round(gpus.reduce((sum, g) => sum + g.utilization.active, 0) / gpus.length);
  document.getElementById('combined-effective-value').textContent = avg + '%';
}
```

Place the GPU utilization section at the **top** of the right-side metrics panel, above the existing metric cards. It's the most important number.

---

## Task 3: G4 "under pressure" indicator

When G3.5 is disabled, G4 absorbs all overflow. Make this visually obvious.

```javascript
function updateG4Bar(g4State, g35Mode) {
  const g4Bar = document.getElementById('tier-bar-g4');
  const g4Desc = document.getElementById('tier-desc-g4');
  if (g35Mode === 'disabled') {
    g4Bar.classList.add('g4-stressed');
    g4Desc.innerHTML = '⚠ absorbing G3.5 overflow';
    g4Desc.classList.add('tier-stress-label');
  } else {
    g4Bar.classList.remove('g4-stressed');
    g4Desc.innerHTML = 'Cold archive';
    g4Desc.classList.remove('tier-stress-label');
  }
}
```

```css
.g4-stressed .tier-bar-fill {
  background: repeating-linear-gradient(-45deg, var(--color-g4), var(--color-g4) 8px, rgba(232,93,36,0.3) 8px, rgba(232,93,36,0.3) 16px) !important;
  animation: g4-pulse 2s ease-in-out infinite;
}
@keyframes g4-pulse { 0%, 100% { opacity: 0.85; } 50% { opacity: 1; } }
.tier-stress-label { font-size: 9px; color: #EF9F27; font-weight: 600; }
```

---

## Task 4: Live mode comparison strip

A three-column comparison that builds up as the user switches modes. Auto-captures a snapshot of the current mode's metrics whenever the user switches to a different mode.

```
┌─ MODE COMPARISON ──────────────────────────────────────────────┐
│   Disabled           Standard (S3/TCP)    Accelerated (RDMA)   │
│   GPU eff: 38%       GPU eff: 74%         GPU eff: 91%   ←now │
│   TTFT: 1,240 ms     TTFT: 145 ms        TTFT: 72 ms         │
│   I/O stall: 22%     I/O stall: 11%      I/O stall: 3%       │
│   Recompute: 28%     Recompute: 3%       Recompute: 0%        │
│   G4 load: 58%       G4 load: 8%         G4 load: 6%          │
│   Cross-GPU via:     Cross-GPU via:      Cross-GPU via:       │
│   recompute          S3 GET ~10ms        RDMA GET ~500μs      │
└─────────────────────────────────────────────────────────────────┘
```

```javascript
const modeSnapshots = { disabled: null, standard: null, accelerated: null };

function buildSnapshot(metrics, gpus, g35Mode) {
  const avgActive = Math.round(gpus.reduce((s, g) => s + g.utilization.active, 0) / gpus.length);
  const avgStall = Math.round(gpus.reduce((s, g) => s + g.utilization.io_stall, 0) / gpus.length);
  const avgRecomp = Math.round(gpus.reduce((s, g) => s + g.utilization.recompute, 0) / gpus.length);
  return {
    gpu_effective: avgActive, ttft: metrics.avg_ttft_ms,
    io_stall: avgStall, recompute_pct: avgRecomp,
    g4_pct: metrics.shared?.g4?.pct || 0,
    cross_gpu: metrics.cross_gpu_migrations,
    via: g35Mode === 'disabled' ? 'recompute' : g35Mode === 'standard' ? 'S3 GET ~10 ms' : 'RDMA GET ~500 μs',
  };
}

function onModeChange(newMode) {
  const current = simulation.config.g35_mode;
  if (current !== newMode && simulation.running && latestState) {
    modeSnapshots[current] = buildSnapshot(latestState.metrics, latestState.gpus, current);
  }
  simulation.setG35Mode(newMode);
  renderCrossGpuPath(newMode);
  updateG4Bar(latestState?.shared?.g4, newMode);
  renderComparisonStrip();
  // Update policy panel G3.5 tier visibility
  const polG35 = document.getElementById('pol-g35-tier');
  if (polG35) {
    polG35.classList.toggle('disabled', newMode === 'disabled');
    document.getElementById('pol-g3-target').textContent =
      newMode === 'disabled' ? '↓ to G4 (skip G3.5)' : '↓ to G3.5';
  }
}

function renderComparisonStrip() {
  const strip = document.getElementById('mode-comparison');
  const modes = ['disabled', 'standard', 'accelerated'];
  const labels = { disabled: 'Disabled', standard: 'Standard (S3/TCP)', accelerated: 'Accelerated (RDMA)' };

  strip.innerHTML = '<div class="cmp-title">MODE COMPARISON</div><div class="cmp-grid">' +
    modes.map(mode => {
      const isActive = mode === simulation.config.g35_mode;
      const snap = isActive ? buildSnapshot(latestState.metrics, latestState.gpus, mode) : modeSnapshots[mode];
      if (!snap) return `<div class="cmp-col empty"><div class="cmp-col-hdr">${labels[mode]}</div><div class="cmp-empty">Switch to this mode to capture</div></div>`;
      return `
        <div class="cmp-col ${isActive ? 'active' : ''}">
          <div class="cmp-col-hdr">${labels[mode]}${isActive ? ' <span class="cmp-live">● live</span>' : ''}</div>
          <div class="cmp-row cmp-highlight"><span>GPU effective</span><span class="${snap.gpu_effective >= 80 ? 'val-good' : snap.gpu_effective >= 50 ? 'val-warn' : 'val-bad'}">${snap.gpu_effective}%</span></div>
          <div class="cmp-row"><span>Avg TTFT</span><span class="${snap.ttft <= 100 ? 'val-good' : snap.ttft <= 500 ? 'val-warn' : 'val-bad'}">${snap.ttft} ms</span></div>
          <div class="cmp-row"><span>I/O stall</span><span class="${snap.io_stall > 15 ? 'val-bad' : snap.io_stall > 5 ? 'val-warn' : 'val-good'}">${snap.io_stall}%</span></div>
          <div class="cmp-row"><span>Recompute</span><span class="${snap.recompute_pct > 10 ? 'val-bad' : snap.recompute_pct > 0 ? 'val-warn' : 'val-good'}">${snap.recompute_pct}%</span></div>
          <div class="cmp-row"><span>G4 load</span><span class="${snap.g4_pct > 30 ? 'val-warn' : 'val-good'}">${snap.g4_pct}%</span></div>
          <div class="cmp-row cmp-via"><span>Cross-GPU via</span><span class="via-pill">${snap.via}</span></div>
        </div>`;
    }).join('') + '</div>';
}
```

CSS:

```css
#mode-comparison { border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px; margin-top: 16px; }
.cmp-title { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: rgba(255,255,255,0.5); margin-bottom: 10px; }
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.cmp-col { padding: 10px; border-radius: 6px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); }
.cmp-col.active { border-color: rgba(29,158,117,0.4); background: rgba(29,158,117,0.05); }
.cmp-col.empty { opacity: 0.35; }
.cmp-col-hdr { font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.7); margin-bottom: 8px; }
.cmp-live { font-size: 9px; color: #1D9E75; animation: live-blink 1.5s infinite; }
@keyframes live-blink { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.cmp-row { display: flex; justify-content: space-between; padding: 2px 0; font-size: 11px; color: rgba(255,255,255,0.4); }
.cmp-row span:last-child { font-weight: 600; font-variant-numeric: tabular-nums; }
.cmp-highlight { padding: 4px 0; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 4px; }
.val-good { color: #1D9E75; } .val-warn { color: #EF9F27; } .val-bad { color: #E85D24; }
.via-pill { font-size: 9px; font-family: monospace; padding: 2px 5px; background: rgba(255,255,255,0.04); border-radius: 3px; }
.cmp-empty { font-size: 10px; color: rgba(255,255,255,0.25); text-align: center; padding: 24px 8px; font-style: italic; }
```

Place between the tier bars and the session list. Refresh active column on every WebSocket message.

---

## Task 5: Cross-GPU return path diagram

A small inline diagram in the policy panel showing the cross-GPU return flow for the current mode. Swaps content on mode change.

### When G3.5 enabled:

```javascript
function renderCrossGpuPath(g35Mode) {
  const container = document.getElementById('cross-gpu-path');
  if (g35Mode === 'disabled') {
    container.innerHTML = `
      <div class="cgp-hdr">CROSS-GPU RETURN PATH</div>
      <div class="cgp-scenario">User returns → Dynamo routes to GPU-B</div>
      <div class="cgp-diagram">
        <div class="cgp-node"><div class="cgp-lbl">GPU-A</div><div class="cgp-box">G1</div></div>
        <div class="cgp-flow"><div class="cgp-step">①evict</div><div class="cgp-arr">→</div></div>
        <div class="cgp-node"><div class="cgp-lbl">G4</div><div class="cgp-box cgp-cold">cold</div><div class="cgp-det">~50-200 ms</div></div>
        <div class="cgp-flow"><div class="cgp-arr cgp-arr-bad">✗→</div></div>
        <div class="cgp-node"><div class="cgp-lbl">GPU-B</div><div class="cgp-box cgp-recomp">G1</div><div class="cgp-det cgp-det-bad">⚡recompute</div></div>
      </div>
      <div class="cgp-res cgp-res-bad">Cache wasted. Full recomputation. GPU stalls ~500-2000 ms.</div>`;
  } else {
    const lat = g35Mode === 'accelerated' ? '~500 μs (RDMA)' : '~5-10 ms (S3/TCP)';
    const proto = g35Mode === 'accelerated' ? 'NVMe-oF / RDMA' : 'S3 over TCP';
    container.innerHTML = `
      <div class="cgp-hdr">CROSS-GPU RETURN PATH</div>
      <div class="cgp-scenario">User returns → Dynamo routes to GPU-B</div>
      <div class="cgp-diagram">
        <div class="cgp-node"><div class="cgp-lbl">GPU-A</div><div class="cgp-box">G1</div></div>
        <div class="cgp-flow"><div class="cgp-step">①evict</div><div class="cgp-arr">→</div></div>
        <div class="cgp-node cgp-node-minio"><div class="cgp-lbl">G3.5</div><div class="cgp-box cgp-minio">MinIO</div><div class="cgp-det">${proto}</div><div class="cgp-det">②PUT + GET</div></div>
        <div class="cgp-flow"><div class="cgp-step">③promote</div><div class="cgp-arr">→</div></div>
        <div class="cgp-node"><div class="cgp-lbl">GPU-B</div><div class="cgp-box cgp-promoted">G1</div></div>
      </div>
      <div class="cgp-lat">Round-trip: ${lat}</div>
      <div class="cgp-res cgp-res-good">Cache reused. No recomputation. GPU stays busy.</div>`;
  }
}
```

```css
.cgp-hdr { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: rgba(255,255,255,0.5); margin-bottom: 4px; }
.cgp-scenario { font-size: 10px; color: rgba(255,255,255,0.35); margin-bottom: 10px; }
.cgp-diagram { display: flex; align-items: center; justify-content: center; gap: 4px; padding: 8px 0; }
.cgp-node { text-align: center; }
.cgp-lbl { font-size: 9px; color: rgba(255,255,255,0.45); margin-bottom: 3px; }
.cgp-box { width: 40px; height: 40px; border: 1.5px solid rgba(232,93,36,0.4); background: rgba(232,93,36,0.08); border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: #E85D24; }
.cgp-minio { border-color: rgba(29,158,117,0.5); background: rgba(29,158,117,0.12); color: #1D9E75; width: 48px; }
.cgp-promoted { border-color: rgba(29,158,117,0.6); background: rgba(29,158,117,0.15); color: #1D9E75; }
.cgp-cold { border-color: rgba(136,135,128,0.4); background: rgba(136,135,128,0.1); color: #888780; }
.cgp-recomp { border-color: rgba(232,93,36,0.6); background: rgba(232,93,36,0.2); animation: recomp-flash 1s ease-in-out infinite; }
@keyframes recomp-flash { 0%,100% { background: rgba(232,93,36,0.15); } 50% { background: rgba(232,93,36,0.35); } }
.cgp-det { font-size: 8px; color: rgba(255,255,255,0.3); margin-top: 2px; }
.cgp-det-bad { color: #E85D24; font-weight: 600; font-size: 9px; }
.cgp-flow { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.cgp-step { font-size: 8px; color: rgba(255,255,255,0.35); }
.cgp-arr { font-size: 14px; color: rgba(255,255,255,0.25); font-family: monospace; }
.cgp-arr-bad { color: #E85D24; }
.cgp-lat { text-align: center; font-size: 10px; color: rgba(29,158,117,0.8); font-family: monospace; margin: 4px 0; }
.cgp-res { font-size: 10px; font-weight: 500; text-align: center; padding: 5px 8px; border-radius: 4px; margin-top: 6px; }
.cgp-res-good { color: #1D9E75; background: rgba(29,158,117,0.08); }
.cgp-res-bad { color: #E85D24; background: rgba(232,93,36,0.08); }
```

Place inside the eviction policy panel, below the tier chain. Call `renderCrossGpuPath(mode)` on every mode change.

---

## Task 6: Scale comparison scenario update

Update the "Scale comparison" button to run three rounds and auto-populate all columns:

```javascript
async function runScaleComparison() {
  const modes = ['disabled', 'standard', 'accelerated'];
  const duration = 20000; // 20 seconds per mode

  for (const mode of modes) {
    onModeChange(mode);
    showToast(`Running ${mode} mode for 20s...`);
    if (!simulation.running) { simulation.start(); }
    else { simulation.reset(); simulation.start(); }
    await sleep(duration);
    modeSnapshots[mode] = buildSnapshot(latestState.metrics, latestState.gpus, mode);
    renderComparisonStrip();
  }

  simulation.stop();
  showToast('Comparison complete — all three modes captured');
  onModeChange('accelerated');  // End on the good note
  renderComparisonStrip();
}
```

---

## Expected metric ranges by mode

Tune engine parameters if needed to hit these ranges:

| Metric | Disabled | Standard (TCP) | Accelerated (RDMA) |
|--------|----------|----------------|---------------------|
| GPU effective util | 35-55% | 70-85% | 88-96% |
| I/O stall | 15-30% | 8-15% | 1-5% |
| Recompute waste | 15-35% | 2-8% | 0-2% |
| Avg TTFT | 800-2000 ms | 100-250 ms | 40-90 ms |
| G4 load | 40-65% | 5-15% | 3-10% |

The headline: **GPU effective utilization goes from ~40% → ~78% → ~92%.** MinIO nearly doubles GPU ROI even without BlueField.

---

## Verification

### Unit tests

```python
def test_gpu_time_tracker_sums_to_100():
    tracker = GPUTimeTracker(window_size=50)
    for _ in range(100):
        tracker.record_tick(active_sessions=5, max_sessions=10)
    u = tracker.utilization()
    total = u["active"] + u["io_stall"] + u["recompute"] + u["idle"]
    assert 98 <= total <= 102

def test_io_stall_higher_from_g4_than_g35():
    fast = GPUTimeTracker(window_size=50)
    fast.register_io_stall(3)
    for _ in range(50): fast.record_tick(5, 10)
    slow = GPUTimeTracker(window_size=50)
    slow.register_io_stall(50)
    for _ in range(50): slow.record_tick(5, 10)
    assert slow.utilization()["io_stall"] > fast.utilization()["io_stall"]

def test_recompute_counted_separately():
    tracker = GPUTimeTracker(window_size=20)
    tracker.register_recompute(10)
    for _ in range(20): tracker.record_tick(5, 10)
    u = tracker.utilization()
    assert u["recompute"] > 0
    assert u["active"] < 100

def test_accelerated_higher_util_than_disabled():
    results = {}
    for mode in [G35Mode.DISABLED, G35Mode.ACCELERATED]:
        config = SimulationConfig(g35_mode=mode, users=80)
        engine = SimulationEngine(config)
        for _ in range(500): engine._process_tick()
        snap = engine._build_state_snapshot()
        results[mode] = snap["metrics"]["combined_effective_util"]
    assert results[G35Mode.ACCELERATED] > results[G35Mode.DISABLED]

def test_standard_between_disabled_and_accelerated():
    results = {}
    for mode in [G35Mode.DISABLED, G35Mode.STANDARD, G35Mode.ACCELERATED]:
        config = SimulationConfig(g35_mode=mode, users=80)
        engine = SimulationEngine(config)
        for _ in range(500): engine._process_tick()
        snap = engine._build_state_snapshot()
        results[mode] = snap["metrics"]["combined_effective_util"]
    assert results[G35Mode.DISABLED] < results[G35Mode.STANDARD]
    assert results[G35Mode.STANDARD] <= results[G35Mode.ACCELERATED]

def test_state_includes_utilization_breakdown():
    config = SimulationConfig()
    engine = SimulationEngine(config)
    for _ in range(100): engine._process_tick()
    snap = engine._build_state_snapshot()
    for gpu in snap["gpus"]:
        u = gpu["utilization"]
        assert all(k in u for k in ["active", "io_stall", "recompute", "idle"])
```

### Playwright E2E

```typescript
test.describe('GPU Utilization & G4 Impact', () => {
  test('shows stacked utilization bars', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    await expect(page.locator('#gpu-a-active')).toBeVisible();
    await expect(page.locator('#gpu-a-stall')).toBeVisible();
    await expect(page.locator('#gpu-a-recompute')).toBeVisible();
    await expect(page.locator('text=Inference')).toBeVisible();
    await expect(page.locator('text=I/O stall')).toBeVisible();
  });

  test('disabled mode shows lower effective utilization', async ({ page }) => {
    await page.click('[data-testid="g35-mode-accelerated"]');
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(8000);
    const accel = parseInt((await page.locator('#combined-effective-value').textContent())!);
    await page.click('[data-testid="g35-mode-disabled"]');
    await page.waitForTimeout(8000);
    const disabled = parseInt((await page.locator('#combined-effective-value').textContent())!);
    expect(disabled).toBeLessThan(accel);
  });

  test('disabled mode shows recompute segment', async ({ page }) => {
    await page.click('[data-testid="g35-mode-disabled"]');
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(8000);
    const width = await page.locator('#gpu-a-recompute').evaluate(el => parseFloat(getComputedStyle(el).width));
    expect(width).toBeGreaterThan(0);
  });

  test('G4 shows stress when G3.5 disabled', async ({ page }) => {
    await page.click('[data-testid="g35-mode-disabled"]');
    await expect(page.locator('.g4-stressed')).toBeVisible();
    await expect(page.locator('text=absorbing G3.5 overflow')).toBeVisible();
  });

  test('comparison auto-captures on mode switch', async ({ page }) => {
    await page.click('[data-testid="g35-mode-accelerated"]');
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    await page.click('[data-testid="g35-mode-standard"]');
    await page.waitForTimeout(1000);
    const accelCol = page.locator('.cmp-col').nth(2);
    await expect(accelCol).not.toHaveClass(/empty/);
  });

  test('cross-GPU path shows recompute when disabled', async ({ page }) => {
    await page.click('[data-testid="g35-mode-disabled"]');
    await expect(page.locator('text=recompute')).toBeVisible();
    await expect(page.locator('text=Cache wasted')).toBeVisible();
  });

  test('cross-GPU path shows MinIO when enabled', async ({ page }) => {
    await page.click('[data-testid="g35-mode-accelerated"]');
    await expect(page.locator('text=MinIO')).toBeVisible();
    await expect(page.locator('text=Cache reused')).toBeVisible();
  });
});
```

---

## What NOT to do

- Don't show GPU utilization as a single flat percentage anymore — always show the stacked breakdown
- Don't count recomputation as "active inference" — it's wasted GPU work, show it as red
- Don't let I/O stalls and recompute ticks overlap in the same tick — they're mutually exclusive (stall takes priority, then recompute, then normal operation)
- Don't animate the cross-GPU path diagram — keep it as a static inline diagram that swaps on mode change
- Don't add a manual "Capture snapshot" button — auto-capture on mode switch is less friction
- Don't show the comparison strip until simulation has run at least 3 seconds
