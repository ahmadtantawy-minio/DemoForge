from __future__ import annotations

import asyncio
import collections
import random
import time
from collections import deque

from app.config import settings
from app.models import (
    SimConfig, SimStatus, TierState, GPUTierState, SharedTierState, SessionState,
)
from app.simulation.kv_block_manager import KVBlockManager, GPU_IDS
from app.simulation.session_manager import SessionManager
from app.simulation.request_generator import RequestGenerator
from app.simulation.minio_backend import MinIOBackend
from app.simulation import metrics as sim_metrics

# 100 KB per KV block (laptop-friendly, not real 50 MB)
KV_BLOCK_SIZE_BYTES = 100 * 1024


class SimulationEngine:
    def __init__(self) -> None:
        self.config = SimConfig(
            users=settings.sim_default_users,
            context_tokens=settings.sim_default_context,
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

        # Promotion latency: rolling window for TTFT (last 100 promotions)
        self._promotion_latency_ticks: list[int] = []
        self._rolling_ttft: collections.deque = collections.deque(maxlen=100)

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

        self._init_components()

    def _effective_g35_mode(self) -> str:
        """Resolve g35_mode from config with backward compat for cmx_enabled."""
        mode = getattr(self.config, "g35_mode", None)
        if mode and mode != "accelerated":
            # Explicit g35_mode takes precedence
            return mode
        # Backward compat: cmx_enabled=false -> disabled
        if not self.config.cmx_enabled:
            return "disabled"
        return mode or "accelerated"

    def _apply_g35_mode(self) -> None:
        """Set block_manager.cmx_enabled based on effective g35_mode."""
        mode = self._effective_g35_mode()
        self.block_manager.cmx_enabled = mode != "disabled"

    def _init_components(self) -> None:
        self.block_manager = KVBlockManager(
            g1_cap=settings.g1_capacity_gb,
            g2_cap=settings.g2_capacity_gb,
            g3_cap=settings.g3_capacity_gb,
            g35_cap=settings.g35_capacity_gb,
            g4_cap=settings.g4_capacity_gb,
            cmx_enabled=self._effective_g35_mode() != "disabled",
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

    async def ensure_buckets(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.minio_g35.ensure_bucket)
        await loop.run_in_executor(None, self.minio_g4.ensure_bucket)

    async def start(self, config: SimConfig | None = None) -> None:
        async with self._lock:
            if self._running:
                return
            if config:
                self.config = config
            self._apply_g35_mode()
            self._running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        async with self._lock:
            if not self._running:
                return
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None

    async def update_config(self, config: SimConfig) -> None:
        async with self._lock:
            self.config = config
            self._apply_g35_mode()

    async def reset(self) -> None:
        await self.stop()
        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.minio_g35.delete_all)
            await loop.run_in_executor(None, self.minio_g4.delete_all)
            self.block_manager.clear()
            self.session_manager.clear()
            self._tick = 0
            self._s3_ops_count = 0
            self._last_s3_ops_count = 0
            self._promotion_latency_ticks.clear()
            self._rolling_ttft.clear()
            self._cross_gpu_migrations = 0
            self._recomputations = 0
            self._cache_hits = 0
            self._cache_misses = 0
            self._tick_events.clear()
            self._all_events.clear()

    async def get_state(self) -> SimStatus:
        async with self._lock:
            return self._build_status()

    def _build_status(self) -> SimStatus:
        # Build per-GPU tier states
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
            ))

        # Build shared tier state
        shared_tiers = self.block_manager.get_shared_tier_state()
        shared_map = {t["name"]: t for t in shared_tiers}
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
                used_gb=shared_map["G4"]["used_gb"],
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

        # Per-GPU utilization: G1.used / G1.capacity * 100
        gpu_utils = {}
        for gpu_id in GPU_IDS:
            g1 = self.block_manager.gpu_tiers[gpu_id]["G1"]
            util = (g1.used_gb / g1.capacity_gb * 100) if g1.capacity_gb > 0 else 0.0
            gpu_utils[gpu_id] = clamp(util)

        # Cache hit rate from counters
        total_lookups = self._cache_hits + self._cache_misses
        hit_rate = clamp(
            (self._cache_hits / total_lookups * 100) if total_lookups > 0 else 100.0
        )

        # Save current tick's promotions to rolling window
        for lat in self._promotion_latency_ticks:
            self._rolling_ttft.append(lat)

        avg_promo = (
            sum(self._rolling_ttft) / len(self._rolling_ttft)
            if self._rolling_ttft
            else 0.0
        )
        ttft = avg_promo * 200  # ticks x 200ms base

        now = time.monotonic()
        elapsed = now - self._last_rate_ts
        ops_rate = (
            (self._s3_ops_count - self._last_s3_ops_count) / elapsed
            if elapsed > 0
            else 0.0
        )

        metrics_dict = {
            "gpu_a_utilization": round(gpu_utils.get("gpu-a", 0.0), 4),
            "gpu_b_utilization": round(gpu_utils.get("gpu-b", 0.0), 4),
            "gpu_utilization": round(
                (gpu_utils.get("gpu-a", 0.0) + gpu_utils.get("gpu-b", 0.0)) / 2, 4
            ),
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
        }

        g35_mode = self._effective_g35_mode()

        return SimStatus(
            running=self._running,
            tick=self._tick,
            gpus=gpu_states,
            shared=shared,
            sessions=session_states,
            metrics=metrics_dict,
            events=(self._all_events + self._tick_events)[-15:],
            eviction_policy=self.block_manager.get_eviction_policy(g35_mode),
            config={
                "users": self.config.users,
                "context_tokens": self.config.context_tokens,
                "speed": self.config.speed,
                "g35_mode": g35_mode,
                "cmx_enabled": g35_mode != "disabled",
            },
        )

    async def _loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            interval = 0.2 / max(self.config.speed, 0.1)
            await asyncio.sleep(interval)

            async with self._lock:
                await self._tick_once(loop)

            # Broadcast to WebSocket clients
            state = self._build_status()
            sim_metrics.update_metrics(state.model_dump())
            await self._broadcast(state)

    async def _tick_once(self, loop: asyncio.AbstractEventLoop) -> None:
        self._tick += 1
        self._promotion_latency_ticks.clear()
        # Save previous tick events to persistent buffer before clearing
        if self._tick_events:
            self._all_events.extend(self._tick_events)
            if len(self._all_events) > 50:
                self._all_events = self._all_events[-50:]
        self._tick_events.clear()

        # 1. Generate new sessions — pick GPU with more G1 free space
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
                    await loop.run_in_executor(
                        None,
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
        for s in self.session_manager.get_returning_sessions():
            current_tier = self.block_manager.get_block_tier(s.id)
            current_gpu = self.block_manager.get_block_gpu(s.id)

            if current_tier is None:
                # Block not found — recompute
                self._recomputations += 1
                self._cache_misses += 1
                self._promotion_latency_ticks.append(50)
                sim_metrics.recomputations_total.inc()
                continue

            # Decide target GPU: ~20-30% chance of cross-GPU migration
            target_gpu = s.gpu_id
            if random.random() < 0.25:
                other_gpu = [g for g in GPU_IDS if g != s.gpu_id]
                if other_gpu:
                    target_gpu = other_gpu[0]

            is_cross_gpu = target_gpu != (current_gpu or s.gpu_id)

            # S3 read for shared tiers
            if current_tier in ("G3.5", "G4"):
                backend = self.minio_g35 if current_tier == "G3.5" else self.minio_g4
                await loop.run_in_executor(
                    None,
                    backend.get_kv_block,
                    s.id,
                    self._tick,
                )
                self._s3_ops_count += 1

            if is_cross_gpu:
                self._cross_gpu_migrations += 1
                g35_mode = self._effective_g35_mode()
                if g35_mode != "disabled":
                    # Cross-GPU promotion goes through G3.5
                    ticks = self.block_manager.promote(s.id, target_gpu, "G1")
                    # Differentiate Standard vs Accelerated latency
                    if g35_mode == "standard":
                        ticks = max(ticks, 15)  # S3/TCP: ~5-10ms simulated
                        reason = "Cross-GPU via G3.5 (S3/TCP, ~5-10ms)"
                        policy = "Dynamo router → S3 transfer from shared G3.5"
                    else:
                        ticks = max(ticks, 3)   # RDMA: ~500μs simulated
                        reason = "Cross-GPU via G3.5 (NVMe-oF/RDMA, ~500μs)"
                        policy = "Dynamo router → NIXL RDMA from shared G3.5"
                    self._promotion_latency_ticks.append(ticks)
                    self._tick_events.append({
                        "type": "PROMOTE_CROSS_GPU",
                        "session": s.id,
                        "from_gpu": current_gpu or s.gpu_id,
                        "to_gpu": target_gpu,
                        "via": "G3.5",
                        "reason": reason,
                        "policy": policy,
                    })
                    self._cache_hits += 1
                else:
                    # G3.5 disabled — cross-GPU returns trigger RECOMPUTE
                    self.block_manager.promote(s.id, target_gpu, "G1")
                    self._promotion_latency_ticks.append(50)
                    self._recomputations += 1
                    self._cache_misses += 1
                    sim_metrics.recomputations_total.inc()
                    self._tick_events.append({
                        "type": "RECOMPUTE_CROSS_GPU",
                        "session": s.id,
                        "from_gpu": current_gpu or s.gpu_id,
                        "to_gpu": target_gpu,
                        "reason": "G3.5 disabled — no shared tier for cross-GPU cache",
                        "policy": "Full KV cache recomputation required",
                    })
            else:
                # Same-GPU promotion
                ticks = self.block_manager.promote(s.id, target_gpu, "G1")
                self._promotion_latency_ticks.append(ticks)
                if ticks == 50:
                    self._recomputations += 1
                    self._cache_misses += 1
                    sim_metrics.recomputations_total.inc()
                elif current_tier == "G1":
                    self._cache_hits += 1
                else:
                    self._cache_hits += 1

            # Update session gpu_id if migrated
            s.gpu_id = target_gpu

        # 7. Free blocks for terminated sessions
        for sid in terminated_ids:
            current_tier = self.block_manager.get_block_tier(sid)
            if current_tier in ("G3.5", "G4"):
                backend = self.minio_g35 if current_tier == "G3.5" else self.minio_g4
                await loop.run_in_executor(None, backend.delete_session, sid)
                self._s3_ops_count += 1
            self.block_manager.free(sid)

        # 8. Update S3 ops rate snapshot
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
