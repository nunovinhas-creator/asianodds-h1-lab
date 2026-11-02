# E5 exclusive Telegram emitter — 2026-11-02

From this change on, the MASTER BRAIN Telegram bot sends **only** E5 alerts
(V5 pattern `P5-8bced1b27e`, Over 2,5 golos). Code: `h1lab/e5_notify.py`.
Receipts: `data/e5-over25-notifications.json` (collector-owned).

## Retired emitters (no new messages; history kept and frozen)

| emitter | module | ledger (frozen, `LEGACY_FROZEN`) |
|---|---|---|
| ≥ 3 distinct Total movements | `h1lab.three_moves_notify` | `data/three-total-moves-notifications.json` |
| ≥ 2 distinct Total rises, no fall | `h1lab.two_up_notify` | `data/two-up-total-notifications.json` |
| E1–E4 (fixed V5 selection) | `h1lab.strategy_notify` | `data/strategy-notifications.json` |
| legacy E4 | `h1lab.e4_notify` | `data/e4-notifications.json` |
| T05 | `h1lab.t05_notify` | `data/t05-notifications.json` |
| Pattern Watch notifier | `h1lab.pattern_notify` | `data/pattern-notifications.json` |
| H1 singles / triples | `h1lab.notify` | (in `data/state.json`) |

* `collect.yml` no longer invokes any of them; only `h1lab.e5_notify` receives `TG_BOT_TOKEN`.
* Their command-line entry points refuse to send (`h1lab/telegram_emitters.py`); only a
  read-only `--dry-run` remains where one existed. CI checks both.
* Every publisher (collector, LAB V4, FT) refuses any change to a frozen ledger.
  Nothing was deleted or reset.

## Rule (strict)

`{"op": "AND_NOT", "all": ["G_NET_IMPLIED_SMALL"], "none": ["G_FIRST_LEAD_LT_6H"]}`

* `net_dlam` is the V5 engine's value (`pattern_features.match_features`), and `abs(net) < 0.10`
  (0.1000 is not eligible). E5 is not E2: single messages may move ≥ 0.05.
* First alert ≥ 6 h before kickoff, proven from the first message's own timestamp
  (`kickoff − first_observed_at ≥ 6 h`; V5's 0.1-minute rounding cannot upgrade 5h59m59s).
* Every Total snapshot is `V4_EXPLICIT` with valid implied lambdas; one legacy-only or
  unparseable Total excludes the fixture. Ambiguous identity, inconsistent kickoff, a
  message after the decision instant or a started game exclude it as well.
* Decision instant = real UTC clock of the run; nothing observed later and no FT result is read.

## Delivery

* All future fixtures, every date, ordered by kickoff; no 12-hour window, no game quota.
  A 14-minute time budget per run only defers the remainder to the next 5-minute cycle.
* One alert per fixture and rule version. A withdrawal (`<match>|WITHDRAWN`) is sent once,
  only before kickoff and only from new valid V4 evidence observed after the alert that
  proves `abs(net) ≥ 0.10`. Missing data never withdraws anything.
* **At-most-once, mandatory**: the collected data is published first; then, before each
  Telegram request, the intent (`send_in_progress`) is published on `main` through the
  collector's selective publisher (`scripts.collect_publish_safe.e5_receipt_publisher`,
  policy `E5_RECEIPTS`). If that publication fails nothing is sent and the job fails.
  An interrupted send becomes `delivery_uncertain_manual_review` and is never resent.
  429/401/403 use the shared pause file. ≥ 3 s between Telegram requests.
* History line: read from the current V5 report (`docs/lab/pattern-research.json`, < 24 h old).
  When E5 is absent from it the message says so; rates are exploratory, never probabilities
  or proven profitability.

## Rollback

Revert the PR. The E5 ledger stays as historical proof (add it to `LEGACY_LEDGERS`).
