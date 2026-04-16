from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    started_at: float = field(default_factory=time.time)
    identity_loaded: bool = False
    node_id: str | None = None
    registered: bool = False
    verified: bool = False
    challenge_required: bool = False
    last_register_at: float | None = None
    last_heartbeat_at: float | None = None
    last_challenge_at: float | None = None
    last_error: str | None = None
    last_register_response: dict[str, Any] = field(default_factory=dict)
    last_heartbeat_response: dict[str, Any] = field(default_factory=dict)
    last_challenge_response: dict[str, Any] = field(default_factory=dict)
    last_probe_snapshot: dict[str, Any] = field(default_factory=dict)
    consecutive_failures: int = 0

    def mark_failure(self, error: str) -> None:
        self.last_error = error
        self.consecutive_failures += 1

    def clear_failure(self) -> None:
        self.last_error = None
        self.consecutive_failures = 0

    def ready(self, heartbeat_interval_seconds: float) -> bool:
        if not self.identity_loaded:
            return False
        if not self.registered:
            return False
        if self.last_heartbeat_at is None:
            return False
        if (time.time() - self.last_heartbeat_at) >= heartbeat_interval_seconds * 3:
            return False
        return self.verified or not self.challenge_required
