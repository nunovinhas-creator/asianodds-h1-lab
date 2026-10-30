# LAB publication barrier — 29 October 2026

Baseline: `9be650a0cf6c066a400e79d7d6328f728a03c749`.

## Evidence and failure mode

Both LAB workflows used continue-on-error producers followed by file-existence
staging. Audit staged v6-shadow/readiness/price-quality, forecasts, hypotheses and
trajectory outputs even after producer failure. FT did the same for research,
residuals, pattern registry/watch and discovery files. A producer could write one
output, fail on the next or on verification, and still have the first committed.
Dependent successful steps could also consume its partial local state.

## Change and tradeoff

Before any staging, require outcome=success for every optional producer (including
previously unnamed chronology steps). GitHub conclusion=success is deliberately
insufficient: continue-on-error masks failure there. Mandatory steps already block
publication through normal workflow success conditions.

Publication is all-or-nothing for each LAB workflow. A scientific producer failure
now also delays that workflow's FT or V4/Golden bundle; the previous public bundle
stays available and the workflow fails visibly. This is a conservative containment
choice, not isolation of independently recoverable sub-bundles. H1 collection and
H1 settlement have separate workflows and are not blocked by this guard.

After staging, read prospective commit bytes from the Git index. Required reports
must exist; staged JSON/JSONL must parse, have no NaN/Infinity and journals must end
with a newline. Seal their SHA-256 values together with unchanged owned journals.
After every rebase, before push, compare the committed bytes and journal inventory
with the seal. Reject deleted, newly introduced or modified owned streams and
reports. An unrelated collector commit remains allowed. Git push remains atomic;
conflicts and concurrent owned-output changes require a fresh workflow run.

This guard complements existing semantic/replay checks; syntactically valid wrong
data is not universally detectable. Adding a producer requires adding its outcome
and output contract. It does not make filesystem writes transactional inside a job.

## Verification and release

Tests inject failed/skipped/cancelled/missing producer outcomes, masked conclusions,
truncated and nonfinite JSON, partial JSONL, missing staged files and concurrent
changes to sealed files in a temporary Git repository. Workflow wiring is tested
for guard-before-commit and verification after rebase/before push. Existing real
baseline reports and journals pass format validation.

After authorized integration, confirm successful normal publications for both LAB
workflows and inspect failures, source freshness and replay separately. Do not
start the 24h/48h/7d operational windows merely because unit tests pass.
