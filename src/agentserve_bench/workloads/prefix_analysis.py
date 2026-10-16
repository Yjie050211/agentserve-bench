"""Algorithm validation with a deterministic fixture encoding, not model tokens."""

from __future__ import annotations

import json
from typing import Any

from agentserve_bench.traces.load import LoadedTrace, canonical_bytes, sha256


def fixture_encode(body: dict[str, Any]) -> list[int]:
    # Preserves all message/tool structures; intentionally not a real chat template.
    rendered = json.dumps(
        {"messages": body["messages"], "tools": body.get("tools")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return list(rendered.encode("utf-8"))


def common_prefix(left: list[int], right: list[int]) -> int:
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return index
    return min(len(left), len(right))


def analyze(trace: LoadedTrace) -> dict[str, Any]:
    rows = []
    previous: list[int] | None = None
    for source in trace.selected:
        tokens = fixture_encode(source.record["request_body"])
        rows.append(
            {
                "request_id": source.request_id,
                "fixture_units": len(tokens),
                "common_prefix_fixture_units_with_previous": common_prefix(previous, tokens)
                if previous is not None
                else None,
                "body_sha256": sha256(canonical_bytes(source.record["request_body"])),
            }
        )
        previous = tokens
    return {
        "encoding": "deterministic-utf8-fixture-v1",
        "real_tokenizer": False,
        "server_template_verified": False,
        "cache_hit_evidence": False,
        "warning": "Fixture units are bytes, not actual model tokens or cache blocks.",
        "requests": rows,
    }
