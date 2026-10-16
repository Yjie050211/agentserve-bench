# Architecture

AgentServe consumes immutable model-request traces and body artifacts. It does not execute tools or derive subsequent requests from newly generated output. `load_trace` validates the versioned JSON schema, canonical-object hash, optional original-wire hash, message/tool history, unique request IDs, ordered steps and source attempts before any requests are sent.

The source selection report contains every source attempt. A successful attempt per logical call is selected; failed source attempts remain visible with exclusion reasons. A new experiment assigns independent run/attempt IDs and keeps source identities.

`replay` limits active sessions with an asyncio semaphore. Requests in each session are sequential. Failure or cancellation stops only that session, with later calls explicitly recorded as `not_sent`. A backend exception becomes a result rather than dropping the entire report. No automatic retries alter the experiment request set.

Bodies are immutable at the source boundary. Preserve mode uses the verified source bytes. If a fake export lacks wire bytes, reconstruction is explicitly labeled. Stream adaptation and model mapping create derived bodies and transformation records. Both actual byte hashes and artifact paths are retained; the canonical-object hash serves structural validation only.

`FixtureBackend` supplies deterministic protocol data. `VllmHttpBackend` records raw SSE payloads and typed content observations with monotonic relative times. It validates a single choice, stream completion and response structure. The real backend does not certify GPU placement or cache state.

The cache helper separately checks exact service version, models, raw metrics and server drain counters. Cache reset acknowledgement is never sufficient. Matrix execution is deliberately gated until an engine-specific reset calibration and controlled isolation are actually validated.

No cross-repository imports, shared SDK, database, API server or GPU dependency is required for CPU use. Contract snapshots and golden metric semantics are tested locally.
