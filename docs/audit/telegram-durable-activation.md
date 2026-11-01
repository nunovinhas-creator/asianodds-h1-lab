# Telegram durable delivery - activation, limits and rollback

Status: code merged OFF by default. Nothing below is active until the repository variable
`TG_DURABLE_INTENT` is set to `1`. Requires the Telegram delivery PR (#197) to be merged first.

## What changes (this PR, `collect.yml` only + one `.gitignore` line)
1. `data/telegram-delivery-block.json` is committed by the existing "Store data for dashboard" step, so a
   429 `retry_after` or a 401/403 pause survives between jobs. Without this, the pause only lasts for the
   current job.
2. The two notify steps receive `TG_DURABLE_INTENT` and `TG_IGNORE_AUTH_BLOCK` from repository variables
   (default `0`). Cron, concurrency group (`asianodds-h1-write`), permissions and every other step are unchanged.

## Guarantees
| mode | across jobs | cost |
|---|---|---|
| default (`0`) | **at-least-once**: a job that dies after Telegram accepts and before the final commit can resend | none |
| durable (`1`) | **at-most-once**: intent is pushed BEFORE the HTTP call (fail closed if the push fails), outcome right after; a crash can lose an alert (flagged `delivery_uncertain_manual_review`) but cannot duplicate it; two concurrent runs cannot both send the same alert (claim check on the remote ledger) | 2 small data-only commits per sent alert (≈6-7 alerts per 5 days) + 1 fetch per alert |
Exactly-once is NOT claimable: the Bot API has no idempotency key. Trade-off: durable mode prefers losing an
alert (visible for review) to sending a duplicate.

## Residual risks
* A crash between Telegram accepting and the outcome push (seconds) leaves `send_in_progress` -> reconciled to
  `delivery_uncertain_manual_review` by the next job (no resend, alert possibly delivered once).
* Publication of the outcome can fail (`TELEGRAM_PUBLISH_FAILED` on stderr, counter `publish_failed`); the job's
  final commit step still stores the outcome.
* `git push` of the intent competes with other `main` writers only through the shared concurrency group; a rejected
  push is retried with `fetch` + `rebase --autostash` (max 3) and the claim check.
* Not exercised in production yet.

## Activation plan (needs explicit authorization)
1. Merge #197, then this PR (variable still unset => behaviour unchanged).
2. Dry observation: confirm `MASTER_BRAIN_*_NOTIFY` stats lines and that the Store step still commits.
3. Set repository variable `TG_DURABLE_INTENT=1` (Settings -> Variables). Watch the next alert: expect commits
   `data: telegram delivery state [skip ci]` (intent, then outcome) and no failed run.
4. After a 429/401: expect `data/telegram-delivery-block.json` committed with `until`; after credentials are
   fixed set `TG_IGNORE_AUTH_BLOCK=1` for one run (lifts only a 401/403 pause, never a 429).

## Rollback
Set `TG_DURABLE_INTENT` back to `0` (or delete the variable): takes effect on the next run; ledgers keep their
format. Any `send_in_progress` left behind is converted to `delivery_uncertain_manual_review` on the next run
(never resent). To drop a stale pause: delete `data/telegram-delivery-block.json` in a normal commit.
