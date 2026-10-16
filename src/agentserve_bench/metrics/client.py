"""Metrics derived from typed observations, never SSE chunk counts as tokens."""

from __future__ import annotations

from typing import Any


def stream_metrics(
    events: list[dict[str, Any]], sent_at_ms: float = 0, *, complete: bool = True
) -> dict[str, Any]:
    def content(kind: str) -> list[float]:
        return [e["at_ms"] for e in events if e["kind"] == kind and e.get("text")]

    texts, tools, reasoning = content("text"), content("tool_arguments"), content("reasoning")
    usages = [e for e in events if e["kind"] == "usage"]
    usage = usages[-1] if usages else {}
    tokens = usage.get("completion_tokens")
    reasoning_tokens = usage.get("reasoning_tokens")
    done = [e["at_ms"] for e in events if e["kind"] == "done"]
    ended = done[-1] if done else events[-1]["at_ms"] if events else sent_at_ms
    reliable_count = isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
    mixed_metadata = any(e["kind"] in {"tool_metadata", "refusal"} for e in events)
    pure_text = (
        bool(texts) and not tools and not reasoning and not mixed_metadata and reasoning_tokens == 0
    )
    tpot = None
    if complete and done and pure_text and reliable_count and tokens > 1:
        tpot = (texts[-1] - texts[0]) / (tokens - 1)
    return {
        "first_text_delta_at": texts[0] if texts else None,
        "first_tool_arguments_delta_at": tools[0] if tools else None,
        "first_reasoning_delta_at": reasoning[0] if reasoning else None,
        "last_text_delta_at": texts[-1] if texts else None,
        "protocol_terminal_at": done[-1] if done else None,
        "text_ttft_ms": texts[0] - sent_at_ms if texts else None,
        "tool_arguments_ttft_ms": tools[0] - sent_at_ms if tools else None,
        "text_tpot_proxy_ms": tpot,
        "e2e_ms": ended - sent_at_ms,
        "completion_tokens": tokens if reliable_count else None,
        "reasoning_tokens": reasoning_tokens,
        "complete": bool(complete and done),
        "output_types": [
            name
            for name, values in (
                ("text", texts),
                ("tool_arguments", tools),
                ("reasoning", reasoning),
            )
            if values
        ],
    }
