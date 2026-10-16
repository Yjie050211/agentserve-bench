import json

import httpx
import pytest

from agentserve_bench.backends.vllm_http import VllmHttpBackend
from agentserve_bench.metrics.client import stream_metrics


@pytest.mark.parametrize("kind", ["tool_metadata", "refusal"])
def test_mixed_metadata_disables_text_tpot(kind):
    events = [
        {"kind": "text", "text": "a", "at_ms": 1},
        {"kind": kind, "text": "extra", "at_ms": 2},
        {"kind": "text", "text": "b", "at_ms": 3},
        {"kind": "usage", "completion_tokens": 4, "reasoning_tokens": 0, "at_ms": 4},
        {"kind": "done", "at_ms": 5},
    ]
    assert stream_metrics(events)["text_tpot_proxy_ms"] is None


async def test_non_object_non_stream_body_fails_cleanly():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        result = await VllmHttpBackend(client, "http://test/v1").send(
            json.dumps({"stream": False}).encode(), "req"
        )
    assert result.status == "failed"


async def test_http_error_preserves_response_body():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="temporary failure"))
    ) as client:
        result = await VllmHttpBackend(client, "http://test/v1").send(
            json.dumps({"stream": True}).encode(), "req"
        )
    assert result.status == "failed"
    assert result.raw_events[0]["data"] == "temporary failure"
