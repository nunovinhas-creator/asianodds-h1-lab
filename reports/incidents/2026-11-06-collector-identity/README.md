# Collector publication refusal — 2026-11-06

Status: **offline recovery verified; production H1/E5 recovery unproven**.
No merge or production notification is authorized by this PR. Two consecutive
real collector cycles after an authorized merge are still required.

## Evidence and exact conflict

- Repository: `nunovinhas-creator/asianodds-h1-lab`.
- Read/auth proof supplied: probe `42178954142`, attempt 2; collection
  `42181923012`, attempt 2 (`TELEGRAM_READ_OK checkpoint 53130 new_messages 61`).
- Artifact `13486524957`: original receipt and Git bundle retained here.
- Base: `45712d02f93605ecfdafb588416121dbba22feb0`.
- Unpublished source: `619347ede68a5395fe1e9ac44c3108300219ae48`.
- Original publisher refused before pushing or sending:
  `PERSISTENT_INCOMPATIBILITY / INTEGRITY / Fixture identity rewritten in collector state`.
- Comparing *all* shared alert/signal identity sets finds exactly one changed key:
  `2026-11-06,563,47650`.

| Field | Published observation | Newly collected observation |
| --- | --- | --- |
| Event ID | `3571094759:52615` | `3571094759:53107` |
| Telegram message ID | `52615` | `53107` |
| Home | CA Independiente de Avellaneda | CA Independiente de Avellaneda |
| Away | Deportivo Riestra | Deportivo Riestra |
| Competition | Argentina Liga Profesional | Argentina Liga Profesional |
| Kickoff UTC | `2026-11-06T22:00:00+00:00` | `2026-11-06T22:15:00+00:00` |
| Original Telegram time | `2026-11-03T14:04:08+00:00` | `2026-11-06T03:13:58+00:00` |
| V4 collector known_at | `2026-11-03T14:06:13+00:00` | `2026-11-06T08:09:19+00:00` |
| Market trigger | total | 1x2 |
| Identity provenance | `url_match / telegram_clock` | `url_match / telegram_clock` |
| V4 parser checkout | `76ea61caf3f74a351e414c374e67a29a61f3f724` | `45712d02f93605ecfdafb588416121dbba22feb0` |
| V4 revision ID | `V4R:72011e043cb5daa11827e3072d3b` | `V4R:7948b6f401568f08b0fecea4f0ce` |
| V4 snapshot SHA256 | `57db1ab114ee694d6c4fa5bb12809c72b8400b29a4a264402e51af71cb536276` | `67b7d7638d30f34bb57b28985985ca4e2cc70a3a27d74dd387ce0b4cba5d35ae` |

AsianOdds source URLs (including the original market):

- https://asianodds.com/en/live-dropping-odds?match=2026-11-06%2C563%2C47650&market=ou
- https://asianodds.com/en/live-dropping-odds?match=2026-11-06%2C563%2C47650&market=1x2

The channel/message coordinates above are the retained source references; no
public Telegram username or original raw message text is present in this artifact.
The structured source pair is also frozen in
`tests/fixtures/collector-identity-2026-11-06.json`.

## Cause and limits of the evidence

Both H1 and independent V4 parsing agree on each observed kickoff. Both V4 records
have `identity_source.kickoff_utc=telegram_clock`, `match_key=url_match`, and the
same parser source SHA256:
`625556e28930947d90a9325ad77cf87c863a87921d6b97214a9c5431a41846ae`.
These are distinct message IDs, with `FIRST_SEEN_BY_COLLECTOR` revisions and no
verified Telegram edit date. No historical alert, signal or ticket was rewritten:
`incorporate()` appended a different kickoff under an already established key,
and `stable_fixtures` correctly rejected the expanded identity set.

This proves a source-observed schedule discrepancy of 15 minutes and an admission
bug (contradictory observations entered the active H1 identity collection). It
does **not** prove an official reschedule. The bundle has no independent schedule
confirmation or raw text to resolve a source typo versus a real calendar change.
There is no demonstrated cross-parser divergence or evidence of different-team
ID reuse in this pair. No identity is automatically corrected or merged.

## Change and preservation

Admission now checks the established `(home, away, kickoff_utc)` before appending
to active H1 observations. A contradictory new event is stored whole in
`state.fixture_quarantine`, with its first collector time, reason, event ID and
references to conflicting established observations. Quarantine is append-only,
validated by the publisher, deduplicated by event ID and never automatically
released. Historical records cannot be moved into quarantine.

The entire batch is admitted before signal generation, so a contradiction later
in the same batch cannot create a new bet. Quarantined keys cannot generate new
H1 signals or triples. Existing signals/tickets stay immutable. E5 explicitly
excludes quarantined keys even if a later V4 projection changes or is absent;
exclusion never triggers a withdrawal. `stable_fixtures`, receipt delivery gates,
intent-before-send publication and terminal ledger immutability remain intact.

The data recovery uses the original bundle, without re-querying Telegram:

- Cursor `53069 → 53130`; all 61 new structured messages retained exactly:
  60 active alerts and one full quarantined alert.
- All 2471 old alerts, 533 old signals and 164 old tickets unchanged.
- All source signals/tickets retained (542/167 total); the conflicting fixture
  had no signal or ticket in the base or source.
- All three collector V4 files byte-identical to the unpublished source: each
  gained exactly 61 rows; production SHA-chain/projection replay passes.
- E5 ledger byte-identical to base/source, SHA256
  `bc1bc9cb0e79d8604fa1acdb28fa57b3de729e0e6d74551ec442ac54fa7aeeaa`.
- Scientific journals, FT ledgers and historical result files are outside the
  recovery diff. Autonomous LLM remains `llm_live_enabled=false`.
- Dashboard re-rendered from recovered state and existing H1 results.

`offline-proof.json` records the reproducible counts and hashes. The original
bundle SHA256 is
`9f93dc27a9a50cd1a0f8c4e55cabf0864a53295658307d776f5cbb680f20e771`.

## Offline verification

From a full clone containing the base (a shallow CI clone needs the base history):

```sh
git fetch reports/incidents/2026-11-06-collector-identity/collect-unpublished.bundle HEAD:refs/heads/evidence/collect-42181923012
python -m scripts.audit_collector_identity_recovery
python -m unittest tests.test_fixture_identity_quarantine -v
python -m unittest discover -s tests -v
python -m h1lab.e5_notify --dry-run
node --test tests/*.test.cjs scheduler/worker.test.mjs
```

The audit and dry-run make no Telegram/provider requests. The dry-run reports
`IDENTIDADE_EM_QUARENTENA` for the affected key and leaves the ledger unchanged.

## Operational impact and required acceptance after merge

This PR restores the saved checkpoint/observations and prevents this ambiguity
from blocking unrelated collection. The affected fixture remains quarantined
until a separately reviewed identity resolution has evidence. No betting history
is changed to accommodate a newer clock.

Before an authorized merge, recheck current main's collector paths against this
PR; if another collector has published, reconcile its observations and receipts
without overwriting them. Concurrent FT/V4 scientific outputs must be kept.

After explicit merge authorization, observe two **consecutive real** `collect.yml`
cycles on main. For each, retain run ID/attempt, checkout/base/published SHA,
`TELEGRAM_READ_OK`, checkpoint before/after, `COLLECT_PUBLISH_RECEIPT=PUBLISHED`
(or a justified no-change result), V4 replay and an E5 completed evaluation.
Compare the E5 ledger between cycles: all old terminal receipts unchanged, no
second send for an existing intent, and every new send preceded by a durably
published intent and followed by its terminal receipt. Also inspect the shared
Telegram block and uncertain delivery statuses. A valid no-candidate evaluation
is not evidence of a new Telegram delivery; do not send artificial notifications
merely to create proof. Keep the original fixture excluded throughout.

Only call H1 and E5 operational after both cycles pass persistence/publication
and E5 completes without duplicate notification or unresolved delivery failure.
This PR's offline checks alone do not establish total recovery.
