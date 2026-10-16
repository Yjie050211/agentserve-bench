from __future__ import annotations

import asyncio
import json

from agentserve_bench.backends.base import Observation
from agentserve_bench.metrics.client import stream_metrics


class FixtureBackend:
    """Deterministic protocol observations, not synthetic GPU performance claims."""

    execution_mode = "fixture"

    def __init__(self, fail_ids: set[str] | None = None, delay_s: float = 0):
        self.fail_ids = fail_ids or set()
        self.delay_s = delay_s
        self.active = 0
        self.max_active = 0
        self.sent_ids: list[str] = []

    async def send(self, body: bytes, request_id: str) -> Observation:
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        self.sent_ids.append(request_id)
        try:
            await asyncio.sleep(self.delay_s)
            if request_id in self.fail_ids:
                return Observation("failed", error="deliberate fixture failure")
            if json.loads(body).get("stream", False):
                events = [
                    {"at_ms": 10, "kind": "metadata"},
                    {"at_ms": 30, "kind": "text", "text": "fixture "},
                    {"at_ms": 90, "kind": "text", "text": "answer"},
                    {"at_ms": 100, "kind": "usage", "completion_tokens": 4, "reasoning_tokens": 0},
                    {"at_ms": 110, "kind": "done"},
                ]
                metrics = stream_metrics(events)
            else:
                events = [{"at_ms": 110, "kind": "response", "text": "fixture answer"}]
                metrics = {
                    "e2e_ms": 110,
                    "text_ttft_ms": None,
                    "text_tpot_proxy_ms": None,
                    "complete": True,
                    "completion_tokens": 4,
                }
            return Observation(
                "succeeded",
                events,
                [{**e, "fixture": True} for e in events],
                metrics,
                server_drain_confirmed=True,
            )
        finally:
            self.active -= 1
