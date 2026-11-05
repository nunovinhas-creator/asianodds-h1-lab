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

Operational memory path `data/research/memory.jsonl` (not committed; written only by the
prepared workflow after approval). Hash chain (`seq`, `prev_sha256`, `sha256`). Records:
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

### Prepared migration (NOT active)

`.github/proposed-workflows/v6-llm-autonomous.research.yml` (outside
`.github/workflows`, so GitHub never runs it): same cron `43 1,7,13,19 * * *`, same
`v6-llm-global` group, discover job with secrets writes a scratch copy, secret-free publish job
runs `scripts/lab_research_publish.py` (strict extension, one OPERATIONAL cycle, ≤1 call,
no validated/demo content). `lab_research_cycle --mode llm-live` mirrors the old guards: main,
attempt 1, exact cron string, ≤4 real calls per UTC day, or dispatch with
`RESEARCH_LLM_CONFIRMATION=INVESTIGAR_UMA_VEZ`.

Activation (human approval required): (1) `git mv` the file over
`.github/workflows/v6-llm-autonomous.yml` (replaces, does not add, so still 4 opportunities/day);
(2) set `llm_live_enabled: true`. Rollback: revert either change; the old memory stays valid.

### Isolation

`scripts/research_isolation_check.py --base origin/main`: changed paths must be allow-listed,
no pre-existing module imports `research_*`, an offline cycle leaves `data/`, `docs/lab/`,
`config/` byte-identical and `scientific_gate()` unchanged. The only shared file touched is
`scripts/publication_ownership.py` (two `LLM_SHADOW` paths and a `SITE` demo pattern, both
already in every publisher's keep-set).

## Safety and cost

* No new scheduled job, no publisher to `main`, no change to H1, FT, Telegram, quotas,
  cooldowns, credentials, frozen forecasts or V6 journals.
* `llm_live_enabled=false`. `--mode llm-live` refuses unless config, `--allow-network`
  and `RESEARCH_LLM_CONFIRMATION=INVESTIGAR_UMA_VEZ` all agree; one request, no retry.
  Wiring it into the existing 4 daily slots requires human approval.
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
python -m unittest discover -s tests -p 'test_research_*.py'
node --test tests/research-autonomy-ui.test.cjs
```
