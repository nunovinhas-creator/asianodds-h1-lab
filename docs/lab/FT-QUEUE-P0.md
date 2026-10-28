# MASTER BRAIN — P0: FT queue fairness and bounded recovery (28 October 2026)

## Verified baseline

At 2026-10-28T20:04:53Z: 367 observed fixtures, 113 FINAL, 254 without FT
(125 FUTURE, 61 in KO+3h grace, 68 overdue). Exactly one overdue
fixture had zero checks:

- `2026-10-28,72758,29209`, Spartak Myjava Women – Hammarby IF DFF Women,
  KO 17:00Z. At 20:04:53Z it met KO+3h but was deferred.
- The real push run [40760023987](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/40760023987)
  processed 30 matches, with no additional FT; it invoked TheSportsDB
  30 times, while GOAL, OpenFoot and API-Football were disabled on this push.
  `pending_due_checks=1` after the 30-game cap. The legacy priority ordering
  sorts reviewed/forced/alias candidates ahead of ordinary first checks.
  Research hints reorder candidates within priority tiers.
  This proves a capacity-selection omission, not an absent credential.
- Eight 27 October fixtures remain pending (11–12 attempts each), with last
  checks at 17:33:10Z. Their latest diagnostics: BSD no exact archive match,
  ESPN unsupported competition, GOAL/OpenFoot/API-Football no core identity
  match, SportScore no exact match or insufficient 90-minute evidence,
  and TheSportsDB suppressed after 429 on the final observed attempt.
- In particular `2026-10-27,10017282,84806` and
  `2026-10-27,25158,84806` share an away team and kickoff but have DIFFERENT
  home-team identities. These are two observations, not two automatically
  interchangeable matches. No FT may be transferred between them.
- The MK Dons Reserves and Mersin entries have regulation-time uncertainty:
  a cup score after extra time or penalties is NOT proof of 90-minute FT.

## Changes in this PR

1. First consultations are selected ahead of ordinary repeated checks.
   The deliberately authorized one-shot emergency recovery retains its
   established forced-backlog priority. Ordinary scheduled and push cycles
   can no longer starve the first eligible game behind repeated checks.
   Remaining capacity and skipped keys are published in `ft_queue`.
2. Four-hour retry for attempts 1–5; 12 hours for attempts 6–9; 24 hours
   for 10+. New verified supplier/version, pre-reviewed identity evidence
   and explicit recovery runs retain their existing override rules. Existing
   FINAL results, 90-minute safety rules and the 30-day provider horizon
   are unchanged. This is a bounded backoff, NOT abandonment.
3. `lookup_source_version` can only increase. Running an ordinary
   no-GOAL push after a credentialed scheduled run no longer downgrades the
   recorded provider coverage.
4. Per-provider `provider_attempts` records total adapter invocations,
   first and last UTC timestamps, last reason and confirmed-return count.
   IMPORTANT: cache hits and unsupported competition returns are included.
   Old historical attempts cannot be reconstructed from the prior ledger:
   counters begin with this deployment; do not infer zero historical calls.
5. Each overdue match now exposes queue state, elapsed overdue hours,
   ordinary next-eligible UTC date, latest provider errors and historical
   adapter counters. The public dashboard is `docs/ft-recovery.html`.
6. Each scheduled/authorized audit stores queue fairness and new FT metrics
   in the existing bounded `ft-api-audit.json` journal (32 runs). No new
   external API polling jobs, Actions schedules or paid sources.

## Existing constraints / deliberate non-goals

- No H1, Telegram, triples FIFO, V6 prospective predictions, or journal
  rewriting. No pending match becomes a defeat or a fictional 0–0.
- Current provider date adapters cache per run; GOAL/OpenFoot retain
  two dates/run and API-Football three on authorized windows. Because the
  adapters load dates on demand, old games can still consume early date slots
  and newer fixtures can receive `budget_deferred`. This PR improves
  game-level fairness, not yet optimal inter-day allocation. Investigate
  provider-by-day round-robin separately with a quota ledger.
- `ft_queue.never_checked_deferred=0` in an ordinary cycle with <=30 first
  checks is an expected invariant; with >30 first checks, oldest first
  will be selected up to the cap, remainder will persist.
- `next_eligible_at` means the earliest ordinary backoff time. Verified
  new identity evidence or an upgraded source version can justify an earlier
  attempt. It is not a promise of a completed network request at that time.
- Verified identity IDs, KO, league/team lineage and 90-minute match type
  still need a reviewed crosswalk with explicit provenance. Fuzzy cache
  candidates remain review-only. No unreviewed alias is automatically
  promoted to FT.

## Acceptance and validation

Run in CI:

```bash
python -m unittest discover -s tests -p 'test_lab_results.py' -v
python -m unittest discover -s tests -p 'test_lab_ft_fair_queue.py' -v
python -m unittest discover -s tests -p 'test_lab_ft_recovery.py' -v
python -m unittest discover -s tests -p 'test_lab_identity_review.py' -v
```

The FT workflow checks capacity `selected <= 30`, queue arithmetic
`selected + deferred = eligible`, published schema and provider limits.
After merge, confirm a real *scheduled* FT run (not merely a push), its
`ft_queue`, provider call totals, the first-consultation key and the new
dashboard publication. Compare 68 overdue / 1 never / 113 FINAL baseline
against a timestamped run; explain changes in the universe. Do NOT claim
real-world success from synthetic tests or because the PR is merged.

## Next structural investigation

Add an evidence-backed identity crosswalk (provider event ID + teams +
competition + kickoff tolerance + 90-minute protocol), date rotation for
GOAL/OpenFoot/API-Football, and historical provider retrieval for fixtures
no longer returned by recent-day endpoints. Each requires source-specific
capability and free-tier quota checks before enabling any additional calls.
