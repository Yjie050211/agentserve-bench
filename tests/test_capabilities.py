import httpx
import pytest

from agentserve_bench.backends.capabilities import (
    cache_window,
    inspect_server,
    parse_prometheus,
    request_cache_reset,
    server_drained,
)


def counters(hits, queries):
    return {"vllm:prefix_cache_hits_total": hits, "vllm:prefix_cache_queries_total": queries}


def window(before, after, **kwargs):
    options = dict(
        exclusive=True, drained_before=True, drained_after=True, token_units_verified=True
    )
    return cache_window(before, after, **{**options, **kwargs})


def test_valid_token_counter_difference():
    result = window(counters(5, 10), counters(15, 30))
    assert result.valid is True and result.hit_rate == 0.5 and result.unit == "token"


@pytest.mark.parametrize(
    "before,after",
    [
        ({}, {}),
        (counters(1, 1), counters(1, 1)),
        (counters(2, 4), counters(1, 3)),
        (counters(0, 0), counters(3, 2)),
        (counters(0, 0), counters(float("nan"), 2)),
    ],
)
def test_invalid_window_is_na(before, after):
    result = window(before, after)
    assert result.valid is False and result.hit_rate is None


@pytest.mark.parametrize(
    "flag", ["exclusive", "drained_before", "drained_after", "token_units_verified"]
)
def test_missing_proof_is_na(flag):
    assert window(counters(0, 0), counters(1, 2), **{flag: False}).valid is False


def test_prometheus_drain_and_missing_metrics():
    parsed = parse_prometheus(
        'vllm:num_requests_running{model_name="test"} 0\nvllm:num_requests_waiting 0\n'
    )
    assert server_drained(parsed)
    assert server_drained({}) is False


async def test_http_200_cache_reset_is_not_proof():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=True))
    ) as client:
        result = await request_cache_reset(client, "http://test/v1")
    assert result["cache_reset_verified"] is False
    assert result["cache_state"] == "not_verified"


async def test_engine_version_must_match():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"version": "other"})
        )
    ) as client:
        with pytest.raises(ValueError, match="version mismatch"):
            await inspect_server(client, "http://test/v1", "pinned")
