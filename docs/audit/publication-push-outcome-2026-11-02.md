# FT push outcome machine — incident HTTP 408 (2026-11-02 05:17 UTC)

Run: <https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41393026365>
(job `reconcile` 125108318444, job `integrity / health` 125108724935).

## 1. Reconstruction (from logs + Git history of `main`)

| Item | Value | Evidence |
|---|---|---|
| Initial HEAD (`FT_BASE_HEAD`) | `9eb7f3f7357903dd75032980f471454723a739e3` (05:16:09) | job env |
| Local sealed FT commit (source) | `d0b74cf` — 45 files, seal `PUBLICATION_BUNDLE_SEALED ft 57` | job log 05:17:15 |
| Immutable guard | baseline 443 FINAL → candidate 444, `new_final_count 1`, previous FINAL unchanged | `FT_IMMUTABLE_GUARD` |
| Remote `main` at push time | `edaf600ef255e6de03f9515189a4fc74d05b78f5` (V4 refresh 05:16:48) — the transport commit was assembled on it; its SHA was **not logged** (gap closed by this PR) | history |
| Push | 05:17:16 → 05:17:37, `RPC failed; HTTP 408`, `unexpected disconnect`, `remote end hung up` | job log |
| Did GitHub accept? | **No.** The next commit on `main`, `85c1005` (05:21:08), has parent `edaf600`; no FT transport commit exists between 05:16 and 05:57. Had the 408 response been lost after acceptance, `85c1005^` would be the FT commit. | `git rev-parse 85c1005^` |
| FT files published by this run | None | same |
| Recovery | Next FT run published `6a59d53` (05:57:04): FINAL 443→444, the new FINAL is `2026-11-02,59190,67067` (kick-off 02:00Z) with `attempts: 1`, `provider_attempts.bsd.first_at 05:56:25` | ledger diff `edaf600..6a59d53` |
| Evidence lost? | The 05:17 candidate bytes were not retained, so the identity of its single new FINAL cannot be proven; the most likely candidate is the one above, re-certified at 05:56 inside its 24 h window. **Cost: one repeated BSD invocation** and the loss of the 05:17 attempt counters. The two expirations at 05:56 (`2026-11-01,1488,22807`, `2026-11-01,38174,28378`, kick-off 2026-11-01 05:00Z) had their windows closed at 05:00, before the 05:17 run, so no temporally valid FINAL was lost. | ledger |
| Integrity job | correctly FAILED closed (`upstream_ft_run_failed`) | job 125108724935 |

Conclusion: in this incident HTTP 408 coincided with non-publication, but the
old code could not know that. It treated a transport failure as an
unexplained push error and aborted without reading the remote — if GitHub
had accepted the ref, the next run would have been correct but the alerting
would have reported a false failure; if it had not, a bounded safe retry
would have saved the 40 minutes and the repeated provider call.

## 2. State machine (`scripts/git_publish_outcome.py`, used by `scripts/lab_ft_publish_safe.py`)

| State | Detection | Action |
|---|---|---|
| PUBLISHED | push exit 0, or after an uncertain error the candidate is an ancestor of (or equal to) remote `main` | receipt `PUBLISHED` / `PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR`; no second push |
| CAS_REJECTED | non-fast-forward, `fetch first`, `stale info`, exact `cannot lock ref 'refs/heads/main': is at <sha> but expected <sha>` | fetch, re-verify every remote path, re-assemble, re-verify seal + immutable FINAL + discovery, push again (bounded) |
| UNCERTAIN | HTTP 408/5xx, `RPC failed`, `unexpected disconnect`, `remote end hung up`, `early EOF`, reset/time-out | read remote (bounded fetches). Accepted → PUBLISHED. Not accepted → bounded retry with full revalidation (max 3 transport failures, back-off 2/4/8 s). Remote unreadable → abort `outcome unknown` (never blind retry) |
| AUTH | 401/403, `Permission to … denied`, GH006/GH013 protected branch | abort, never retried |
| TRANSIENT | DNS / connection refused / unreachable before sending | same path as UNCERTAIN (probe first) |
| INCOMPATIBLE | remote changed FT program, FT artefacts with different bytes, unknown paths | abort through `allowed_remote_changes` (unchanged rules) |

Idempotence: before every attempt, if remote `main` already carries the
**identical** Git entries for every produced FT path (lost response, crash
after push, concurrent twin publisher), the publisher returns
`ALREADY_PUBLISHED_EQUIVALENT` and pushes nothing.

Invariants kept: no provider call (receipt `provider_requeries: 0`), no
rebase/recompute of FT evidence, no force push, no change to FINAL, no
extension of the 24 h window, the seal and the immutable-FINAL baseline are
re-verified before every push.

## 3. Tests (`tests/test_lab_ft_publish_408.py`, bare Git + injected faults)

408 before acceptance · 408 after acceptance · 408 after acceptance with a
later collector commit · connection failure before response · CAS rejection
over independent H1 data · main advanced with FT code (refused, remote
untouched) · incompatible sealed bundle (no push) · auth refusal (no retry) ·
persistent transport failure (bounded to 4 pushes) · crash after publication
then rerun (no second push) · two concurrent identical publishers (exactly
one commit) · concurrent different FT publication (refused) · classifier.

```
python -m unittest tests.test_lab_ft_publish_408 tests.test_lab_ft_publish_safe \
  tests.test_lab_ft_publish_incident tests.test_lab_ft_publish_telegram_block
```

## 4. Acceptance criteria in production

* A future `HTTP 408` produces a `FT_PUSH_OUTCOME_PROBE` line with
  `remote_before_push`, `candidate`, `remote_after` and `state`.
* No `FT_PUBLISH_RECEIPT` ever shows `provider_requeries` ≠ 0.
* FINAL count never decreases; `IDENTITY_CONFLICT` unchanged by the publisher.
