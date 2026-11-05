# Telegram P0 — 2026-11-05

Refs #107. Audit began with live Actions, not the historical report. All times UTC.

## Observed production evidence

- Old run [42122834556](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42122834556), SHA `a7283b60f44b92b107e04505ddc5192c63e3fb28`: read step ran 22:36:14–23:01:10 and was cancelled before this intervention. Publication and E5 were skipped. No run was cancelled by this intervention.
- That revision had no application deadline around connect, authorization, lookup, read or disconnect. PR [251](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/251) merged at 22:37:48 (`250fc06a37348c1ab8c2c55052c3728b07c08990`), after the old run started. A running process does not acquire merged code. Its exact stalled phase and transport cause cannot be established from the old phase-less log.
- Run [42126237176](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42126237176), SHA `8b9e66755fe1b2e87f552d534c59ca89f7bd1f67`: read 23:01:38–23:02:09, exact result **`TELEGRAM_TIMEOUT CONNECT`**; publication/E5 skipped. This proves PR 251's connection deadline was active.
- Next automatic run [42126930603](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42126930603), SHA `9ff2a1881e037a9955f2ce753ac60a5503bef8f4`: read 23:06:12–23:06:42, also **`TELEGRAM_TIMEOUT CONNECT`**; publication/E5 skipped. Queue progress is proven; Telegram recovery is not.
- At 23:09 UTC, no `in_progress`, `pending`, `waiting` or `requested` run existed; the sole queued run was unrelated Pages. Thus no run held `asianodds-h1-write` at that observation. `collect.yml`, `results.yml` and `lab-quality.yml` share this group. Its `cancel-in-progress: false` serializes writers. While a run is stuck, GitHub retains one pending run and replaces older pending runs; this explains queue churn, not simultaneous collection. Concurrency is unchanged.
- Cursor snapshot: `last_id=53069`, `collector.last_poll_at=2026-11-05T19:36:21+00:00`; latest state commit [4b4ffd2662de2202ba73b2af4a7c73f1e6ae9379](https://github.com/nunovinhas-creator/asianodds-h1-lab/commit/4b4ffd2662de2202ba73b2af4a7c73f1e6ae9379), 19:36:22. These failed reads did not publish a checkpoint.
- E5 latest ledger change: [2f20a76324af4545071c7230157300b7ccb1bd68](https://github.com/nunovinhas-creator/asianodds-h1-lab/commit/2f20a76324af4545071c7230157300b7ccb1bd68), 19:06:25. Snapshot: 158 entries, 155 `sent`, 3 pre-existing `delivery_uncertain_manual_review`. Those uncertain deliveries are not re-sent. No delivery is claimed for skipped E5 steps. The durable-intent-before-send and selective publication paths are unchanged.
- FT ran independently: [42126429240](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42126429240), receipt **`FT_PUBLISH_RECEIPT status=PUBLISHED`**, commit [9ff2a1881e037a9955f2ce753ac60a5503bef8f4](https://github.com/nunovinhas-creator/asianodds-h1-lab/commit/9ff2a1881e037a9955f2ce753ac60a5503bef8f4), `provider_requeries=0`. Its integrity job passed. This is publication evidence, not proof of complete FT coverage.

## Corrections on the review branch

Baseline tested: `287c3e660864aeca75a9e7a0465c87fd8bf275fb`, Telethon 1.45.0. Local interpreter: Python 3.12; Actions remains Python 3.11.

1. Bounded Telethon retries, disabled automatic reconnect, retained phase budgets (30s connect/auth/lookup, 300s read, 5s disconnect). No interactive start, flood-wait sleep, or unbounded retry was added.
2. Flushed phase start/success diagnostics contain only fixed phase names. Rejections, channel errors, timeouts and temporary transport remain distinct. Cleanup cannot mask an existing rejection with a secondary RPC failure.
3. Cursor, H1 incorporation and shadow persistence occur only after network read and disconnect succeed. A partial read or failed cleanup cannot publish or advance a checkpoint. Parsing, original Telegram dates, historical-edit isolation and scientific rules are preserved.
4. GNU `timeout` outside Python terminates even cancellation-resistant/background tasks: 140s probe / 420s collect, TERM then KILL after 10s. Exit 124/137 emits `TELEGRAM_TIMEOUT PROCESS_DEADLINE` and remains nonzero; collection also has an 8-minute step limit. Normal budget sum is 395s; the process limit covers synchronous work and `asyncio.run()` shutdown as well. Workflow job limits remain 3/25 minutes; concurrency is unchanged.

Telethon 1.45.0 shields its disconnect coroutine. Python cancellation deadlines alone cannot guarantee that every background task exits, so the external process deadline is necessary. The full workflow still includes checkout, installation, publication and watchdog work; 430s is the collector process ceiling, not a promise about total job duration.

## Real authentication probe: TELEGRAM_TIMEOUT CONNECT

The first CLI dispatch attempt was refused by GitHub (`401 Bad credentials`) before any run existed. The owner then confirmed correcting only `TG_SESSION` and authorized another attempt. GitHub dispatch subsequently worked; no Telegram credential was read, copied or changed by this intervention.

Exactly one real read-only probe was executed after that correction: [42127990243](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42127990243), main SHA `6a9dab152ebd08aab56335e7bbca6d20b045e5b5`, created 23:13:45 UTC. Its exact log result at 23:14:34 is **`TELEGRAM_TIMEOUT CONNECT`**, exit code 1. The collect job was skipped. There was no collection, publication, E5 request or provider request from the probe. It finished and released concurrency.

**TG_SESSION validity remains INCONCLUSIVE.** This is a connection timeout before authentication, not `AuthKeyUnregisteredError` or another proven rejection. Do not rotate the session solely on this evidence. No second probe was dispatched, and no extra normal collection was initiated without a successful probe. The required two successful real cycles remain **BLOCKED by Telegram connectivity**, not by GitHub dispatch access.

The code audited locally matches main's session/CLI/workflow contents at the resumed audit. This branch's additional changes remain unmerged and therefore were not used by that real probe. Local mocks and the shell kill regression cannot prove connectivity from GitHub runners.

Once the connection fault is independently corrected, the owner can authorize a new single probe; after `TELEGRAM_AUTH_PROBE_OK`, run two normal cycles serially, accepting zero new messages. Verify a checkpoint publication receipt (or NOTHING_TO_PUBLISH), E5 durable receipts and queue release. Those real acceptance gates are not replaced by offline tests.

If a subsequently authorized probe returns `TELEGRAM_SESSION_REJECTED AuthKeyUnregisteredError`, stop credential retries. On the owner's trusted local machine, run the existing `scripts/authorize.py` with the same Telegram application credentials, complete Telegram's authorized login locally, and copy the generated StringSession directly into **only** GitHub Secret `TG_SESSION`. Never put the value in chat, a commit, an artifact or CI logs. This session did not run authorization or alter secrets.

## Scope and status

- **CORRIGIDO on review branch:** process deadlines, bounded retries, phase diagnostics, cleanup error preservation, no checkpoint before successful disconnect.
- **RECUPERADO COM PROVA:** Actions queue progress; FT checkpoint publication with receipt.
- **BLOQUEADO:** Telegram CONNECT and two successful normal production cycles; review changes are not merged or deployed.
- **INCONCLUSIVO:** session validity, channel access, precise transport fault, Telegram recovery, new H1 publication and E5 delivery.

No merges, secret changes, provider calls, autonomous LLM activation, cron changes or concurrency-rule changes were performed. Production data/history and Telegram delivery rules are not edited by this branch.

Offline focused checks: 10 reader tests, 4 session-loading tests, 8 workflow-infrastructure tests and 53 E5 tests pass. The E5 production-fixture `--dry-run` and compile checks also pass. The reader regressions reproduced a checkpoint advance after failed disconnect and a rejected-session diagnosis masked by a secondary RPC error on the baseline; the fixed branch preserves both state and diagnosis. The workflow test executes a synthetic child that ignores TERM and verifies the real shell wrapper kills it and returns failure. Two empty incremental cycles pass offline without moving the cursor or requiring activity.

The full suite and final source identity are recorded with the PR validation evidence. Offline successful empty cycles do not establish real Telegram recovery.
