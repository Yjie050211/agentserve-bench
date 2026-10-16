# ADR 001: Frozen replay and explicit evidence

Status: accepted for the CPU framework, 2026-10-16.

Use independent Python 3.11 repositories joined by a versioned file contract. Keep Agent execution in Harness and service workload replay here. A fixed request sequence controls experimental inputs; it cannot measure live Agent task success.

Use one selected successful source attempt per call while preserving all attempts and exclusion reasons. During a new replay never hide failures or retry for cosmetic results. Stop failed sessions, record their unissued tails, and allow independent sessions to continue.

Preserve actual request bytes separately from canonical hashes. Derived stream/model changes are explicit. Fixture encoding tests the algorithm only. Cache reset and GPU claims require evidence beyond a successful transport call.

Tradeoffs: duplicated minimal transport code in Nano and AgentServe requires shared golden semantic tests; strict cold-cache verification delays the full matrix until actual engine calibration. These costs keep project boundaries and interpretations clear.
