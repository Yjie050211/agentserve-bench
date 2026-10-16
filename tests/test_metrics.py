import json
from pathlib import Path

import pytest

from agentserve_bench.metrics.client import stream_metrics
from agentserve_bench.workloads.prefix_analysis import common_prefix

GOLDEN = json.loads(Path("tests/fixtures/stream-metrics-v1.json").read_text())


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda case: case["name"])
def test_shared_golden_semantics(case):
    actual = stream_metrics(case["events"], case["sent_at_ms"])
    for key, expected in case["expected"].items():
        assert actual[key] == expected


def test_partial_stream_cannot_have_tpot():
    case = GOLDEN["cases"][0]
    result = stream_metrics(case["events"], case["sent_at_ms"], complete=False)
    assert result["text_tpot_proxy_ms"] is None


@pytest.mark.parametrize("tokens", [None, 0, 1, True])
def test_unreliable_token_count(tokens):
    events = [
        {"kind": "text", "text": "a", "at_ms": 1},
        {"kind": "text", "text": "b", "at_ms": 2},
        {"kind": "usage", "completion_tokens": tokens, "reasoning_tokens": 0, "at_ms": 3},
        {"kind": "done", "at_ms": 4},
    ]
    assert stream_metrics(events)["text_tpot_proxy_ms"] is None


def test_hidden_reasoning_unknown_no_proxy():
    events = [
        {"kind": "text", "text": "a", "at_ms": 1},
        {"kind": "usage", "completion_tokens": 3, "at_ms": 3},
        {"kind": "done", "at_ms": 4},
    ]
    assert stream_metrics(events)["text_tpot_proxy_ms"] is None


def test_prefix_algorithm():
    assert common_prefix([1, 2], [1, 2, 3]) == 2
    assert common_prefix([1, 2], [1, 3]) == 1
    assert common_prefix([], [1]) == 0
