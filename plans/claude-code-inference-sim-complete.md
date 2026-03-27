# Claude Code Instruction: Inference Simulator — Complete Overhaul

This is a single consolidated instruction covering all simulation changes. Apply AFTER `claude-code-stx-experience-enhancement.md` (which set up Experience mode, GroupNode, AnnotationNode, base template).

This file replaces both `claude-code-inference-sim-ui-overhaul.md` and `claude-code-gpu-server-internals.md`. If either was partially applied, finish applying this file instead — it is the authoritative source.

Read before starting:
- `components/inference-sim/app/` — entire simulation container
- `frontend/src/components/canvas/nodes/` — all node types
- `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx` — edge rendering
- `frontend/src/types/index.ts` — type definitions
- `demo-templates/experience-stx-inference.yaml` — current template (from file #1)
- `backend/app/models/demo.py` — DemoDefinition model

---

## Part 1: Dual-GPU Simulation Engine

### 1.1 Configuration model

File: `components/inference-sim/app/config.py`

```python
from enum import Enum
from pydantic import BaseModel

class G35Mode(str, Enum):
    DISABLED = "disabled"        # No G3.5 — evict from G3 straight to G4
    STANDARD = "standard"        # S3 over TCP — works, ~5-10ms latency
    ACCELERATED = "accelerated"  # NVMe-oF/RDMA via BlueField-4 — ~500μs latency

class SimulationConfig(BaseModel):
    gpu_count: int = 2
    g1_capacity_gb: float = 10       # Per GPU (scaled down from real 80GB)
    g2_capacity_gb: float = 15       # Per GPU (scaled down from real 512GB)
    g3_capacity_gb: float = 20       # Per GPU (scaled down from real 4TB)
    g35_capacity_gb: float = 40      # Shared across GPUs
    g4_capacity_gb: float = 100      # Shared across GPUs
    g35_mode: G35Mode = G35Mode.ACCELERATED
    users: int = 50
    context_tokens: int = 32768
    speed: int = 5                   # 1=slow, 5=normal, 20=fast
```

### 1.2 State model

File: `components/inference-sim/app/simulation/kv_block_manager.py`

```python
from dataclasses import dataclass, field
from enum import Enum

class EvictionReason(str, Enum):
    TIER_FULL = "tier_full"              # Tier at capacity, must evict coldest
    IDLE_TIMEOUT = "idle_timeout"        # Session idle too long, proactively evict
    CROSS_GPU_PREP = "cross_gpu_prep"    # Prestaging for cross-GPU migration

class PromotionReason(str, Enum):
    SESSION_RETURN = "session_return"     # User came back, need cache in G1
    CROSS_GPU = "cross_gpu_migration"    # Session routed to different GPU, pull from G3.5
    PRESTAGE = "prestage"                # Proactively move to G1 before decode phase

@dataclass
class TierState:
    name: str                   # "g1", "g2", "g3", "g35", "g4"
    capacity_gb: float
    used_gb: float = 0.0
    block_count: int = 0
    eviction_threshold: float = 0.90   # Start evicting when tier hits 90%

@dataclass
class GPUState:
    id: str                     # "gpu-a" or "gpu-b"
    g1: TierState
    g2: TierState
    g3: TierState

@dataclass
class Session:
    id: str
    gpu_id: str                 # Which GPU currently owns this session
    tier: str                   # Which tier holds the KV cache
    size_gb: float              # KV cache size for this session
    active: bool = True
    idle_ticks: int = 0
    total_tokens: int = 0
    created_tick: int = 0

@dataclass
class SimEvent:
    tick: int
    event_type: str             # "EVICT", "PROMOTE", "RECOMPUTE", "NEW", "TERMINATE"
    session_id: str
    from_tier: str = ""
    to_tier: str = ""
    from_gpu: str = ""
    to_gpu: str = ""
    reason: str = ""            # Human-readable reason for the event
    policy_rule: str = ""       # Which policy triggered this

class KVBlockManager:
    """
    Manages KV cache blocks across the 5-tier memory hierarchy.
    
    Eviction policies (in order of evaluation):
    1. TIER_CAPACITY — when a tier exceeds its eviction_threshold (90%),
       evict the coldest idle session to the next tier down.
    2. IDLE_TIMEOUT — when a session has been idle for >idle_timeout ticks,
       proactively evict down regardless of tier pressure.
    3. CROSS_GPU_PREP — when Dynamo routes a returning session to a different
       GPU, prestage the KV cache from G3.5 to the new GPU's G1.
    
    Promotion policies:
    1. SESSION_RETURN — user comes back, promote KV cache to the serving GPU's G1.
    2. CROSS_GPU — cache is on GPU-A but session routed to GPU-B.
       With G3.5: GPU-A evicts to G3.5, GPU-B promotes from G3.5. Fast.
       Without G3.5: cache in G4 or lost. GPU-B recomputes. Slow.
    3. PRESTAGE — proactively move warm cache closer to G1 before decode.
    """

    def __init__(self, config: 'SimulationConfig'):
        self.config = config
        self.gpus = [
            GPUState(
                id=f"gpu-{'a' if i == 0 else 'b'}",
                g1=TierState("g1", config.g1_capacity_gb, eviction_threshold=0.90),
                g2=TierState("g2", config.g2_capacity_gb, eviction_threshold=0.85),
                g3=TierState("g3", config.g3_capacity_gb, eviction_threshold=0.80),
            )
            for i in range(config.gpu_count)
        ]
        self.shared_g35 = TierState("g35", config.g35_capacity_gb, eviction_threshold=0.95)
        self.shared_g4 = TierState("g4", config.g4_capacity_gb, eviction_threshold=1.0)
        self.sessions: list[Session] = []
        self.events: list[SimEvent] = []
        self.idle_timeout_ticks = 20   # Proactively evict after 20 ticks of idle

    def get_gpu(self, gpu_id: str) -> GPUState:
        return next(g for g in self.gpus if g.id == gpu_id)

    def get_tier(self, gpu_id: str, tier_name: str) -> TierState:
        gpu = self.get_gpu(gpu_id)
        if tier_name == "g1": return gpu.g1
        if tier_name == "g2": return gpu.g2
        if tier_name == "g3": return gpu.g3
        if tier_name == "g35": return self.shared_g35
        if tier_name == "g4": return self.shared_g4
        raise ValueError(f"Unknown tier: {tier_name}")

    def eviction_cascade(self, gpu_id: str, tick: int) -> list[SimEvent]:
        """
        Check all tiers on a GPU for capacity pressure.
        Evict coldest idle sessions downward.
        Returns list of events generated.
        """
        events = []
        gpu = self.get_gpu(gpu_id)
        tier_chain = [
            ("g1", gpu.g1, "g2", gpu.g2),
            ("g2", gpu.g2, "g3", gpu.g3),
        ]

        # G3 → G3.5 or G4 depending on mode
        if self.config.g35_mode != G35Mode.DISABLED:
            tier_chain.append(("g3", gpu.g3, "g35", self.shared_g35))
        else:
            tier_chain.append(("g3", gpu.g3, "g4", self.shared_g4))

        # G3.5 → G4
        if self.config.g35_mode != G35Mode.DISABLED:
            tier_chain.append(("g35", self.shared_g35, "g4", self.shared_g4))

        for from_name, from_tier, to_name, to_tier in tier_chain:
            while from_tier.used_gb > from_tier.capacity_gb * from_tier.eviction_threshold:
                # Find coldest idle session in this tier on this GPU
                candidates = [
                    s for s in self.sessions
                    if s.tier == from_name
                    and (s.gpu_id == gpu_id or from_name in ("g35", "g4"))
                    and not s.active
                ]
                if not candidates:
                    break
                victim = max(candidates, key=lambda s: s.idle_ticks)

                # Move the block
                from_tier.used_gb -= victim.size_gb
                from_tier.block_count -= 1
                to_tier.used_gb += victim.size_gb
                to_tier.block_count += 1
                old_tier = victim.tier
                victim.tier = to_name

                events.append(SimEvent(
                    tick=tick,
                    event_type="EVICT",
                    session_id=victim.id,
                    from_tier=old_tier,
                    to_tier=to_name,
                    from_gpu=gpu_id,
                    reason=f"{from_name.upper()} at {int(from_tier.used_gb/from_tier.capacity_gb*100)}% capacity",
                    policy_rule=f"Tier capacity > {int(from_tier.eviction_threshold*100)}%",
                ))
        return events

    def idle_eviction(self, tick: int) -> list[SimEvent]:
        """
        Proactively evict sessions that have been idle too long,
        even if tiers aren't full. This keeps hot tiers available.
        """
        events = []
        for session in self.sessions:
            if not session.active and session.idle_ticks > self.idle_timeout_ticks:
                if session.tier == "g1":
                    # Proactively move from G1 to G2
                    gpu = self.get_gpu(session.gpu_id)
                    gpu.g1.used_gb -= session.size_gb
                    gpu.g1.block_count -= 1
                    gpu.g2.used_gb += session.size_gb
                    gpu.g2.block_count += 1
                    session.tier = "g2"
                    events.append(SimEvent(
                        tick=tick,
                        event_type="EVICT",
                        session_id=session.id,
                        from_tier="g1", to_tier="g2",
                        from_gpu=session.gpu_id,
                        reason=f"Idle for {session.idle_ticks} ticks",
                        policy_rule=f"Idle timeout > {self.idle_timeout_ticks} ticks",
                    ))
        return events

    def promote_session(self, session: Session, target_gpu_id: str, tick: int) -> SimEvent:
        """
        Promote a session's KV cache back to G1 on the target GPU.
        Returns the event with latency and reason.
        """
        source_tier = session.tier
        source_gpu = session.gpu_id
        cross_gpu = (target_gpu_id != source_gpu)

        # Determine promotion path and latency
        if source_tier == "g1" and not cross_gpu:
            # Already in G1 on the right GPU — no movement needed
            return None

        # Remove from source tier
        src = self.get_tier(source_gpu, source_tier)
        src.used_gb -= session.size_gb
        src.block_count -= 1

        # Add to target GPU's G1
        target_gpu = self.get_gpu(target_gpu_id)
        target_gpu.g1.used_gb += session.size_gb
        target_gpu.g1.block_count += 1

        session.tier = "g1"
        session.gpu_id = target_gpu_id

        # Determine reason
        if cross_gpu and source_tier in ("g35",):
            reason = f"Cross-GPU migration via G3.5 (cache shared through MinIO)"
            policy = "Dynamo KV-aware router → NIXL transfer from shared G3.5"
        elif cross_gpu and source_tier in ("g4",):
            reason = f"Cross-GPU from G4 (slow — {source_tier} retrieval)"
            policy = "Cache too cold — retrieved from enterprise storage"
        elif cross_gpu:
            reason = f"Cross-GPU — cache was in {source_gpu}:{source_tier}, needed on {target_gpu_id}"
            policy = "Recomputation required — no shared tier available"
        else:
            reason = f"Session returned — promoting from {source_tier} to G1"
            policy = f"Dynamo prestage from {source_tier}"

        return SimEvent(
            tick=tick,
            event_type="PROMOTE" if source_tier != "g4" else "PROMOTE_SLOW",
            session_id=session.id,
            from_tier=source_tier,
            to_tier="g1",
            from_gpu=source_gpu,
            to_gpu=target_gpu_id,
            reason=reason,
            policy_rule=policy,
        )

    def compute_promotion_latency(self, source_tier: str) -> int:
        """
        Return simulated latency in ticks for promoting from source_tier to G1.
        """
        latency_map = {
            "g1": 0,       # Already there
            "g2": 1,       # ~100 μs — CPU DRAM to GPU HBM
            "g3": 2,       # ~500 μs — local NVMe read
        }

        if self.config.g35_mode == G35Mode.ACCELERATED:
            latency_map["g35"] = 3    # ~500 μs — RDMA/NVMe-oF
        elif self.config.g35_mode == G35Mode.STANDARD:
            latency_map["g35"] = 15   # ~5-10 ms — S3 over TCP
        else:
            latency_map["g35"] = 999  # Shouldn't happen — G3.5 disabled

        latency_map["g4"] = 50        # ~50 ms — enterprise storage retrieval
        # Recomputation (no cache) = 100 ticks (~2 seconds)

        return latency_map.get(source_tier, 100)
```

### 1.3 Simulation engine

File: `components/inference-sim/app/simulation/engine.py`

```python
import asyncio
import random
import time
from ..config import SimulationConfig, G35Mode
from .kv_block_manager import KVBlockManager, Session, SimEvent

class SimulationEngine:
    def __init__(self, config: SimulationConfig, minio_backend=None):
        self.config = config
        self.manager = KVBlockManager(config)
        self.minio = minio_backend
        self.running = False
        self.tick = 0
        self.metrics = SimMetrics()
        self.recent_events: list[SimEvent] = []  # Last 50 events

    def kv_size_gb(self) -> float:
        """KV cache size per session based on context length."""
        return round(self.config.context_tokens / 1024 * 0.08, 2)  # ~80MB per 1K tokens

    async def run(self, ws_callback=None):
        """Main simulation loop. Each tick = 200ms real-time / speed factor."""
        self.running = True
        self.tick = 0

        while self.running:
            tick_events = []

            for _ in range(self.config.speed):
                self.tick += 1
                tick_events.extend(self._process_tick())

            # Keep last 50 events
            self.recent_events = (self.recent_events + tick_events)[-50:]

            # Compute metrics
            self._update_metrics()

            # Push state via WebSocket
            if ws_callback:
                await ws_callback(self._build_state_snapshot())

            await asyncio.sleep(0.2)  # 5 updates per second

    def _process_tick(self) -> list[SimEvent]:
        events = []

        # 1. Generate new sessions (arrival rate based on user count)
        if random.random() < 0.12 and len(self.manager.sessions) < self.config.users:
            events.extend(self._create_session())

        # 2. Session lifecycle — some go idle, some return
        for s in list(self.manager.sessions):
            if s.active and random.random() < 0.06:
                s.active = False  # User paused
            elif not s.active:
                s.idle_ticks += 1
                if random.random() < 0.03:
                    s.active = True  # User returned
                    s.idle_ticks = 0
                    events.extend(self._handle_session_return(s))

        # 3. Idle-based proactive eviction
        events.extend(self.manager.idle_eviction(self.tick))

        # 4. Capacity-based eviction cascade (both GPUs)
        for gpu in self.manager.gpus:
            events.extend(self.manager.eviction_cascade(gpu.id, self.tick))

        # 5. Random session termination
        if random.random() < 0.02 and len(self.manager.sessions) > 5:
            events.extend(self._terminate_session())

        return events

    def _create_session(self) -> list[SimEvent]:
        """Create a new session on the GPU with more available G1 capacity."""
        # Pick GPU with more G1 headroom
        gpu_a_free = self.manager.gpus[0].g1.capacity_gb - self.manager.gpus[0].g1.used_gb
        gpu_b_free = self.manager.gpus[1].g1.capacity_gb - self.manager.gpus[1].g1.used_gb
        target_gpu = self.manager.gpus[0].id if gpu_a_free >= gpu_b_free else self.manager.gpus[1].id

        session = Session(
            id=f"s-{random.randint(10000, 99999)}",
            gpu_id=target_gpu,
            tier="g1",
            size_gb=self.kv_size_gb(),
            active=True,
            created_tick=self.tick,
            total_tokens=self.config.context_tokens,
        )
        self.manager.sessions.append(session)

        gpu = self.manager.get_gpu(target_gpu)
        gpu.g1.used_gb += session.size_gb
        gpu.g1.block_count += 1

        return [SimEvent(
            tick=self.tick,
            event_type="NEW",
            session_id=session.id,
            to_tier="g1",
            to_gpu=target_gpu,
            reason=f"Routed to {target_gpu} (more G1 headroom: {gpu_a_free:.1f} vs {gpu_b_free:.1f} GB)",
            policy_rule="Dynamo load-balanced routing",
        )]

    def _handle_session_return(self, session: Session) -> list[SimEvent]:
        """Handle a returning session — may need cross-GPU migration."""
        events = []

        # 20-30% chance of routing to the OTHER GPU (load balancing)
        original_gpu = session.gpu_id
        gpu_a_free = self.manager.gpus[0].g1.capacity_gb - self.manager.gpus[0].g1.used_gb
        gpu_b_free = self.manager.gpus[1].g1.capacity_gb - self.manager.gpus[1].g1.used_gb

        if random.random() < 0.25:
            # Route to the other GPU
            target_gpu = "gpu-b" if original_gpu == "gpu-a" else "gpu-a"
        else:
            target_gpu = original_gpu

        cross_gpu = (target_gpu != original_gpu)

        if cross_gpu and session.tier in ("g1", "g2", "g3"):
            # Cache is on the wrong GPU's local storage
            if self.config.g35_mode != G35Mode.DISABLED:
                # Evict to G3.5 first, then promote to new GPU
                # (In reality Dynamo would handle this via NIXL)
                src_tier = self.manager.get_tier(original_gpu, session.tier)
                src_tier.used_gb -= session.size_gb
                src_tier.block_count -= 1
                self.manager.shared_g35.used_gb += session.size_gb
                self.manager.shared_g35.block_count += 1
                session.tier = "g35"
                # Then promote from G3.5 to new GPU's G1
                evt = self.manager.promote_session(session, target_gpu, self.tick)
                if evt:
                    events.append(evt)
                    self.metrics.cache_hits += 1
                    self.metrics.cross_gpu_count += 1
                    self._record_s3_ops(2)  # PUT + GET
            else:
                # No G3.5 — must recompute
                events.append(SimEvent(
                    tick=self.tick,
                    event_type="RECOMPUTE",
                    session_id=session.id,
                    from_gpu=original_gpu,
                    to_gpu=target_gpu,
                    reason=f"Cache on {original_gpu}:{session.tier}, routed to {target_gpu}. No shared tier available.",
                    policy_rule="G3.5 disabled — full KV cache recomputation required",
                ))
                self.metrics.recomputation_count += 1
                self.metrics.cache_misses += 1
                # Move session to new GPU's G1 (recomputed)
                src_tier = self.manager.get_tier(original_gpu, session.tier)
                src_tier.used_gb -= session.size_gb
                src_tier.block_count -= 1
                new_gpu = self.manager.get_gpu(target_gpu)
                new_gpu.g1.used_gb += session.size_gb
                new_gpu.g1.block_count += 1
                session.tier = "g1"
                session.gpu_id = target_gpu
        else:
            # Same GPU or cache already in shared tier — just promote
            if session.tier != "g1":
                evt = self.manager.promote_session(session, target_gpu, self.tick)
                if evt:
                    events.append(evt)
                    if session.tier in ("g35", "g4"):
                        self._record_s3_ops(1)  # GET from MinIO
                    self.metrics.cache_hits += 1
            else:
                self.metrics.cache_hits += 1

        return events

    def _record_s3_ops(self, count: int):
        """Track S3 operations for the ops/sec metric."""
        self.metrics.s3_ops_total += count
        # Also write real objects to MinIO if backend is configured
        if self.minio:
            # Real S3 PUT/GET happens here (existing logic from minio_backend.py)
            pass

    def _build_state_snapshot(self) -> dict:
        """Build the WebSocket state message."""
        return {
            "tick": self.tick,
            "gpus": [
                {
                    "id": gpu.id,
                    "g1": _tier_dict(gpu.g1),
                    "g2": _tier_dict(gpu.g2),
                    "g3": _tier_dict(gpu.g3),
                }
                for gpu in self.manager.gpus
            ],
            "shared": {
                "g35": {
                    **_tier_dict(self.manager.shared_g35),
                    "mode": self.config.g35_mode.value,
                },
                "g4": _tier_dict(self.manager.shared_g4),
            },
            "metrics": {
                "gpu_a_utilization": _clamp_pct(self.manager.gpus[0].g1),
                "gpu_b_utilization": _clamp_pct(self.manager.gpus[1].g1),
                "avg_ttft_ms": self._compute_ttft(),
                "cache_hit_rate": self._compute_hit_rate(),
                "cross_gpu_migrations": self.metrics.cross_gpu_count,
                "recomputations": self.metrics.recomputation_count,
                "s3_ops_per_sec": self._compute_s3_ops_rate(),
                "active_sessions": len([s for s in self.manager.sessions if s.active]),
                "total_kv_blocks": self._total_blocks(),
            },
            "events": [
                {
                    "tick": e.tick,
                    "type": e.event_type,
                    "session": e.session_id,
                    "from_tier": e.from_tier,
                    "to_tier": e.to_tier,
                    "from_gpu": e.from_gpu,
                    "to_gpu": e.to_gpu,
                    "reason": e.reason,
                    "policy": e.policy_rule,
                }
                for e in self.recent_events[-15:]
            ],
            "sessions": [
                {
                    "id": s.id,
                    "gpu": s.gpu_id,
                    "tier": s.tier,
                    "active": s.active,
                    "size_gb": s.size_gb,
                    "idle_ticks": s.idle_ticks,
                }
                for s in self.manager.sessions[:25]
            ],
            "eviction_policy": {
                "g1_threshold": f"{int(self.manager.gpus[0].g1.eviction_threshold * 100)}%",
                "g2_threshold": f"{int(self.manager.gpus[0].g2.eviction_threshold * 100)}%",
                "g3_threshold": f"{int(self.manager.gpus[0].g3.eviction_threshold * 100)}%",
                "g35_threshold": f"{int(self.manager.shared_g35.eviction_threshold * 100)}%",
                "idle_timeout_ticks": self.manager.idle_timeout_ticks,
                "strategy": "LRU (coldest idle session evicted first)",
                "g35_mode": self.config.g35_mode.value,
            },
        }

def _tier_dict(tier) -> dict:
    return {
        "capacity_gb": tier.capacity_gb,
        "used_gb": round(min(tier.used_gb, tier.capacity_gb * 1.05), 1),  # Clamp slight overshoot
        "block_count": tier.block_count,
        "pct": min(100, max(0, round(tier.used_gb / tier.capacity_gb * 100))),
        "threshold_pct": int(tier.eviction_threshold * 100),
    }

def _clamp_pct(tier) -> int:
    return min(100, max(0, round(tier.used_gb / tier.capacity_gb * 100)))
```

### 1.4 Metrics model

```python
from dataclasses import dataclass

@dataclass
class SimMetrics:
    cache_hits: int = 0
    cache_misses: int = 0
    recomputation_count: int = 0
    cross_gpu_count: int = 0
    s3_ops_total: int = 0
    start_time: float = 0.0
```

---

## Part 2: Simulation UI — Complete Rewrite

File: `components/inference-sim/app/static/index.html`

### 2.1 Layout structure

```
┌─────────────────────────────────────────────────────────────────┐
│  NVIDIA STX: Inside Inference Memory    ● RUNNING    tick: 1234 │
│  TIERS  ● G1  ● G2  ● G3  ● G3.5  ● G4                       │
├───────────────────────────────────────────┬─────────────────────┤
│                                           │                     │
│  MEMORY HIERARCHY                         │  LIVE METRICS       │
│                                           │                     │
│  ┌─ GPU-A ────────┐  ┌─ GPU-B ────────┐  │  GPU-A     GPU-B    │
│  │ G1 ████░░ 65%  │  │ G1 ███░░ 52%   │  │  65%       52%     │
│  │    6.5/10 GB   │  │    5.2/10 GB    │  │                     │
│  │ G2 █████░ 80%  │  │ G2 ████░ 72%   │  │  Avg TTFT  85 ms   │
│  │    12/15 GB    │  │    10.8/15 GB   │  │  Cache hits  92%   │
│  │ G3 ██████ 90%  │  │ G3 █████ 85%   │  │  Cross-GPU   47    │
│  │    18/20 GB    │  │    17/20 GB     │  │  Recomputes   3    │
│  └────────────────┘  └────────────────┘  │  S3 ops/s    24    │
│                                           │  Sessions    48    │
│  ┌─ G3.5 MinIO CMX (shared) ──────────┐  │                     │
│  │ ████████████████████░░░░░ 72%      │  ├─────────────────────┤
│  │ 28.8 / 40 GB   evicts > 95%       │  │                     │
│  └────────────────────────────────────┘  │  EVICTION POLICY    │
│                                           │                     │
│  ┌─ G4 Enterprise (shared) ───────────┐  │  Strategy: LRU      │
│  │ ████░░░░░░░░░░░░░░░░░░░░ 12%      │  │                     │
│  │ 12 / 100 GB                        │  │  ┌ G1 ─────────┐   │
│  └────────────────────────────────────┘  │  │ Evict > 90%  │   │
│                                           │  │ ↓ to G2      │   │
│  ACTIVE SESSIONS (48 total)              │  └──────────────┘   │
│  Session  GPU  Tier    Status  Size      │  ┌ G2 ─────────┐   │
│  s-12345  A    G1      active  0.8 GB    │  │ Evict > 85%  │   │
│  s-23456  B    G3.5    idle    1.2 GB    │  │ ↓ to G3      │   │
│  s-34567  A    G2      idle    0.6 GB    │  └──────────────┘   │
│  ...                                     │  ┌ G3 ─────────┐   │
│                                           │  │ Evict > 80%  │   │
│  EVENT STREAM                            │  │ ↓ to G3.5    │   │
│  ↓ EVICT s-123 A:G1→G2 (G1 at 92%)     │  └──────────────┘   │
│  ↑ PROMOTE s-456 G3.5→B:G1 (cross-GPU) │  ┌ G3.5 ────────┐  │
│  ⚡ RECOMPUTE s-789 on B (no G3.5)      │  │ Evict > 95%  │   │
│                                           │  │ ↓ to G4      │   │
│                                           │  └──────────────┘   │
│                                           │                     │
│                                           │  Idle timeout:      │
│                                           │  20 ticks → evict   │
│                                           │  from G1 to G2      │
│                                           │                     │
├───────────────────────────────────────────┴─────────────────────┤
│  CONTROLS                                                       │
│                                                                 │
│  G3.5 context memory tier                                       │
│  ○ Disabled  ● Standard (S3/TCP, ~10ms)  ○ Accelerated (RDMA)  │
│                                                                 │
│  Concurrent sessions  ●───────────── 50   Context  [32K]        │
│  Simulation pace   [Slow] [Normal] [Fast]                       │
│                                                                 │
│  [Start Simulation]    [Reset]                                  │
│                                                                 │
│  ┌ Scenarios ───────────────────────────────────────────────┐   │
│  │ [Multi-turn burst] [Agentic reasoning] [GPU migration]   │   │
│  │ [Scale comparison — runs all 3 modes and compares]        │   │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Simulation uses scaled-down capacities. Real-world Vera Rubin: │
│  G1=80GB HBM, G2=512GB DRAM, G3=4TB NVMe per GPU.             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Eviction policy panel

This is the NEW section that answers "how/when does data move between tiers?"

Render as a vertical flow diagram on the right side, below the metrics:

```html
<div class="policy-panel">
  <div class="policy-header">EVICTION POLICY</div>
  <div class="policy-strategy">
    Strategy: <strong>LRU</strong> (coldest idle session evicted first)
  </div>

  <!-- Visual policy chain -->
  <div class="policy-chain">
    <div class="policy-tier" data-tier="g1">
      <div class="policy-tier-name">G1 GPU HBM</div>
      <div class="policy-rule">Evict when &gt; <span id="pol-g1-threshold">90</span>%</div>
      <div class="policy-arrow">↓ to G2</div>
    </div>
    <div class="policy-tier" data-tier="g2">
      <div class="policy-tier-name">G2 CPU DRAM</div>
      <div class="policy-rule">Evict when &gt; <span id="pol-g2-threshold">85</span>%</div>
      <div class="policy-arrow">↓ to G3</div>
    </div>
    <div class="policy-tier" data-tier="g3">
      <div class="policy-tier-name">G3 local NVMe</div>
      <div class="policy-rule">Evict when &gt; <span id="pol-g3-threshold">80</span>%</div>
      <div class="policy-arrow" id="pol-g3-target">↓ to G3.5</div>
    </div>
    <div class="policy-tier" data-tier="g35" id="pol-g35-tier">
      <div class="policy-tier-name">G3.5 MinIO CMX</div>
      <div class="policy-rule">Evict when &gt; <span id="pol-g35-threshold">95</span>%</div>
      <div class="policy-arrow">↓ to G4</div>
    </div>
    <div class="policy-tier" data-tier="g4">
      <div class="policy-tier-name">G4 Enterprise</div>
      <div class="policy-rule">Last resort — cold archive</div>
    </div>
  </div>

  <div class="policy-idle">
    <strong>Idle timeout:</strong> <span id="pol-idle-timeout">20</span> ticks →
    proactively evict from G1 to G2 even if G1 isn't full
  </div>

  <div class="policy-cross-gpu">
    <strong>Cross-GPU:</strong> When a session returns to a different GPU,
    Dynamo pulls the KV cache from G3.5 instead of recomputing.
    <span id="pol-cross-gpu-note">
      This is why G3.5 exists — it's the shared shelf between isolated GPUs.
    </span>
  </div>
</div>
```

**Dynamic behavior:**
- When the G3.5 mode is "Disabled", gray out the G3.5 tier in the policy chain, change the G3 arrow to "↓ to G4 (skip G3.5)", and update the cross-GPU note to say "Cross-GPU = full recomputation (no shared tier)."
- When a tier is currently over its eviction threshold, highlight that tier's policy box with a pulsing border (amber).
- The threshold percentages come from the WebSocket state's `eviction_policy` object.

**Eviction threshold indicators on tier bars:**

On each tier bar, draw a thin vertical line at the eviction threshold position:

```css
.tier-threshold-marker {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255, 200, 50, 0.6);  /* Amber — warning line */
  /* Position at threshold percentage */
  left: 90%;  /* For G1's 90% threshold */
}
```

When the fill bar reaches the threshold line, the audience sees why eviction is happening — the bar hit the line. Add a tiny label above the marker: "evict >" in 9px text.

### 2.3 Event stream with policy reasons

Each event in the event stream now shows WHY it happened:

```html
<div class="event" data-type="EVICT">
  <span class="event-icon">↓</span>
  <span class="event-time">12:34:05</span>
  <span class="event-text">
    EVICT <strong>s-12345</strong> GPU-A G1 → G2
  </span>
  <span class="event-reason">G1 at 92% capacity (threshold: 90%)</span>
</div>

<div class="event" data-type="PROMOTE">
  <span class="event-icon">↑</span>
  <span class="event-time">12:34:06</span>
  <span class="event-text">
    PROMOTE <strong>s-23456</strong> G3.5 → GPU-B G1
  </span>
  <span class="event-reason">Cross-GPU migration via shared MinIO G3.5</span>
</div>

<div class="event" data-type="RECOMPUTE">
  <span class="event-icon">⚡</span>
  <span class="event-time">12:34:07</span>
  <span class="event-text">
    RECOMPUTE <strong>s-34567</strong> on GPU-B
  </span>
  <span class="event-reason">G3.5 disabled — no shared tier available</span>
</div>
```

Style the reason line as smaller, muted text below the main event:

```css
.event-reason {
  display: block;
  font-size: 10px;
  color: rgba(255,255,255,0.4);
  margin-left: 20px;
  font-style: italic;
}
```

### 2.4 Three-mode G3.5 selector

Replace the binary toggle with radio buttons:

```html
<div class="g35-selector">
  <div class="g35-header">G3.5 context memory tier</div>
  <div class="g35-options">
    <label class="g35-option" data-mode="disabled">
      <input type="radio" name="g35mode" value="disabled">
      <div class="g35-option-content">
        <div class="g35-option-title">Disabled</div>
        <div class="g35-option-desc">No G3.5 tier. KV cache evicts G3 → G4. Cross-GPU = recompute.</div>
      </div>
    </label>
    <label class="g35-option" data-mode="standard">
      <input type="radio" name="g35mode" value="standard">
      <div class="g35-option-content">
        <div class="g35-option-title">Standard (S3 over TCP)</div>
        <div class="g35-option-desc">MinIO AIStor via Dynamo NIXL. Any infrastructure. ~5-10 ms.</div>
      </div>
    </label>
    <label class="g35-option selected" data-mode="accelerated">
      <input type="radio" name="g35mode" value="accelerated" checked>
      <div class="g35-option-content">
        <div class="g35-option-title">Accelerated (NVMe-oF / RDMA)</div>
        <div class="g35-option-desc">MinIO AIStor on BlueField-4 + Spectrum-X. ~200-500 μs.</div>
      </div>
    </label>
  </div>
</div>
```

### 2.5 Metric rules (no values >100%)

All percentage metrics MUST be clamped:

```javascript
function formatPct(value) {
  return Math.min(100, Math.max(0, Math.round(value))) + '%';
}

function formatMs(value) {
  return Math.round(Math.max(0, value)) + ' ms';
}

function formatCount(value) {
  const v = Math.max(0, Math.round(value));
  return v === 0 && !simulationStarted ? '—' : v.toString();
}
```

### 2.6 Scenario buttons

Four pre-built scenarios:

| Button | Config | What it shows |
|--------|--------|---------------|
| Multi-turn chat burst | 100 users, 32K, both GPUs busy | G3.5 absorbing bursty idle/return cycles |
| Agentic deep reasoning | 10 users, 128K, huge KV caches | Caches too big for G1+G2, G3.5 holds overflow |
| GPU migration stress | 200 users, 16K, 50% cross-GPU | G3.5 as the shared shelf — high cross-GPU migration rate |
| Scale comparison | Auto-runs disabled→standard→accelerated, 30s each | Three-column comparison at the end |

---

## Part 3: SchematicNode for React Flow Canvas

### 3.1 Type definition

File: `frontend/src/types/index.ts`

```typescript
export interface SchematicChild {
  id: string;
  label: string;
  detail?: string;
  color: 'red' | 'amber' | 'blue' | 'teal' | 'gray';
}

export interface SchematicNodeData {
  label: string;
  sublabel?: string;
  children?: SchematicChild[];
  variant: 'gpu' | 'tier' | 'generic';
  width?: number;
  height?: number;
}
```

### 3.2 SchematicNode component

File: `frontend/src/components/canvas/nodes/SchematicNode.tsx`

A visual-only node that renders GPU internals with tier children. Not selectable, not connectable, not deletable. Excluded from compose generation.

```tsx
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import type { SchematicNodeData, SchematicChild } from '../../../types';

const tierColors: Record<string, { bg: string; border: string; text: string }> = {
  red:   { bg: 'bg-red-500/10',   border: 'border-red-400/40',   text: 'text-red-300' },
  amber: { bg: 'bg-amber-500/10', border: 'border-amber-400/40', text: 'text-amber-300' },
  blue:  { bg: 'bg-blue-500/10',  border: 'border-blue-400/40',  text: 'text-blue-300' },
  teal:  { bg: 'bg-teal-500/10',  border: 'border-teal-400/40',  text: 'text-teal-300' },
  gray:  { bg: 'bg-zinc-500/10',  border: 'border-zinc-400/40',  text: 'text-zinc-400' },
};

function SchematicNode({ data }: NodeProps) {
  const d = data as SchematicNodeData;

  if (d.variant === 'gpu') {
    return (
      <div
        className="rounded-lg border border-dashed border-purple-400/30 bg-purple-500/5 p-3"
        style={{ width: d.width || 200, minHeight: d.height || 160 }}
      >
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs font-semibold text-purple-200">{d.label}</span>
          {d.sublabel && (
            <span className="text-[10px] text-purple-400/60 ml-auto">{d.sublabel}</span>
          )}
        </div>
        <div className="space-y-1.5">
          {d.children?.map((child: SchematicChild) => {
            const c = tierColors[child.color] || tierColors.gray;
            return (
              <div key={child.id} className={`rounded px-2 py-1.5 border ${c.bg} ${c.border}`}>
                <div className={`text-[11px] font-medium ${c.text}`}>{child.label}</div>
                {child.detail && (
                  <div className="text-[9px] text-zinc-500 mt-0.5">{child.detail}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded border border-dashed border-zinc-600 bg-zinc-800/30 px-3 py-2"
         style={{ width: d.width || 150 }}>
      <div className="text-xs font-medium text-zinc-300">{d.label}</div>
      {d.sublabel && <div className="text-[10px] text-zinc-500 mt-0.5">{d.sublabel}</div>}
    </div>
  );
}

export default memo(SchematicNode);
```

Register in `DiagramCanvas.tsx` nodeTypes and ensure compose generator skips schematic nodes.

### 3.3 Backend model

File: `backend/app/models/demo.py`

```python
class SchematicChild(BaseModel):
    id: str
    label: str
    detail: str = ""
    color: str = "gray"

class DemoSchematicNode(BaseModel):
    id: str
    position: NodePosition
    label: str
    sublabel: str = ""
    variant: str = "generic"
    children: list[SchematicChild] = []
    parent_group: str | None = None
    width: int | None = None
    height: int | None = None
```

Add `schematics: list[DemoSchematicNode] = []` to `DemoDefinition`.

---

## Part 4: Edge Protocol & Latency Labels

### 4.1 Edge data model

File: `frontend/src/types/index.ts`

```typescript
export interface DemoEdgeData {
  label?: string;
  protocol?: string;    // "NVMe-oF / RDMA · S3 / TCP"
  latency?: string;     // "~500 μs (RDMA) · ~10 ms (TCP)"
  bandwidth?: string;   // "800 Gb/s"
}
```

File: `backend/app/models/demo.py` — add to `DemoEdge`:

```python
class DemoEdge(BaseModel):
    # ... existing fields ...
    protocol: str = ""
    latency: str = ""
    bandwidth: str = ""
```

### 4.2 Edge label rendering

File: `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx`

Add protocol/latency pills below the main edge label. Teal pill for protocol, amber for latency, blue for bandwidth. Different edge stroke styles per protocol (RDMA = thick teal 2.5px, S3/TCP = normal gray, gRPC = dashed blue).

### 4.3 Template edge definitions

```yaml
edges:
  - id: e-client-sim
    source: inference-client
    target: sim-1
    connection_type: inference-api
    label: "Inference requests"
    protocol: "gRPC"
    latency: "~1 ms"

  - id: e-sim-g35
    source: sim-1
    target: minio-g35
    connection_type: s3
    label: "G3.5 context memory"
    protocol: "NVMe-oF / RDMA  ·  S3 / TCP"
    latency: "~500 μs (RDMA) · ~10 ms (TCP)"
    bandwidth: "800 Gb/s"

  - id: e-sim-g4
    source: sim-1
    target: minio-g4
    connection_type: s3
    label: "G4 enterprise storage"
    protocol: "S3 over TCP"
    latency: "~50-200 ms"
    bandwidth: "25 Gb/s"
```

---

## Part 5: Updated Template — Complete YAML

File: `demo-templates/experience-stx-inference.yaml`

The full template includes:
- 5 component nodes: inference-client, sim-1, minio-g35, minio-g4, prometheus-1
- 1 group: gpu-server (dashed purple, 480x300)
- 2 schematic nodes: sch-gpu-a, sch-gpu-b (inside gpu-server, each with G1/G2/G3 children)
- 5 edges with protocol/latency labels
- 10 annotations covering: architecture overview, GPU isolation, G3.5 two-mode explanation, connectivity comparison, step guidance (3 steps), performance claim, inference client explanation
- sim-1 has `parent_group: gpu-server`

(Use the template from the gpu-server-internals file, merged with the three-mode G3.5 annotations.)

---

## Part 6: Verification

### Unit tests

```python
def test_three_g35_modes():
    """Simulation should support disabled, standard, accelerated modes."""
    for mode in [G35Mode.DISABLED, G35Mode.STANDARD, G35Mode.ACCELERATED]:
        config = SimulationConfig(g35_mode=mode)
        engine = SimulationEngine(config)
        assert engine.config.g35_mode == mode

def test_eviction_threshold_triggers():
    """Eviction should trigger when tier exceeds threshold."""
    config = SimulationConfig()
    mgr = KVBlockManager(config)
    # Fill G1 to 95% (above 90% threshold)
    mgr.gpus[0].g1.used_gb = 9.5
    mgr.gpus[0].g1.block_count = 10
    # Add an idle session in G1
    mgr.sessions.append(Session(id="test", gpu_id="gpu-a", tier="g1", size_gb=1.0, active=False, idle_ticks=5))
    events = mgr.eviction_cascade("gpu-a", tick=1)
    assert len(events) > 0
    assert events[0].event_type == "EVICT"
    assert "90%" in events[0].policy_rule

def test_idle_timeout_eviction():
    """Sessions idle beyond timeout should be proactively evicted."""
    config = SimulationConfig()
    mgr = KVBlockManager(config)
    mgr.gpus[0].g1.used_gb = 5.0
    mgr.gpus[0].g1.block_count = 5
    session = Session(id="idle-test", gpu_id="gpu-a", tier="g1", size_gb=1.0, active=False, idle_ticks=25)
    mgr.sessions.append(session)
    events = mgr.idle_eviction(tick=100)
    assert len(events) > 0
    assert "Idle for 25 ticks" in events[0].reason

def test_cross_gpu_with_g35_standard():
    """Cross-GPU migration with standard G3.5 should work but show higher latency."""
    config = SimulationConfig(g35_mode=G35Mode.STANDARD)
    mgr = KVBlockManager(config)
    latency = mgr.compute_promotion_latency("g35")
    assert latency == 15  # ~5-10 ms simulated

def test_cross_gpu_with_g35_accelerated():
    """Cross-GPU with accelerated G3.5 should show low latency."""
    config = SimulationConfig(g35_mode=G35Mode.ACCELERATED)
    mgr = KVBlockManager(config)
    latency = mgr.compute_promotion_latency("g35")
    assert latency == 3  # ~500 μs simulated

def test_cross_gpu_disabled_recomputes():
    """Cross-GPU with G3.5 disabled should require recomputation."""
    config = SimulationConfig(g35_mode=G35Mode.DISABLED)
    engine = SimulationEngine(config)
    # Force a cross-GPU return scenario...
    # Assert recomputation event generated

def test_metrics_never_exceed_100():
    """All percentage metrics must be 0-100."""
    config = SimulationConfig(users=200)
    engine = SimulationEngine(config)
    # Run 200 ticks
    for _ in range(200):
        engine._process_tick()
    engine._update_metrics()
    snapshot = engine._build_state_snapshot()
    assert 0 <= snapshot["metrics"]["gpu_a_utilization"] <= 100
    assert 0 <= snapshot["metrics"]["gpu_b_utilization"] <= 100
    assert 0 <= snapshot["metrics"]["cache_hit_rate"] <= 100
    for gpu in snapshot["gpus"]:
        assert 0 <= gpu["g1"]["pct"] <= 100
        assert 0 <= gpu["g2"]["pct"] <= 100
        assert 0 <= gpu["g3"]["pct"] <= 100

def test_eviction_policy_in_state():
    """State snapshot should include eviction policy details."""
    config = SimulationConfig()
    engine = SimulationEngine(config)
    snapshot = engine._build_state_snapshot()
    assert "eviction_policy" in snapshot
    assert snapshot["eviction_policy"]["strategy"] == "LRU (coldest idle session evicted first)"
    assert snapshot["eviction_policy"]["g1_threshold"] == "90%"

def test_events_include_reasons():
    """Every event should have a non-empty reason and policy_rule."""
    config = SimulationConfig(users=100)
    engine = SimulationEngine(config)
    for _ in range(500):
        engine._process_tick()
    for event in engine.recent_events:
        assert event.reason, f"Event {event.event_type} missing reason"
        assert event.policy_rule, f"Event {event.event_type} missing policy_rule"

def test_schematic_not_in_compose():
    """Schematic nodes must not appear in generated compose file."""
    template = load_template("experience-stx-inference")
    compose = generate_compose(template, "/tmp")
    with open(compose) as f:
        data = yaml.safe_load(f)
    assert "sch-gpu-a" not in data.get("services", {})
    assert "sch-gpu-b" not in data.get("services", {})
```

### Playwright E2E

```typescript
test.describe('Inference Simulator', () => {
  test.beforeAll(async () => {
    // Deploy STX Experience, wait for healthy
  });

  // --- Canvas tests ---
  test('GPU schematics show G1/G2/G3 tiers', async ({ page }) => {
    await expect(page.locator('text=G1 — GPU HBM')).toHaveCount(2);  // One per GPU
    await expect(page.locator('text=G2 — CPU DRAM')).toHaveCount(2);
    await expect(page.locator('text=80 GB')).toBeVisible();
  });

  test('G3.5 edge shows both protocols', async ({ page }) => {
    await expect(page.locator('text=NVMe-oF / RDMA')).toBeVisible();
    await expect(page.locator('text=S3 / TCP')).toBeVisible();
  });

  test('edges show latency values', async ({ page }) => {
    await expect(page.locator('text=~500 μs')).toBeVisible();
    await expect(page.locator('text=~10 ms')).toBeVisible();
  });

  // --- Simulation UI tests ---
  test('shows two GPU columns', async ({ page }) => {
    // Navigate to simulation UI
    await expect(page.locator('[data-testid="gpu-column-a"]')).toBeVisible();
    await expect(page.locator('[data-testid="gpu-column-b"]')).toBeVisible();
  });

  test('shows eviction policy panel', async ({ page }) => {
    await expect(page.locator('text=EVICTION POLICY')).toBeVisible();
    await expect(page.locator('text=LRU')).toBeVisible();
    await expect(page.locator('text=Evict when')).toBeVisible();
  });

  test('tier bars show eviction threshold markers', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(3000);
    // Threshold markers should be visible on tier bars
    const markers = page.locator('[data-testid^="threshold-marker-"]');
    await expect(markers).toHaveCount({ minimum: 6 }); // 3 tiers x 2 GPUs
  });

  test('three G3.5 modes available', async ({ page }) => {
    await expect(page.locator('[data-testid="g35-mode-disabled"]')).toBeVisible();
    await expect(page.locator('[data-testid="g35-mode-standard"]')).toBeVisible();
    await expect(page.locator('[data-testid="g35-mode-accelerated"]')).toBeVisible();
  });

  test('standard mode shows higher TTFT than accelerated', async ({ page }) => {
    await page.click('[data-testid="g35-mode-accelerated"]');
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(5000);
    const ttftAccel = parseInt(await page.locator('[data-testid="metric-ttft"]').textContent() || '0');

    await page.click('[data-testid="g35-mode-standard"]');
    await page.waitForTimeout(5000);
    const ttftStd = parseInt(await page.locator('[data-testid="metric-ttft"]').textContent() || '0');

    expect(ttftStd).toBeGreaterThan(ttftAccel);
  });

  test('events show reasons', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(8000);
    // Event stream should show reason text
    const reasons = page.locator('.event-reason');
    await expect(reasons.first()).toBeVisible();
    const text = await reasons.first().textContent();
    expect(text!.length).toBeGreaterThan(5); // Not empty
  });

  test('cross-GPU events visible with G3.5 enabled', async ({ page }) => {
    await page.click('[data-testid="g35-mode-accelerated"]');
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(15000);
    await expect(page.locator('text=cross-GPU')).toBeVisible({ timeout: 20000 });
  });

  test('disabled mode grays out G3.5 in policy panel', async ({ page }) => {
    await page.click('[data-testid="g35-mode-disabled"]');
    await expect(page.locator('[data-testid="pol-g35-tier"]')).toHaveClass(/disabled/);
  });

  test('metrics never exceed 100%', async ({ page }) => {
    await page.click('[data-testid="start-sim-btn"]');
    await page.waitForTimeout(10000);
    const pcts = page.locator('[data-testid^="tier-pct-"]');
    for (let i = 0; i < await pcts.count(); i++) {
      const val = parseInt((await pcts.nth(i).textContent())!.replace('%', ''));
      expect(val).toBeLessThanOrEqual(100);
      expect(val).toBeGreaterThanOrEqual(0);
    }
  });
});
```

---

## What NOT to do

- Don't show individual KV blocks as rectangles inside tier bars — use simple fill bars with threshold markers
- Don't allow metrics to exceed 100% — clamp everything with `Math.min(100, Math.max(0, value))`
- Don't use more than 2 GPUs — 2 is enough to demonstrate shared context
- Don't create Docker containers for schematic nodes — they are canvas-only
- Don't hardcode protocol/latency rendering for STX only — the edge enhancement is generic
- Don't animate DOM elements flying across the screen for block movement — show events in the log, update bars via CSS transitions
- Don't make the three-mode selector a dropdown — use visible radio buttons so the audience can see all options at once
- Don't forget the footer note about scaled-down capacities vs real-world specs
