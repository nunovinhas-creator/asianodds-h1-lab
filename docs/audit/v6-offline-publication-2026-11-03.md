# V6 offline statistics — concurrency-safe publication (issue #107)

## Incidents

| Run | Input commit (checkout) | Concurrent commits before the push | Result |
|---|---|---|---|
| 41420785839 (2026-11-02 09:27) | `e90ec069` | LAB V4 `e75323e4`: `docs/lab/v6-falsification.json`, `v6-p0-gates.json`, `v6-readiness.json`, `v4-audit.json`, … | `[rejected] HEAD -> main (fetch first)` |
| 41540018891 (2026-11-02 22:46) | `e59023de` | collector `2809ad5e` (`docs/data.json`), LAB V4 `db891b1d`, FT `2c1b7851` (`ft-ledger.json`, FT/discovery events, segmented state) | `[rejected] HEAD -> main (fetch first)` |

Root cause: the publish job committed on the pinned checkout and ran a bare
`git push origin HEAD:main`. Any commit by another producer during the ~1 minute
between checkout and push made it a non-fast-forward. In BOTH incidents the race
also changed V6 inputs (the planner reads `v6-falsification`, `v6-p0-gates`,
`v6-readiness`; the build hashes every top-level `data/lab/*` file), so a plain
rebase-and-push would have published a report that does not describe the tree it
sits on.

## Fix

`scripts/lab_v6_offline_publish_safe.py`, on the shared selective engine
(`scripts/git_selective_publish.py`, same transport and push-outcome machine as
collector/H1/FT/LAB V4). No rebase, no force push, no LLM, provider or Telegram call.

| Concurrent change | Decision |
|---|---|
| Path that is not a V6 input (H1 dashboard, results, V4 reports not read, receipts, docs) | kept byte-for-byte, report transported unchanged |
| Valid change of a V6 input | report recomputed offline on the exact remote tree (network and subprocesses blocked), `V6-Input-Commit: <remote>` |
| FT FINAL changed/removed, append-only journal rewritten, fixture identity rewritten, input deleted, recomputation failure | `REFUSED` (red), receipt + bundle, nothing pushed |
| Program/config change | `SUPERSEDED_BY_NEWER_INPUTS` (exit 0, receipt); next run recomputes with the new code |
| Existing run history rewritten/deleted, this run's history written by someone else, unknown path | `REFUSED` |
| This run's history already on main (re-run, lost HTTP response) | `ALREADY_PUBLISHED_FOR_RUN`, never overwritten |

Verification of every candidate: latest report == run history bytes; research
invariants (`llm_calls == 0`, `validated == 0`, no hypothesis `scientifically_proven`);
no V6 input differs between the trailer's input commit and the parent; the report's
`source_sha256` equals the blobs of the published tree.

Receipt: `V6_OFFLINE_STATS_FINAL_RECEIPT` (stdout, job summary, artifact
`v6-offline-publish-receipt-<run_id>`): `status`, `path` (FIRST_ATTEMPT / AFTER_CAS /
CONFIRMED_AFTER_TRANSPORT_ERROR …), `input_commit`, `published_commit`,
`published_report_sha256`, recomputations. Independent check:
`git show <published_commit>:docs/lab/llm-statistics-runs/<run_id>.json | sha256sum`.

## Tests

`tests/test_v6_offline_publish_safe.py` reproduces both incidents on a local bare
repository (the legacy push fails with `fetch first`; the new publisher recomputes
on the remote inputs and preserves every concurrent blob) plus CAS during push,
HTTP 408 after acceptance, re-run, retry bound, program supersession, FT FINAL
rewrite, journal rewrite, run-history rewrite, unknown path, recomputation failure,
network isolation, and a traced real-repository build proving that every file the
build opens is a declared V6 input and that `source_sha256` is reproducible from blobs.
