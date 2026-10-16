"""OpenAI-compatible transport with typed SSE observations and raw event retention."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from agentserve_bench.backends.base import Observation
from agentserve_bench.metrics.client import stream_metrics
from agentserve_bench.traces.load import strict_json


def parse_chunk(chunk: dict[str, Any], at_ms: float) -> list[dict[str, Any]]:
    if not isinstance(chunk, dict):
        raise ValueError("SSE payload must be an object")
    if chunk.get("error"):
        raise ValueError(f"server stream error: {chunk['error']}")
    events: list[dict[str, Any]] = []
    choices = chunk.get("choices", [])
    if not isinstance(choices, list) or any(not isinstance(c, dict) for c in choices):
        raise ValueError("choices must be an array of objects")
    if len(choices) > 1 or any(c.get("index", 0) != 0 for c in choices):
        raise ValueError("only one choice with index=0 is supported")
    for choice in choices:
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            raise ValueError("delta must be an object")
        unexpected = set(delta) - {
            "role",
            "content",
            "reasoning_content",
            "reasoning",
            "tool_calls",
            "refusal",
        }
        if unexpected:
            raise ValueError(f"unsupported delta fields: {sorted(unexpected)}")
        if delta.get("role") is not None and not isinstance(delta["role"], str):
            raise ValueError("role must be a string or null")
        if delta.get("content") is not None and not isinstance(delta["content"], str):
            raise ValueError("content must be string or null")
        if delta.get("content"):
            if not isinstance(delta["content"], str):
                raise ValueError("only string text deltas are supported")
            events.append({"at_ms": at_ms, "kind": "text", "text": delta["content"]})
        for key in ("reasoning_content", "reasoning"):
            if delta.get(key) is not None and not isinstance(delta[key], str):
                raise ValueError("reasoning delta must be string or null")
            if delta.get(key):
                events.append({"at_ms": at_ms, "kind": "reasoning", "text": delta[key]})
        calls = delta.get("tool_calls", [])
        if not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls):
            raise ValueError("tool_calls must be an array of objects")
        for call in calls:
            if not isinstance(call.get("function", {}), dict):
                raise ValueError("tool function must be an object")
            arguments = call.get("function", {}).get("arguments")
            if arguments is not None and not isinstance(arguments, str):
                raise ValueError("tool arguments must be a string")
            if arguments:
                events.append({"at_ms": at_ms, "kind": "tool_arguments", "text": arguments})
            else:
                events.append({"at_ms": at_ms, "kind": "tool_metadata", "data": call})
        if delta.get("refusal") is not None:
            if not isinstance(delta["refusal"], str):
                raise ValueError("refusal must be a string or null")
            if delta["refusal"]:
                events.append({"at_ms": at_ms, "kind": "refusal", "text": delta["refusal"]})
        if not events:
            events.append({"at_ms": at_ms, "kind": "metadata"})
        finish = choice.get("finish_reason")
        if finish is not None:
            if not isinstance(finish, str) or not finish:
                raise ValueError("finish_reason must be a non-empty string or null")
            events.append({"at_ms": at_ms, "kind": "finish", "reason": finish})
    usage = chunk.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            raise ValueError("usage must be an object or null")
        detail = usage.get("completion_tokens_details") or {}
        if not isinstance(detail, dict):
            raise ValueError("completion_tokens_details must be an object")
        for value in (usage.get("completion_tokens"), detail.get("reasoning_tokens")):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError("usage counts must be nonnegative integers or null")
        events.append(
            {
                "at_ms": at_ms,
                "kind": "usage",
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": detail.get("reasoning_tokens"),
            }
        )
    return events


class VllmHttpBackend:
    execution_mode = "real"

    def __init__(self, client: httpx.AsyncClient, base_url: str, timeout_s: float = 60):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def send(self, body: bytes, request_id: str) -> Observation:
        events: list[dict[str, Any]] = []
        raw_events: list[dict[str, Any]] = []
        start = time.perf_counter()

        def elapsed() -> float:
            return (time.perf_counter() - start) * 1000

        try:
            async with asyncio.timeout(self.timeout_s):
                if not json.loads(body).get("stream", False):
                    response = await self.client.post(
                        self.base_url + "/chat/completions",
                        content=body,
                        headers={"Content-Type": "application/json"},
                    )
                    raw_events.append(
                        {
                            "at_ms": elapsed(),
                            "http_status": response.status_code,
                            "data": response.text,
                        }
                    )
                    response.raise_for_status()
                    data = strict_json(response.content)
                    if not isinstance(data, dict):
                        raise ValueError("non-streaming response must be an object")
                    choices = data.get("choices", [])
                    if (
                        not isinstance(choices, list)
                        or len(choices) != 1
                        or not isinstance(choices[0], dict)
                    ):
                        raise ValueError("expected one non-streaming choice")
                    choice = choices[0]
                    message = choice.get("message")
                    if (
                        not isinstance(message, dict)
                        or message.get("role") != "assistant"
                        or not isinstance(choice.get("finish_reason"), str)
                        or not choice["finish_reason"]
                    ):
                        raise ValueError("non-streaming response lacks message or finish_reason")
                    parse_chunk(
                        {
                            "choices": [{"index": choice.get("index", 0), "delta": message}],
                            "usage": data.get("usage"),
                        },
                        elapsed(),
                    )
                    if data.get("error"):
                        raise ValueError("server response contains an error")
                    metrics = {
                        "e2e_ms": elapsed(),
                        "text_ttft_ms": None,
                        "text_tpot_proxy_ms": None,
                        "complete": True,
                        "completion_tokens": (data.get("usage") or {}).get("completion_tokens"),
                    }
                    return Observation("succeeded", events, raw_events, metrics)
                async with self.client.stream(
                    "POST",
                    self.base_url + "/chat/completions",
                    content=body,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.is_error:
                        await response.aread()
                        raw_events.append(
                            {
                                "at_ms": elapsed(),
                                "http_status": response.status_code,
                                "data": response.text,
                            }
                        )
                    response.raise_for_status()
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise ValueError("streaming response is not text/event-stream")
                    lines: list[str] = []
                    done = False
                    finished = False
                    usage_seen = False
                    async for line in response.aiter_lines():
                        if line == "":
                            if not lines:
                                continue
                            payload = "\n".join(lines)
                            lines.clear()
                            stamp = elapsed()
                            raw_events.append({"at_ms": stamp, "data": payload})
                            if done:
                                raise ValueError("extra data after [DONE]")
                            if payload == "[DONE]":
                                if not finished:
                                    raise ValueError("[DONE] before finish_reason")
                                events.append({"at_ms": stamp, "kind": "done"})
                                done = True
                                continue
                            parsed = parse_chunk(strict_json(payload), stamp)
                            new_finish = any(e["kind"] == "finish" for e in parsed)
                            new_usage = any(e["kind"] == "usage" for e in parsed)
                            if new_finish and finished:
                                raise ValueError("duplicate finish_reason")
                            if new_usage and usage_seen:
                                raise ValueError("duplicate usage")
                            if finished and any(
                                e["kind"] in {"text", "tool_arguments", "reasoning"} for e in parsed
                            ):
                                raise ValueError("content after finish_reason")
                            finished |= new_finish
                            usage_seen |= new_usage
                            events.extend(parsed)
                        elif line.startswith("data:"):
                            lines.append(line[5:].removeprefix(" "))
                            if sum(map(len, lines)) > 2_000_000:
                                raise ValueError("SSE event exceeds 2 MB")
                    if not done:
                        raise ValueError("stream ended without a complete [DONE] event")
                    if lines:
                        raise ValueError("unterminated data after [DONE]")
                return Observation(
                    "succeeded",
                    events,
                    raw_events,
                    stream_metrics(events),
                )
        except (TimeoutError, httpx.TimeoutException) as exc:
            status, error = "timeout", type(exc).__name__
        except asyncio.CancelledError:
            # Preserve cancellation observations; caller still owns session cleanup.
            status, error = "cancelled", "client_cancelled_server_state_unknown"
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        metrics = stream_metrics(events, complete=False)
        metrics["e2e_ms"] = elapsed()
        return Observation(status, events, raw_events, metrics, error)
