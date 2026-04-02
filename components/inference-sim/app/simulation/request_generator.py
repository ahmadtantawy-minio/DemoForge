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
        """Pick GPU via round-robin for symmetric load across GPUs.

        Round-robin ensures both GPUs react simultaneously to scenario changes,
        producing clean side-by-side utilization for demo comparisons.
        """
        gpu = GPU_IDS[self._rr_index % len(GPU_IDS)]
        self._rr_index += 1
        return gpu
