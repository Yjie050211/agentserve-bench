"""Load, verify, and select source calls without discarding source attempts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json(value: str | bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    return json.loads(value, parse_constant=reject_constant, object_pairs_hook=unique_object)


@dataclass(frozen=True)
class SourceRequest:
    record: dict[str, Any]
    wire_body: bytes
    source_wire_verified: bool = True

    @property
    def session(self) -> tuple[str, str]:
        return self.record["source_run_id"], self.record["task_id"]

    @property
    def request_id(self) -> str:
        return self.record["request_id"]


@dataclass(frozen=True)
class LoadedTrace:
    requests: tuple[SourceRequest, ...]
    selected: tuple[SourceRequest, ...]
    selection: tuple[dict[str, Any], ...]
    trace_sha256: str


def validate_chat_body(body: dict[str, Any]) -> None:
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise ValueError("request requires a non-empty model")
    if body.get("n", 1) != 1:
        raise ValueError("only n=1 is supported")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    pending: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("each message must be an object")
        role = message.get("role")
        if role not in {"system", "developer", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {role}")
        if role == "tool":
            tool_id = message.get("tool_call_id")
            if tool_id not in pending:
                raise ValueError("tool message has no matching preceding tool call")
            pending.remove(tool_id)
        elif pending:
            raise ValueError("unresolved tool calls before next non-tool message")
        calls = message.get("tool_calls", [])
        if calls and role != "assistant":
            raise ValueError("tool_calls require assistant role")
        for call in calls:
            call_id = call.get("id")
            if not call_id or call_id in pending or call.get("type") != "function":
                raise ValueError("invalid or duplicate tool call ID")
            function = call.get("function", {})
            if not isinstance(function.get("name"), str) or not isinstance(
                function.get("arguments"), str
            ):
                raise ValueError("invalid tool function")
            pending.add(call_id)
    if pending:
        raise ValueError("trace ends with unresolved tool calls")


def load_trace(path: Path) -> LoadedTrace:
    raw = path.read_bytes()
    schema = strict_json(
        files("agentserve_bench.resources").joinpath("model-request-v1.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    attempts: list[SourceRequest] = []
    seen: set[str] = set()
    sessions: dict[tuple[str, str], list[SourceRequest]] = defaultdict(list)
    root = path.parent.resolve()
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = strict_json(line)
            validator.validate(record)
            if record["request_id"] in seen:
                raise ValueError("duplicate request_id")
            seen.add(record["request_id"])
            body = record["request_body"]
            validate_chat_body(body)
            if sha256(canonical_bytes(body)) != record["body_sha256"]:
                raise ValueError("canonical body_sha256 mismatch")
            verified = "wire_body_artifact" in record
            if verified:
                artifact = (root / record["wire_body_artifact"]).resolve()
                if not artifact.is_relative_to(root):
                    raise ValueError("wire artifact escapes trace directory")
                wire = artifact.read_bytes()
                if sha256(wire) != record["wire_body_sha256"]:
                    raise ValueError("wire_body_sha256 mismatch")
                if canonical_bytes(strict_json(wire)) != canonical_bytes(body):
                    raise ValueError("wire body and request_body differ")
            else:
                wire = canonical_bytes(body)
            attempt = SourceRequest(record, wire, verified)
            attempts.append(attempt)
            sessions[attempt.session].append(attempt)
        except Exception as exc:
            raise ValueError(f"trace line {line_no}: {exc}") from exc
    if not attempts:
        raise ValueError("trace is empty")
    selected: list[SourceRequest] = []
    reasons: dict[str, str] = {}
    for session in sessions.values():
        last_step = -1
        calls: dict[str, list[SourceRequest]] = {}
        step_calls: dict[int, str] = {}
        for attempt in session:
            record = attempt.record
            step, call = record["step_id"], record["logical_call_id"]
            if step < last_step:
                raise ValueError("session steps must be nondecreasing in the source file")
            if step in step_calls and step_calls[step] != call:
                raise ValueError("one logical call per session step is required")
            if call in calls and calls[call][0].record["step_id"] != step:
                raise ValueError("logical_call_id reused across steps")
            group = calls.setdefault(call, [])
            if record["source_attempt_no"] != len(group) + 1:
                raise ValueError("source attempts must be consecutive starting at 1")
            group.append(attempt)
            step_calls[step] = call
            last_step = step
        for group in calls.values():
            successful = [a for a in group if a.record["outcome"]["status"] == "succeeded"]
            winner = successful[-1] if successful else None
            if winner:
                selected.append(winner)
            for attempt in group:
                reasons[attempt.request_id] = (
                    "selected_successful_source_attempt"
                    if attempt is winner
                    else "superseded_successful_source_attempt"
                    if attempt in successful
                    else "source_outcome_" + attempt.record["outcome"]["status"]
                )
    chosen = {item.request_id for item in selected}
    return LoadedTrace(
        tuple(attempts),
        tuple(a for a in attempts if a.request_id in chosen),
        tuple(
            {
                "request_id": a.request_id,
                "included": a.request_id in chosen,
                "reason": reasons[a.request_id],
                "source_record": a.record,
            }
            for a in attempts
        ),
        sha256(raw),
    )
