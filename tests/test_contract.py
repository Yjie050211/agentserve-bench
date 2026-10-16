import json
from importlib.resources import files
from pathlib import Path

import pytest

from agentserve_bench.traces.load import canonical_bytes, load_trace, sha256
from agentserve_bench.workloads.synthetic import generate


def rewrite(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_schema_snapshot():
    assert (
        Path("schemas/model-request-v1.schema.json").read_bytes()
        == files("agentserve_bench.resources").joinpath("model-request-v1.schema.json").read_bytes()
    )


def test_generate_and_validate(tmp_path):
    trace = load_trace(generate(tmp_path / "trace"))
    assert len(trace.requests) == len(trace.selected) == 4
    assert all(request.source_wire_verified for request in trace.requests)


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "duplicate",
        "hash",
        "wire_hash",
        "order",
        "attempt",
        "escape",
        "tool",
        "n",
        "real_wire",
    ],
)
def test_reject_invalid_trace(tmp_path, mutation):
    path = generate(tmp_path / "trace")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == "version":
        rows[0]["schema_version"] = "2.0"
    elif mutation == "duplicate":
        rows[1]["request_id"] = rows[0]["request_id"]
    elif mutation == "hash":
        rows[0]["body_sha256"] = "0" * 64
    elif mutation == "wire_hash":
        rows[0]["wire_body_sha256"] = "0" * 64
    elif mutation == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "attempt":
        rows[0]["source_attempt_no"] = 2
    elif mutation == "escape":
        rows[0]["wire_body_artifact"] = "../../outside.json"
    elif mutation in {"tool", "n"}:
        body = rows[0]["request_body"]
        if mutation == "tool":
            body["messages"] = [{"role": "tool", "tool_call_id": "absent", "content": "x"}]
        else:
            body["n"] = 2
        rows[0]["body_sha256"] = sha256(canonical_bytes(body))
    elif mutation == "real_wire":
        rows[0]["model_mode"] = "real"
        del rows[0]["wire_body_artifact"]
        del rows[0]["wire_body_sha256"]
    rewrite(path, rows)
    with pytest.raises(ValueError):
        load_trace(path)


def test_source_failure_selection_preserves_attempts(tmp_path):
    path = generate(tmp_path / "trace", sessions=1, steps=1)
    first = json.loads(path.read_text())
    second = {**first, "request_id": "retry", "source_attempt_no": 2}
    first["outcome"] = {"status": "timeout"}
    rewrite(path, [first, second])
    trace = load_trace(path)
    assert len(trace.requests) == 2
    assert [r.request_id for r in trace.selected] == ["retry"]
    assert trace.selection[0]["reason"] == "source_outcome_timeout"


def test_fake_without_wire_is_explicit_reconstruction(tmp_path):
    path = generate(tmp_path / "trace", sessions=1, steps=1)
    first = json.loads(path.read_text())
    del first["wire_body_artifact"]
    del first["wire_body_sha256"]
    rewrite(path, [first])
    assert load_trace(path).selected[0].source_wire_verified is False


def test_bool_int_wire_mismatch_rejected(tmp_path):
    path = generate(tmp_path / "trace", sessions=1, steps=1)
    row = json.loads(path.read_text())
    wire = json.dumps({**row["request_body"], "temperature": False}).encode()
    (path.parent / row["wire_body_artifact"]).write_bytes(wire)
    row["wire_body_sha256"] = sha256(wire)
    rewrite(path, [row])
    with pytest.raises(ValueError, match="wire body and request_body differ"):
        load_trace(path)
