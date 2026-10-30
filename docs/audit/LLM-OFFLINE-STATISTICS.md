# LLM offline statistics v1 — research-only protocol

Run `python -m scripts.lab_v6_offline_statistics`. No dependencies beyond Python stdlib and existing LAB modules, no network/AI calls. Optional `--now` and `--output` permit deterministic replay without writing production outputs. Inputs are never modified. Scope: archived LLM hypotheses, not active strategies, H1, Telegram or settlement.

## Data and membership

V5 version-1 definitions identify 2–3-code AND combinations. Hash-verified archives are deduplicated by canonical candidate ID; earliest archive timestamp defines registration. Historical current projections are explicitly EXPLORATORY, even when Telegram timestamps precede kickoff. Source conflicts fail closed. Timelines are regenerated using only strictly pre-kickoff messages; one match key is one statistical unit.

Market membership is three-valued. Missing/suspect quotes are unknown, excluded from both group and controls. Both sides must pass existing V6 price/margin rules for market-dependent features. This conservative complete-case policy can lose genuine cases; per-code missingness is published. The baseline uses the last observed Total only, with Q2 validity and existing Poisson de-margining, never a substituted earlier clean quote. Not a tradable O2.5 price.

FT comes from the hash-verified universal event stream reconciled against the authoritative ledger. Only FINAL with specified provider evidence, accepted identity, non-negative integer goals, matching kickoff and verification at least 90 minutes after kickoff enters scoring. Verification must follow feature decision; journal recording must follow verification and precede analysis cutoff. CORE_NAME identity matches are conservatively excluded; ledger-final coverage is therefore higher than statistical coverage. Missing provenance/time, quarantine and identity exclusions are explicit. Extra-time penalties are not reconstructed: the existing ledger's regulation-FT contract remains an upstream dependency.

## Historical exploration

The whole 14,190-space coverage audit counts membership and FT/baseline availability only: it does NOT run or rank 14,190 outcome tests. Examples are hash-ordered. Only archived proposals receive analyses.

Show full observed group, known-negative controls, 95% Wilson intervals and descriptive Fisher/BH values (BH family = archived hypotheses only, not a confirmatory correction for adaptive selection). Match controls 1:1 without replacement by p±0.05, same first-lead bin and kickoff within 7 days. Matching never reads FT; paired complete-case counts and unmatched attrition are explicit. Competition is not controlled: a permanent blocker to confirmatory inference in v1.

Split completed fixture calendar days chronologically at 70%; same-day rows never straddle train/test. Training requires FT to have been recorded BEFORE the earliest test decision AND proposal registration. Fit a shrunken probability residual `sum(y-p)/(n+20)` only with ≥20 eligible training games. Clip probabilities to [1e-6,1-1e-6]. Baseline and model Brier/Log Loss use the same evaluable games; no hypothesis text is converted into an invented forecast. Without a fit, model metrics stay null.

A two-sided sign randomization on DAY-cluster sums of paired log-loss improvement requires ≥30 evaluable test games and ≥5 days. Exact enumeration up to 16 days, otherwise 9,999 fixed-seed sign flips with plus-one correction. Assumes symmetric independent day clusters; team/league dependence can violate this. Multiply p by the entire fixed 14,190 search space (Bonferroni). Even an exploratory positive needs ≥30 completed matched pairs to be flagged for prospective validation; a negative may be labelled exploratory rejection. Neither state means proven. Repeated looks/adaptive LLM proposals preclude confirmatory claims, and the report never emits scientific approval.

## Prospective independent monitoring

For each hypothesis/match, select the FIRST forecast journal capture after registration, regardless of outcome. Require all referenced V4 versions known by that capture, and no referenced original observation or first recorded V4 version predating the hypothesis. Rebuild only these immutable snapshots; never use current odds to backfill frozen features. Missing V2 source IDs or version evidence is counted and excluded. Scoring can reuse only the historical train offset, never fit on prospective outcomes.

This is operational forward monitoring, not human preregistration of a confirmatory experiment. A frozen protocol with fixed checkpoints, target power, competition controls, alpha allocation and independent OOS games is still required before claiming discovery. No small-sample automatic validation or strategy promotion.

## Outputs and automation

`docs/lab/llm-statistics.json` includes hashes, counts, cases, controls, temporal split keys, missing inputs and verdicts. Separate workflow runs four times/day, with zero IA/API calls. PR runs only produce artifacts. Main runs publish just research report + immutable per-run history, rejecting a concurrent main change rather than rebasing stale evidence. Latest report includes generation time; clients warn when stale or missing. Independent of all betting workflows.

Synthetic tests exercise missing-as-unknown, post-KO exclusion, FT chronology/quarantine, outcome-blind matching, train/result leakage, day clustering and no fitting on OOS. CI additionally replays REAL inputs twice, verifies deterministic equality and unchanged source files. These are different evidence classes.

## Corrected real snapshot: 2026-10-30 12:00 UTC

605 timelines; 597 usable; 8 without pre-KO observations. **131 accepted FT, 98 clean baselines, 34 provisional FT excluded from all scoring**, 45 identity exclusions. Catalogue: 10,185 combinations with matches, 5,710 with accepted FT, **48 with at least 30 accepted FT and baseline**. Coverage is not discovery.

**T05 is NAO_TESTAVEL in this snapshot:** 3 cases, zero accepted FT. Two scores previously counted are now provisional; the third is pending. Brier, Log Loss and hit-rate interval are null. There is no available training sample or scientific conclusion. Five later captures are excluded because the matches were already observed before registration.

Explicit TWO_PROVIDER_FT_CHRONOLOGY_NOT_CERTIFIED evidence remains visible as provisional scores but cannot enter training, scoring, controls or catalogue FT counts. Other accepted levels indicate policy acceptance, not independent certification. Original result journals remain unchanged.

Historical pre-correction values (165 FT / 126 baselines / 121 combinations, and T05 2 FT) are obsolete and must not be used. Git history preserves the earlier assessment.

The sole automatic trigger is four daily cron slots; manual dispatch remains available under the shared concurrency group. Publication rejects concurrent main changes rather than overwriting data. A failed publication is not a guarantee of a successful subsequent run.
