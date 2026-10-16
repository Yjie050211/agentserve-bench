from __future__ import annotations

import json
from pathlib import Path

from agentserve_bench.traces.load import canonical_bytes, sha256


def generate(output: Path, sessions: int = 2, steps: int = 2) -> Path:
    if sessions < 1 or steps < 1:
        raise ValueError("sessions and steps must be positive")
    output.mkdir(parents=True, exist_ok=False)
    (output / "bodies").mkdir()
    records = []
    for session in range(sessions):
        messages = [{"role": "system", "content": "You are a careful code assistant."}]
        for step in range(steps):
            messages.append({"role": "user", "content": f"Inspect synthetic file {step}."})
            request_id = f"synthetic-{session}-{step}"
            body = {
                "model": "fixture-model",
                "messages": list(messages),
                "max_tokens": 16,
                "temperature": 0,
                "n": 1,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            wire = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            artifact = f"bodies/{request_id}.json"
            (output / artifact).write_bytes(wire)
            records.append(
                {
                    "schema_version": "1.0",
                    "source_run_id": "synthetic-v1",
                    "task_id": f"task-{session}",
                    "step_id": step,
                    "logical_call_id": f"call-{session}-{step}",
                    "source_attempt_no": 1,
                    "request_id": request_id,
                    "relative_start_ms": float(step * 100),
                    "request_body": body,
                    "body_sha256": sha256(canonical_bytes(body)),
                    "wire_body_artifact": artifact,
                    "wire_body_sha256": sha256(wire),
                    "outcome": {"status": "succeeded"},
                    "usage": None,
                    "model_mode": "fake",
                    "workload_origin": "synthetic",
                }
            )
            messages.append({"role": "assistant", "content": "Synthetic previous answer."})
    path = output / "model_requests.jsonl"
    path.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8"
    )
    return path
