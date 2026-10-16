# Metric definitions

All client timings use a monotonic clock and milliseconds. Raw events retain receive times relative to request send. HTTP first byte, role metadata, tool ID/name and usage are not text tokens.

- `text_ttft_ms`: send to the first non-empty text content delta. Null for tool-only or non-streaming output.
- `tool_arguments_ttft_ms`: send to the first non-empty tool-argument delta, separate from text.
- `first_reasoning_delta_at`: separately observed reasoning content, never ordinary text.
- `text_tpot_proxy_ms`: `(last_text - first_text) / (completion_tokens - 1)` only for a complete pure-text stream, reliable integer Token counts >1 and an explicitly zero reasoning-token count. Missing reasoning details leave count scope unknown and the proxy null. SSE chunk count is never a Token count.
- `e2e_ms`: send through protocol terminal observation, including stream drain as observed by the client. A non-streaming response has only e2e, not invented TTFT.
- `failure_rate`: failed, timeout and cancelled sent calls / all sent calls. Not-sent session tails are separately counted.
- `successful_requests_per_s`: successful requests divided by the full observed window from first send to last terminal, only for real execution. Fixture output leaves it null.

Partial outputs stay in raw/typed events and do not receive a successful TPOT. Success latency summaries and failure fractions remain separate. The first CPU baseline reports mean TTFT and sample count, not small-sample p99 stability claims.

Cache hit rate is a distinct server metric: verified exclusive-window delta hits / delta queries, with verified Token units. Missing counters, zero denominators, rollback, NaN/Infinity or an unverified drain/isolation condition produce N/A. Aggregated service counters are not request-level hit rates. The helper requires explicit unit and isolation assertions and is not automatically used to certify a replay.

`execution_mode=fixture|real` describes where observations came from; `workload_origin=synthetic|harness_export` describes request origin. Synthetic requests sent to a real server are a real service experiment but not evidence about a natural Agent workload distribution. Every currently produced report sets `cache_comparison_eligible=false` and `real_gpu_validated=false`.
