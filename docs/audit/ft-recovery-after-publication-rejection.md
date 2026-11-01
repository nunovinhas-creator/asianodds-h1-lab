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
