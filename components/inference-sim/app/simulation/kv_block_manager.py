from __future__ import annotations

import time
from dataclasses import dataclass, field


def effective_g4_ticks(base_ticks: int, n_concurrent_reads: int, scenario_params: dict) -> int:
    """Calculate effective G4 latency ticks accounting for concurrency.

    For File/POSIX: non-linear degradation due to metadata lock contention.
    For MinIO S3: graceful scaling up to parallel_factor, gentle degradation after.
    """
    parallel_factor = scenario_params["g4_parallel_factor"]

    if scenario_params.get("concurrency_collapse_enabled", False):
        # POSIX concurrency collapse model
        if n_concurrent_reads <= 2:
            multiplier = 1.0
        elif n_concurrent_reads <= 5:
            multiplier = 1.0 + 0.4 * (n_concurrent_reads - 2)
        else:
            multiplier = 1.0 + 0.4 * 3 + 0.8 * (n_concurrent_reads - 5)
        return int(base_ticks * multiplier)
    else:
        # S3 parallel model: graceful up to parallel_factor
        excess = max(0, n_concurrent_reads - parallel_factor)
        multiplier = 1.0 + 0.1 * excess
        return int(base_ticks * multiplier)


def get_tier_ticks(tier: str, scenario_params: dict) -> int | None:
    """Get latency ticks for a tier based on active scenario."""
    STATIC_TICKS = {"G1": 0, "G2": 0, "G3": 1}
    if tier in STATIC_TICKS:
        return STATIC_TICKS[tier]
    elif tier == "G3.5":
        if not scenario_params["g35_enabled"]:
            return None  # Tier doesn't exist in this scenario
        return scenario_params["g35_ticks"]
    elif tier == "G4":
        return scenario_params["g4_base_ticks"]
    return 0


@dataclass
class KVBlock:
    session_id: str
    size_gb: float
    tier: str
    gpu_id: str
    last_access: float = field(default_factory=time.time)
    idle_ticks: int = 0


@dataclass
class Tier:
    name: str
    capacity_gb: float
    latency_ms: float
    used_gb: float = 0.0
    blocks: dict = field(default_factory=dict)

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def free_gb(self) -> float:
        return self.capacity_gb - self.used_gb

    def has_capacity(self, size_gb: float) -> bool:
        return self.free_gb >= size_gb


GPU_IDS = ["gpu-a", "gpu-b"]


class KVBlockManager:
    """Dual-GPU KV block manager.

    Each GPU has private G1/G2/G3 tiers.
    G3.5 and G4 are shared across both GPUs.
    Eviction cascade: GPU's G1 -> G2 -> G3 -> shared G3.5 -> shared G4.
    When CMX disabled, skip G3.5 (G3 -> G4 directly).
    """

    # Per-GPU tier names in eviction order
    GPU_TIER_ORDER = ["G1", "G2", "G3"]
    # Shared tier names in eviction order
    SHARED_TIER_ORDER = ["G3.5", "G4"]
    # Full eviction order
    TIER_ORDER = ["G1", "G2", "G3", "G3.5", "G4"]

    # Eviction triggers at these utilisation fractions per tier
    EVICTION_THRESHOLDS: dict[str, float] = {
        "G1": 0.90,
        "G2": 0.85,
        "G3": 0.80,
        "G3.5": 0.95,
        "G4": 1.0,
    }

    def __init__(
        self,
        g1_cap: float = 10.0,
        g2_cap: float = 15.0,
        g3_cap: float = 20.0,
        g35_cap: float = 40.0,
        g4_cap: float = 100.0,
        cmx_enabled: bool = True,
        g1_hbm_total_gb: float = 80.0,
        g1_weights_gb: float = 35.0,
        g1_overhead_gb: float = 4.0,
    ) -> None:
        self.cmx_enabled = cmx_enabled
        self.g1_hbm_total_gb = float(g1_hbm_total_gb)
        self.g1_weights_gb = float(g1_weights_gb)
        self.g1_overhead_gb = float(g1_overhead_gb)

        # Per-GPU tiers: gpu_tiers[gpu_id][tier_name] = Tier
        self.gpu_tiers: dict[str, dict[str, Tier]] = {}
        for gpu_id in GPU_IDS:
            self.gpu_tiers[gpu_id] = {
                "G1": Tier("G1", g1_cap, latency_ms=0.1),
                "G2": Tier("G2", g2_cap, latency_ms=1.0),
                "G3": Tier("G3", g3_cap, latency_ms=5.0),
            }

        # Shared tiers
        self.shared_tiers: dict[str, Tier] = {
            "G3.5": Tier("G3.5", g35_cap, latency_ms=20.0),
            "G4": Tier("G4", g4_cap, latency_ms=200.0),
        }

        # session_id -> (gpu_id, tier_name)
        self._location: dict[str, tuple[str, str]] = {}

    def _is_shared_tier(self, tier_name: str) -> bool:
        return tier_name in ("G3.5", "G4")

    def _get_tier(self, gpu_id: str, tier_name: str) -> Tier:
        if self._is_shared_tier(tier_name):
            return self.shared_tiers[tier_name]
        return self.gpu_tiers[gpu_id][tier_name]

    def _next_tier(self, from_tier: str) -> str | None:
        """Return the next colder tier after from_tier, respecting cmx_enabled."""
        idx = self.TIER_ORDER.index(from_tier)
        for candidate in self.TIER_ORDER[idx + 1:]:
            if candidate == "G3.5" and not self.cmx_enabled:
                continue
            return candidate
        return None

    def evict(self, gpu_id: str, from_tier: str) -> tuple[str, str, str] | None:
        """LRU-evict coldest idle block from a specific GPU's tier to next tier.

        Returns (session_id, from_tier, to_tier) or None.
        """
        tier = self._get_tier(gpu_id, from_tier)
        if not tier.blocks:
            return None

        # Find coldest block (highest idle_ticks, then oldest last_access)
        # For shared tiers, only evict blocks that belong to this GPU (or any if gpu doesn't matter)
        candidates = list(tier.blocks.keys())
        if self._is_shared_tier(from_tier):
            # In shared tiers, evict any block (not GPU-specific)
            pass

        if not candidates:
            return None

        coldest_id = max(
            candidates,
            key=lambda sid: (tier.blocks[sid].idle_ticks, -tier.blocks[sid].last_access),
        )
        to_tier_name = self._next_tier(from_tier)
        if to_tier_name is None:
            return None

        block = tier.blocks.pop(coldest_id)

        to_tier = self._get_tier(gpu_id, to_tier_name)
        block.tier = to_tier_name
        to_tier.blocks[coldest_id] = block
        self._location[coldest_id] = (block.gpu_id, to_tier_name)
        self._reconcile_tier_used(tier)
        self._reconcile_tier_used(to_tier)

        return (coldest_id, from_tier, to_tier_name)

    def promote(self, session_id: str, to_gpu: str, to_tier: str = "G1") -> int:
        """Move block back to to_tier on to_gpu. Returns simulated latency in ticks."""
        loc = self._location.get(session_id)
        if loc is None:
            return 50  # not found -> recompute

        current_gpu, current_tier = loc

        latency_map = {
            "G1": 0,
            "G2": 0,
            "G3": 1,
            "G3.5": 2,
            "G4": 10,
        }
        ticks = latency_map.get(current_tier, 50)

        if current_tier == to_tier and current_gpu == to_gpu:
            return 0

        # Remove from source tier
        src = self._get_tier(current_gpu, current_tier)
        block = src.blocks.pop(session_id, None)
        if block is None:
            return 50

        # Place in destination tier
        dst = self._get_tier(to_gpu, to_tier)
        block.tier = to_tier
        block.gpu_id = to_gpu
        block.idle_ticks = 0
        block.last_access = time.time()
        dst.blocks[session_id] = block
        self._location[session_id] = (to_gpu, to_tier)
        self._reconcile_tier_used(src)
        self._reconcile_tier_used(dst)

        return ticks

    def enforce_capacity(self) -> list[tuple[str, str, str, str]]:
        """Cascade evictions through all tiers until each is within capacity.

        Returns list of (session_id, from_tier, to_tier, gpu_id) eviction events.
        """
        events: list[tuple[str, str, str, str]] = []

        # Per-GPU tiers first
        for gpu_id in GPU_IDS:
            for tier_name in self.GPU_TIER_ORDER:
                tier = self.gpu_tiers[gpu_id][tier_name]
                threshold = tier.capacity_gb * self.EVICTION_THRESHOLDS[tier_name]
                while tier.used_gb > threshold:
                    result = self.evict(gpu_id, tier_name)
                    if result is None:
                        break
                    sid, ft, tt = result
                    events.append((sid, ft, tt, gpu_id))

        # Shared tiers
        for tier_name in self.SHARED_TIER_ORDER[:-1]:  # G4 is effectively unlimited
            tier = self.shared_tiers[tier_name]
            threshold = tier.capacity_gb * self.EVICTION_THRESHOLDS[tier_name]
            while tier.used_gb > threshold:
                # Pick any block to evict from shared tier
                if not tier.blocks:
                    break
                coldest_id = max(
                    tier.blocks,
                    key=lambda sid: (tier.blocks[sid].idle_ticks, -tier.blocks[sid].last_access),
                )
                block = tier.blocks[coldest_id]
                gpu_id = block.gpu_id
                to_tier_name = self._next_tier(tier_name)
                if to_tier_name is None:
                    break

                tier.blocks.pop(coldest_id)

                to_tier = self._get_tier(gpu_id, to_tier_name)
                block.tier = to_tier_name
                to_tier.blocks[coldest_id] = block
                self._location[coldest_id] = (gpu_id, to_tier_name)
                self._reconcile_tier_used(tier)
                self._reconcile_tier_used(to_tier)
                events.append((coldest_id, tier_name, to_tier_name, gpu_id))

        self._reconcile_all_tiers()
        return events

    def allocate(self, session_id: str, size_gb: float, gpu_id: str) -> None:
        """Place new KV block in the specified GPU's G1, cascade evictions if needed."""
        g1 = self.gpu_tiers[gpu_id]["G1"]
        block = KVBlock(session_id=session_id, size_gb=size_gb, tier="G1", gpu_id=gpu_id)
        g1.blocks[session_id] = block
        self._location[session_id] = (gpu_id, "G1")
        self._reconcile_tier_used(g1)
        self.enforce_capacity()

    def free(self, session_id: str) -> None:
        """Remove block from whatever tier it is in."""
        loc = self._location.pop(session_id, None)
        if loc is None:
            return
        gpu_id, tier_name = loc
        tier = self._get_tier(gpu_id, tier_name)
        tier.blocks.pop(session_id, None)
        self._reconcile_tier_used(tier)

    def _reconcile_tier_used(self, tier: Tier) -> None:
        """Keep used_gb aligned with block accounting (avoids float drift)."""
        tier.used_gb = sum(b.size_gb for b in tier.blocks.values())

    def _reconcile_all_tiers(self) -> None:
        for gid in GPU_IDS:
            for t in self.gpu_tiers[gid].values():
                self._reconcile_tier_used(t)
        for t in self.shared_tiers.values():
            self._reconcile_tier_used(t)

    def _tier_public_dict(self, t: Tier) -> dict:
        """Snapshot for API/UI: utilization never exceeds 100% of capacity."""
        actual = sum(b.size_gb for b in t.blocks.values())
        cap = float(t.capacity_gb)
        if cap <= 0:
            used_out = 0.0
            pct = 0.0
        else:
            used_out = min(actual, cap)
            pct = min(100.0, (actual / cap) * 100.0)
        return {
            "name": t.name,
            "capacity_gb": cap,
            "used_gb": used_out,
            "pct": round(pct, 2),
            "block_count": t.block_count,
            "latency_ms": t.latency_ms,
        }

    def get_gpu_tier_state(self, gpu_id: str) -> list[dict]:
        """Return per-GPU tier states as list of dicts."""
        return [self._tier_public_dict(self.gpu_tiers[gpu_id][tn]) for tn in self.GPU_TIER_ORDER]

    def get_shared_tier_state(self) -> list[dict]:
        """Return shared tier states as list of dicts."""
        return [self._tier_public_dict(t) for t in self.shared_tiers.values()]

    def get_gpu_g1_free(self, gpu_id: str) -> float:
        """Return free capacity in a GPU's G1 tier."""
        return self.gpu_tiers[gpu_id]["G1"].free_gb

    def aggregate_gpu_tier_across_gpus(self, tier_name: str) -> dict[str, float | int]:
        """Sum block counts and used_gb for a per-GPU tier across gpu-a and gpu-b."""
        total_blocks = 0
        total_used = 0.0
        total_cap = 0.0
        for gpu_id in GPU_IDS:
            t = self.gpu_tiers[gpu_id][tier_name]
            total_blocks += t.block_count
            total_used += t.used_gb
            total_cap += t.capacity_gb
        return {
            "sessions_active": total_blocks,
            "used_gb": round(total_used, 4),
            "capacity_gb": total_cap,
        }

    def increment_idle_ticks(self, session_id: str) -> None:
        loc = self._location.get(session_id)
        if loc:
            gpu_id, tier_name = loc
            tier = self._get_tier(gpu_id, tier_name)
            block = tier.blocks.get(session_id)
            if block:
                block.idle_ticks += 1

    def get_block_tier(self, session_id: str) -> str | None:
        loc = self._location.get(session_id)
        if loc:
            return loc[1]
        return None

    def get_block_gpu(self, session_id: str) -> str | None:
        loc = self._location.get(session_id)
        if loc:
            return loc[0]
        return None

    def idle_eviction(self, idle_timeout: int = 20) -> list[tuple[str, str, str, str, int]]:
        """Proactively evict idle G1 sessions to G2 when idle_ticks > idle_timeout.

        Returns list of (session_id, from_tier, to_tier, gpu_id, idle_ticks).
        """
        events: list[tuple[str, str, str, str, int]] = []
        for gpu_id in GPU_IDS:
            g1 = self.gpu_tiers[gpu_id]["G1"]
            # Collect candidates first to avoid mutating dict during iteration
            idle_candidates = [
                (sid, block.idle_ticks)
                for sid, block in g1.blocks.items()
                if block.idle_ticks > idle_timeout
            ]
            for sid, idle_ticks in idle_candidates:
                block = g1.blocks.pop(sid, None)
                if block is None:
                    continue
                g2 = self.gpu_tiers[gpu_id]["G2"]
                block.tier = "G2"
                g2.blocks[sid] = block
                self._location[sid] = (gpu_id, "G2")
                self._reconcile_tier_used(g1)
                self._reconcile_tier_used(g2)
                events.append((sid, "G1", "G2", gpu_id, idle_ticks))
        return events

    def get_eviction_policy(self, scenario: str = "file-g4") -> dict:
        """Return current eviction policy configuration."""
        _SCENARIO_TO_G35 = {"file-g4": "disabled", "minio-g4": "standard", "minio-full": "accelerated"}
        return {
            "g1_threshold": f"{int(self.EVICTION_THRESHOLDS['G1'] * 100)}%",
            "g2_threshold": f"{int(self.EVICTION_THRESHOLDS['G2'] * 100)}%",
            "g3_threshold": f"{int(self.EVICTION_THRESHOLDS['G3'] * 100)}%",
            "g35_threshold": f"{int(self.EVICTION_THRESHOLDS['G3.5'] * 100)}%",
            "idle_timeout_ticks": 20,
            "strategy": "LRU (coldest idle session evicted first)",
            "scenario": scenario,
            "g35_mode": _SCENARIO_TO_G35.get(scenario, "disabled"),
        }

    def clear(self) -> None:
        for gpu_id in GPU_IDS:
            for tier in self.gpu_tiers[gpu_id].values():
                tier.blocks.clear()
                tier.used_gb = 0.0
        for tier in self.shared_tiers.values():
            tier.blocks.clear()
            tier.used_gb = 0.0
        self._location.clear()
