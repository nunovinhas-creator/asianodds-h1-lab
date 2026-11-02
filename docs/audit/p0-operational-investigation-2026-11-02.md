# P0 operational investigation — 2026-11-02 (#107 DEGRADED, #63 INCONCLUSIVO)

Scope: real operational failures only. No validator was relaxed and no strategy, quota, provider,
certified history, cooldown or security rule was changed. No Telegram message was sent.

## Certified baseline (checked before any change)

`origin/main` @ `3c34257`: `data/results.csv` = **119 H1 rows, all `final`**;
`docs/lab/ft-results.json` `final_recorded` = **455 FT**. The only code change in this branch
(below) does not touch result, certification or publication code.

## Priority 1 — publishers

| Incident | Verdict | Root cause | Recovery |
|---|---|---|---|
| FT run 41502044305 — `H1 notification receipt invalid: data/e5-over25-notifications.json` | **Correct fail-closed refusal, one-off, not reproducible today** | FT checkout `0b4a959` (merge of #209) had **no** E5 ledger; 24 s later commit `2371cc5f` *created* it (first E5 receipt ever). `valid_notification_update(None, …)` refuses by design (“retained receipts only”). Reproduced locally: `False` for base `0b4a959` vs remote `2371cc5f`/`523e565b`. | Automatic: next FT run 41504475993 (18:51) published (`0503c36`); 41510694293 also green. All 7 receipt ledgers now exist on `main`, so this path cannot recur unless a new ledger is introduced. |
| LAB V4 run 41507672240 — `Incompatible program change: h1lab/e5_notify.py` | **Correct refusal** | The audit was computed on `92cf013`; PR #211 (`f33a779`, 19:12:20) changed `h1lab/e5_notify.py` + tests during the run. Publishing results computed with the old program would be wrong. | Automatic: `56fd2c2` (19:14:11) published the next V4 refresh. |
| Collector run 41479757276 — HTTP 500 on push | **Real transient provider failure; fix already on `main`** | `! [remote rejected] … (Internal Server Error)` was classified `UNKNOWN` → no retry. Fix `45497967` (16:39:55, after the 16:16 incident) classifies it `UNCERTAIN` → read remote, bounded retry; regression test `tests/test_lab_ft_publish_408.py`. Verified: the exact stderr from the run now yields `UNCERTAIN`. | Automatic: the unpublished observations (Telegram ids 52429/52430, `alerts_added: 2`) were re-ingested by the next collect run (16:21, `a45e6623`); both ids are in `data/state.json` now. No Telegram resend (`telegram_requests: 0`). |

No code change is justified for Priority 1.

## Priority 2 — the 9 “possible false negatives”

`docs/lab/telegram-eligibility.json` evaluates the **retired** rules
`THREE_V4_INDEPENDENT_TOTAL_MOVES_20261031` and `TWO_DISTINCT_V4_TOTAL_UP_NO_REVERSAL_20261031`.
Since #209, `.github/workflows/collect.yml` invokes only `h1lab.e5_notify` (E5 Over 2,5,
`E5_P5-8bced1b27e_OVER_2_5_V1_20261102`). The 9 flags therefore cannot be false negatives of
the active emitter. Each game was re-evaluated with the active E5 rule at the report instant
(2026-11-02T19:51:51Z, `e5_notify.load_rows`, read-only, no sender):

| Game | Kickoff (UTC) | E5 at report time | E5 receipt |
|---|---|---|---|
| AD Unión Magdalena vs Envigado FC | 11-02 23:10 | ELIGIBLE (net +0.0432, lead 31 h) | **sent** |
| Worthing FC vs Fulham FC U21 | 11-03 19:45 | ELIGIBLE (+0.0454) | **sent** |
| FC København vs FC Iberia 1999 | 11-05 20:00 | ELIGIBLE (−0.0602) | **sent** |
| Oxford City FC vs Leicester City | 11-06 19:45 | ELIGIBLE (+0.0638) | **sent** |
| Yunnan Yukun vs Wuhan Three Towns | 11-08 07:30 | ELIGIBLE (+0.0742) | **sent** |
| Akademisk Boldklub vs Vendsyssel FF | 11-06 18:00 | NOT_E5: net +0.7781 ≥ 0.10 | none (correct) |
| Olympiakos vs PAOK | 11-08 19:00 | NOT_E5: net +0.191 ≥ 0.10 | none (correct) |
| FK Jablonec vs FK Mladá Boleslav | 11-08 14:00 | NOT_E5: net +0.257 ≥ 0.10 | none (correct) |
| Mainz 05 vs Bayern München | 11-07 10:00 | EXCLUDED: first Total snapshot is `H1_LEGACY_ONLY` (rule 3: every Total must be `V4_EXPLICIT`) | none (correct) |

Result: **0 real false negatives** (5 alerted, 4 correctly excluded). Deduplication: the E5
ledger holds 64 entries, all `sent`, one rule version, one `|WITHDRAWN`, no duplicate
fixture key and no duplicate Telegram message id. The only E5-eligible fixture without a
receipt (Heracles Almelo vs Roda JC, 11-06 19:00) is outside the 12 h alert window and is
correctly deferred. No code defect; the stale report is a diagnostic gap (residual risk 2).

## Priority 3 — the 48 “past_due_never_checked” FT games

All 48 *were* consulted: every one has a recorded queue visit, and SportScore answered for
48/48 (`sportscore_no_exact_match` ×43, `source_home_away_conflict` ×5). They are “never
checked” only in the scientific sense: `evidence_checked_at` is set only by a verified result
or a complete GOAL/OpenFoot/API-Football list snapshot, never by an absent answer. That is the
intended rule and is kept. Obstacles at the last visit: ESPN unsupported competition ×45,
GOAL/OpenFoot date rotation in 4 h cooldown ×44, BSD date cooldown ×38, TSDB 429 cooldown ×33,
API-Football account suspension (deferred until 22:51 UTC). Queue capacity is not binding
(17 eligible, 17 selected, 0 deferred by capacity; limit 30 FT).

**Defect found (observability, now fixed):** GOAL and OpenFoot returned `UNAVAILABLE` for
*every* request of Saturday 10-31 and Sunday 11-01 (GOAL 6+7, OpenFoot 8+7 requests) and
`COMPLETE` for every weekday. Both adapters read a single page (GOAL `limit=500`, OpenFoot
`limit=100`; the documented weekday OpenFoot list had 63 rows) and correctly refuse a list
with more pages — but the refusal was swallowed as `*_unavailable`, identical to a network
error, so each 4 h retry spent quota with no way to tell the cause. 25 of the 48 games are
11-01 games. The fix records a fixed category per refused day in
`goal_search.date_errors` / `openfoot_search.date_errors`
(`MORE_PAGES`, `COUNT_MISMATCH`, `UNAUTHENTICATED`, `INVALID_PAYLOAD`,
`TRANSPORT_HTTP_OR_UNPARSEABLE`). Behaviour, requests, refusals, quotas and cooldowns are
unchanged. Regression test: `tests/test_lab_ft_day_list_errors.py` (fails on old code).

The pagination hypothesis could not be confirmed against the live APIs from this environment
(outbound access to the providers is blocked here). The next FT run touching a weekend date will
show the category; only then should bounded paging (each page counted against the *existing*
GOAL 80/day and OpenFoot 4500/month ceilings) be proposed — as a separate PR.

## Residual risks

1. Weekend GOAL/OpenFoot coverage stays at zero until paging is proven and approved.
2. `telegram-eligibility.json` still audits retired rules; it should be re-targeted to E5
   (needs a coordinated change to its schema validator in `lab_ft_publish_safe.py`, so it is
   not done here).
3. A future *new* receipt ledger will trigger the same one-off FT refusal as incident 1 unless
   it is created before a FT checkout; this is safe (fail-closed) and self-recovers.
4. #107 stays open and DEGRADED; #63 stays INCONCLUSIVO. The 24 h / 48 h / 7-day stability audits
   are untouched.
