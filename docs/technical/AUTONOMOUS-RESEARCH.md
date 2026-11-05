# MASTER BRAIN — Autonomous research (exploratory)

Liberdade para descobrir, rigor para testar, provas para validar.

## Why this exists

Audited on `main` `f1c13ab` (2026-11-05):

* `scripts/lab_v6_llm_autonomous.py` → `choose_candidates()` → `plan()`/`build_packet()`
  raise `ScientificGateBlocked` whenever the 7-day P0 gate is `BELOW_99_PERCENT`
  (97.28% at audit time). Scheduled run 41907675562 failed with
  `AUTONOMOUS_DISCOVERY_BLOCKED: ScientificGateBlocked`.
* The model only wrote prose for feature codes chosen by Python (hash order), outcome
  fixed to `OVER_2_5`, V5 boolean patterns only, no executor feedback, no memory.

The old path is **unchanged**. The new path is separate and can be switched off.

## Two contracts

| Gate | Module | Decides | Blocks on |
|---|---|---|---|
| `EXPLORATION_GATE` | `h1lab/research_gates.py` | whether data can be explored | missing/corrupt files, missing provenance ids, duplicate ids, archive gaps, size limits, unusable timestamps (per operation) |
| `SCIENTIFIC_VALIDATION_GATE` | existing `v6_llm_investigator.scientific_gate` | whether anything could be validated | the existing 99% coverage, chronology, prospective and OOS criteria (unchanged) |

`BELOW_99_PERCENT`, `WARMUP` and `INCONCLUSIVO` are **limitations** for exploration.
`promotion_guard` raises if any exploratory record claims `VALIDATED`.

## Pipeline

`HIPÓTESE → PLANO → VALIDAÇÃO DO PLANO → EXECUÇÃO PYTHON → RESULTADOS → FALSIFICAÇÃO → MEMÓRIA → PRÓXIMO CICLO`

| Step | Module |
|---|---|
| Dataset (pre-kickoff trajectories, separate outcomes) | `research_dataset.py` |
| Safe indicator language | `research_dsl.py` |
| Plan contract | `research_plan.py` |
| LLM packet / parsing / one bounded call | `research_llm.py` |
| Executor (stats, falsification, multiplicity) | `research_executor.py` |
| Append-only memory, novelty, agenda | `research_memory.py` |
| Cycle, offline proposer, panel | `research_cycle.py` |
| CLI | `scripts/lab_research_cycle.py` |
| Panel | `docs/research-autonomy.html` + `docs/research/autonomous-research.json` |

### Variables (49)

Time/sequence, Total line, implied goals (λ) path/velocity/acceleration/reversals/runs,
unobserved gaps, line-up-then-λ-down sequences, 1X2 de-margined probabilities, AH line
moves, Total×AH and Total×1X2 co-observation, competition type. Computed only from
messages observed before kickoff. Bookmaker divergence, in-play odds and the BTTS price
are declared `UNAVAILABLE` (not in the sources) instead of being invented.

### Markets

`OVER_2_5` (Poisson Total baseline), `HOME_WIN`/`DRAW`/`AWAY_WIN` (de-margined 1X2),
`AH_HOME_COVER` (de-margined AH; quarter lines split), `BTTS_YES` (no market price:
frequency comparison only, flagged).

### DSL

JSON trees: `var`, `const`, and allow-listed operators (`add sub mul div neg abs sign min
max gt ge lt le eq ne between and or not is_known`). Typed, depth ≤ 8, ≤ 64 nodes,
finite constants ≤ 1e4. No strings evaluated, no code, SQL, I/O or writes. Unknown input
→ unknown output → excluded (never a control). New indicators `X_*` cannot use
outcome-like names.

### Executor (RX1)

Primary statistic: difference in mean residual `y − p_market` between group and control
(or frequency difference when no baseline). Day-stratified permutation test (2000),
day-cluster bootstrap CI, Wilson/Newcombe, Fisher (descriptive), Brier/log-loss of the
baseline, chronological 70/30 day split (train → test sign + train-offset log-loss),
period halves, stratum-weighted effect by lead time / line / competition type, BH q
within cycle and Bonferroni over the cumulative family from memory.

States: `INSUFFICIENT_DATA` (< 15 FT+baseline per side, with what is missing),
`NO_SUPPORT_IN_DATA`, `FALSIFIED_EXPLORATORY`, `INCONCLUSIVE`, `PROMISING_EXPLORATORY`.
Always `scientific_status=EXPLORATORY_NOT_VALIDATED`, `promotion_eligible=false`.

### Memory

Operational memory path `data/research/memory.jsonl` (committed only by the `publish` job of
the active workflow, together with the panel). Hash chain (`seq`, `prev_sha256`, `sha256`). Records:
`EXPERIMENT` (hypothesis id, question, variables + definitions, plan, dataset SHA,
sources SHA, information cut-off, test version, results, limitations, state, novelty,
related ids, next question), `PLAN_REJECTED`, `CYCLE` (agenda for next cycle).
Same question + same data → skipped; same question + new data → new version.

### Prioritisation (offline proposer)

`score = novelty × testability × availability × informativeness × (1 − 0.5·redundancy)`
with a per-outcome cap. Reads FT *availability* only, never outcome values (tested by
shuffling outcomes).

### Run kinds and provenance (no demo presented as current research)

| run_kind | Files | Accepted hypothesis origins |
|---|---|---|
| `OPERATIONAL` | `data/research/memory.jsonl`, `docs/research/autonomous-research.json` | `OFFLINE_PROPOSER`, `LLM_LIVE` (one real bounded call) |
| `DEMONSTRATION` | `docs/research/demo/{memory.jsonl,panel.json}` | `OFFLINE_PROPOSER`, `SIMULATED_LLM`, `RESPONSE_FILE_NOT_LIVE_LLM` |
| `TEST` | explicit temporary paths only | all, for tests |

A memory file holds exactly one run kind (mixing is refused). Panel schema 2 carries
`provenance` (kind, reference time, origins, real LLM calls, `is_current_autonomous_research`).
The page shows the operational report; only if it does not exist (HTTP 404) it shows the
demo under a "DEMONSTRAÇÃO — NÃO É INVESTIGAÇÃO AUTÓNOMA ATUAL" banner. Any other error is
shown as unavailable data, never replaced by the demo.

### Concurrency and crash safety

* Exclusive `fcntl` lock on `<memory>.lock`, bounded wait (`MEMORY_LOCK_TIMEOUT`, no hang).
* Chain re-read inside the lock; `expected_tip` CAS: a cycle computed against a memory that
  changed meanwhile raises `MemoryConflict` and writes nothing (no lost update, no seq clash).
* Atomic write: temp file + fsync + `os.replace` + directory fsync. A crash leaves the old file.
* A file ending without newline (foreign interrupted write) raises `MemoryTornTail`; only the
  explicit `--mode recover-torn-tail` quarantines the fragment (`.torn-<sha>`), and only if
  every complete line is a valid chain. Mid-file corruption is never repaired.
* Across GitHub runs: same `v6-llm-global` concurrency group; the publisher accepts only a
  byte-exact strict extension of the tracked memory and aborts on any rebase conflict.

### LLM context: real pre-kickoff trajectories

`research_context.trajectory_examples`: up to 8 real matches, ≤10 messages each, ≤16 KB,
one per structural bucket (message count, AH/1X2 present, line moved), lowest salted hash.
Selection never reads outcomes or FT status (tested by blanking outcomes). Content: minutes to
kickoff, trigger, Total/AH quotes before/after, implied goals, de-margined 1X2. Pseudonymous
`ref`, no names, dates or competition names; provenance = hashed event ids + SHA-256 of the
market files. The whole packet is bounded (44 KB) by trimming examples, then memory.

### Simulated LLM proof

`h1lab/research_simulated_llm.py` is an opener for `invoke_once`: it receives the real request
body and derives plans from it (catalogue availability, thresholds from the trajectory
examples, avoiding variable pairs found in the memory digest). Tests prove that Python runs
exactly those plans (fingerprints), that they are neither offline-proposer nor fixture plans,
and that a second cycle chooses different pairs after reading memory. It found two real bugs:
the DSL name filter rejected `..._ONLY_MOVE`/`..._AWAY_NET` (substring `y_`), and the
simulator's own memory check. Always labelled `SIMULATED_LLM`; never accepted as operational.

### Active workflow (migration PR, replaces the retired V6 workflow)

`.github/workflows/v6-llm-autonomous.yml` now runs the research cycle. The prepared file was
moved over the old workflow (`git mv`), so there is still **one** scheduled LLM workflow:
same cron `43 1,7,13,19 * * *`, same `v6-llm-global` group (`cancel-in-progress: false`),
same provider and model (`@cf/meta/llama-3.1-8b-instruct-fast`), one request per run, no
model retries. `config/research-autonomy.json` has `llm_live_enabled: true`.
The retired `scripts/lab_v6_llm_autonomous.py` is kept unwired, for rollback only.

| Job | Permissions | Secrets | Does |
|---|---|---|---|
| `budget` | `contents: read`, `actions: read` | none (only `GITHUB_TOKEN`) | `scripts/lab_research_budget.py`: pre-call attempt ledger from GitHub run history |
| `discover` | `contents: read` | `CLOUDFLARE_ACCOUNT_ID`, `MASTER_BRAIN_LLM_API_KEY`, **only in the live step** | preflight tests, then ONE call into a scratch copy of the memory; `git diff --exit-code` |
| `publish` | `contents: write` | none | `lab_research_publish.py` strict-extension check, commits exactly two files |

#### Daily budget: two independent counters, larger wins

1. **Published memory**: `LLM_LIVE` cycles recorded today (only sees calls that were published).
2. **Pre-call ledger** (`RESEARCH_PRIOR_LLM_ATTEMPTS`): every started LLM step today in
   `v6-llm-autonomous.yml` *and* the manual `v6-llm-investigator.yml` (same Cloudflare account),
   over all run attempts and any conclusion. It therefore also counts calls that were made but
   never reached memory (invalid reply, executor error, timeout, push conflict, cancellation).
   A run touching the UTC day in any timestamp counts; the current run is excluded.

`--mode llm-live` refuses (before any request) when: the ledger value is missing/malformed,
`max(memory, ledger) >= 4`, not `refs/heads/main`, `GITHUB_RUN_ATTEMPT != 1`, a schedule string
other than the cron above, a dispatch without `INVESTIGAR_UMA_VEZ`, `--now` is passed, the config
flag is off, or secrets are missing. Ledger API failure/overflow → no output → `discover` gets
no ledger → refused. Over-counting (e.g. a step that refused before calling) is accepted.

Manual `live_once` dispatches share the same four-per-UTC-day total; they can only use slots the
scheduler did not use (GitHub frequently delays or drops cron runs).

#### Queued runs see fresh memory

Both checkouts use `ref: ${{ github.ref }}` (the branch tip when the job starts, i.e. after the
concurrency lock), not the trigger SHA, so a run queued behind another sees the memory that run
published instead of producing a guaranteed rebase conflict and a wasted call.

#### Preflight in the secret job

The discover job runs `test_research_*.py` with `RESEARCH_PREFLIGHT=1`. PyYAML is deliberately
not installed in the job that holds secrets; only the YAML-structure test skips there (the PR CI
`research-autonomy-smoke.yml` runs it with PyYAML and also replays the preflight without PyYAML,
asserting exactly `OK (skipped=1)`).

#### Cost bound (Cloudflare Workers AI)

Request body ≤ 48,000 bytes (≈ 12–16k tokens), `max_tokens: 2400`, ≤ 4 attempts per UTC day.
The repository's earlier measurement (`V6_LLM_AUTONOMY_CONTROLLED.md`) observed ≈ 25 neurons for one
≈ 20 KB request; this packet is ≈ 25 KB on today's data. Even at a pessimistic 300 neurons per call,
4 calls ≈ 1,200 neurons/day, ≈ 12% of the 10,000 neurons/day free allocation documented there.
Not verified: the account plan and the actual remaining allocation (`account_quota_verified=false`;
no usage API is called). Other Workers AI usage on the same account shares that allocation.

#### Rollback

* Stop real calls immediately, no deploy: set `"llm_live_enabled": false` (scheduled runs then
  fail closed in `discover` with `LLM_LIVE_DISABLED_BY_CONFIG`, zero requests), or disable the
  workflow in GitHub Actions.
* Full rollback: `git revert` the migration merge commit — restores the old workflow file,
  the old tests and `llm_live_enabled: false`. Operational memory and panel stay valid and are
  simply no longer extended (delete both files to return the page to DEMONSTRAÇÃO).

### LLM → Python contract v2 (after the first live call, 2026-11-05)

First live call: GitHub Actions run `42021728675`, model `@cf/meta/llama-3.1-8b-instruct-fast`
(from the code at `71d00ffb`; the v2 cycle record did not store it). The model returned 3 plans;
all were refused before execution: `INDICATOR_DEFINED_BUT_UNUSED` ×2 and
`DSL:INVALID_INDICATOR_NAME` ×1. The 40 executed experiments all came from `OFFLINE_PROPOSER`.
The raw reply was never persisted (memory keeps only structural reasons; `result.json` drops
the records), so the exact JSON cannot be reconstructed. Instruction-side causes found:

* the prompt never said a defined indicator must be referenced by `condition`,
  `control_condition` or a used indicator (the validator rule);
* it never said indicator names are UPPERCASE only (`X_[A-Z0-9_]{2,40}`), while every catalogue
  variable is lowercase, so a small model naturally writes `X_line_up_...`;
* the only example used its indicator in `control_condition` while `condition` used a catalogue
  variable, and was never checked against `validate_plan`.

Fix (the validator is unchanged): `contract_spec()` is built from the validator's own constants
(name regex, forbidden tokens, plan keys, text lengths, markets/outcomes, strata, DSL limits), the
system prompt lists the rules plus a self-check, and the example (two indicators, both used) is
validated by `validate_plan` every time a packet is built (`verified_example`). A verbatim copy of
the example is refused (`COPIED_RESPONSE_EXAMPLE`). Rejections now record `field`
(e.g. `indicators[0].name`) and code-validated `detail` tokens (never free model text).
The raw reply goes to `llm-response-audit.json` in the workflow artifact only (7 days).

Provenance (cycle_version 3, new cycles only; the 44 published records are never rewritten):
`llm_model`, `llm_response_sha256`, `llm_tokens`, `llm_plans_received/accepted/rejected`,
`llm_rejection_reasons`, `llm_plans_duplicate_skipped`, `experiments_from_llm`,
`experiments_from_offline`. The publisher refuses a v3 cycle whose funnel is inconsistent with its
records (`CYCLE_PROVENANCE_INCONSISTENT`). The panel's `research_split` separates autonomous
(model-planned) from deterministic (offline grid) research; legacy cycles are derived from their
records and shown as such. `is_current_autonomous_research` now also requires ≥ 1 executed LLM plan.
The operational panel is still written only by the publisher (isolation rule); until the next
published cycle, the page derives the split from the pre-v3 report (card origins + refused plans).

Operational containment: the workflow was disabled in the GitHub UI by the owner after run
`42021728675` (no change to `main`; `llm_live_enabled` stays `true`). Re-enable only for one
authorised `live_once` validation after this contract is merged.

### Isolation

`scripts/research_isolation_check.py --base origin/main`: changed paths must be allow-listed,
no pre-existing module imports `research_*`, an offline cycle leaves `data/`, `docs/lab/`,
`config/` byte-identical and `scientific_gate()` unchanged. The only shared file touched is
`scripts/publication_ownership.py` (two `LLM_SHADOW` paths and a `SITE` demo pattern, both
already in every publisher's keep-set).

## Safety and cost

* No new scheduled job (the old one is replaced in place), one publisher to `main` for two
  files, no change to H1, FT, Telegram, quotas, cooldowns, credentials, frozen forecasts or V6 journals.
* `llm_live_enabled=true` after the migration PR. `--mode llm-live` refuses unless config,
  `--allow-network`, the schedule/dispatch guards and both daily counters agree; one request, no retry.
* Kill switches: `config/research-autonomy.json` (`exploration_enabled`,
  `offline_cycle_enabled`) and env `MASTER_BRAIN_EXPLORATION=off`. Missing/corrupt config
  → disabled.

## Commands

```bash
python -m scripts.lab_research_cycle                       # offline cycle, zero LLM calls
python -m scripts.lab_research_cycle --mode packet          # what the LLM would see
python -m scripts.lab_research_cycle --run-kind DEMONSTRATION --mode llm-simulated
python -m scripts.lab_research_cycle --run-kind DEMONSTRATION --mode llm-response --response FILE
python -m scripts.research_isolation_check --base origin/main
python -m scripts.lab_research_budget --repo OWNER/REPO --exclude-run 0   # needs GH_TOKEN; read-only
python -m unittest discover -s tests -p 'test_research_*.py'
node --test tests/research-autonomy-ui.test.cjs
```
