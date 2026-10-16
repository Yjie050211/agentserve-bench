"""Fail-closed vLLM capability and cache-state checks.

No endpoint status code is evidence that a prefix cache is cold.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import httpx


def parse_prometheus(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-zA-Z_:][\w:]*)(?:\{.*\})?\s+([^\s]+)(?:\s+\d+)?", line)
        if match:
            value = float(match[2])
            if not math.isfinite(value):
                raise ValueError("non-finite Prometheus sample")
            values[match[1]] = values.get(match[1], 0) + value
    return values


def server_drained(values: dict[str, float]) -> bool:
    names = ("vllm:num_requests_running", "vllm:num_requests_waiting")
    return all(name in values and values[name] == 0 for name in names)


@dataclass(frozen=True)
class CacheWindow:
    hit_rate: float | None
    valid: bool
    reason: str
    unit: str | None = None


def cache_window(
    before: dict[str, float],
    after: dict[str, float],
    *,
    exclusive: bool,
    drained_before: bool,
    drained_after: bool,
    token_units_verified: bool,
    hits_name: str = "vllm:prefix_cache_hits_total",
    queries_name: str = "vllm:prefix_cache_queries_total",
) -> CacheWindow:
    if not exclusive or not drained_before or not drained_after or not token_units_verified:
        return CacheWindow(None, False, "isolation, drain, or metric units not verified")
    if any(
        name not in snapshot for name in (hits_name, queries_name) for snapshot in (before, after)
    ):
        return CacheWindow(None, False, "counter missing")
    if any(
        not math.isfinite(snapshot[name])
        for name in (hits_name, queries_name)
        for snapshot in (before, after)
    ):
        return CacheWindow(None, False, "non-finite counter")
    hits = after[hits_name] - before[hits_name]
    queries = after[queries_name] - before[queries_name]
    if hits < 0 or queries < 0:
        return CacheWindow(None, False, "counter reset or rollback")
    if hits > queries:
        return CacheWindow(None, False, "hits exceed queries; inconsistent window")
    if queries == 0:
        return CacheWindow(None, False, "zero denominator")
    return CacheWindow(hits / queries, True, "exclusive token-counter difference", "token")


async def inspect_server(
    client: httpx.AsyncClient,
    base_url: str,
    expected_version: str,
) -> dict[str, Any]:
    base = base_url.rstrip("/")
    root = base.removesuffix("/v1")
    response = await client.get(root + "/version")
    response.raise_for_status()
    actual = response.json().get("version")
    if actual != expected_version:
        raise ValueError(f"vLLM version mismatch: expected {expected_version!r}, got {actual!r}")
    models = await client.get(base + "/models")
    models.raise_for_status()
    model_ids = [item["id"] for item in models.json()["data"]]
    metrics = await client.get(root + "/metrics")
    raw = metrics.text
    parsed = parse_prometheus(raw) if metrics.is_success else {}
    return {
        "version": actual,
        "models": model_ids,
        "metrics_available": metrics.is_success,
        "server_drained": server_drained(parsed),
        "raw_metrics": raw,
        "cache_state": "not_verified",
        "cache_reset_verified": False,
        "tool_template_verified": False,
    }


async def verify_tool_template(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    """Probe acceptance of tools + assistant/tool history, not tool task accuracy."""
    body = {
        "model": model,
        "max_tokens": 2,
        "n": 1,
        "stream": False,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "inspect_file",
                    "description": "Read a fixture file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
        "messages": [
            {"role": "user", "content": "Read fixture.txt, then summarize."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "probe_1",
                        "type": "function",
                        "function": {"name": "inspect_file", "arguments": '{"path":"fixture.txt"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "probe_1", "content": "fixture content"},
        ],
    }
    response = await client.post(base_url.rstrip("/") + "/chat/completions", json=body)
    response.raise_for_status()
    data = response.json()
    if data.get("error") or len(data.get("choices", [])) != 1:
        raise ValueError("tool/template preflight returned invalid completion")
    return {
        "accepted": True,
        "scope": "tools and assistant/tool history acceptance only",
        "probe_request": body,
        "probe_response": data,
        "cache_polluted_by_probe": True,
    }


async def request_cache_reset(
    client: httpx.AsyncClient,
    base_url: str,
) -> dict[str, Any]:
    response = await client.post(base_url.rstrip("/").removesuffix("/v1") + "/reset_prefix_cache")
    return {
        "http_status": response.status_code,
        "response": response.text,
        "cache_reset_verified": False,
        "cache_state": "not_verified",
        "reason": "HTTP acknowledgement does not establish calibrated cache-reset semantics",
    }
