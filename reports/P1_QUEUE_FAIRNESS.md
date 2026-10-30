# P1: oldest unexamined fixtures, after cooldown

Baseline e31f8f5a; 191 overdue, 101 without an effective-check record, 246 FINAL.

Reproduction: an older fixture without evidence_checked_at, but with an operational visit older than 4h, loses to a newly overdue fixture without a visit. Regression failed: selected ['new'] instead of ['old']. Cause: queue_visited_at sorted before kickoff even inside first-evidence tier -4.

Fix only tier -4: kickoff then operational visit; other priorities, grace, 4h visit gate, adaptive evidence retries and 30-game ceiling unchanged. On the same real snapshot at 2026-10-30 23:00 UTC, baseline cohort in first 30 slots: 17 before, 30 after. This is improved selection, NOT 13 recovered results or 30 HTTP calls.

Acceptance after authorized merge: normal provider-enabled runs, per-key effective evidence and new FINAL compared with baseline; 246 original FINAL intact. Older eligible cohort must advance without changing cooldowns or permanently dropping later fixtures. No production H1/Telegram, source validators, quotas or schedules changed. No merge performed.
