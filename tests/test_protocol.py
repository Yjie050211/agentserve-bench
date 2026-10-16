import json

import httpx
import pytest

from agentserve_bench.backends.vllm_http import VllmHttpBackend, parse_chunk


def sse(payloads):
    return "".join(
        "data: " + (p if isinstance(p, str) else json.dumps(p)) + "\n\n" for p in payloads
    ).encode()


TEXT = {"choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": None}]}
FINISH = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
USAGE = {
    "choices": [],
    "usage": {"completion_tokens": 3, "completion_tokens_details": {"reasoning_tokens": 0}},
}


async def send(payloads, stream=True):
    def respond(request):
        assert "Authorization" not in str(request.content)
        if stream:
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, content=sse(payloads)
            )
        return httpx.Response(200, json=payloads)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        backend = VllmHttpBackend(client, "http://test/v1")
        return await backend.send(json.dumps({"stream": stream}).encode(), "req")


async def test_valid_sse_preserves_raw_and_typed():
    result = await send([TEXT, FINISH, USAGE, "[DONE]"])
    assert result.status == "succeeded"
    assert result.metrics["text_ttft_ms"] is not None
    assert result.metrics["complete"] is True
    assert len(result.raw_events) == 4


@pytest.mark.parametrize(
    "payloads",
    [
        ["[DONE]"],
        [TEXT],
        [TEXT, "[DONE]"],
        [TEXT, FINISH, "[DONE]", "[DONE]"],
        [TEXT, FINISH, "[DONE]", TEXT],
        [TEXT, FINISH, FINISH, "[DONE]"],
        [TEXT, FINISH, USAGE, USAGE, "[DONE]"],
        [TEXT, FINISH, TEXT, "[DONE]"],
        [{"choices": [{"index": 1, "delta": {"content": "x"}}]}, FINISH, "[DONE]"],
        [{"error": {"message": "model failed"}}],
    ],
)
async def test_incomplete_or_invalid_streams_fail(payloads):
    result = await send(payloads)
    assert result.status == "failed"
    assert result.metrics["text_tpot_proxy_ms"] is None


@pytest.mark.parametrize(
    "chunk",
    [
        [],
        {"choices": {}},
        {"choices": [False]},
        {"choices": [{"delta": []}]},
        {"choices": [{"delta": {"content": 1}}]},
        {"choices": [{"delta": {"reasoning": 1}}]},
        {"choices": [{"delta": {"tool_calls": {}}}]},
        {"choices": [{"delta": {"tool_calls": [{"function": []}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": 1}}]}}]},
        {"usage": {"completion_tokens": -1}},
        {"usage": {"completion_tokens": True}},
    ],
)
def test_malformed_delta_types(chunk):
    with pytest.raises(ValueError):
        parse_chunk(chunk, 0)


async def test_tool_only_never_claims_text_latency():
    tool = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {"index": 0, "function": {"name": "read_file", "arguments": "{}"}}
                    ]
                }
            }
        ]
    }
    result = await send([tool, FINISH, USAGE, "[DONE]"])
    assert result.status == "succeeded"
    assert result.metrics["text_ttft_ms"] is None
    assert result.metrics["tool_arguments_ttft_ms"] is not None
    assert result.metrics["text_tpot_proxy_ms"] is None


@pytest.mark.parametrize(
    "data",
    [
        {"choices": [{}]},
        {"choices": []},
        {"choices": [{"message": {"role": "assistant", "content": "x"}}]},
    ],
)
async def test_invalid_non_stream_response(data):
    assert (await send(data, stream=False)).status == "failed"


async def test_valid_non_stream_response_only_e2e():
    result = await send(
        {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]},
        stream=False,
    )
    assert result.status == "succeeded"
    assert result.metrics["text_ttft_ms"] is None
