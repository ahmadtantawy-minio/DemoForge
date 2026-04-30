import random

from app.config import settings


def arrival_target_users(requested_users: int, replica_count: int) -> int:
    """Cap concurrent-session target for Poisson arrivals (cluster replica story).

    The UI "Concurrent sessions" slider is *desired* load; the simulator only
    tries to sustain up to `replica_count` live sessions toward that target.
    """
    ru = max(0, int(requested_users))
    rc = max(1, int(replica_count))
    return min(ru, rc)


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

    def pick_node(self, node_g1_free: dict[str, float]) -> str:
        """Place new work on the node with the most aggregate G1 headroom; tie-break with round-robin."""
        ids = list(settings.node_ids)
        if not node_g1_free:
            g = ids[self._rr_index % len(ids)]
            self._rr_index += 1
            return g
        max_free = max(node_g1_free.get(g, 0.0) for g in ids)
        tied = [g for g in ids if node_g1_free.get(g, 0.0) >= max_free - 1e-6]
        if not tied:
            g = ids[self._rr_index % len(ids)]
            self._rr_index += 1
            return g
        if len(tied) == 1:
            return tied[0]
        pick = tied[self._rr_index % len(tied)]
        self._rr_index += 1
        return pick
