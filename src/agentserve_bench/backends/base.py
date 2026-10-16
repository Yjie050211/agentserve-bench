from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Observation:
    status: str
    events: list[dict[str, Any]] = field(default_factory=list)
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    server_drain_confirmed: bool = False


class Backend(Protocol):
    execution_mode: str

    async def send(self, body: bytes, request_id: str) -> Observation: ...
