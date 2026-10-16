# Controlled cache experiments

The current CLI implements ordinary fixed-trace replay and a matrix **plan**, not an automatically validated cache experiment. The following is the acceptance protocol for the next GPU phase:

1. Pin an actually installed vLLM release, model/revision, dtype, tokenizer, chat template, generation parameters and tools serialization. Save identities and hashes.
2. Use one exclusive instance without external KV connectors. Establish a server-state/drain check; client completion alone is insufficient.
3. Warm the engine, drain all traffic, calibrate a version-specific cache reset by observing repeatable reuse before reset and its disappearance after reset. Reset calibration probes themselves pollute the cache and must be cleaned again.
4. For **batch-start cold**, verify reset and start immediately. Subsequent calls in the same batch may legitimately reuse earlier calls. For fixed-prefix-primed, record priming request hashes, repetition count, order and coverage, then drain. The APC-off warm condition is a priming control, not a cache-hit claim.
5. Take server counter baselines after priming. Execute the same effective request set per comparison cell. Save raw counters after both client and server drain. Counter semantics and units must match the pinned version.
6. Preserve all failures and not-sent tails. Mismatched sent sets are incomplete cells, not clean performance comparisons. A timeout/cancellation leaves server state unknown until verified drain or a controlled restart and fresh setup.
7. Repeat in recorded order; initial plan uses three repetitions but does not imply high-percentile stability. Report negative or inconclusive results honestly.

`request_cache_reset` records the endpoint response only. A 200 response leaves `cache_reset_verified=false`. Missing state verification fails closed. No current command labels a run cold/warm or calculates a claimed cache speedup.

Current prefix analysis uses a deterministic CPU byte fixture. A real Token-prefix analysis must render with the same tokenizer, chat template, tools and generation-prompt configuration as the server; otherwise it is only an estimate. String overlap and fixture units cannot establish KV cache reuse.

References (protocol must still be checked against the installed release):
- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/)
- [vLLM metrics design](https://docs.vllm.ai/en/stable/design/metrics/)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/stable/serving/openai_compatible_server/)
