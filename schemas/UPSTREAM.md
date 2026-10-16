# Model-request contract snapshot

Canonical maintainer: [Yjie050211/agent-harness-lab](https://github.com/Yjie050211/agent-harness-lab), `schemas/model-request-v1.schema.json`, `schema_version="1.0"`.

Snapshot SHA-256: `f546c2582363ed2fb48d69906b4d6ab9f02064aecca1a4a454062eab5becd893`.

This initial snapshot is authored in the coordinated 2026-10-16 framework build; the upstream initial commit has not yet been published at snapshot time. No upstream commit ID is invented. The parent release process can record the actual published commit later. Runtime copy in `src/agentserve_bench/resources/` is byte-compared with this file by a contract test.

`body_sha256` hashes UTF-8 JSON with sorted object keys, no insignificant whitespace, preserved array order and `allow_nan=False`. It is not an original network-body hash. The actual wire artifact and `wire_body_sha256` are independently validated, required for a real source model and optional for fake sources. Wire artifact paths resolve under the JSONL parent; traversal outside that directory is rejected.

Consumers reject unsupported versions, duplicate request IDs, reordered session steps and invalid source attempt numbering. `usage=null` means unavailable, never zero. The session key is `(source_run_id, task_id)`. New replays add their own experiment/attempt IDs without overwriting source identities.

Golden metric fixture `tests/fixtures/stream-metrics-v1.json` is synchronized with NanoServe-Lab in the same coordinated build. It contains deterministic test observations, not real GPU data.
