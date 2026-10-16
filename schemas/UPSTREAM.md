# Model-request contract snapshot

Canonical maintainer: [Yjie050211/agent-harness-lab](https://github.com/Yjie050211/agent-harness-lab), `schemas/model-request-v1.schema.json`, `schema_version="1.0"`.

Snapshot SHA-256: `f546c2582363ed2fb48d69906b4d6ab9f02064aecca1a4a454062eab5becd893`.

Upstream source commit: `0709f4bd8ec698bc2b57109bd2a680254a289574`.

This snapshot was authored in the coordinated 2026-10-16 framework build. The canonical file is pinned to the actual upstream commit above; the local release process verifies that its Git blob matches the recorded snapshot SHA-256. Runtime copy in `src/agentserve_bench/resources/` is byte-compared with this file by a contract test. Repository text uses LF while wire-body artifacts are excluded from newline normalization to preserve their byte hashes.

`body_sha256` hashes UTF-8 JSON with sorted object keys, no insignificant whitespace, preserved array order and `allow_nan=False`. It is not an original network-body hash. The actual wire artifact and `wire_body_sha256` are independently validated, required for a real source model and optional for fake sources. Wire artifact paths resolve under the JSONL parent; traversal outside that directory is rejected.

Consumers reject unsupported versions, duplicate request IDs, reordered session steps and invalid source attempt numbering. `usage=null` means unavailable, never zero. The session key is `(source_run_id, task_id)`. New replays add their own experiment/attempt IDs without overwriting source identities.

Golden metric fixture `tests/fixtures/stream-metrics-v1.json` is synchronized with NanoServe-Lab at commit `cf711f724b84b365a697e299a09198105590f34a`. It contains deterministic test observations, not real GPU data.
