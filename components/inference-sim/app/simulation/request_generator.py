import random

from app.simulation.kv_block_manager import GPU_IDS


class RequestGenerator:
    """Simulated inference request arrival using Poisson-like arrival model."""

    def __init__(self) -> None:
        self._rr_index = 0

    def generate(
        self,
        tick: int,
        num_users: int,
        context_tokens: int,
        current_active: int,
        current_idle: int,
        current_returning: int,
    ) -> int:
        """Return the number of new sessions to create this tick.

        Uses a Poisson-like arrival: spawn sessions proportional to deficit
        relative to target num_users.
        """
        total_live = current_active + current_idle + current_returning
        deficit = num_users - total_live
        if deficit <= 0:
            return 0

        # Probability of spawning a new session this tick, proportional to deficit
        spawn_prob = min(1.0, deficit / max(num_users, 1) * 2.0)
        count = 0
        # Allow spawning up to min(deficit, 5) sessions per tick
        for _ in range(min(deficit, 5)):
            if random.random() < spawn_prob:
                count += 1
        return count

    def pick_gpu(self, gpu_g1_free: dict[str, float]) -> str:
        """Place new work on the GPU with the most G1 headroom; tie-break with round-robin.

        Pure round-robin (old behavior) ignored `gpu_g1_free` and could skew load when:
        - one GPU had more evictions / fuller G1 from random session lifecycles;
        - cross-GPU returns (25% in engine) moved sessions to the *other* GPU;
        - random idle/return/terminate left unequal active counts.

        Scenario selection still applies the same `SCENARIO_PARAMS` to both GPUs; imbalance
        was from scheduling, not from config failing to cascade.
        """
        ids = list(GPU_IDS)
        if not gpu_g1_free:
            g = ids[self._rr_index % len(ids)]
            self._rr_index += 1
            return g
        max_free = max(gpu_g1_free.get(g, 0.0) for g in ids)
        # All tied at ~0 or equal headroom → fall back to round-robin
        tied = [g for g in ids if gpu_g1_free.get(g, 0.0) >= max_free - 1e-6]
        if not tied:
            g = ids[self._rr_index % len(ids)]
            self._rr_index += 1
            return g
        if len(tied) == 1:
            return tied[0]
        pick = tied[self._rr_index % len(tied)]
        self._rr_index += 1
        return pick
