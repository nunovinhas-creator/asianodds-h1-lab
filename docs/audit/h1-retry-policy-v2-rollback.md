# H1 retry policy v2 (24 h) - rollback plan

Scope: PR "H1 retry policy v2". Applies after merge. Nothing here is automatic.

## What persists after the merge (why a plain revert is not enough)
* `data/result_audit.json`: fixtures past kickoff+24h and unresolved become
  `status: expired_unverified` (+ `expired_at`, `expiry_reason`, `retry_policy_version: 2`,
  `status_before_expiry`, `checked_before_expiry`). The previous `checked_at`, `reason` and
  `thesportsdb_reason` are kept. These are committed and survive a code revert.
* `data/results.csv`, ROI, FIFO and triples are **not** modified by the policy.

## Invariants of any rollback
1. Never reopen a terminal state automatically. The v2 planner skips every persisted
   `expired_unverified` entry **whatever `H1_RETRY_HORIZON` is**, so lengthening the horizon alone
   neither reopens nor re-queries them (tested).
2. Never touch certified results (`results.csv`), never delete history, never turn pending into LOSS.
3. No duplicate provider queries: expired fixtures stay out of the queue until explicitly reopened.

## Procedure
A. *Stop the effect on new fixtures only* (safe, 1 line): set `H1_RETRY_HORIZON = timedelta(days=30)`
   in `h1lab/results.py` (and nothing else). Already-expired fixtures stay expired (invariant 1).
B. *Reopen specific fixtures* (needs explicit authorization, per key, with a reason):
   `python -m scripts.h1_reopen_expired --key "<match_key>" --reason "<why>"` (dry run), then `--apply`.
   Only `data/result_audit.json` changes; the expiry record is kept in `expired_history`.
   Do A first, otherwise the next sync expires them again (documented, tested).
C. *Full code revert*: `git revert -m 1 <merge sha of the v2 PR>`. WARNING: the pre-v2 planner does
   not know `expired_unverified` and would treat those entries as retryable (checked_at older than 4h).
   Therefore before reverting code, either keep the guard (cherry-pick only the
   `if previous.get("status") == "expired_unverified": continue` lines) or reopen intentionally via B.
D. Verify: `results.csv` blob unchanged; `H1_RETRY_POLICY expired_now` stops growing; no `settled` entry changed.

## Pre-merge reference (drafting time, origin/main fb87a79639b963341bee82b7ce99720122d9658c)
| file | blob |
|---|---|
| data/results.csv | 437b2d0f2f61 |
| data/result_audit.json | 48a3ef4db00d |
| data/state.json | c265c59d9eec |
| docs/data.json | 20542f9f1b5c |
| data/health/h1-results.json | 183dcc0fd8ee |

The authoritative pre-merge SHAs/blobs are also recorded in the #107 comment written at merge time.
