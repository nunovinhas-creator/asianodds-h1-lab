# P1 individual baseline and P2 durable capacity trial

Source e31f8f5a, frozen snapshot 2026-10-30 22:41 UTC; 191 overdue in 107 observed competition labels; 101 lack an effective-check record. Complete individual CSV and JSON are attached in this branch. Primary mutually exclusive diagnoses: 101 NO_EFFECTIVE_CHECK_DOCUMENTED; 62 IDENTITY_OR_COVERAGE_UNRESOLVED; 21 OPERATIONAL_ERROR; 7 INSUFFICIENT_OR_CONTRADICTORY_FT. Provider-level causes overlap. Of the 101, 27 have historical adapter invocations; neither these counters nor their absence prove historical HTTP traffic.

Metrics distinguish current certified population, pending/due/effectively examined games, per-provider/competition evidence and baseline-key recovery rates. API audit has 32 retained instrumented runs, documenting API-Football 13, GOAL 7 and OpenFoot 13 request attempts; missing historical BSD/ESPN/etc accounting is unknown, not zero. Shared DATE calls cannot honestly be billed to one competition. New optional fields preserve all eight providers' request-attempt totals and selected/newly-certified/unchecked cohort keys on future normal runs, without changing certification or spending quota. Provider billing is not independently observable.

No pending fixture is proven globally irrecoverable. ESPN unsupported competition is provider-specific. No matching name cannot distinguish lack of coverage from alias/identity gaps. Historical HTTP errors/429s are diagnostics, not proof of a current outage.

## Capacity trial (never loaded by production)

discoveries.json 1,383,395 / 1,400,000; public cache can compact old points while keeping durable history. discovery-state.json 1,449,137 / 2,000,000, margin 550,863 (27.54%). Offline experimental partition: 6 pattern shards <=256,000 bytes (largest 255,999), manifest 159,155 bytes. Reconstruction equals every original field and original input bytes remain unchanged. Missing/corrupt shard or oversized pattern fails closed.

Future migration requires a separately authorized loader/writer version: write and verify every shard, publish manifest last in one guarded Git bundle; keep schema-1 fallback until replay equality and recovery after failed write are demonstrated. Maintain monthly append-only event archives. No live format migration here.

Acceptance: 191 unique diagnostic rows; stable baseline-key deltas, no double-counting new fixtures as recovery; no fictitious per-game HTTP allocation. Existing producer schemas remain compatible through additive audit fields. Normal production recovery remains a separate acceptance gate after authorized merge. No schedules, source validators, H1/Telegram/strategies or main changed.
