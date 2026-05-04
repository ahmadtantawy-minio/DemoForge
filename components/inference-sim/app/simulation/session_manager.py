from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field

from app.simulation.kv_memory_model import kv_per_session_gb


@dataclass
class Session:
    id: str
    status: str  # queued | active | idle | returning | terminated
    kv_size_gb: float
    node_id: str
    active_ticks: int = 0
    idle_ticks: int = 0
    return_latency_remaining: int = 0
    # Initial user request: sim tick when accepted + when first token is modeled (queue + prefill).
    request_sent_tick: int = 0
    first_token_scheduled_tick: int | None = None
    initial_ttft_recorded: bool = False


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    def create_session(
        self, context_tokens: int, node_id: str, status: str = "active"
    ) -> Session:
        """Create new session assigned to a specific node (DGX aggregate).

        KV size from TP=2 per-GPU formula (see kv_memory_model).
        """
        kv_gb = kv_per_session_gb(context_tokens)
        session = Session(
            id=str(uuid.uuid4())[:8],
            status=status,
            kv_size_gb=kv_gb,
            node_id=node_id,
        )
        self.sessions[session.id] = session
        return session

    def tick_sessions(self) -> list[str]:
        """Tick all sessions. Returns list of terminated session IDs."""
        terminated: list[str] = []
        for session in list(self.sessions.values()):
            if session.status == "active":
                session.active_ticks += 1
                if random.random() < 0.05:
                    session.status = "idle"
                    session.idle_ticks = 0

            elif session.status == "idle":
                session.idle_ticks += 1
                r = random.random()
                if r < 0.02:
                    # Return — latency depends on which tier block is in (set externally)
                    session.status = "returning"
                    session.return_latency_remaining = 2
                elif r < 0.025:
                    # Low termination rate so sessions accumulate and fill tiers
                    session.status = "terminated"
                    terminated.append(session.id)

            elif session.status == "returning":
                session.return_latency_remaining -= 1
                if session.return_latency_remaining <= 0:
                    session.status = "active"
                    session.idle_ticks = 0
            elif session.status == "queued":
                # Admission is handled by SimulationEngine._admit_queued_sessions().
                pass

        # Clean up terminated sessions from dict
        for sid in terminated:
            del self.sessions[sid]

        return terminated

    def set_return_latency(self, session_id: str, ticks: int) -> None:
        """Set the return latency for a returning session based on source tier."""
        session = self.sessions.get(session_id)
        if session:
            session.return_latency_remaining = ticks

    def get_active_sessions(self) -> list[Session]:
        return [s for s in self.sessions.values() if s.status == "active"]

    def get_queued_sessions(self) -> list[Session]:
        return [s for s in self.sessions.values() if s.status == "queued"]

    def get_idle_sessions(self) -> list[Session]:
        return [s for s in self.sessions.values() if s.status == "idle"]

    def get_returning_sessions(self) -> list[Session]:
        return [s for s in self.sessions.values() if s.status == "returning"]

    def get_all(self) -> list[Session]:
        return list(self.sessions.values())

    def remove(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def clear(self) -> None:
        self.sessions.clear()
