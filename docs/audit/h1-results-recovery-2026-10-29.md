# H1 result schedule recovery — 29 October 2026

Baseline: `9be650a0cf6c066a400e79d7d6328f728a03c749`.

## Evidence

The hourly `41 * * * *` schedule did not provide hourly executions. GitHub runs
40836869737 (07:39:47 UTC) and 40893743846 (14:39:54 UTC) both succeeded on
29 October, but were separated by seven hours. The preceding scheduled run,
40799052679, began at 01:13:05 UTC. Collector dispatches continued every five
minutes. A fresh collector dashboard therefore did not prove recent H1 settlement.
The observations establish a scheduling gap, not its underlying GitHub cause.

## Change

The existing collector invokes an independent H1 watchdog only after its push.
It uses the existing Actions token, calls no sports API and dispatches `results.yml`
only when there is no verified completion receipt younger than 90 minutes, no
active/queued result run, and no attempt within 90 minutes. Invalid API history
fails closed. Failure is nonblocking for collection and is visible in the step log.

Results writes `data/health/h1-results.json` after reconciliation, LAB promotion
and rendering succeed. Receipt and results are committed together. The receipt
contains completion time, run ID, actual reconciled source SHA, and hashes of
results.csv and result_audit.json. Missing, future, naive or mismatching receipts
cannot establish freshness. A queued fallback checks again after checkout/rebase
and skips if a cycle completed in the meantime; schedules skip cycles younger
than 45 minutes. Manual and push runs remain explicit reruns.

A receipt means CYCLE_COMPLETED, not all matches settled or all providers healthy.
The fallback still depends on the collector and GitHub dispatch availability;
it does not guarantee execution within 90 minutes. Active stuck runs are reported
rather than cancelled. Existing provider rules, budgets and signal rules remain.

## Verification and release

Offline tests cover cadence, active jobs, malformed history, damaged receipts,
partial outputs, API failures, token/context restrictions and exact dispatch body.
No real workflow was dispatched for testing. Compare committed receipt timestamps
with normal GitHub runs after authorized integration. Require successful ordinary
result cycles, verified publication and observed fallback behaviour before starting
24h/48h/7d observation. No stability claim or observation window starts in this PR.
