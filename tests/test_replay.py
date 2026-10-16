import asyncio
import json

import pytest

from agentserve_bench.backends.fixture import FixtureBackend
from agentserve_bench.replay.runner import effective_request, replay
from agentserve_bench.traces.load import load_trace, sha256
from agentserve_bench.workloads.synthetic import generate


async def test_order_concurrency_failure_and_not_sent(tmp_path):
    trace = load_trace(generate(tmp_path / "trace", sessions=3, steps=3))
    backend = FixtureBackend({"synthetic-0-1"}, delay_s=0.001)
    output = tmp_path / "run"
    summary = await replay(trace, backend, output, concurrency=2)
    assert backend.max_active <= 2
    assert backend.sent_ids.index("synthetic-1-0") < backend.sent_ids.index("synthetic-1-1")
    assert "synthetic-0-2" not in backend.sent_ids
    assert summary["counts"] == {"succeeded": 7, "failed": 1, "not_sent": 1}
    assert summary["request_set_complete"] is False
    assert summary["cache_hit_rate"] is None
    results = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    assert len(results) == 9
    for result in results:
        assert (
            sha256((output / result["effective_body_artifact"]).read_bytes())
            == result["effective_body_sha256"]
        )


def test_preserve_and_explicit_stream_model_transforms(tmp_path):
    trace = load_trace(generate(tmp_path / "trace", sessions=1, steps=1))
    source = trace.selected[0]
    wire, _, changes = effective_request(source)
    assert wire == source.wire_body and changes == []
    wire, body, changes = effective_request(source, model="new-model")
    assert body["model"] == "new-model"
    assert changes == [{"field": "model", "before": "fixture-model", "after": "new-model"}]
    assert wire != source.wire_body


async def test_output_not_overwritten(tmp_path):
    trace = load_trace(generate(tmp_path / "trace", sessions=1, steps=1))
    output = tmp_path / "run"
    await replay(trace, FixtureBackend(), output)
    with pytest.raises(FileExistsError):
        await replay(trace, FixtureBackend(), output)


@pytest.mark.parametrize("exception", [RuntimeError("unexpected"), asyncio.CancelledError()])
async def test_backend_exception_still_writes_complete_results(tmp_path, exception):
    class BrokenBackend:
        execution_mode = "fixture"

        async def send(self, body, request_id):
            raise exception

    trace = load_trace(generate(tmp_path / "trace", sessions=1, steps=2))
    output = tmp_path / "run"
    summary = await replay(trace, BrokenBackend(), output)
    assert summary["sent"] == 1
    assert summary["counts"]["not_sent"] == 1
    assert summary["cache_comparison_eligible"] is False
    assert len((output / "results.jsonl").read_text().splitlines()) == 2
