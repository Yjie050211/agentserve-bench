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


async def test_external_cancel_keeps_active_and_waiting_sessions(tmp_path):
    trace = load_trace(generate(tmp_path / "trace", sessions=3, steps=2))
    started = asyncio.Event()

    class SignallingBackend(FixtureBackend):
        async def send(self, body, request_id):
            started.set()
            return await super().send(body, request_id)

    backend = SignallingBackend(delay_s=10)
    output = tmp_path / "run"
    task = asyncio.create_task(replay(trace, backend, output, concurrency=1))
    # Wait for the actual send, not a scheduler timing assumption.
    async with asyncio.timeout(1):
        await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    results = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    summary = json.loads((output / "summary.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(results) == 6
    assert summary["counts"] == {"cancelled": 1, "not_sent": 5}
    assert summary["interrupted"] is True
    assert manifest["run_status"] == "cancelled"
    assert backend.active == 0
    assert (output / "report.md").exists()
    from agentserve_bench.replay.runner import summarize

    assert summarize(results, manifest) == summary
