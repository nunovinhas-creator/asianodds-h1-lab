# B1 — independent Work audit handoff (Draft, no merge)

Issue #258. Base: `b284a9909` (main at checkout). A1 is already merged;
this branch contains only B1. No operational integration or scheduled-cycle change.

## Contract and design

`h1lab/research_quality.py` is a pure diagnostic evaluator after DSL validation.
`STRUCTURALLY_VALID` does not imply `SCIENTIFICALLY_TESTABLE`; the latter means
only that an exploratory comparison can be attempted, never scientific validation.
Rejected reasons take precedence over insufficient-data reasons, all retained.
Malformed inputs fail closed. Reports contain stable code reasons and metrics,
never model narrative. No quality result is appended to existing memory.

A priori candidate design floors: probabilities .05 in fraction units (5 percentage
points), implied goals .10, Total and AH .25 in their own line units. These are
unvalidated design choices, not fitted thresholds or demonstrated effects. A signed
bound must exclude the dead zone. Arbitrary transformed movement expressions are
blocked pending review; combining different movement units is rejected. Indicator
aliases are inlined. Contextual booleans remain eligible without numeric constants.
No automatic threshold rewriting or outcome-based tuning occurs.

Separate metadata contains pregame variables, source IDs, decision/kickoff times,
per-feature observation times and freeze time, plus *availability flags* for FT
provenance and baseline. It must be supplied by a trusted source adapter; arbitrary
caller assertions are not cryptographic proof. The evaluator refuses outcome-bearing
rows and does not inspect targets, scores, profits, rates or p-values. Availability
is counted after assignment and never used for membership or ranking. Duplicate
match keys fail closed. `MIN_N=15` and chronological day split share the executor's
existing constants; both train and test require at least five eligible matches in
each arm. No executor or scientific-gate rule is replaced or relaxed.

Confounders are checked for structural data availability, not causal identification;
alternative-explanation text is explicitly unverified. Unavailable narrative concepts
use a conservative denylist, not semantic comprehension. Complex materiality and
unproven provenance defer rather than fabricate evidence. Near duplicates use the
same outcome and variable set, a diagnostic heuristic, not proof of equivalence.
These limits require independent review before broader use.

## Exact replay and before/after

Original run: https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42202804803

Run source: `ede8b771cc20a9236a0163df47ce2f6e7e915b25`.
Original output commit: `58c928893f0ba95df361b3ae43c17a3ecdba53e3`,
whose commit message names that run. `real-plans.json` preserves the exact three
EXPERIMENT records with original chain hashes and a hash of the complete memory
file at that commit. The artifact API identified artifact 13495242713, but its
direct download returned HTTP 403; the committed output supplies immutable proof.

`replay.json` verifies the rebuilt dataset digest against the original experiment
records before producing any comparison. Same plans, same original dataset,
no new outcomes or experiment recomputation. The three zero-threshold plans are
REJECTED (`IMMATERIAL_MOVEMENT`):

| Outcome | Raw group/control | Original eligible group/control | B1 |
| --- | ---: | ---: | --- |
| HOME_WIN | 78 / 65 | 17 / 20 | REJECTED |
| AH_HOME_COVER | 58 / 52 | 11 / 15 | REJECTED |
| DRAW | 51 / 36 | 8 / 12 | REJECTED |

Unknown and unassigned cases remain separate; full coverage, FT and baseline
counts are in the diagnostic agenda. Original HOME_WIN 12/17 (70.6%) is unchanged
and remains exploratory, not validation. Before: 3 received, 3 syntactically valid,
3 historically executed. After diagnostic eligibility: 0 testable, 0 insufficient,
3 rejected; actual diagnostic executions: 0. No new predictive success claim.

Legacy rows have decision timestamps and source IDs but no separate per-feature
freeze proof or outcome-free FT source proof; original plans also lack a documented
threshold freeze. B1 leaves those fields absent, reports insufficiency reasons,
and counts zero provenance-qualified eligible rows. It does not infer timestamps
from rounded trajectory minutes, derive FT provenance from outcomes, or pretend
that the historical eligible counts satisfy the new provenance contract.

## Reproduction

From repository root (offline, using already available Git objects):

```sh
mkdir -p /tmp/b1-frozen
git archive ede8b771cc20a9236a0163df47ce2f6e7e915b25 data | tar -x -C /tmp/b1-frozen
python -m scripts.lab_research_quality --source-root /tmp/b1-frozen --output /tmp/b1-replay.json
python -m unittest discover -s tests -p test_research_quality.py -v
python -m compileall -q h1lab scripts
python -m unittest discover -s tests -v
node --test tests/*.test.cjs scheduler/worker.test.mjs
```

`input_sha256`, `proof_sha256` and `output_sha256` are deterministic canonical JSON
hashes. `output_sha256` hashes the report before that field is inserted. The CLI
requires explicit output and refuses data/ and docs/; it produces a standalone
JSON diagnostic panel/agenda, never publishes Pages. Existing operational agenda,
ranker, executor, memory chain, config and cron remain unchanged. Isolation allowlist
adds only the four exact B1 audit-evidence paths; no previous rule/test is relaxed.

Costs: zero live LLM calls, zero neurons, zero provider queries, zero paid services,
zero money operations. `llm_schedule_live_enabled=false` unchanged. H1, E5,
Telegram, FT, Pages, all historical ledgers and scientific gates untouched.

Work should independently inspect materiality conservatism, temporal/provenance
limits, outcome isolation, replay hashes and CI. Owner alone authorizes merge;
this delivery remains Draft and does not request promotion or operational enablement.
