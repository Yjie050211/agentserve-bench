from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentserve_bench.backends.base import Backend, Observation
from agentserve_bench.traces.load import LoadedTrace, SourceRequest, sha256


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def effective_request(
    source: SourceRequest,
    mode: str = "preserve",
    model: str | None = None,
) -> tuple[bytes, dict[str, Any], list[dict[str, Any]]]:
    body = json.loads(source.wire_body)
    changes: list[dict[str, Any]] = []
    if not source.source_wire_verified:
        changes.append(
            {
                "operation": "reconstruct_from_canonical_object",
                "reason": "source has no wire artifact; exact wire replay unavailable",
            }
        )
    if mode == "stream":
        if body.get("stream") is not True:
            changes.append({"field": "stream", "before": body.get("stream"), "after": True})
            body["stream"] = True
        options = body.get("stream_options", {})
        if options.get("include_usage") is not True:
            changes.append(
                {
                    "field": "stream_options.include_usage",
                    "before": options.get("include_usage"),
                    "after": True,
                }
            )
            body["stream_options"] = {**options, "include_usage": True}
    elif mode != "preserve":
        raise ValueError("mode must be preserve or stream")
    if model is not None and body["model"] != model:
        changes.append({"field": "model", "before": body["model"], "after": model})
        body["model"] = model
    wire = (
        json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if changes
        else source.wire_body
    )
    return wire, body, changes


async def replay(
    trace: LoadedTrace,
    backend: Backend,
    output: Path,
    *,
    concurrency: int = 1,
    mode: str = "preserve",
    model: str | None = None,
    workload_origin: str = "synthetic",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if workload_origin not in {"synthetic", "harness_export"}:
        raise ValueError("invalid workload origin")
    if not trace.selected:
        raise ValueError("no successful complete source calls selected")
    output.mkdir(parents=True, exist_ok=False)
    (output / "bodies").mkdir()
    experiment_id = str(uuid.uuid4())
    selection = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in trace.selection)
    (output / "source_selection.jsonl").write_text(selection, encoding="utf-8")
    sessions: dict[tuple[str, str], list[SourceRequest]] = defaultdict(list)
    for source in trace.selected:
        sessions[source.session].append(source)
    prepared = {
        source.request_id: effective_request(source, mode, model) for source in trace.selected
    }
    manifest = {
        "schema_version": "1.0",
        "experiment_run_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "execution_mode": backend.execution_mode,
        "workload_origin": workload_origin,
        "source_trace_sha256": trace.trace_sha256,
        "concurrency": concurrency,
        "replay_mode": "closed_loop_frozen_trace",
        "body_mode": mode,
        "source_attempts": len(trace.requests),
        "selected_calls": len(trace.selected),
        "effective_request_set": [
            {
                "request_id": source.request_id,
                "effective_body_sha256": sha256(prepared[source.request_id][0]),
            }
            for source in trace.selected
        ],
        "cache_state": "not_verified",
        "cache_hit_rate": None,
        "server_drain_confirmed": backend.execution_mode == "fixture",
        "metadata": metadata or {},
    }
    (output / "manifest.json").write_text(json_text(manifest), encoding="utf-8")
    results: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(concurrency)
    run_start = time.perf_counter()

    # Prepare identities and immutable body artifacts for every selected request before
    # any awaits. Global cancellation can then account for sessions not yet admitted.
    common_by_id: dict[str, dict[str, Any]] = {}
    for source in trace.selected:
        record = source.record
        wire, body, changes = prepared[source.request_id]
        attempt_id = str(uuid.uuid4())
        stem = f"bodies/{attempt_id}"
        (output / (stem + ".source.json")).write_bytes(source.wire_body)
        (output / (stem + ".effective.json")).write_bytes(wire)
        common_by_id[source.request_id] = {
            "experiment_run_id": experiment_id,
            "attempt_id": attempt_id,
            "source_request_id": source.request_id,
            "source_run_id": record["source_run_id"],
            "task_id": record["task_id"],
            "step_id": record["step_id"],
            "logical_call_id": record["logical_call_id"],
            "source_attempt_no": record["source_attempt_no"],
            "source_body_sha256": sha256(source.wire_body) if source.source_wire_verified else None,
            "source_body_artifact": stem + ".source.json",
            "source_body_encoding": "verified_wire"
            if source.source_wire_verified
            else "canonical_reconstruction",
            "effective_body_sha256": sha256(wire),
            "effective_body_artifact": stem + ".effective.json",
            "effective_request_body": body,
            "transformations": changes,
            "execution_mode": backend.execution_mode,
            "workload_origin": workload_origin,
        }

    async def session_run(session: list[SourceRequest]) -> None:
        async with semaphore:
            failed_id: str | None = None
            for source in session:
                wire = prepared[source.request_id][0]
                common = common_by_id[source.request_id]
                attempt_id = common["attempt_id"]
                if failed_id:
                    result = {
                        **common,
                        "status": "not_sent",
                        "metrics": {},
                        "error": f"session_stopped_after:{failed_id}",
                        "sent_at_ms": None,
                        "terminal_at_ms": None,
                    }
                else:
                    sent_at = (time.perf_counter() - run_start) * 1000
                    with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(
                            json.dumps(
                                {**common, "event": "requested", "at_ms": sent_at},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                    try:
                        observation = await backend.send(wire, source.request_id)
                    except asyncio.CancelledError:
                        observation = Observation(
                            "cancelled", error="client_cancelled_server_state_unknown"
                        )
                    except Exception as exc:
                        observation = Observation(
                            "failed", error=f"unexpected_backend_error:{type(exc).__name__}"
                        )
                    terminal_at = (time.perf_counter() - run_start) * 1000
                    event_file = f"{attempt_id}.events.json"
                    (output / event_file).write_text(
                        json_text(
                            {
                                "raw": observation.raw_events,
                                "typed": observation.events,
                            }
                        ),
                        encoding="utf-8",
                    )
                    result = {
                        **common,
                        **{
                            k: v
                            for k, v in asdict(observation).items()
                            if k not in {"events", "raw_events"}
                        },
                        "raw_events_artifact": event_file,
                        "sent_at_ms": sent_at,
                        "terminal_at_ms": terminal_at,
                    }
                    if observation.status != "succeeded":
                        failed_id = source.request_id
                results.append(result)
                with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps({"event": "terminal", **result}, ensure_ascii=False) + "\n"
                    )

    tasks = [asyncio.create_task(session_run(items)) for items in sessions.values()]
    interrupted = False
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        interrupted = True
        for task in tasks:
            if not task.done():
                task.cancel()
        # Active backend calls get a chance to persist cancellation observations;
        # semaphore waiters have no sent call and are accounted for below.
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if interrupted:
            completed = {item["source_request_id"] for item in results}
            with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
                for source in trace.selected:
                    if source.request_id in completed:
                        continue
                    result = {
                        **common_by_id[source.request_id],
                        "status": "not_sent",
                        "metrics": {},
                        "error": "run_cancelled_before_send",
                        "sent_at_ms": None,
                        "terminal_at_ms": None,
                    }
                    results.append(result)
                    stream.write(
                        json.dumps({"event": "terminal", **result}, ensure_ascii=False) + "\n"
                    )
        manifest["run_status"] = "cancelled" if interrupted else "completed"
        manifest["interrupted"] = interrupted
    order = {source.request_id: i for i, source in enumerate(trace.selected)}
    results.sort(key=lambda item: order[item["source_request_id"]])
    (output / "results.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n" for item in results),
        encoding="utf-8",
    )
    summary = summarize(results, manifest)
    manifest["server_drain_confirmed"] = summary["server_drain_confirmed"]
    (output / "manifest.json").write_text(json_text(manifest), encoding="utf-8")
    (output / "summary.json").write_text(json_text(summary), encoding="utf-8")
    (output / "report.md").write_text(report(summary), encoding="utf-8")
    if interrupted:
        raise asyncio.CancelledError
    return summary


def summarize(results: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    counts = dict(Counter(item["status"] for item in results))
    sent = [item for item in results if item["status"] != "not_sent"]
    succeeded = [item for item in sent if item["status"] == "succeeded"]
    start = min((x["sent_at_ms"] for x in sent), default=0)
    end = max((x["terminal_at_ms"] for x in sent), default=start)
    seconds = (end - start) / 1000
    text_ttfts = [
        x["metrics"]["text_ttft_ms"]
        for x in succeeded
        if x["metrics"].get("text_ttft_ms") is not None
    ]
    fixture = manifest["execution_mode"] == "fixture"
    return {
        "experiment_run_id": manifest["experiment_run_id"],
        "execution_mode": manifest["execution_mode"],
        "workload_origin": manifest["workload_origin"],
        "interrupted": manifest.get("interrupted", False),
        "selected": len(results),
        "sent": len(sent),
        "counts": counts,
        "failure_rate": (len(sent) - len(succeeded)) / len(sent) if sent else None,
        "measurement_window_s": seconds,
        # Fixture observation timings are deterministic test data, not wall throughput.
        "successful_requests_per_s": len(succeeded) / seconds
        if seconds > 0 and not fixture
        else None,
        "text_ttft_mean_ms": sum(text_ttfts) / len(text_ttfts) if text_ttfts else None,
        "text_ttft_samples": len(text_ttfts),
        "request_set_complete": len(sent) == len(results),
        "request_set_successful": len(sent) == len(results) and len(succeeded) == len(results),
        "cache_comparison_eligible": False,
        "cache_state": "not_verified",
        "cache_hit_rate": None,
        "real_gpu_validated": False,
        "server_drain_confirmed": all(x.get("server_drain_confirmed", False) for x in sent),
        "interpretation": "CPU fixture protocol validation only"
        if fixture
        else "Client observations only; cache state and real GPU environment not certified",
    }


def report(summary: dict[str, Any]) -> str:
    return (
        "# AgentServe replay report\n\n"
        f"- Execution mode: `{summary['execution_mode']}`\n"
        f"- Workload origin: `{summary['workload_origin']}`\n"
        f"- Selected / sent: {summary['selected']} / {summary['sent']}\n"
        f"- Outcomes: `{summary['counts']}`\n"
        f"- Failure rate among sent calls: {summary['failure_rate']}\n"
        f"- Cache state: `{summary['cache_state']}`; hit rate: N/A\n"
        f"- Server drain confirmed: `{summary['server_drain_confirmed']}`\n\n"
        f"{summary['interpretation']}.\n\n"
        "Frozen replay does not measure Agent task success. Fixture values are not model "
        "performance. Failed and not-sent calls remain in results.jsonl. No cold/warm or "
        "cache-speedup claim is established by this run.\n"
    )
