# Claude Code Instruction: Guided Demo Mode, SE Onboarding Overlay & G4 Storage Insights

Apply AFTER `claude-code-gpu-util-g4-impact.md` (already implemented).

Read before starting:
- `components/inference-sim/app/static/index.html` — simulation UI
- `components/inference-sim/app/simulation/engine.py` — simulation engine

---

## Part 1: Guided Demo Mode — Tell, Show, Tell

### Concept

The simulator currently drops the user into a dashboard with controls and expects them to figure out what to do. For an SE delivering a customer demo, this is risky — they might fumble with controls, forget to toggle the right setting, or lose the narrative thread.

The guided mode automates the entire demo as a scripted sequence:

1. **TELL** — A brief card appears explaining what's about to happen and why it matters
2. **SHOW** — The simulation auto-runs with the right settings, and UI elements highlight as events occur
3. **TELL** — A recap card appears with the captured metrics, explaining what the audience just saw

The SE clicks "Start guided demo" and the simulator walks through the entire story autonomously. The SE narrates along with the cards, or lets the cards speak for themselves.

### UI: Guided mode launcher

Add a "Guided demo" button alongside the existing scenario buttons:

```html
<div class="guided-launcher">
  <button id="guided-demo-btn" class="guided-btn">
    <span class="guided-btn-icon">▶</span>
    <div class="guided-btn-text">
      <div class="guided-btn-title">Guided demo</div>
      <div class="guided-btn-desc">Auto-runs the full story: disabled → standard → accelerated</div>
    </div>
  </button>
</div>
```

```css
.guided-launcher {
  margin-bottom: 12px;
}

.guided-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(29,158,117,0.12), rgba(29,158,117,0.04));
  border: 1px solid rgba(29,158,117,0.3);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  color: inherit;
}
.guided-btn:hover {
  border-color: rgba(29,158,117,0.5);
  background: linear-gradient(135deg, rgba(29,158,117,0.18), rgba(29,158,117,0.06));
}

.guided-btn-icon {
  font-size: 20px;
  color: #1D9E75;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(29,158,117,0.15);
  border-radius: 50%;
}

.guided-btn-title {
  font-size: 13px;
  font-weight: 600;
  color: rgba(255,255,255,0.85);
}

.guided-btn-desc {
  font-size: 10px;
  color: rgba(255,255,255,0.4);
  margin-top: 2px;
}
```

### Guided demo script definition

```javascript
const GUIDED_SCRIPT = [
  // --- Act 1: The Problem ---
  {
    phase: "tell",
    title: "The inference memory challenge",
    body: "Modern LLMs maintain a KV cache for every conversation — the model's short-term memory. As context windows grow to 128K+ tokens, this cache can reach tens of gigabytes per session.\n\nGPU HBM is fast but limited. When it fills up, cache gets evicted. If a user returns and their cache is gone, the GPU must recompute it from scratch — burning expensive compute cycles.",
    duration: 8000,    // Show for 8 seconds
    icon: "⚡",
  },
  {
    phase: "tell",
    title: "What you're about to see",
    body: "This simulation models two GPUs serving 50 concurrent inference sessions. We'll run three scenarios:\n\n1. No shared cache tier (the baseline)\n2. MinIO AIStor over standard S3/TCP\n3. MinIO AIStor over NVMe-oF/RDMA (BlueField-4)\n\nWatch the GPU utilization bar — it tells the whole story.",
    duration: 8000,
    icon: "🔬",
  },

  // --- Act 2: Disabled mode ---
  {
    phase: "tell",
    title: "Scenario 1: No shared tier (G3.5 disabled)",
    body: "KV cache evicts from local NVMe (G3) directly to enterprise storage (G4). When a session moves between GPUs, there's no fast shared layer — the GPU must recompute the entire KV cache.\n\nWatch for: red 'recompute' segments in the GPU bar, high TTFT, and G4 filling up.",
    duration: 6000,
    icon: "1",
    highlight: ["g35-mode-disabled"],   // Highlight this UI element
  },
  {
    phase: "show",
    mode: "disabled",
    duration: 18000,    // Run for 18 seconds
    highlights: {
      3000: { element: "gpu-a-recompute", tooltip: "Recompute waste — GPU burning cycles rebuilding lost cache" },
      6000: { element: "tier-bar-g4", tooltip: "G4 filling up — absorbing all the overflow" },
      10000: { element: "metric-recomps", tooltip: "Recomputation count climbing" },
      14000: { element: "combined-effective-value", tooltip: "Effective GPU utilization — low because of stalls and recompute" },
    },
  },
  {
    phase: "tell",
    title: "Scenario 1 results",
    useCapture: "disabled",   // Pull metrics from the captured snapshot
    body: "Without a shared cache tier:\n\n• GPU effective utilization: {gpu_effective}%\n• Time wasted on I/O stalls: {io_stall}%\n• Time wasted on recomputation: {recompute_pct}%\n• Average time to first token: {ttft} ms\n• G4 load: {g4_pct}%\n\nThat means {waste_pct}% of your GPU investment is doing no useful work.",
    duration: 8000,
    icon: "📊",
  },

  // --- Act 3: Standard mode ---
  {
    phase: "tell",
    title: "Scenario 2: MinIO AIStor over S3/TCP",
    body: "Now we enable the G3.5 tier — MinIO AIStor connected via standard S3 over TCP. No special hardware required. This works on any infrastructure you have today.\n\nKV cache evicts to MinIO instead of G4. When sessions move between GPUs, the cache is pulled from MinIO — no recomputation needed.",
    duration: 6000,
    icon: "2",
    highlight: ["g35-mode-standard"],
  },
  {
    phase: "show",
    mode: "standard",
    duration: 18000,
    highlights: {
      3000: { element: "shared-g35", tooltip: "G3.5 is absorbing overflow — shared between both GPUs" },
      8000: { element: "gpu-a-active", tooltip: "Green segment growing — more time on actual inference" },
      13000: { element: "combined-effective-value", tooltip: "Effective utilization improving significantly" },
    },
  },
  {
    phase: "tell",
    title: "Scenario 2 results",
    useCapture: "standard",
    body: "With MinIO AIStor over standard S3/TCP:\n\n• GPU effective utilization: {gpu_effective}% (was {prev_gpu_effective}%)\n• I/O stalls: {io_stall}% (was {prev_io_stall}%)\n• Recomputation: {recompute_pct}% (was {prev_recompute_pct}%)\n• Average TTFT: {ttft} ms (was {prev_ttft} ms)\n\nMinIO eliminated most recomputation using standard networking — no special hardware needed.",
    duration: 8000,
    icon: "📊",
    prevCapture: "disabled",
  },

  // --- Act 4: Accelerated mode ---
  {
    phase: "tell",
    title: "Scenario 3: MinIO AIStor over NVMe-oF/RDMA",
    body: "Now we enable hardware acceleration — BlueField-4 DPU with NVMe-over-Fabrics and RDMA. The KV cache transfers bypass the CPU entirely, running at 800 Gb/s with sub-millisecond latency.\n\nThis is the full STX architecture: Dynamo + NIXL + MinIO AIStor on BlueField-4.",
    duration: 6000,
    icon: "3",
    highlight: ["g35-mode-accelerated"],
  },
  {
    phase: "show",
    mode: "accelerated",
    duration: 18000,
    highlights: {
      3000: { element: "gpu-a-active", tooltip: "Green fills nearly the entire bar — GPU doing useful work" },
      8000: { element: "gpu-a-stall", tooltip: "I/O stall almost invisible — sub-millisecond transfers" },
      13000: { element: "combined-effective-value", tooltip: "Effective utilization approaching maximum" },
    },
  },
  {
    phase: "tell",
    title: "Scenario 3 results",
    useCapture: "accelerated",
    body: "With MinIO AIStor over NVMe-oF/RDMA:\n\n• GPU effective utilization: {gpu_effective}%\n• I/O stalls: {io_stall}%\n• Recomputation: {recompute_pct}%\n• Average TTFT: {ttft} ms\n\nGPU utilization went from {baseline_gpu}% → {standard_gpu}% → {accelerated_gpu}%.",
    duration: 8000,
    icon: "📊",
    prevCapture: "standard",
    baselineCapture: "disabled",
  },

  // --- Act 5: Recap ---
  {
    phase: "tell",
    title: "The MinIO AIStor value",
    body: "MinIO AIStor serves as the shared KV cache tier between GPU servers.\n\n• Works today on any infrastructure (S3/TCP)\n• Hardware-accelerated with BlueField-4 (RDMA)\n• Eliminates cross-GPU recomputation\n• Improves effective GPU utilization from ~{baseline_gpu}% to ~{accelerated_gpu}%\n• Scales to petabytes — handles any number of concurrent sessions\n\nThe same MinIO cluster that stores your training data, model weights, and checkpoints now also stores inference context. One storage platform for the entire AI lifecycle.",
    duration: 12000,
    icon: "🏁",
    isFinale: true,
  },
];
```

### Guided demo engine

```javascript
class GuidedDemoRunner {
  constructor(simulation, script) {
    this.simulation = simulation;
    this.script = script;
    this.currentStep = 0;
    this.running = false;
    this.captures = {};       // mode → captured snapshot
    this.overlayEl = document.getElementById('guided-overlay');
    this.cardEl = document.getElementById('guided-card');
    this.highlightEl = document.getElementById('guided-highlight');
    this.progressEl = document.getElementById('guided-progress');
  }

  async start() {
    this.running = true;
    this.currentStep = 0;
    this.captures = {};
    this.showOverlay();

    for (let i = 0; i < this.script.length && this.running; i++) {
      this.currentStep = i;
      this.updateProgress();
      const step = this.script[i];

      if (step.phase === 'tell') {
        await this.runTellStep(step);
      } else if (step.phase === 'show') {
        await this.runShowStep(step);
      }
    }

    this.hideOverlay();
    this.running = false;
  }

  stop() {
    this.running = false;
    this.simulation.stop();
    this.hideOverlay();
    this.clearHighlights();
  }

  async runTellStep(step) {
    // Build the card content, substituting captured metrics
    let body = step.body;
    if (step.useCapture && this.captures[step.useCapture]) {
      const snap = this.captures[step.useCapture];
      body = body
        .replace('{gpu_effective}', snap.gpu_effective)
        .replace('{io_stall}', snap.io_stall)
        .replace('{recompute_pct}', snap.recompute_pct)
        .replace('{ttft}', snap.ttft)
        .replace('{g4_pct}', snap.g4_pct)
        .replace('{waste_pct}', snap.io_stall + snap.recompute_pct);
    }
    if (step.prevCapture && this.captures[step.prevCapture]) {
      const prev = this.captures[step.prevCapture];
      body = body
        .replace('{prev_gpu_effective}', prev.gpu_effective)
        .replace('{prev_io_stall}', prev.io_stall)
        .replace('{prev_recompute_pct}', prev.recompute_pct)
        .replace('{prev_ttft}', prev.ttft);
    }
    if (step.baselineCapture && this.captures[step.baselineCapture]) {
      const base = this.captures[step.baselineCapture];
      body = body
        .replace('{baseline_gpu}', base.gpu_effective)
        .replace('{standard_gpu}', this.captures['standard']?.gpu_effective || '—')
        .replace('{accelerated_gpu}', this.captures['accelerated']?.gpu_effective || '—');
    }

    this.showCard({
      icon: step.icon,
      title: step.title,
      body: body,
      isFinale: step.isFinale || false,
      stepNumber: this.currentStep + 1,
      totalSteps: this.script.length,
    });

    if (step.highlight) {
      step.highlight.forEach(id => this.highlightElement(id));
    }

    await this.wait(step.duration);
    this.clearHighlights();
  }

  async runShowStep(step) {
    // Set the mode
    this.simulation.setG35Mode(step.mode);
    onModeChange(step.mode);

    // Hide the tell card, show a small "running" indicator
    this.showRunningBadge(step.mode);

    // Reset and start simulation
    this.simulation.reset();
    this.simulation.start();

    // Schedule highlights at specific timestamps
    const highlightTimers = [];
    if (step.highlights) {
      for (const [ms, highlight] of Object.entries(step.highlights)) {
        const timer = setTimeout(() => {
          if (this.running) {
            this.highlightElement(highlight.element, highlight.tooltip);
          }
        }, parseInt(ms));
        highlightTimers.push(timer);
      }
    }

    await this.wait(step.duration);

    // Clear timers and highlights
    highlightTimers.forEach(t => clearTimeout(t));
    this.clearHighlights();

    // Capture metrics for this mode
    if (latestState) {
      this.captures[step.mode] = buildSnapshot(
        latestState.metrics, latestState.gpus, step.mode
      );
    }

    this.simulation.stop();
    this.hideRunningBadge();
  }

  showCard({ icon, title, body, isFinale, stepNumber, totalSteps }) {
    // Convert markdown-like formatting in body
    const formatted = body
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n•/g, '<br>•')
      .replace(/\n(\d)\./g, '<br>$1.');

    this.cardEl.innerHTML = `
      <div class="gc-card ${isFinale ? 'gc-finale' : ''}">
        <div class="gc-step-indicator">Step ${stepNumber} of ${totalSteps}</div>
        <div class="gc-icon">${icon}</div>
        <div class="gc-title">${title}</div>
        <div class="gc-body"><p>${formatted}</p></div>
        <div class="gc-controls">
          <button class="gc-skip" onclick="guidedDemo.stop()">End guided demo</button>
        </div>
      </div>
    `;
    this.cardEl.style.display = 'flex';
  }

  highlightElement(elementId, tooltip) {
    const el = document.getElementById(elementId) ||
               document.querySelector(`[data-testid="${elementId}"]`);
    if (!el) return;

    const rect = el.getBoundingClientRect();

    // Create a highlight ring around the element
    const ring = document.createElement('div');
    ring.className = 'guided-ring';
    ring.style.left = (rect.left - 4) + 'px';
    ring.style.top = (rect.top - 4) + 'px';
    ring.style.width = (rect.width + 8) + 'px';
    ring.style.height = (rect.height + 8) + 'px';

    if (tooltip) {
      const tip = document.createElement('div');
      tip.className = 'guided-tooltip';
      tip.textContent = tooltip;
      // Position tooltip below the element
      tip.style.left = rect.left + 'px';
      tip.style.top = (rect.bottom + 8) + 'px';
      ring.appendChild(tip);
    }

    this.highlightEl.appendChild(ring);
  }

  clearHighlights() {
    this.highlightEl.innerHTML = '';
  }

  showOverlay() {
    this.overlayEl.style.display = 'block';
  }
  hideOverlay() {
    this.overlayEl.style.display = 'none';
    this.cardEl.style.display = 'none';
  }

  updateProgress() {
    const pct = Math.round((this.currentStep / this.script.length) * 100);
    this.progressEl.style.width = pct + '%';
  }

  showRunningBadge(mode) {
    this.cardEl.innerHTML = `
      <div class="gc-running-badge">
        <div class="gc-running-dot"></div>
        Running: ${mode === 'disabled' ? 'No G3.5' : mode === 'standard' ? 'Standard S3/TCP' : 'Accelerated RDMA'}
      </div>`;
    this.cardEl.style.display = 'flex';
  }
  hideRunningBadge() {
    this.cardEl.style.display = 'none';
  }

  wait(ms) {
    return new Promise(resolve => {
      const timer = setTimeout(resolve, ms);
      // Allow early termination
      const check = setInterval(() => {
        if (!this.running) {
          clearTimeout(timer);
          clearInterval(check);
          resolve();
        }
      }, 100);
    });
  }
}

// Initialize
const guidedDemo = new GuidedDemoRunner(simulation, GUIDED_SCRIPT);
document.getElementById('guided-demo-btn').addEventListener('click', () => guidedDemo.start());
```

### Guided mode HTML skeleton

Add to the simulation page:

```html
<!-- Guided demo overlay -->
<div id="guided-overlay" class="guided-overlay" style="display: none;">
  <div id="guided-progress-track" class="guided-progress-track">
    <div id="guided-progress" class="guided-progress-bar"></div>
  </div>
</div>

<!-- Guided card (tell phase) -->
<div id="guided-card" class="guided-card-container" style="display: none;"></div>

<!-- Highlight rings and tooltips -->
<div id="guided-highlight" class="guided-highlight-layer"></div>
```

### Guided mode CSS

```css
/* Overlay — subtle dimming of the background during tell phases */
.guided-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  pointer-events: none;
  z-index: 900;
}

/* Progress bar at the very top */
.guided-progress-track {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: rgba(255,255,255,0.05);
  z-index: 1000;
}
.guided-progress-bar {
  height: 100%;
  background: #1D9E75;
  transition: width 0.5s ease;
  width: 0%;
}

/* Card container — centered overlay */
.guided-card-container {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 950;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
}

/* The tell card */
.gc-card {
  background: #1a1a2e;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 32px 40px;
  max-width: 520px;
  width: 90%;
  box-shadow: 0 24px 48px rgba(0,0,0,0.4);
  animation: gc-card-in 0.3s ease-out;
}
@keyframes gc-card-in {
  from { opacity: 0; transform: translateY(20px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.gc-card.gc-finale {
  border-color: rgba(29,158,117,0.4);
  background: linear-gradient(135deg, #1a1a2e, rgba(29,158,117,0.08));
}

.gc-step-indicator {
  font-size: 10px;
  color: rgba(255,255,255,0.3);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 16px;
}

.gc-icon {
  font-size: 28px;
  margin-bottom: 12px;
}

.gc-title {
  font-size: 18px;
  font-weight: 700;
  color: rgba(255,255,255,0.9);
  margin-bottom: 12px;
}

.gc-body {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255,255,255,0.6);
}
.gc-body p { margin-bottom: 8px; }

.gc-controls {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.gc-skip {
  font-size: 11px;
  color: rgba(255,255,255,0.35);
  background: none;
  border: 1px solid rgba(255,255,255,0.1);
  padding: 6px 14px;
  border-radius: 4px;
  cursor: pointer;
}
.gc-skip:hover {
  color: rgba(255,255,255,0.6);
  border-color: rgba(255,255,255,0.2);
}

/* Running badge (during show phase) */
.gc-running-badge {
  background: rgba(0,0,0,0.7);
  border: 1px solid rgba(29,158,117,0.3);
  border-radius: 20px;
  padding: 8px 16px;
  font-size: 12px;
  color: rgba(255,255,255,0.7);
  display: flex;
  align-items: center;
  gap: 8px;
  backdrop-filter: blur(8px);
}
.gc-running-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #1D9E75;
  animation: live-blink 1s infinite;
}

/* Highlight rings */
.guided-highlight-layer {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  pointer-events: none;
  z-index: 960;
}

.guided-ring {
  position: fixed;
  border: 2px solid #1D9E75;
  border-radius: 6px;
  animation: ring-pulse 1.5s ease-in-out infinite;
  pointer-events: none;
}
@keyframes ring-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(29,158,117,0.3); }
  50% { box-shadow: 0 0 0 6px rgba(29,158,117,0); }
}

.guided-tooltip {
  position: fixed;
  background: rgba(0,0,0,0.85);
  color: rgba(255,255,255,0.8);
  font-size: 11px;
  padding: 6px 10px;
  border-radius: 4px;
  max-width: 240px;
  white-space: normal;
  backdrop-filter: blur(8px);
  border: 1px solid rgba(29,158,117,0.2);
  animation: tooltip-in 0.2s ease-out;
}
@keyframes tooltip-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
```

---

## Part 2: SE Onboarding Overlay

A product-tour-style walkthrough that the SE sees the first time they open the simulator, or on demand via a "?" help button. Step-by-step overlay with arrows pointing at UI elements.

### Tour steps

```javascript
const SE_TOUR_STEPS = [
  {
    target: 'gpu-util-section',          // Element ID or selector
    title: 'GPU utilization breakdown',
    body: 'This stacked bar shows how each GPU spends its time. Green = useful inference. Amber = waiting for storage I/O. Red = wasted recomputation. The goal is to maximize green.',
    position: 'right',                    // Tooltip position relative to target
  },
  {
    target: 'tier-bar-g1-a',
    title: 'Memory hierarchy — per GPU',
    body: 'Each GPU has three private tiers: G1 (HBM, fastest), G2 (DRAM), G3 (NVMe). KV cache starts in G1 and evicts downward when tiers fill up. The eviction threshold marker (amber line) shows when eviction triggers.',
    position: 'right',
  },
  {
    target: 'shared-g35',
    title: 'G3.5 — the MinIO tier (shared)',
    body: 'This is MinIO AIStor. It\'s shared between both GPUs — that\'s the key. When a session moves from GPU-A to GPU-B, the KV cache is pulled from G3.5 instead of being recomputed. This tier makes or breaks GPU utilization.',
    position: 'right',
  },
  {
    target: 'g35-selector',
    title: 'The three modes — your main demo control',
    body: 'Disabled: no G3.5 (baseline). Standard: MinIO over S3/TCP (works today, any infra). Accelerated: MinIO over RDMA (BlueField-4). Toggle between these to show the customer the impact on GPU utilization.',
    position: 'left',
  },
  {
    target: 'cross-gpu-path',
    title: 'Cross-GPU return path',
    body: 'This diagram shows what happens when a user\'s session is routed to a different GPU. With G3.5: cache is shared, no recompute. Without: cache is lost, GPU must rebuild it. This is the visual "aha moment" for the customer.',
    position: 'left',
  },
  {
    target: 'mode-comparison',
    title: 'Mode comparison — builds automatically',
    body: 'As you switch between modes, metrics are captured here automatically. After running all three modes, you have a side-by-side comparison showing the GPU utilization improvement. The "Guided demo" button does this for you.',
    position: 'top',
  },
  {
    target: 'guided-demo-btn',
    title: 'Guided demo — autopilot mode',
    body: 'Click this to run the full demo story automatically. It walks through all three modes with explanation cards, highlights key events, and ends with a metrics recap. Perfect for when you want to narrate along without managing controls.',
    position: 'top',
  },
  {
    target: 'event-stream',
    title: 'Event stream — real-time narrative',
    body: 'Every eviction, promotion, and recomputation appears here with the reason it happened. Point the customer at red "RECOMPUTE" events when G3.5 is off, then show how they disappear when G3.5 is enabled.',
    position: 'top',
  },
];
```

### Tour engine

```javascript
class OnboardingTour {
  constructor(steps) {
    this.steps = steps;
    this.currentStep = 0;
    this.active = false;
    this.overlayEl = null;
  }

  start() {
    this.active = true;
    this.currentStep = 0;
    this.createOverlay();
    this.showStep(0);
  }

  createOverlay() {
    // Create a full-screen overlay with a cutout for the target element
    this.overlayEl = document.createElement('div');
    this.overlayEl.className = 'tour-overlay';
    this.overlayEl.id = 'tour-overlay';
    document.body.appendChild(this.overlayEl);
  }

  showStep(index) {
    if (index >= this.steps.length) {
      this.finish();
      return;
    }

    this.currentStep = index;
    const step = this.steps[index];
    const targetEl = document.getElementById(step.target) ||
                     document.querySelector(`[data-testid="${step.target}"]`);

    if (!targetEl) {
      // Skip to next step if target not found
      this.showStep(index + 1);
      return;
    }

    const rect = targetEl.getBoundingClientRect();

    // Create spotlight cutout (the target element is visible, everything else dimmed)
    this.overlayEl.innerHTML = `
      <div class="tour-backdrop" onclick="tour.next()"></div>
      <div class="tour-spotlight" style="
        left: ${rect.left - 8}px;
        top: ${rect.top - 8}px;
        width: ${rect.width + 16}px;
        height: ${rect.height + 16}px;
      "></div>
      <div class="tour-card tour-pos-${step.position}" style="${this.cardPosition(rect, step.position)}">
        <div class="tour-step-count">${index + 1} / ${this.steps.length}</div>
        <div class="tour-title">${step.title}</div>
        <div class="tour-body">${step.body}</div>
        <div class="tour-nav">
          ${index > 0 ? '<button class="tour-prev" onclick="tour.prev()">← Back</button>' : '<span></span>'}
          ${index < this.steps.length - 1
            ? '<button class="tour-next-btn" onclick="tour.next()">Next →</button>'
            : '<button class="tour-done" onclick="tour.finish()">Got it!</button>'}
        </div>
      </div>
      <div class="tour-arrow tour-arrow-${step.position}" style="${this.arrowPosition(rect, step.position)}"></div>
    `;

    // Scroll target into view if needed
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  next() { this.showStep(this.currentStep + 1); }
  prev() { this.showStep(this.currentStep - 1); }

  finish() {
    this.active = false;
    if (this.overlayEl) {
      this.overlayEl.remove();
      this.overlayEl = null;
    }
    // Remember that the user has seen the tour
    localStorage.setItem('stx-sim-tour-complete', 'true');
  }

  cardPosition(rect, position) {
    const gap = 16;
    switch (position) {
      case 'right': return `left: ${rect.right + gap}px; top: ${rect.top}px;`;
      case 'left': return `right: ${window.innerWidth - rect.left + gap}px; top: ${rect.top}px;`;
      case 'top': return `left: ${rect.left}px; bottom: ${window.innerHeight - rect.top + gap}px;`;
      case 'bottom': return `left: ${rect.left}px; top: ${rect.bottom + gap}px;`;
      default: return `left: ${rect.right + gap}px; top: ${rect.top}px;`;
    }
  }

  arrowPosition(rect, position) {
    switch (position) {
      case 'right': return `left: ${rect.right + 4}px; top: ${rect.top + rect.height / 2 - 6}px;`;
      case 'left': return `left: ${rect.left - 16}px; top: ${rect.top + rect.height / 2 - 6}px;`;
      case 'top': return `left: ${rect.left + rect.width / 2 - 6}px; top: ${rect.top - 16}px;`;
      case 'bottom': return `left: ${rect.left + rect.width / 2 - 6}px; top: ${rect.bottom + 4}px;`;
      default: return '';
    }
  }
}

const tour = new OnboardingTour(SE_TOUR_STEPS);

// Show tour on first visit, or via help button
if (!localStorage.getItem('stx-sim-tour-complete')) {
  // Auto-start after 1 second
  setTimeout(() => tour.start(), 1000);
}

// Help button always available
document.getElementById('help-btn').addEventListener('click', () => tour.start());
```

### Tour CSS

```css
.tour-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  z-index: 2000;
}

.tour-backdrop {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.65);
}

.tour-spotlight {
  position: fixed;
  border-radius: 8px;
  box-shadow: 0 0 0 9999px rgba(0,0,0,0.65);
  z-index: 2001;
  pointer-events: none;
  border: 2px solid rgba(29,158,117,0.5);
}

.tour-card {
  position: fixed;
  background: #1e1e32;
  border: 1px solid rgba(29,158,117,0.3);
  border-radius: 10px;
  padding: 20px 24px;
  max-width: 320px;
  z-index: 2002;
  box-shadow: 0 12px 32px rgba(0,0,0,0.5);
  animation: tour-card-in 0.25s ease-out;
}
@keyframes tour-card-in {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.tour-step-count {
  font-size: 10px;
  color: rgba(29,158,117,0.6);
  margin-bottom: 8px;
  font-weight: 600;
}

.tour-title {
  font-size: 14px;
  font-weight: 700;
  color: rgba(255,255,255,0.9);
  margin-bottom: 8px;
}

.tour-body {
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255,255,255,0.55);
}

.tour-nav {
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
}

.tour-prev, .tour-next-btn, .tour-done {
  font-size: 11px;
  padding: 6px 14px;
  border-radius: 4px;
  cursor: pointer;
  border: none;
}
.tour-prev {
  background: none;
  color: rgba(255,255,255,0.4);
  border: 1px solid rgba(255,255,255,0.1);
}
.tour-next-btn {
  background: rgba(29,158,117,0.2);
  color: #1D9E75;
  border: 1px solid rgba(29,158,117,0.3);
}
.tour-done {
  background: #1D9E75;
  color: white;
}

/* Arrow pointing from card to target */
.tour-arrow {
  position: fixed;
  width: 12px;
  height: 12px;
  z-index: 2002;
}
.tour-arrow-right { border-left: 8px solid rgba(29,158,117,0.5); border-top: 6px solid transparent; border-bottom: 6px solid transparent; }
.tour-arrow-left { border-right: 8px solid rgba(29,158,117,0.5); border-top: 6px solid transparent; border-bottom: 6px solid transparent; }
.tour-arrow-top { border-bottom: 8px solid rgba(29,158,117,0.5); border-left: 6px solid transparent; border-right: 6px solid transparent; }
.tour-arrow-bottom { border-top: 8px solid rgba(29,158,117,0.5); border-left: 6px solid transparent; border-right: 6px solid transparent; }
```

### Help button

Add a "?" button in the top-right corner of the simulation UI:

```html
<button id="help-btn" class="help-btn" title="Show guided tour">?</button>
```

```css
.help-btn {
  position: fixed;
  top: 12px;
  right: 12px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.15);
  color: rgba(255,255,255,0.4);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}
.help-btn:hover {
  background: rgba(29,158,117,0.15);
  border-color: rgba(29,158,117,0.3);
  color: #1D9E75;
}
```

---

## Part 3: G4 Storage Backend Insight (lightweight, no separate simulation)

### Concept

Rather than building a separate object-vs-file-vs-block simulation, add a contextual insight callout that appears when G4 is under stress.

When G3.5 is disabled and G4 is above 30% capacity, show a subtle callout below the G4 bar:

```html
<div id="g4-insight" class="g4-insight" style="display: none;">
  <div class="g4-insight-header">Why object storage for G4?</div>
  <div class="g4-insight-body">
    <div class="g4-insight-comparison">
      <div class="g4-insight-col">
        <div class="g4-insight-proto">Object (S3)</div>
        <div class="g4-insight-row"><span>Parallel reads</span><span class="val-good">✓ linear scaling</span></div>
        <div class="g4-insight-row"><span>Metadata</span><span class="val-good">✓ flat namespace</span></div>
        <div class="g4-insight-row"><span>Concurrent writers</span><span class="val-good">✓ immutable objects</span></div>
        <div class="g4-insight-row"><span>Multi-tenant</span><span class="val-good">✓ bucket policies</span></div>
      </div>
      <div class="g4-insight-col">
        <div class="g4-insight-proto">File (NFS)</div>
        <div class="g4-insight-row"><span>Parallel reads</span><span class="val-warn">⚠ metadata lock</span></div>
        <div class="g4-insight-row"><span>Metadata</span><span class="val-bad">✗ tree traversal</span></div>
        <div class="g4-insight-row"><span>Concurrent writers</span><span class="val-warn">⚠ locking overhead</span></div>
        <div class="g4-insight-row"><span>Multi-tenant</span><span class="val-bad">✗ UID/export hacks</span></div>
      </div>
    </div>
    <div class="g4-insight-note">
      KV cache blocks are immutable, variable-sized, and accessed in parallel bursts — a natural fit for object storage. File and block protocols add locking, metadata traversal, and consistency overhead that creates bottlenecks at scale.
    </div>
  </div>
</div>
```

Show/hide logic:

```javascript
function updateG4Insight(g4State, g35Mode) {
  const el = document.getElementById('g4-insight');
  // Show insight when G4 is stressed (disabled mode + high utilization)
  if (g35Mode === 'disabled' && g4State.pct > 30) {
    el.style.display = 'block';
  } else {
    el.style.display = 'none';
  }
}
```

```css
.g4-insight {
  margin-top: 8px;
  padding: 10px 12px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
  animation: insight-in 0.3s ease-out;
}
@keyframes insight-in {
  from { opacity: 0; max-height: 0; }
  to { opacity: 1; max-height: 300px; }
}
.g4-insight-header { font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.5); margin-bottom: 8px; }
.g4-insight-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.g4-insight-col { padding: 6px 8px; border-radius: 4px; background: rgba(255,255,255,0.02); }
.g4-insight-proto { font-size: 10px; font-weight: 600; color: rgba(255,255,255,0.6); margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 4px; }
.g4-insight-row { display: flex; justify-content: space-between; font-size: 10px; padding: 2px 0; color: rgba(255,255,255,0.4); }
.g4-insight-row span:last-child { font-size: 9px; }
.g4-insight-note { font-size: 10px; color: rgba(255,255,255,0.35); margin-top: 8px; line-height: 1.5; font-style: italic; }
```

This callout appears organically when the demo shows G4 stress — the SE doesn't have to navigate to a separate view. It plants the "why object storage" seed exactly when the customer is seeing the problem.

---

## Verification

### Unit tests (for guided demo script)

```python
def test_guided_script_covers_all_modes():
    """Script should have show phases for disabled, standard, and accelerated."""
    show_phases = [s for s in GUIDED_SCRIPT if s['phase'] == 'show']
    modes = {s['mode'] for s in show_phases}
    assert modes == {'disabled', 'standard', 'accelerated'}

def test_guided_script_alternates_tell_show():
    """Script should alternate between tell and show phases."""
    for i in range(len(GUIDED_SCRIPT) - 1):
        # No two consecutive show phases
        if GUIDED_SCRIPT[i]['phase'] == 'show':
            assert GUIDED_SCRIPT[i+1]['phase'] == 'tell'
```

### Playwright E2E

```typescript
test.describe('Guided Demo Mode', () => {
  test('guided demo button is visible', async ({ page }) => {
    await expect(page.locator('#guided-demo-btn')).toBeVisible();
  });

  test('clicking guided demo shows first tell card', async ({ page }) => {
    await page.click('#guided-demo-btn');
    await expect(page.locator('.gc-card')).toBeVisible();
    await expect(page.locator('.gc-title')).toContainText('inference memory');
  });

  test('guided demo progresses through steps', async ({ page }) => {
    await page.click('#guided-demo-btn');
    // First tell card should appear
    await expect(page.locator('.gc-card')).toBeVisible();
    // Wait for it to auto-advance (8 seconds)
    await page.waitForTimeout(9000);
    // Should be on a different step now
    await expect(page.locator('.gc-title')).not.toContainText('inference memory');
  });

  test('can end guided demo early', async ({ page }) => {
    await page.click('#guided-demo-btn');
    await expect(page.locator('.gc-card')).toBeVisible();
    await page.click('.gc-skip');
    await expect(page.locator('.gc-card')).not.toBeVisible();
  });

  test('show phase highlights UI elements', async ({ page }) => {
    await page.click('#guided-demo-btn');
    // Advance to first show phase (after ~16 seconds of tell cards)
    await page.waitForTimeout(17000);
    // Should see highlight rings
    await expect(page.locator('.guided-ring')).toBeVisible({ timeout: 15000 });
  });
});

test.describe('SE Onboarding Tour', () => {
  test('tour auto-starts on first visit', async ({ page }) => {
    // Clear localStorage to simulate first visit
    await page.evaluate(() => localStorage.removeItem('stx-sim-tour-complete'));
    await page.reload();
    await page.waitForTimeout(1500);
    // Tour overlay should appear
    await expect(page.locator('.tour-card')).toBeVisible();
  });

  test('tour does not auto-start on subsequent visits', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('stx-sim-tour-complete', 'true'));
    await page.reload();
    await page.waitForTimeout(1500);
    await expect(page.locator('.tour-card')).not.toBeVisible();
  });

  test('help button opens tour', async ({ page }) => {
    await page.click('#help-btn');
    await expect(page.locator('.tour-card')).toBeVisible();
  });

  test('tour navigates forward and back', async ({ page }) => {
    await page.click('#help-btn');
    const title1 = await page.locator('.tour-title').textContent();
    await page.click('.tour-next-btn');
    const title2 = await page.locator('.tour-title').textContent();
    expect(title2).not.toBe(title1);
    await page.click('.tour-prev');
    const title3 = await page.locator('.tour-title').textContent();
    expect(title3).toBe(title1);
  });

  test('tour highlights target elements', async ({ page }) => {
    await page.click('#help-btn');
    await expect(page.locator('.tour-spotlight')).toBeVisible();
  });

  test('completing tour sets localStorage flag', async ({ page }) => {
    await page.click('#help-btn');
    // Click through all steps
    for (let i = 0; i < 7; i++) {
      await page.click('.tour-next-btn');
    }
    await page.click('.tour-done');
    const flag = await page.evaluate(() => localStorage.getItem('stx-sim-tour-complete'));
    expect(flag).toBe('true');
  });
});

test.describe('G4 Storage Insight', () => {
  test('G4 insight hidden when G3.5 is enabled', async ({ page }) => {
    await page.click('[data-testid="g35-mode-accelerated"]');
    await expect(page.locator('#g4-insight')).not.toBeVisible();
  });

  test('G4 insight appears when G3.5 disabled and G4 loaded', async ({ page }) => {
    await page.click('[data-testid="g35-mode-disabled"]');
    await page.click('[data-testid="start-sim-btn"]');
    // Wait for G4 to fill above 30%
    await page.waitForTimeout(15000);
    await expect(page.locator('#g4-insight')).toBeVisible({ timeout: 20000 });
    await expect(page.locator('text=Why object storage')).toBeVisible();
  });
});
```

---

## What NOT to do

- Don't make the guided demo skippable only at the end — allow "End guided demo" at every step
- Don't play the guided demo with sound or auto-play video — SE is narrating live
- Don't make the tour mandatory — auto-start only on first visit, always available via "?" button
- Don't build a separate simulation for object vs file/block at G4 — the contextual callout is lighter and appears at the right moment
- Don't make the tell cards auto-advance too fast — 6-8 seconds per card gives the SE time to elaborate
- Don't show the comparison strip during guided mode's show phases — it updates in the background and the metrics appear in the tell recap cards
- Don't use localStorage for anything other than the tour-complete flag — the simulator state should not persist between sessions
