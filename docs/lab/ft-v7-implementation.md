# MASTER BRAIN V7 — FT evidence retry (2026-10-28)

## Scope delivered (first safe intervention)

- Push events **never** reconcile FT provider calls or advance retry. They may refresh the observed catalogue.
- A real FT scan uses the already persisted `ft-provider-day-rotation.json` limits, not an even-hour gate.
- Each unresolved match stores score-free `examined_against` per provider (day, SHA-256 fingerprint, nearby fixture count, observed time and completeness), `evidence_attempts`, `evidence_checked_at`, and `queue_visited_at`.
- Matching attempts only advance for changed, complete authenticated day-list evidence or a verified result. A repeated snapshot does not advance cooldown.
- Fair queue visits with no fresh evidence have a 45-minute revisit gate independent of the 4/12/24-hour evidence backoff.
- Previous `provider_reasons` are preserved when a provider is disabled, deferred or unavailable.
- Watchdog filters GitHub push-triggered FT runs; the scheduled/manual runs remain eligible to suppress duplicate dispatch.
- API-Football 90 requests/day and local GOAL 80/day ceilings are checked against persisted per-day usage; GOAL truncation at 500 rows without pagination fails closed.
- No H1 / Telegram / triplas FIFO / V6 forecast logic is edited. This PR does not consume result API quota.

## Gaps explicitly **not yet completed**

- Provider-specific `fixture?ids=` batch reconciliation and a reviewed ID crosswalk from AsianOdds team IDs are still P1. Do not promote fuzzy candidates to automatic settlement.
- Existing human review queue persists candidates across runs, but a full historical replay of past provider list content is not available; the new hash only records **future** successful reads.
- Existing legacy attempts/checked_at are preserved for audit, not retroactively interpreted as validated evidence. New evidence counters begin at zero on first V7 scan.
- The day fingerprint intentionally ignores scores, so it is not a cryptographic proof of score correctness. Existing FT validation and corroboration rules apply.
- No provisional duplicate or COVERAGE_ABSENT automatic classification: both require reviewed identities and coverage evidence.
- BSD cup regulation-time semantics and GOAL provider quotas need independent documentation.

## Acceptance

Run `python -m compileall -q h1lab scripts` and `python -m unittest discover -s tests -v`. Confirm live authentic runs via `data/lab/ft-api-audit.json`: `authenticated_providers_ran`, requests by provider and `effective_evidence_checks`. Check no push increases `evidence_attempts`. No FT result should be claimed recovered until ledger and review queues show verified sources.
