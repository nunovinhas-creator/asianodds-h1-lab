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

`data/research/memory.jsonl`: hash chain (`seq`, `prev_sha256`, `sha256`). Records:
`EXPERIMENT` (hypothesis id, question, variables + definitions, plan, dataset SHA,
sources SHA, information cut-off, test version, results, limitations, state, novelty,
related ids, next question), `PLAN_REJECTED`, `CYCLE` (agenda for next cycle).
Same question + same data → skipped; same question + new data → new version.

### Prioritisation (offline proposer)

`score = novelty × testability × availability × informativeness × (1 − 0.5·redundancy)`
with a per-outcome cap. Reads FT *availability* only, never outcome values (tested by
shuffling outcomes).

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
python -m scripts.lab_research_cycle --mode llm-response --response FILE
python -m unittest discover -s tests -p 'test_research_*.py'
node --test tests/research-autonomy-ui.test.cjs
```
