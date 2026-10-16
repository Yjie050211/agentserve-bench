from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import subprocess
import sys
from pathlib import Path

import httpx
import yaml

from agentserve_bench.backends.capabilities import inspect_server, verify_tool_template
from agentserve_bench.backends.fixture import FixtureBackend
from agentserve_bench.backends.vllm_http import VllmHttpBackend
from agentserve_bench.replay.runner import json_text, replay
from agentserve_bench.traces.load import load_trace, sha256
from agentserve_bench.workloads.prefix_analysis import analyze
from agentserve_bench.workloads.synthetic import generate


def provenance() -> dict:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        revision = result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        revision = None
    lock = Path("uv.lock")
    return {
        "git_commit": revision,
        "lock_sha256": sha256(lock.read_bytes()) if lock.exists() else None,
        "python": sys.version,
        "platform": platform.platform(),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agentserve", description="Agent workload replay bench")
    sub = root.add_subparsers(dest="command", required=True)
    synthetic = sub.add_parser("synthetic", help="write a self-contained synthetic source trace")
    synthetic.add_argument("--output", type=Path, required=True)
    synthetic.add_argument("--sessions", type=int, default=2)
    synthetic.add_argument("--steps", type=int, default=2)
    for name in ("validate", "prefix"):
        command = sub.add_parser(name)
        command.add_argument("trace", type=Path)
    run = sub.add_parser("replay")
    run.add_argument("trace", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--backend", choices=["fixture", "http"], default="fixture")
    run.add_argument("--origin", choices=["synthetic", "harness_export"], default="synthetic")
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--body-mode", choices=["preserve", "stream"], default="preserve")
    run.add_argument("--model")
    run.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    run.add_argument("--expected-version", help="exact installed vLLM release; required for http")
    run.add_argument("--timeout-s", type=float, default=60)
    run.add_argument(
        "--probe-tools",
        action="store_true",
        help="send an explicit preflight before replaying tool histories",
    )
    run.add_argument("--fixture-fail-request", action="append", default=[])
    matrix = sub.add_parser("plan-matrix", help="emit a plan only, never measured cache results")
    matrix.add_argument("--config", type=Path, required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    inspect.add_argument("--expected-version", required=True)
    return root


async def execute(args: argparse.Namespace) -> dict:
    if args.command == "synthetic":
        path = generate(args.output, args.sessions, args.steps)
        return {"trace": str(path), "workload_origin": "synthetic"}
    if args.command in {"validate", "prefix"}:
        trace = load_trace(args.trace)
        return (
            analyze(trace)
            if args.command == "prefix"
            else {
                "valid": True,
                "source_attempts": len(trace.requests),
                "selected_calls": len(trace.selected),
                "trace_sha256": trace.trace_sha256,
                "selection": list(trace.selection),
            }
        )
    if args.command == "plan-matrix":
        config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        if config.get("repetitions", 0) < 1:
            raise ValueError("repetitions must be positive")
        return {
            "status": "plan_only_not_measured",
            "real_gpu_validated": False,
            "config": config,
            "required_evidence": [
                "fixed engine/model/template versions",
                "exclusive service and drain",
                "calibrated reset semantics",
                "priming trace hash and ordering",
                "matching effective request sets",
                "before/after raw server metrics",
            ],
            "cache_hit_rate": None,
        }
    if args.command == "replay":
        trace = load_trace(args.trace)
        if not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
            raise ValueError("timeout-s must be positive")
        if args.backend == "fixture":
            return await replay(
                trace,
                FixtureBackend(set(args.fixture_fail_request)),
                args.output,
                concurrency=args.concurrency,
                mode=args.body_mode,
                model=args.model,
                workload_origin=args.origin,
                metadata=provenance(),
            )
        if not args.expected_version:
            raise ValueError("--expected-version is required for a real backend")
    url = httpx.URL(args.base_url)
    if (
        url.scheme not in {"http", "https"}
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("base URL requires http(s), without credentials or query parameters")
    headers = {}
    if key := os.environ.get("AGENTSERVE_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=False) as client:
        capability = await inspect_server(client, args.base_url, args.expected_version)
        if args.command == "inspect":
            return capability
        models = {args.model or a.record["request_body"]["model"] for a in trace.selected}
        if not models.issubset(set(capability["models"])):
            raise ValueError(f"trace models absent from server: {models}")
        has_tools = any(
            a.record["request_body"].get("tools")
            or any(
                m.get("role") == "tool" or m.get("tool_calls")
                for m in a.record["request_body"]["messages"]
            )
            for a in trace.selected
        )
        tool_probe = None
        if has_tools:
            if not args.probe_tools:
                raise ValueError("tool/template compatibility unverified; use --probe-tools")
            tool_probe = [
                await verify_tool_template(client, args.base_url, model) for model in sorted(models)
            ]
        metadata = {
            **provenance(),
            "capabilities_before": capability,
            "tool_probes": tool_probe,
            "base_url": args.base_url,
            "warning": "No calibrated cache reset; no cold/warm/cache-hit claim",
        }
        summary = await replay(
            trace,
            VllmHttpBackend(client, args.base_url, args.timeout_s),
            args.output,
            concurrency=args.concurrency,
            mode=args.body_mode,
            model=args.model,
            workload_origin=args.origin,
            metadata=metadata,
        )
        after = await inspect_server(client, args.base_url, args.expected_version)
        (args.output / "server_after.json").write_text(json_text(after), encoding="utf-8")
        return summary


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(execute(args))
    except (ValueError, OSError, httpx.HTTPError, KeyError, yaml.YAMLError) as exc:
        print(f"agentserve: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
