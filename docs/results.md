# Validation status

Implemented: versioned trace validation, byte/hash checks, source-attempt selection records, bounded session replay, failure/not-sent preservation, original/effective bodies, fixture backend, HTTP/SSE transport, client metric semantics, fail-closed capability/counter helpers, CLI and installable package.

CPU verification on 2026-10-16, Windows / Python 3.11.15:

| Command / check | Actual result |
|---|---|
| `uv sync --frozen` | Independent editable environment installs |
| `uv run ruff check .` / `uv run ruff format --check .` | Passed |
| `uv run pytest` | 79 passed |
| Synthetic CLI replay, 2 sessions × 2 steps, concurrency 2 | 4 succeeded; fixture-only |
| `prefix` / `plan-matrix` CLI | Explicit fixture/plan-only outputs |
| `uv build` | sdist and wheel built |
| Isolated wheel import + packaged schema resource | Passed |
| Harness export → validate → fixture replay | Both supplied 3-request task traces validated and replayed by the integration reviewer |

The fixture evidence is saved in `results/examples/cpu-smoke/`. CI is configured for Ubuntu CPU only; a configured workflow is not a claim that GitHub Actions has already passed.

Not validated: real vLLM endpoint, Linux/WSL GPU placement, tokenizer/template alignment, calibrated cache reset, actual cold/warm matrix, measured cache reuse or latency benefit. No such results are fabricated. `plan-matrix` is a plan-only command. Real HTTP tests use protocol mocks locally.
