# FT: recovery after a rejected publication (proposal, NOT integrated)

Status: design only. Nothing here is wired into any workflow. Issue #107 stays open/DEGRADED.

## Evidence (incident run 41358783489, 2026-11-01)
- The run polled 30 games and sealed a 57-file bundle, then `lab_ft_publish_safe` refused to publish
  because #198 changed `h1lab/`, `scripts/` and `tests/` during the poll (correct: FT depends on them).
- `.github/workflows/lab-ft-results.yml` has **no upload-artifact step**. When the guard raises, the runner
  is discarded, so the sealed bundle and the provider evidence disappear. The next run starts from the old
  ledger and must re-query the providers (cost, cooldowns, quota) for the same games. This is the real loss:
  not the refusal, but the absence of any durable record of what was observed.

## Constraints (all kept)
1. Never publish results computed with incompatible code.
2. No forced duplicate provider calls; cooldowns and free-tier limits respected.
3. No extension of the 24 h window; a checkpoint never promotes anything.
4. A candidate becomes FINAL only through the normal certification path, run with the *current* code.

## Proposal: non-certified observation checkpoint
**What is saved on rejection.** Only *raw observations*, never ledger rows, never FINAL candidates:
`{schema, run_id, code_commit(head at start), code_commit(remote at rejection), rejection_reasons[],
observations:[{match_key, provider, request_id/endpoint-hash, observed_at, http_status, response_sha256,
response_excerpt_or_ref, adapter_version}], counters}`.
Saved as a GitHub Actions artifact (`if: failure()`, retention 2 days, not in git), so it cannot be read by
any producer or by Pages and cannot be mistaken for a published artifact.

**What a later run may do with it (reuse gate)** — an observation is replayable only if ALL hold:
- `observed_at` within the same 24 h window of its own match (kickoff+24 h not elapsed *at observation time*; the
  checkpoint never extends the window: a match whose window has elapsed is expired, with or without a checkpoint);
- `observed_at` ≤ 6 h old at replay (provider data staleness bound, tunable, default conservative);
- `response_sha256` matches the stored body and `adapter_version`/identity-rules hash is unchanged **or** the
  new code re-derives the same identity from the stored body (replay through the current parser, no network);
- the artifact was produced by this repository's workflow (run id + head SHA verified through the Actions API);
- replay happens in the *normal* reconcile path: the current code re-parses the stored body, the dual-provider
  and immutable-FINAL gates run unchanged, and only then does a candidate appear. Replay counts as the visit
  evidence ("reused_checkpoint") but is not a provider call and does not touch cooldown state.

**What it never does:** promote, backfill a missing evidence timestamp, carry results across kickoff+24 h,
override a cooldown, or satisfy the "two independent providers" rule with a single stored body.

## Alternative that needs no new storage: gate before the poll
Move the cheap structural check *before* provider calls: abort the poll (no provider calls) if
`origin/main` already differs from the checkout in `h1lab/ scripts/ tests/ .github/`, and re-check
immediately before sealing. This does not remove the in-poll window (~100 s), but with the checkpoint it
makes the rejected poll recoverable instead of lost. Both are independent and additive.

## Failure simulation to implement first (bare Git, no network)
1. Seal bundle at base B; push code change C to remote during "poll" -> guard refuses; assert remote tree unchanged,
   baseline FINAL hash unchanged, checkpoint written with both SHAs and all refusal reasons.
2. Replay at current code with a fresh ledger: observations inside window/age -> candidate produced only via the
   normal certification path; provider-call counter stays 0.
3. Replay after kickoff+24 h, after the staleness bound, with a tampered body, with a different adapter version
   that cannot re-derive the identity, from a foreign run id: all refused, ledger unchanged.
4. Checkpoint present but cooldown active: no provider call, cooldown untouched.

## Risks / open questions
- Artifact storage is private to the repo but still public-repo-visible if the repo is public: bodies must be
  stripped of any token/headers (already the case for adapter logs; to be asserted by test).
- The replay path adds a new input to FT; it must be behind an explicit flag defaulting OFF and enabled only
  after the failure simulation passes in CI.
- 6 h staleness bound is a proposal, not a measured value.

## Offline demonstration (2026-11-02) — still NOT integrated

`scripts/lab_ft_observation_checkpoint.py` + `tests/test_lab_ft_observation_checkpoint.py`.
No workflow, producer or publisher imports the module; enabling it needs a separate approval.

| Requirement | Where it is enforced / proven |
|---|---|
| Checkpoint of uncertified observations | `build()` stores raw bodies + hashes only, never ledger rows |
| Immutable identity/provenance | canonical-JSON `seal`; `write_once()` = tmp + fsync + `link` (never overwrites); different document for same run refused |
| Verifiable original timestamp | `observed_at` inside the seal; back-dating breaks the seal (test) |
| Code/config reference | `code_commit`, `remote_commit`, `config_sha256`, per-observation `adapter_version` |
| Isolation from production / no direct FINAL | replay returns `UncertifiedObservation` (no status, `certified=True` raises); bare-Git demo asserts the remote ledger is unchanged |
| 24 h window | refused when observed after kickoff+24 h, and when replayed after kickoff+24 h |
| No provider calls when reusable | `urlopen` patched to fail; reuse path makes 0 calls |
| Revalidation with current code | current parser re-derives from the stored body; `None` → `adapter_incompatible` / `not_rederivable_by_current_parser` |
| Incompatible / expired evidence | tamper (seal), body swap + reseal (body hash), stale > 6 h, future timestamp, foreign run id |
| Free-plan limits | ≤200 observations, ≤64 KiB per body, ≤2 MiB per checkpoint; credential-like bodies refused; intended storage: Actions artifact, 2-day retention, not Git |
| Interruption / concurrency | child killed between write and publish leaves no checkpoint and rerun succeeds; 4 concurrent writers → one identical file |

Run: `python -m unittest tests.test_lab_ft_observation_checkpoint`.

## Security/provenance review (2026-11-02, Architect phase 5) — still a demonstration

| Item | Status |
|---|---|
| Workflow authenticity (not just run-id format) | `verify_provenance()` requires the GitHub Actions API run record: repository, workflow path `lab-ft-results.yml`, `head_sha` == `code_commit`, run id. **Fetching that record is not implemented** (would need the API + token in the replaying job). |
| Run ↔ commit ↔ config | `code_commit` must equal the run's `head_sha`; `config_sha256` stored but **not yet recomputed** from a known config manifest. |
| Request ↔ response | `exchange_sha256` binds endpoint + provider event id + body hash; replay refuses a body whose parsed `event_id` differs (`identity_mismatch`). |
| Timestamp origin | `observed_at` is self-reported by the run; it must fall inside `[run.created_at, run.updated_at]` from GitHub. Sub-run precision is not authenticated. |
| Body swap + recomputed hashes | The seal is **integrity, not authentication**: a forged, resealed file passes `load()`; it is refused only by the GitHub artifact digest check (test). |
| Premature / out-of-window | refused before kickoff+95 min, after kickoff+24 h (at observation and at replay) |
| Other games | provider event id must match the parsed body |
| Current parser | always re-parses; `None` → refused |
| Secrets/headers | field whitelist (no headers/cookies), credential pattern scan on bodies |
| Size/retention | 200 obs, 64 KiB/body, 2 MiB/file; intended Actions artifact with 2-day retention (future, flag OFF by default) |
| Never FINAL | `UncertifiedObservation` only; certification stays in the normal path |

Residual risks before any wiring: the GitHub artifact digest is computed over the uploaded **zip**,
so the verifier must download the artifact and compare the zip digest before extracting; API access
and token scope for the replaying job; config manifest hashing; clock trust inside a run.
