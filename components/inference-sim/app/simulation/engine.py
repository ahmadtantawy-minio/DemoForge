from __future__ import annotations

import asyncio
import collections
import random
import time
from collections import deque

from dataclasses import dataclass, field as dc_field

from app.config import settings


# ---------------------------------------------------------------------------
# GPU Time-Budget Tracker
# ---------------------------------------------------------------------------

@dataclass
class GPUTickBudget:
    """How a single GPU spent one tick of time."""
    active_inference: float = 0.0
    io_stall: float = 0.0
    recompute: float = 0.0
    idle: float = 0.0


@dataclass
class GPUTimeTracker:
    """Tracks how each GPU spends its time over a rolling window.

    Each tick, a GPU's time budget sums to 1.0:
      active_inference + io_stall + recompute + idle = 1.0
    """
    window_size: int = 100
    history: collections.deque = dc_field(default_factory=collections.deque)

    def __post_init__(self):
        self.history = collections.deque(maxlen=self.window_size)
    remaining_stall_ticks: int = 0
    remaining_recompute_ticks: int = 0

    def record_tick(self, active_sessions: int, max_sessions: int):
        budget = GPUTickBudget()
        remaining = 1.0

        # I/O stall: fraction depends on latency magnitude
        # 3 ticks (accelerated) → ~4%, 15 ticks (standard) → ~12%, 50 (g4) → ~25%
        if self.remaining_stall_ticks > 0:
            stall_frac = min(0.3, self.remaining_stall_ticks * 0.012)
            budget.io_stall = stall_frac
            remaining -= stall_frac
            self.remaining_stall_ticks = max(0, self.remaining_stall_ticks - 1)

        # Recompute: heavier penalty — full recompute burns ~40% of tick
        if self.remaining_recompute_ticks > 0:
            recomp_frac = min(remaining, 0.4)
            budget.recompute = recomp_frac
            remaining -= recomp_frac
            self.remaining_recompute_ticks = max(0, self.remaining_recompute_ticks - 1)

        # Active inference from remaining capacity
        if remaining > 0 and max_sessions > 0 and active_sessions > 0:
            budget.active_inference = remaining * min(1.0, active_sessions / max_sessions)
            budget.idle = remaining - budget.active_inference
        else:
            budget.idle = remaining

        self.history.append(budget)

    def register_io_stall(self, ticks: int):
        # Accumulate: concurrent G4/G3.5 restores pile up stall budget.
        # G4 (12-18 ticks each) accumulates fast → high IO stall %.
        # G3.5 (2-3 ticks each) accumulates slowly → low IO stall %.
        # Cap at 80 to prevent runaway on extreme bursts.
        self.remaining_stall_ticks = min(80, self.remaining_stall_ticks + ticks)

    def register_recompute(self, ticks: int):
        # Cap: only the longest recompute matters
        self.remaining_recompute_ticks = max(self.remaining_recompute_ticks, ticks)

    def reset(self):
        self.history.clear()
        self.remaining_stall_ticks = 0
        self.remaining_recompute_ticks = 0

    def utilization(self) -> dict:
        if not self.history:
            return {"active": 0, "io_stall": 0, "recompute": 0, "idle": 100}
        n = len(self.history)
        raw_active = sum(b.active_inference for b in self.history) / n * 100
        raw_stall = sum(b.io_stall for b in self.history) / n * 100
        raw_recomp = sum(b.recompute for b in self.history) / n * 100
        raw_idle = sum(b.idle for b in self.history) / n * 100
        # Normalize to ensure sum = 100 after rounding
        total = raw_active + raw_stall + raw_recomp + raw_idle
        if total > 0:
            scale = 100.0 / total
            raw_active *= scale
            raw_stall *= scale
            raw_recomp *= scale
            raw_idle *= scale
        # Round with remainder correction
        vals = [raw_active, raw_stall, raw_recomp, raw_idle]
        rounded = [int(v) for v in vals]
        remainder = 100 - sum(rounded)
        # Distribute remainder to largest fractional parts
        fracs = [(v - int(v), i) for i, v in enumerate(vals)]
        fracs.sort(reverse=True)
        for j in range(remainder):
            rounded[fracs[j][1]] += 1
        return {
            "active": max(0, rounded[0]),
            "io_stall": max(0, rounded[1]),
            "recompute": max(0, rounded[2]),
            "idle": max(0, rounded[3]),
        }
from app.models import (
    SimConfig, SimStatus, TierState, GPUTierState, SharedTierState, SessionState,
)
from app.simulation.kv_block_manager import KVBlockManager, GPU_IDS, effective_g4_ticks
from app.simulation.kv_memory_model import (
    GPU_TYPE_LABEL,
    KV_PRECISION_NOTE,
    MODEL_NAME,
    kv_bytes_per_token_per_gpu_tp2,
    kv_per_session_gb,
    sessions_fit_in_kv_cap,
)
from app.simulation.session_manager import Session, SessionManager
from app.simulation.request_generator import RequestGenerator
from app.simulation.minio_backend import MinIOBackend
from app.simulation import metrics as sim_metrics

# 100 KB per KV block (laptop-friendly, not real 50 MB)
KV_BLOCK_SIZE_BYTES = 100 * 1024

# ---------------------------------------------------------------------------
# Scenario Parameter Bundles
# ---------------------------------------------------------------------------

SCENARIO_PARAMS: dict[str, dict] = {
    "file-g4": {
        # G4 tier: Traditional NFS/POSIX file storage
        # POSIX metadata bottlenecks, kernel overhead, lock convoys under concurrent GPU access.
        # Sources: NVIDIA tech blog, Introl 2025, WEKA analysis
        "g4_base_ticks": 50,            # ~500ms effective at tick=0.2s
        "g4_jitter_pct": 0.50,          # ±50% variance (metadata lock jitter)
        "g4_parallel_factor": 1,        # Serial: POSIX locks serialize readers
        "g4_label": "File / POSIX",

        "g35_enabled": False,
        "g35_ticks": None,

        # Cross-GPU migration: devastating without G3.5 — heavy stall + recompute vs inference
        "cross_gpu_recompute_chance": 0.55,  # POSIX path often loses race → recompute
        "cross_gpu_restore_ticks": 56,       # Slow, jittery file reads when it does try
        "cross_gpu_restore_jitter_pct": 0.30,

        # POSIX degrades non-linearly under concurrent access
        "concurrency_collapse_enabled": True,
    },
    "minio-g4": {
        # G4 tier: MinIO S3 object storage over TCP
        # S3 GET is stateless — no locks, no metadata server bottleneck.
        # Sources: Pure Storage KVA ("6x faster with S3"), VAST Data, MinIO AIStor specs
        "g4_base_ticks": 12,            # ~120ms effective (S3 GET over TCP)
        "g4_jitter_pct": 0.20,          # ±20% (consistent, no lock contention)
        "g4_parallel_factor": 4,        # 4 concurrent reads before degradation
        "g4_label": "MinIO S3 (G4 tier)",

        "g35_enabled": False,
        "g35_ticks": None,

        # Cross-GPU migration: viable via G4 S3 restore — strong G4 path vs POSIX
        "cross_gpu_recompute_chance": 0.07,  # rare recompute; inference time grows vs file/POSIX
        "cross_gpu_restore_ticks": 16,       # S3/TCP cross-GPU: faster restore than POSIX
        "cross_gpu_restore_jitter_pct": 0.15,

        "concurrency_collapse_enabled": False,
    },
    "minio-full": {
        # G4 tier: same MinIO S3 as minio-g4
        "g4_base_ticks": 12,
        "g4_jitter_pct": 0.20,
        "g4_parallel_factor": 4,
        "g4_label": "MinIO S3",

        # G3.5 tier: MinIO NVMe-oF/RDMA via BlueField-4
        # Sources: NVIDIA BF-4 tech blog, DataCore NVMe-oF ("10-20 microseconds"), VentureBeat STX ("5x TPS")
        "g35_enabled": True,
        "g35_ticks": 2,                 # ~20μs class (RDMA)
        "g35_label": "MinIO RDMA",

        # Cross-GPU migration: cheap via G3.5 RDMA
        "cross_gpu_recompute_chance": 0.002,  # <0.2% recompute — RDMA almost never fails
        "cross_gpu_restore_ticks": 2,         # RDMA promotion: ~20μs class
        "cross_gpu_restore_jitter_pct": 0.10,

        "concurrency_collapse_enabled": False,
    },
}

_SCENARIO_LABELS = {
    "file-g4": "File / POSIX Storage",
    "minio-g4": "G4 as MinIO Object Store",
    "minio-full": "MinIO G4 S3 + G3.5 CTX RDMA",
}

# Narrative targets for stacked GPU time (active inference vs I/O stall vs recompute).
# Blended with live tracker output so the UI shows a clear step-up across scenarios.
_SCENARIO_UTIL_TARGETS: dict[str, dict[str, int]] = {
    # Saturated GPU: idle ~0 — bar reads ~100% busy (POSIX still low *useful* inference).
    "file-g4": {"active": 32, "io_stall": 34, "recompute": 33, "idle": 1},
    # Strong inference uplift; G4 path viable — moderate stall, lower recompute
    "minio-g4": {"active": 64, "io_stall": 21, "recompute": 12, "idle": 3},
    # Near-saturated inference; RDMA path — minimal stall/recompute
    "minio-full": {"active": 92, "io_stall": 5, "recompute": 2, "idle": 1},
}

# Weight on narrative targets vs raw simulation (0..1). Higher = clearer scenario story.
_SCENARIO_UTIL_BLEND = 0.48

# Default promotion-latency ticks when rolling window empty (cold start).
_SCENARIO_DEFAULT_PROMO_TICKS = {
    "file-g4": 12.0,
    "minio-g4": 1.05,
    "minio-full": 0.14,
}

# Scales I/O component of TTFT from tier promotions (multiplier on avg_promo * tick_ms).
_SCENARIO_TTFT_IO_SCALE = {
    "file-g4": 3.15,
    "minio-g4": 0.29,
    "minio-full": 0.035,
}

# Blend raw counter ratio toward scenario-coherent KV hit % (raw counters skew high vs GPU recompute time).
_SCENARIO_CACHE_HIT_BLEND = 0.48
_SCENARIO_CACHE_HIT_ANCHOR = {
    "file-g4": 52.0,
    "minio-g4": 80.0,
    "minio-full": 97.0,
}

_TICK_MS = 200.0  # engine tick interval for latency display (matches sim loop)

# Fallback G4 restore latency (ms) for UI before enough live samples exist — demo-tuned, scenario-specific.
_SCENARIO_G4_RESTORE_UI_MS: dict[str, float] = {
    "file-g4": 880.0,
    "minio-g4": 118.0,
    "minio-full": 118.0,
}


def _blend_scenario_utilization(raw: dict[str, int], scenario: str) -> dict[str, int]:
    """Blend tracker percentages toward scenario targets; normalize to sum 100."""
    targets = _SCENARIO_UTIL_TARGETS.get(scenario, _SCENARIO_UTIL_TARGETS["file-g4"])
    alpha = _SCENARIO_UTIL_BLEND
    keys = ("active", "io_stall", "recompute", "idle")
    blended = [(1.0 - alpha) * float(raw[k]) + alpha * float(targets[k]) for k in keys]
    tot = sum(blended)
    if tot <= 0:
        return raw
    vals = [b * 100.0 / tot for b in blended]
    rounded = [int(v) for v in vals]
    rem = 100 - sum(rounded)
    if rem > 0:
        order = sorted(range(4), key=lambda i: vals[i] - rounded[i], reverse=True)
        for k in range(rem):
            rounded[order[k % 4]] += 1
    elif rem < 0:
        order = sorted(range(4), key=lambda i: vals[i] - rounded[i])
        k = 0
        while sum(rounded) > 100 and k < 50:
            idx = order[k % 4]
            if rounded[idx] > 0:
                rounded[idx] -= 1
            k += 1
    out = {keys[i]: max(0, rounded[i]) for i in range(4)}
    drift = 100 - sum(out.values())
    if drift != 0:
        out["active"] = max(0, out["active"] + drift)
    return out

# Backward-compat mapping: old g35_mode values → new scenario IDs.
# NOTE: "standard" mapped to "minio-g4" (G3.5 disabled) intentionally —
# old "standard" meant S3/TCP without RDMA, which is exactly minio-g4.
# Old "accelerated" (G3.5 RDMA on) → "minio-full".
_G35_TO_SCENARIO = {
    "disabled": "file-g4",
    "standard": "minio-g4",
    "accelerated": "minio-full",
}

_SCENARIO_TO_G35 = {v: k for k, v in _G35_TO_SCENARIO.items()}


def _scenario_recompute_reason(scenario: str) -> str:
    if scenario == "file-g4":
        return "File/NFS read timeout — gave up on slow restore"
    elif scenario == "minio-g4":
        return "S3 restore fallback — rare but possible"
    else:  # minio-full
        return "Rare RDMA transfer timeout — fallback recompute"


def _scenario_cross_gpu_labels(scenario: str, ticks: int) -> tuple[str, str, str]:
    latency_ms = ticks * 200
    if scenario == "minio-full":
        return (
            "MinIO RDMA",
            f"Cross-GPU via G3.5 (NVMe-oF/RDMA, ~{latency_ms}ms)",
            "Dynamo router → NIXL RDMA from shared G3.5",
        )
    elif scenario == "minio-g4":
        return (
            "MinIO S3",
            f"Cross-GPU restore via G4 (S3/TCP, ~{latency_ms}ms)",
            "Dynamo router → S3 GET from G4",
        )
    else:  # file-g4
        return (
            "File/NFS",
            f"Cross-GPU restore via G4 (File/NFS, ~{latency_ms}ms)",
            "File read from NFS/POSIX storage",
        )


class SimulationEngine:
    def __init__(self) -> None:
        self.config = SimConfig(
            users=settings.sim_default_users,
            context_tokens=settings.sim_default_context,
            scenario=settings.sim_default_scenario,
        )
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._tick = 0
        self._running = False
        self._ws_clients: set = set()

        # Rolling window for S3 ops rate
        self._s3_ops_window: deque[float] = deque(maxlen=50)
        self._s3_ops_count = 0
        self._last_s3_ops_count = 0
        self._last_rate_ts = time.monotonic()

        # Promotion latency: rolling window for legacy TTFT I/O leg (restore paths only)
        self._promotion_latency_ticks: list[int] = []
        self._rolling_ttft: collections.deque = collections.deque(maxlen=100)
        # End-to-end TTFT (ms): request accepted tick → first-token tick, including scheduler queue
        self._rolling_ttft_e2e_ms: collections.deque = collections.deque(maxlen=100)

        # Dual-GPU tracking
        self._cross_gpu_migrations = 0
        self._recomputations = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # Event log for current tick (broadcast to WS clients)
        self._tick_events: list[dict] = []
        # Persistent event buffer for REST polling (last 50 events across ticks)
        self._all_events: list[dict] = []
        # Rolling event history (last 15 events with reason/policy)
        self._event_history: deque[dict] = deque(maxlen=15)
        # Surface failures in API/UI instead of silent tick-loop swallow
        self._backend_errors: deque[str] = deque(maxlen=24)

        # Rolling G4 restore latencies (ms); ticks * _TICK_MS from successful G4 read paths
        self._g4_restore_ms_samples: collections.deque = collections.deque(maxlen=120)

        # Per-GPU time-budget trackers
        self.gpu_trackers = {
            gpu_id: GPUTimeTracker(window_size=100)
            for gpu_id in GPU_IDS
        }

        self._init_components()

    def _get_params(self) -> dict:
        """Return scenario params for current scenario."""
        return SCENARIO_PARAMS.get(self.config.scenario, SCENARIO_PARAMS["file-g4"])

    def _record_g4_restore_ms(self, ticks: int) -> None:
        """Sample successful G4 restore latency (exclude recompute penalty ticks==50)."""
        if ticks <= 0 or ticks == 50:
            return
        self._g4_restore_ms_samples.append(float(ticks) * _TICK_MS)

    def _g4_avg_restore_ms_for_metrics(self, scenario: str) -> tuple[float, int]:
        """(display_ms, sample_count) for G4 tier UI."""
        n = len(self._g4_restore_ms_samples)
        if n >= 4:
            avg = sum(self._g4_restore_ms_samples) / float(n)
            return (round(avg, 0), n)
        ref = _SCENARIO_G4_RESTORE_UI_MS.get(
            scenario, _SCENARIO_G4_RESTORE_UI_MS["file-g4"]
        )
        return (ref, n)

    def _apply_scenario(self) -> None:
        """Update block_manager + scenario flags. Does not clear GPU time history.

        Storage-scenario switches used to flush stall/recompute state and the
        rolling utilization window, which made bars and metrics snap to zero.
        We keep trackers and in-flight IO/recompute so transitions stay smooth;
        use `reset()` for a full wipe.

        `self.config.scenario` is the single source of truth: `_get_params()` reads
        `SCENARIO_PARAMS[scenario]` for every tick and both `gpu-a` / `gpu-b` paths
        (shared block manager + per-GPU trackers). There is no per-GPU scenario.
        """
        params = self._get_params()
        self.block_manager.cmx_enabled = params["g35_enabled"]

    def _init_components(self) -> None:
        params = self._get_params()
        self.block_manager = KVBlockManager(
            g1_cap=settings.g1_kv_capacity_gb,
            g2_cap=settings.g2_capacity_gb,
            g3_cap=settings.g3_capacity_gb,
            g35_cap=settings.g35_capacity_gb,
            g4_cap=settings.g4_capacity_gb,
            cmx_enabled=params["g35_enabled"],
            g1_hbm_total_gb=settings.g1_hbm_total_gb,
            g1_weights_gb=settings.g1_weights_gb_per_gpu,
            g1_overhead_gb=settings.g1_overhead_gb_per_gpu,
        )
        self.session_manager = SessionManager()
        self.request_gen = RequestGenerator()
        self.minio_g35 = MinIOBackend(
            endpoint=settings.minio_endpoint_g35,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.kv_bucket_warm,
        )
        self.minio_g4 = MinIOBackend(
            endpoint=settings.minio_endpoint_g4,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.kv_bucket_cold,
        )

    async def _safe_exec(self, loop, fn, *args, timeout=3.0):
        """Run a blocking function in executor with timeout — never blocks the tick loop."""
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, fn, *args), timeout=timeout
            )
        except (asyncio.TimeoutError, Exception):
            return None

    async def ensure_buckets(self) -> None:
        loop = asyncio.get_event_loop()
        await self._safe_exec(loop, self.minio_g35.ensure_bucket, timeout=5.0)
        await self._safe_exec(loop, self.minio_g4.ensure_bucket, timeout=5.0)

    async def start(self, config: SimConfig | None = None) -> None:
        async with self._lock:
            if self._running:
                return
            if config:
                self.config = config
            self._apply_scenario()
            self._running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        # Never await the sim task while holding _lock: _loop needs the same lock each tick.
        # Doing so deadlocks stop() (stuck Stop button, frozen TICK).
        task: asyncio.Task | None = None
        async with self._lock:
            if not self._running:
                return
            self._running = False
            task = self._task
            self._task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def update_config(self, config: SimConfig) -> None:
        async with self._lock:
            if config.scenario != self.config.scenario:
                self._g4_restore_ms_samples.clear()
            self.config = config
            self._apply_scenario()

    async def update_config_partial(self, updates: dict) -> None:
        """Merge partial config updates without resetting unmentioned fields."""
        async with self._lock:
            # Backward compat: map legacy g35_mode to scenario if scenario not explicitly set
            if "g35_mode" in updates and "scenario" not in updates:
                updates = dict(updates)
                updates["scenario"] = _G35_TO_SCENARIO.get(updates["g35_mode"], "file-g4")
            prev_scenario = self.config.scenario
            for key, val in updates.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, val)
            if self.config.scenario != prev_scenario:
                self._g4_restore_ms_samples.clear()
            self._apply_scenario()

    def jittered_g4_ticks(self, n_concurrent_reads: int = 1) -> int:
        """Get G4 ticks with scenario-appropriate jitter and concurrency collapse."""
        params = self._get_params()
        base = params["g4_base_ticks"]
        jitter_range = int(base * params["g4_jitter_pct"])
        jitter = random.randint(-jitter_range, jitter_range) if jitter_range > 0 else 0
        raw = max(1, base + jitter)
        return effective_g4_ticks(raw, n_concurrent_reads, params)

    def _assign_initial_ttft_schedule(self, session: Session, gpu_id: str) -> None:
        """Wall-clock TTFT for a new request: accepted tick → first token (queue + prefill ticks).

        Queue depth uses G1 contention after allocate; each tick is _TICK_MS narrative ms.
        """
        scenario = self.config.scenario
        session.request_sent_tick = self._tick
        g1 = self.block_manager.gpu_tiers[gpu_id]["G1"]
        ahead = max(0, g1.block_count - 1)
        avg_kv = kv_per_session_gb(self.config.context_tokens)
        max_sess = max(1, int(g1.capacity_gb / avg_kv)) if avg_kv > 0 else 10
        denom = max(1, max_sess - 1)
        fill = min(1.0, ahead / float(denom))

        if scenario == "file-g4":
            per_ahead = 3.5 + random.random() * 6.0
            cap = 52
            fill_w = 10.0
        elif scenario == "minio-g4":
            per_ahead = 0.9 + random.random() * 2.2
            cap = 22
            fill_w = 5.0
        else:
            per_ahead = 0.25 + random.random() * 0.55
            cap = 10
            fill_w = 2.0

        queue_ticks = min(
            cap,
            int(ahead * per_ahead + fill * fill_w + random.random() * 2),
        )
        prefill_ticks = 2 + random.randint(0, 4)
        session.first_token_scheduled_tick = self._tick + queue_ticks + prefill_ticks

    async def reset(self) -> None:
        await self.stop()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await self._safe_exec(loop, self.minio_g35.delete_all, timeout=5.0)
            await self._safe_exec(loop, self.minio_g4.delete_all, timeout=5.0)
            self.block_manager.clear()
            self.session_manager.clear()
            self._tick = 0
            self._s3_ops_count = 0
            self._last_s3_ops_count = 0
            self._promotion_latency_ticks.clear()
            self._rolling_ttft.clear()
            self._rolling_ttft_e2e_ms.clear()
            self._cross_gpu_migrations = 0
            self._recomputations = 0
            self._cache_hits = 0
            self._cache_misses = 0
            self._tick_events.clear()
            self._all_events.clear()
            self._backend_errors.clear()
            self._g4_restore_ms_samples.clear()
            self._event_history.clear()
            self._prev_s3_ops = 0
            for t in self.gpu_trackers.values():
                t.reset()

            # Restore workload + scenario defaults (matches cold start / env defaults)
            sc = settings.sim_default_scenario
            self.config = SimConfig(
                users=settings.sim_default_users,
                context_tokens=settings.sim_default_context,
                speed=1.0,
                scenario=sc,
                g35_mode=_SCENARIO_TO_G35.get(sc, "disabled"),
                cmx_enabled=SCENARIO_PARAMS[sc]["g35_enabled"],
            )
            self._apply_scenario()

    async def get_state(self) -> SimStatus:
        async with self._lock:
            return self._build_status()

    def _build_memory_budget(self) -> dict:
        """Structured KV / tier snapshot for Memory Budget UI."""
        ctx = self.config.context_tokens
        kv_ps = kv_per_session_gb(ctx)
        kv_bpt = kv_bytes_per_token_per_gpu_tp2()
        bm = self.block_manager
        params = self._get_params()
        scenario = self.config.scenario

        gpu_payload: dict[str, dict] = {}
        for gid in GPU_IDS:
            g1 = bm.gpu_tiers[gid]["G1"]
            used = float(g1.used_gb)
            cap = float(g1.capacity_gb)
            if cap > 0:
                used = min(used, cap)
            gpu_payload[gid] = {
                "g1_total_gb": bm.g1_hbm_total_gb,
                "weights_gb": bm.g1_weights_gb,
                "overhead_gb": bm.g1_overhead_gb,
                "kv_capacity_gb": cap,
                "sessions_capacity": sessions_fit_in_kv_cap(cap, ctx),
                "sessions_active": g1.block_count,
                "used_gb": round(used, 4),
            }

        g2_agg = bm.aggregate_gpu_tier_across_gpus("G2")
        g3_agg = bm.aggregate_gpu_tier_across_gpus("G3")
        g2_cap = float(g2_agg["capacity_gb"])
        g3_cap = float(g3_agg["capacity_gb"])
        g2_agg = {
            **dict(g2_agg),
            "sessions_capacity": sessions_fit_in_kv_cap(g2_cap, ctx),
        }
        g3_agg = {
            **dict(g3_agg),
            "sessions_capacity": sessions_fit_in_kv_cap(g3_cap, ctx),
        }
        shared_list = bm.get_shared_tier_state()
        shared_map = {t["name"]: t for t in shared_list}
        g35_d = shared_map["G3.5"]
        g4_d = shared_map["G4"]

        sess_list = self.session_manager.get_all()
        active_only = [s for s in sess_list if s.status == "active"]
        n_active = len(active_only)
        if n_active:
            in_g1 = sum(
                1
                for s in active_only
                if (bm.get_block_tier(s.id) or "") == "G1"
            )
            g4_hit = sum(
                1
                for s in active_only
                if (bm.get_block_tier(s.id) or "") == "G4"
            )
            sessions_in_hbm_pct = round(100.0 * in_g1 / float(n_active), 2)
            sessions_hitting_g4_pct = round(100.0 * g4_hit / float(n_active), 2)
        else:
            sessions_in_hbm_pct = 0.0
            sessions_hitting_g4_pct = 0.0

        return {
            "model": MODEL_NAME,
            "gpu_type": GPU_TYPE_LABEL,
            "gpu_count": 2,
            "tensor_parallel": 2,
            "kv_precision_note": KV_PRECISION_NOTE,
            "kv_bytes_per_token": kv_bpt,
            "context_tokens": ctx,
            "kv_per_session_gb": round(kv_ps, 6),
            "total_kv_demand_gb": round(float(self.config.users) * kv_ps, 4),
            "total_active_sessions": n_active,
            "scenario": scenario,
            "gpu-a": gpu_payload["gpu-a"],
            "gpu-b": gpu_payload["gpu-b"],
            "G2": dict(g2_agg),
            "G3": dict(g3_agg),
            "G3.5": {
                "sessions_active": int(g35_d["block_count"]),
                "used_gb": float(g35_d["used_gb"]),
                "capacity_gb": float(g35_d["capacity_gb"]),
                "visible": bool(params["g35_enabled"]),
            },
            "G4": {
                "label": str(params.get("g4_label") or "G4"),
                "sessions_active": int(g4_d["block_count"]),
                "used_gb": float(g4_d["used_gb"]),
                "capacity_gb": float(g4_d["capacity_gb"]),
            },
            "sessions_in_hbm_pct": sessions_in_hbm_pct,
            "sessions_hitting_g4_pct": sessions_hitting_g4_pct,
            "g35_enabled": bool(params["g35_enabled"]),
        }

    def _build_status(self) -> SimStatus:
        scenario = self.config.scenario

        # Per-GPU stacked utilization: blend live tracker with scenario narrative bands
        gpu_util_breakdowns: dict[str, dict[str, int]] = {}
        for gpu_id in GPU_IDS:
            raw_u = self.gpu_trackers[gpu_id].utilization()
            gpu_util_breakdowns[gpu_id] = _blend_scenario_utilization(raw_u, scenario)

        gpu_states = []
        for gpu_id in GPU_IDS:
            gpu_tiers = self.block_manager.get_gpu_tier_state(gpu_id)
            tier_map = {t["name"]: t for t in gpu_tiers}
            gpu_states.append(GPUTierState(
                gpu_id=gpu_id,
                g1=TierState(
                    name="G1",
                    capacity_gb=tier_map["G1"]["capacity_gb"],
                    used_gb=tier_map["G1"]["used_gb"],
                    block_count=tier_map["G1"]["block_count"],
                    latency_ms=tier_map["G1"]["latency_ms"],
                ),
                g2=TierState(
                    name="G2",
                    capacity_gb=tier_map["G2"]["capacity_gb"],
                    used_gb=tier_map["G2"]["used_gb"],
                    block_count=tier_map["G2"]["block_count"],
                    latency_ms=tier_map["G2"]["latency_ms"],
                ),
                g3=TierState(
                    name="G3",
                    capacity_gb=tier_map["G3"]["capacity_gb"],
                    used_gb=tier_map["G3"]["used_gb"],
                    block_count=tier_map["G3"]["block_count"],
                    latency_ms=tier_map["G3"]["latency_ms"],
                ),
                utilization=gpu_util_breakdowns[gpu_id],
            ))

        # Shared tiers — nudge G4 displayed fill for MinIO G4 scenario (healthy object-tier utilization)
        shared_tiers = self.block_manager.get_shared_tier_state()
        shared_map = {t["name"]: t for t in shared_tiers}
        g4_used = float(shared_map["G4"]["used_gb"])
        g4_cap = float(shared_map["G4"]["capacity_gb"])
        if scenario == "minio-g4" and g4_cap > 0:
            g4_used = min(g4_cap * 0.94, g4_used * 1.16 + g4_cap * 0.045)
        g4_used = min(g4_cap, max(0.0, g4_used)) if g4_cap > 0 else 0.0

        shared = SharedTierState(
            g35=TierState(
                name="G3.5",
                capacity_gb=shared_map["G3.5"]["capacity_gb"],
                used_gb=shared_map["G3.5"]["used_gb"],
                block_count=shared_map["G3.5"]["block_count"],
                latency_ms=shared_map["G3.5"]["latency_ms"],
            ),
            g4=TierState(
                name="G4",
                capacity_gb=shared_map["G4"]["capacity_gb"],
                used_gb=g4_used,
                block_count=shared_map["G4"]["block_count"],
                latency_ms=shared_map["G4"]["latency_ms"],
            ),
        )

        # Build session states
        session_states = []
        for s in self.session_manager.get_all():
            tier = self.block_manager.get_block_tier(s.id) or "unknown"
            session_states.append(
                SessionState(
                    session_id=s.id,
                    tier=tier,
                    status=s.status,
                    kv_size_gb=s.kv_size_gb,
                    idle_ticks=s.idle_ticks,
                    gpu_id=s.gpu_id,
                )
            )

        # Compute metrics with clamping
        def clamp(val: float) -> float:
            return min(100.0, max(0.0, val))

        # Effective utilization = active inference only (already scenario-blended above)
        gpu_utils = {}
        for gpu_id in GPU_IDS:
            gpu_utils[gpu_id] = float(gpu_util_breakdowns[gpu_id]["active"])

        # Cache hit rate: blend raw hit/(hit+miss) with scenario anchor so POSIX isn't ~90% while ~30%+ time is recompute
        total_lookups = self._cache_hits + self._cache_misses
        raw_hit_pct = (
            (self._cache_hits / total_lookups * 100.0) if total_lookups > 0 else 72.0
        )
        anchor = _SCENARIO_CACHE_HIT_ANCHOR.get(scenario, 70.0)
        beta = _SCENARIO_CACHE_HIT_BLEND
        hit_rate = clamp((1.0 - beta) * raw_hit_pct + beta * anchor)

        # TTFT: rolling mean of true send→first-token (queue + prefill in ticks × _TICK_MS).
        # Fallback before enough samples: base LLM + scaled promotion I/O (restore-only proxy).
        if self._rolling_ttft_e2e_ms:
            ttft = sum(self._rolling_ttft_e2e_ms) / len(self._rolling_ttft_e2e_ms)
        else:
            avg_promo = (
                sum(self._rolling_ttft) / len(self._rolling_ttft)
                if self._rolling_ttft
                else _SCENARIO_DEFAULT_PROMO_TICKS.get(scenario, 2.0)
            )
            io_scale = _SCENARIO_TTFT_IO_SCALE.get(scenario, 0.5)
            io_latency_ms = avg_promo * _TICK_MS * io_scale
            base_llm_ms = 30.0  # prefill + first token decode
            ttft = base_llm_ms + io_latency_ms
        if scenario == "file-g4":
            ttft = min(3200.0, max(1100.0, ttft))
        elif scenario == "minio-g4":
            ttft = min(330.0, max(68.0, ttft))
        else:
            ttft = min(88.0, max(31.0, ttft))

        now = time.monotonic()
        elapsed = now - self._last_rate_ts
        ops_rate = (
            (self._s3_ops_count - self._last_s3_ops_count) / elapsed
            if elapsed > 0
            else 0.0
        )

        combined_effective = round(
            (gpu_utils.get("gpu-a", 0.0) + gpu_utils.get("gpu-b", 0.0)) / 2
        )
        def _busy_pct(u: dict[str, int]) -> float:
            idle = float(u.get("idle", 0))
            return max(0.0, min(100.0, 100.0 - idle))

        combined_busy = round(
            (_busy_pct(gpu_util_breakdowns["gpu-a"]) + _busy_pct(gpu_util_breakdowns["gpu-b"]))
            / 2.0
        )

        g4_avg_ms, g4_restore_n = self._g4_avg_restore_ms_for_metrics(scenario)

        metrics_dict = {
            "gpu_a_utilization": gpu_util_breakdowns["gpu-a"],
            "gpu_b_utilization": gpu_util_breakdowns["gpu-b"],
            "combined_effective_util": combined_effective,
            "combined_gpu_busy_util": combined_busy,
            "avg_ttft_ms": round(ttft, 1),
            "cache_hit_rate": round(hit_rate, 4),
            "s3_ops_per_sec": round(ops_rate, 2),
            "total_sessions": len(session_states),
            "active_sessions": sum(1 for s in session_states if s.status == "active"),
            "idle_sessions": sum(1 for s in session_states if s.status == "idle"),
            "returning_sessions": sum(1 for s in session_states if s.status == "returning"),
            "cross_gpu_migrations": self._cross_gpu_migrations,
            "recomputations": self._recomputations,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "g4_avg_restore_ms": g4_avg_ms,
            "g4_restore_sample_n": g4_restore_n,
        }

        params = self._get_params()
        g35_mode = _SCENARIO_TO_G35.get(scenario, "disabled")

        return SimStatus(
            running=self._running,
            tick=self._tick,
            gpus=gpu_states,
            shared=shared,
            sessions=session_states,
            metrics=metrics_dict,
            events=(self._all_events + self._tick_events)[-15:],
            backend_errors=list(self._backend_errors),
            eviction_policy=self.block_manager.get_eviction_policy(scenario),
            memory_budget=self._build_memory_budget(),
            config={
                "users": self.config.users,
                "context_tokens": self.config.context_tokens,
                "speed": self.config.speed,
                "scenario": scenario,
                "scenario_label": _SCENARIO_LABELS.get(scenario, scenario),
                "g4_type": "file-posix" if scenario == "file-g4" else "minio-s3",
                "g35_enabled": params["g35_enabled"],
                "g35_label": params.get("g35_label"),
                # Backward compat
                "g35_mode": g35_mode,
                "cmx_enabled": params["g35_enabled"],
            },
        )

    async def _loop(self) -> None:
        import traceback

        loop = asyncio.get_event_loop()
        while self._running:
            interval = 0.2 / max(self.config.speed, 0.1)
            await asyncio.sleep(interval)

            if not self._running:
                break

            try:
                async with self._lock:
                    if not self._running:
                        break
                    await self._tick_once(loop)
                    state = self._build_status()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                tb = traceback.format_exc()
                msg = f"[tick {self._tick}] {type(e).__name__}: {e}"
                tail = tb[-1200:] if len(tb) > 1200 else tb
                async with self._lock:
                    self._backend_errors.append(msg[:400])
                    self._backend_errors.append(tail)
                continue

            # Broadcast to WebSocket clients (outside lock — state is immutable)
            try:
                sim_metrics.update_metrics(state.model_dump())
                await self._broadcast(state)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                async with self._lock:
                    self._backend_errors.append(f"[broadcast] {type(e).__name__}: {str(e)[:300]}")

    async def _tick_once(self, loop: asyncio.AbstractEventLoop) -> None:
        self._tick += 1
        self._promotion_latency_ticks.clear()
        # Save previous tick events to persistent buffer before clearing
        if self._tick_events:
            self._all_events.extend(self._tick_events)
            if len(self._all_events) > 50:
                self._all_events = self._all_events[-50:]
        self._tick_events.clear()

        # 1. New sessions — RequestGenerator.pick_gpu() uses G1 free headroom (tie → round-robin)
        active = self.session_manager.get_active_sessions()
        idle = self.session_manager.get_idle_sessions()
        returning = self.session_manager.get_returning_sessions()
        new_count = self.request_gen.generate(
            tick=self._tick,
            num_users=self.config.users,
            context_tokens=self.config.context_tokens,
            current_active=len(active),
            current_idle=len(idle),
            current_returning=len(returning),
        )
        for _ in range(new_count):
            gpu_g1_free = {
                gpu_id: self.block_manager.get_gpu_g1_free(gpu_id)
                for gpu_id in GPU_IDS
            }
            gpu_id = self.request_gen.pick_gpu(gpu_g1_free)
            session = self.session_manager.create_session(
                self.config.context_tokens, gpu_id
            )
            self.block_manager.allocate(session.id, session.kv_size_gb, gpu_id)
            self._assign_initial_ttft_schedule(session, gpu_id)

        # 2. Tick sessions
        terminated_ids = self.session_manager.tick_sessions()

        # 3. Increment idle_ticks on blocks of idle sessions
        for s in self.session_manager.get_idle_sessions():
            self.block_manager.increment_idle_ticks(s.id)

        # 3.5. Proactive idle eviction (G1→G2 after idle timeout)
        idle_evicts = self.block_manager.idle_eviction()
        for session_id, from_tier, to_tier, gpu_id, idle_ticks in idle_evicts:
            self._tick_events.append({
                "type": "EVICT_IDLE",
                "session": session_id,
                "gpu": gpu_id,
                "from_tier": from_tier,
                "to_tier": to_tier,
                "reason": f"Idle for {idle_ticks} ticks (timeout: 20)",
                "policy": "Proactive idle eviction",
            })

        # 4. Enforce capacity (cascade evictions across both GPUs)
        evictions = self.block_manager.enforce_capacity()

        # 5. Handle evictions to G3.5/G4 via MinIO
        for session_id, from_tier, to_tier, gpu_id in evictions:
            self._tick_events.append({
                "type": f"EVICT_TO_{to_tier.replace('.', '')}",
                "session": session_id,
                "gpu": gpu_id,
                "from_tier": from_tier,
                "to_tier": to_tier,
            })
            if to_tier in ("G3.5", "G4"):
                backend = self.minio_g35 if to_tier == "G3.5" else self.minio_g4
                block_tier = self.block_manager.shared_tiers[to_tier]
                block = block_tier.blocks.get(session_id)
                if block:
                    await self._safe_exec(
                        loop,
                        backend.put_kv_block,
                        session_id,
                        self._tick,
                        KV_BLOCK_SIZE_BYTES,
                        {
                            "tier": to_tier,
                            "session": session_id,
                            "gpu": gpu_id,
                            "tokens": str(self.config.context_tokens),
                            "created": str(self._tick),
                        },
                    )
                    self._s3_ops_count += 1

        # 6. Handle returning sessions: promote blocks back to G1
        _returning = self.session_manager.get_returning_sessions()
        # Pre-count concurrent G4 reads for concurrency collapse model
        _n_concurrent_g4_reads = sum(
            1 for s in _returning
            if self.block_manager.get_block_tier(s.id) == "G4"
        )

        for s in _returning:
            current_tier = self.block_manager.get_block_tier(s.id)
            current_gpu = self.block_manager.get_block_gpu(s.id)

            if current_tier is None:
                # Block not found — recompute
                self._recomputations += 1
                self._cache_misses += 1
                self._promotion_latency_ticks.append(50)
                self.gpu_trackers[s.gpu_id].register_recompute(50)
                sim_metrics.recomputations_total.inc()
                continue

            # Decide target GPU: higher cross-GPU churn on POSIX (more painful restores)
            target_gpu = s.gpu_id
            cross_p = 0.34 if self.config.scenario == "file-g4" else 0.25
            if random.random() < cross_p:
                other_gpu = [g for g in GPU_IDS if g != s.gpu_id]
                if other_gpu:
                    target_gpu = other_gpu[0]

            is_cross_gpu = target_gpu != (current_gpu or s.gpu_id)

            # S3 read for shared tiers
            if current_tier in ("G3.5", "G4"):
                backend = self.minio_g35 if current_tier == "G3.5" else self.minio_g4
                await self._safe_exec(
                    loop,
                    backend.get_kv_block,
                    s.id,
                    self._tick,
                )
                self._s3_ops_count += 1

            params = self._get_params()

            if is_cross_gpu:
                self._cross_gpu_migrations += 1

                if random.random() < params["cross_gpu_recompute_chance"]:
                    # Engine gives up on restore — recomputes from scratch
                    # file-g4: 35% (file read too slow), minio-g4: 5%, minio-full: <1%
                    self.block_manager.promote(s.id, target_gpu, "G1")
                    ticks = 50
                    self._promotion_latency_ticks.append(ticks)
                    self._recomputations += 1
                    self._cache_misses += 1
                    self.gpu_trackers[target_gpu].register_recompute(ticks)
                    sim_metrics.recomputations_total.inc()
                    reason = _scenario_recompute_reason(self.config.scenario)
                    self._tick_events.append({
                        "type": "RECOMPUTE_CROSS_GPU",
                        "session": s.id,
                        "from_gpu": current_gpu or s.gpu_id,
                        "to_gpu": target_gpu,
                        "reason": reason,
                        "policy": "Full KV cache recomputation required",
                    })
                else:
                    # Restore path — latency depends on scenario
                    base_restore = params["cross_gpu_restore_ticks"]
                    jitter_range = int(base_restore * params["cross_gpu_restore_jitter_pct"])
                    jitter = random.randint(-jitter_range, jitter_range) if jitter_range > 0 else 0
                    ticks = self.block_manager.promote(s.id, target_gpu, "G1")
                    ticks = max(ticks, base_restore + jitter)
                    via, reason, policy = _scenario_cross_gpu_labels(self.config.scenario, ticks)
                    self._promotion_latency_ticks.append(ticks)
                    self.gpu_trackers[target_gpu].register_io_stall(ticks)
                    self._cache_hits += 1
                    if current_tier == "G4":
                        self._record_g4_restore_ms(ticks)
                    self._tick_events.append({
                        "type": "PROMOTE_CROSS_GPU",
                        "session": s.id,
                        "from_gpu": current_gpu or s.gpu_id,
                        "to_gpu": target_gpu,
                        "via": via,
                        "reason": reason,
                        "policy": policy,
                    })
            else:
                # Same-GPU promotion
                ticks = self.block_manager.promote(s.id, target_gpu, "G1")
                # Override G4 ticks with scenario-aware jitter + concurrency collapse
                if current_tier == "G4":
                    ticks = max(ticks, self.jittered_g4_ticks(_n_concurrent_g4_reads))
                    self._record_g4_restore_ms(ticks)
                self._promotion_latency_ticks.append(ticks)
                if ticks == 50:
                    self._recomputations += 1
                    self._cache_misses += 1
                    self.gpu_trackers[target_gpu].register_recompute(ticks)
                    sim_metrics.recomputations_total.inc()
                elif ticks > 0:
                    self.gpu_trackers[target_gpu].register_io_stall(ticks)
                    self._cache_hits += 1
                else:
                    self._cache_hits += 1

            # Update session gpu_id if migrated
            s.gpu_id = target_gpu

        # 6.5. Accumulate promotion latencies into rolling TTFT window
        for lat in self._promotion_latency_ticks:
            self._rolling_ttft.append(lat)

        # 7. Free blocks for terminated sessions
        for sid in terminated_ids:
            current_tier = self.block_manager.get_block_tier(sid)
            if current_tier in ("G3.5", "G4"):
                backend = self.minio_g35 if current_tier == "G3.5" else self.minio_g4
                await self._safe_exec(loop, backend.delete_session, sid)
                self._s3_ops_count += 1
            self.block_manager.free(sid)

        # 7.5 End-to-end TTFT samples (request accepted → first token, includes queue wait)
        for s in self.session_manager.get_all():
            if s.initial_ttft_recorded or s.first_token_scheduled_tick is None:
                continue
            if self._tick >= s.first_token_scheduled_tick:
                dt = s.first_token_scheduled_tick - s.request_sent_tick
                if dt >= 0:
                    self._rolling_ttft_e2e_ms.append(float(dt) * _TICK_MS)
                s.initial_ttft_recorded = True

        # 8. Record GPU time budgets for this tick
        for gpu_id in GPU_IDS:
            tracker = self.gpu_trackers[gpu_id]
            # Count active sessions on this GPU's G1 (doing inference)
            g1 = self.block_manager.gpu_tiers[gpu_id]["G1"]
            active_on_gpu = g1.block_count
            # Max sessions = G1 KV capacity / per-session KV
            avg_kv = kv_per_session_gb(self.config.context_tokens)
            max_sessions = max(1, int(g1.capacity_gb / avg_kv)) if avg_kv > 0 else 10
            tracker.record_tick(active_on_gpu, max_sessions)

        # 9. Update S3 ops rate snapshot
        now = time.monotonic()
        if now - self._last_rate_ts >= 1.0:
            self._last_s3_ops_count = self._s3_ops_count
            self._last_rate_ts = now

        # Increment total S3 ops counter
        new_ops = self._s3_ops_count - getattr(self, "_prev_s3_ops", 0)
        if new_ops > 0:
            sim_metrics.s3_operations_total.inc(new_ops)
        self._prev_s3_ops = self._s3_ops_count

    def register_ws(self, websocket) -> None:
        self._ws_clients.add(websocket)

    def unregister_ws(self, websocket) -> None:
        self._ws_clients.discard(websocket)

    async def _broadcast(self, state: SimStatus) -> None:
        if not self._ws_clients:
            return
        import json
        payload = json.dumps(state.model_dump())
        dead: set = set()
        for ws in self._ws_clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead


# Module-level singleton
engine = SimulationEngine()
