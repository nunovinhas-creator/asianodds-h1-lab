# P1 old-cohort recovery: functional correction, not a productive result

Frozen baseline: publication 893d58c2602833bb0557fab7ea00e04122fc1457, 281 FINAL. reports/ft-old-cohort-180.json freezes the 180 remaining match_keys from the original 191 cohort. scripts.lab_old_cohort_audit reports every fixture/provider from persisted data, without HTTP, guessed scores or automatic approvals. The compressed individual report is reproducible JSON, not a new production input.

At observed snapshot 09b5ba1682df688258b383c1f5488e7232a2111a, production has 286 FINAL, all 281 baseline scores/statuses unchanged. One of the frozen 180 recovered normally: 2026-10-28,84620,10030071, NK Sobec Lesce–NK Skofja Loka 0-1, API-Football fixture 1589852, normal watchdog run 41201471771. This predates this PR; no benefit is attributed to unmerged code. Remaining cohort 179; 55 lack effective-check records, down from 56. Global overdue 232 and undocumented checks 101 have risen due to new eligible fixtures. Total FINAL alone is not the recovery KPI.

Individual primary obstacles across the frozen 180: 100 unresolved identity/current FT; 40 missing effective-check records without a strict locator; 18 strict API locators awaiting a valid current response; 16 no coverage demonstrated; 5 insufficient/contradictory FT evidence; 1 certified. Categories overlap underlying facts: 55 total lack effective-check documentation. Zero games are declared irrecoverable and zero proven cross-provider competition bindings exist. Fuzzy STRONG candidate labels are not identities. Fixture-level HTTP cannot be reconstructed from run totals.

## Reproduction and root cause

FC Noah–Syunik (2026-10-29,10016347,10050382) has GOAL locator 858889, exact pair under the pre-existing EXACT normalizer, same order/kickoff, one candidate and no duplicates. It has no prior effective FT check. Existing plan_goal_id requires a prior substantive GOAL FT failure AND checked_at, so it returns no target even after cooldowns. A queue selected by general priority before examining IDs can also consume all 30 places while an eligible old ID remains outside; a 35-fixture deterministic regression reproduces this. It is a scheduling/locator omission, not permission to weaken FT evidence.

## Functional change

Prepare old (>=24h) exact GOAL locators before queue selection, excluding collision/reversed/conflict evidence, claimed IDs, source mismatches, stale candidates, duplicate observed identities, holds/approved mappings and every existing game/24h ID cooldown. Reserve at most ONE existing queue place for a usable old API/GOAL locator, keeping explicit reviewed/quarantine work protected and the remaining 29 general places. No extra game checks, API requests, provider budget, daily limit or cooldown bypass. The preview and actual selection use the same recovery key and are asserted equal by the existing collector guard.

GOAL locator responses must preserve the raw provider names, fixture ID, source competition label and exact kickoff captured in that locator; changes fail closed. The current normal choose/verify path still requires valid regulation FT. No aliases/CORE expansion or inferred competition binding; #159 SportScore CORE remains blocked. Locators contain no scores. Current fixture evidence is mandatory. Existing ID access restrictions are not treated as no coverage.

## Acceptance and risks

Offline tests reproduce omission, fair bounded selection, current valid FT, invalid scores/status, changed competition/team/age/gender/reserve/time/ID, duplicate/colliding IDs and cooldowns, cache reuse/accounting, and no more than two GOAL requests. Full suite runs with socket/DNS forbidden. CI and compatibility with current main must pass before merge; no merge is authorized yet.

Operational acceptance after authorized integration: normal schedule/watchdog only, show selected old turn, actual HTTP/ID outcomes and match_key delta for the frozen cohort. Expected benefit is opportunity to query, NOT guaranteed FT: suppliers may deny historical access or lack regulation scores. Cap reservation at one so uncertain ID paths cannot monopolize general checks. If the same provider changes identity or returns ambiguous evidence, retain PENDING. No productive recovery from this PR is claimed before integration.

TSDB operational observations: natural 429s persist Retry-After=120s deadlines. Normal runs are farther apart than the deadline, so an early cross-run skip has not yet occurred naturally; offline tests prove that boundary. Do not provoke 429 or extend a deadline artificially. Last three normal runs at 11:51/12:31/13:11 used API-Football 4 HTTP, BSD 3, ESPN 6, SportScore 78, TSDB 33, OpenFoot 1, GOAL/FotMob 0. Exact per-run records are retained in the provider audit, rather than inventing per-fixture HTTP.
