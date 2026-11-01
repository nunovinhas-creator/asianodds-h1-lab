# Telegram durable mode - acceptance report (offline evidence) and trade-off

Status: **evidence from offline tests only**. `TG_DURABLE_INTENT` is `0`; nothing here is a production result.
Activation needs a new authorization. Neither mode is exactly-once.

## Acceptance matrix (all with real local git remotes: bare repo + independent clones)
| # | requirement | test (tests/test_telegram_delivery.py) | result |
|---|---|---|---|
| 1 | intent published before the HTTP call | `DurableIntentTests.test_crash_after_acceptance_...` (remote shows `send_in_progress` before/after the crash) | pass |
| 2 | durable state recognised in an independent checkout | same, fresh clone reads `send_in_progress`/`sent` | pass |
| 3 | two concurrent workers, no duplicate send | `test_two_concurrent_runs_cannot_both_send_the_same_alert` (claim guard; 1 send, other `intent_not_durable`) | pass |
| 4 | git failure prevents the send | `test_unpublishable_intent_fails_closed_and_nothing_is_sent` | pass |
| 5 | receipt sent and published | `test_confirmed_receipt_is_published_right_after_the_send...` | pass |
| 6 | crash after Telegram accepted | `test_crash_during_send_never_duplicates`, `..._in_a_fresh_checkout` | pass |
| 7 | recovery without a resend | `send_in_progress` -> `delivery_uncertain_manual_review`, 0 sends | pass |
| 8 | eligibility filters untouched | no change to `candidates()`/rules; `telegram_eligibility` parity check unchanged | pass |
| 9 | negligible extra cost | see below | by arithmetic, not yet measured |
| 10 | safe rollback | variable back to `0`; ledger format unchanged; `test_rollback_to_default_mode_changes_nothing...` | pass |
Also: dirty collector tree + remote race (`rebase --autostash`), intent survives the job's final `pull --rebase`,
post-outcome publication failure is reported (`TELEGRAM_PUBLISH_FAILED`) and the outcome is kept, shared 429 pause
published and seen by a fresh checkout, a pause is never shortened.

## Quantitative trade-off (observed inputs: ledgers, `git log`)
* Observed alert volume: **13 alerts** (all `sent`) between 2026-10-31 19:12 and 2026-11-01 20:06 UTC (~1.04 days).
* Observed `main` activity: **150 commits on 2026-11-01 UTC up to 23:00** (62 of them `collect and notify`), i.e. ~150/day.
* Durable cost: 2 small data-only commits per alert => ~26 extra commits/day at the observed rate = **~17 %** of the
  existing commit count (mostly 1-file ledger updates) + 1 `git fetch` per alert; no extra workflow minutes worth noting
  (a few seconds per alert), no new service.
* Normal mode (default): a duplicate needs *Telegram accepts -> job dies -> receipt not committed*. The exposed
  window is the time between the notify step and the "Store data" commit (seconds per job). Expected duplicates =
  alerts/day x P(job dies inside that window). With ~13 alerts/day and a window of seconds the expectation is far below
  one per month under normal runner reliability, but it is **not zero and not measured**; the consequence is one
  repeated message.
* Durable mode: that duplicate is removed, but a crash between the Telegram accept and the outcome push (seconds)
  leaves `send_in_progress` -> `delivery_uncertain_manual_review` (message possibly delivered, alert state needs a
  look) and a crash *before* the HTTP call after the intent push **loses** the alert (flagged uncertain). So
  durable converts "rare duplicate" into "rare lost-or-uncertain alert + 2 extra commits/alert".
* Neither mode guarantees exactly-once: the Bot API has no idempotency key.

## Recommendation (after >= 24 h of normal operation, to be filled with observations)
Keep `TG_DURABLE_INTENT=0` until: (a) #197 and this PR have run >= 24 h without `block_unreadable`,
`publish_failed` or unexpected `rejected` counters; (b) the real window between notify and Store is measured from
run logs; (c) the owner prefers rare lost alerts over rare duplicates. If a duplicate is judged worse than a missed
alert, enable it first for one day with `TG_DURABLE_INTENT=1`, watching `intent_not_durable`/`publish_failed`.
