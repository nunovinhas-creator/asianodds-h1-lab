# H1 results publication — `cannot lock ref` (2026-11-02 06:57 UTC)

Run: <https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41403070558>
(run #87 of `results.yml`, `workflow_dispatch` from `h1-results-watchdog`, job 125138940540).

## Diagnosis

| Item | Value |
|---|---|
| Checkout / `H1_SOURCE_SHA` | `fd38613d26f4a771fa02b63f35505fd1e6253ee6` (collector, 06:56:11) |
| Work done | `H1_LAB_BRIDGE imported 0` (rejected: `not_final` 251, `observed_after_24h_window` 3); `H1_RETRY_POLICY expired_now 1`; `H1_RESULTS_PLAN eligible 19, retries_due 19, first_checks_due 0`; `RESULTS_SYNC checked 19, new finals 1, provider errors 1, unresolved 253`; TheSportsDB circuit `http_429`, 8 calls skipped |
| Local commit | `ecbcb0a` — 4 files (`results.csv`, `result_audit.json`, `docs/data.json`, `data/health/h1-results.json`), +59/−49 |
| Final rebase | 06:57:00.12 `Current branch main is up to date` |
| Concurrent writer | `1612e8e` *data(lab): refresh V4 comparison and log checks* (LAB V4 audit, concurrency group `asianodds-lab-v4-audit`, committed 06:56:59) reached GitHub after the fetch |
| Push | 06:57:01 `! [remote rejected] main -> main (cannot lock ref 'refs/heads/main': is at 1612e8e… but expected fd38613…)` — a pure CAS race, ~1.3 s window |
| Published? | **No.** No `reconcile verified H1 finals` commit after `fa20ea0` (05:46:33) on `main` as of 07:16 UTC. |
| Lost (not published) | 1 new certified result (`results.csv` 115→116 in the run), 1 expiry, the 19 `checked_at`/counter updates, the cycle receipt |
| Did another run publish it? | Not as of the audit time (07:16 UTC). The next `results.yml` cron is 07:41 UTC; the watchdog's receipt was also lost, so the next dispatch will repeat the 19 retries (provider calls repeated *because of a Git race*; the 24 h window and the 20-call cap still bound them). |
| Root cause | `results.yml` (group `asianodds-h1-write`) and LAB V4/FT (other groups) all push `main`; `git pull --rebase && git push` has an unbounded race window and no retry. |
| Watchdog | The run is marked failed (exit 1); `h1_results_watchdog` sees no fresh receipt and will dispatch again ≥65 min after the last receipt — recovery by **re-querying**, not by re-publishing. |

`result_audit.json` at `fa20ea0` was not damaged: nothing partial reached the remote.

## Fix: `scripts/h1_publish_safe.py`

Replaces `git pull --rebase && git push` in `results.yml`; reuses the FT
publisher's isolated-index transport helpers and the shared push-outcome
machine (`scripts/git_publish_outcome.py`, PR #202).

* Bounded attempts (6), each re-fetches `main` and re-proves every concurrent path.
* Independent data accepted: `data/lab/**`, `docs/lab/**` (LAB/FT/V4), append-only
  journals, notification receipts, Telegram block/eligibility, collector
  `data/state.json` with unchanged fixture identities (dashboard re-rendered offline).
* Refused: code/config changes, another writer of `results.csv`/`result_audit.json`/receipt,
  fixture identity rewrites, unknown paths.
* Own-change guards: certified rows immutable and unique per key (no
  contradictory results), `expired_unverified`/`settled` never reopened,
  `checked_at`/`expired_at` and counters never go back. Validated on the 65
  real H1 audit/results commits since 2026-10-26: 0 false refusals.
* Transport errors (408/5xx/disconnect) read the remote first; an accepted
  commit is recognised; identical outputs already on `main` → `ALREADY_PUBLISHED_EQUIVALENT`.
* No provider call, no rebase of results, no force push. Receipt
  (`H1_PUBLISH_RECEIPT`) uploaded as artifact `h1-publish-receipt-<run_id>`.

## Tests — `tests/test_h1_publish_safe.py` (bare Git)

LAB commit between rebase and push (the incident) · exact GitHub
`cannot lock ref` text · concurrent FT publication · collector state change +
offline re-render · code change (abort) · identity rewrite (abort) ·
contradictory concurrent H1 writer (abort) · unknown path (abort) · certified
row change (abort pre-push) · duplicate contradictory key · expired reopen ·
counter/timestamp regression · auth refusal (no retry) · 408 after acceptance
(single push) · crash after push + rerun (no push) · realistic concurrency with
LAB V4 + FT writers pushing in a thread (every writer commit preserved, one H1 commit).

## Acceptance criteria

* A `results.yml` run that races LAB/FT logs `H1_PUSH_FAILURE … CAS_REJECTED`
  followed by `H1_PUBLISH_RECEIPT … PUBLISHED`; no failed run for a pure race.
* `provider_requeries` always 0; `results.csv` rows of the base never change.
