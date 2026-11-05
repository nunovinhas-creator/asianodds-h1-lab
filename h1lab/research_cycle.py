"""One bounded autonomous research cycle.

  memory + new data -> agenda -> plans (LLM and/or offline proposer) -> plan validation
  -> Python execution -> falsification + multiplicity -> append-only memory -> panel

The offline proposer lets the engine run many experiments without extra LLM calls.
Its ranking uses explicit, outcome-blind criteria: novelty against memory,
testability (expected matches with verified FT), data availability, redundancy and
informativeness (market baseline available). Ties break on the plan fingerprint,
never randomly and never by results.

Nothing here writes outside ``memory_path``/``panel_path``, touches H1/FT/Telegram,
frozen forecasts or scientific criteria, or contacts the network.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timezone
from pathlib import Path

from .research_dataset import OUTCOMES, VARIABLES, catalogue, describe
from .research_executor import assign_states, execute, membership
from .research_gates import EXPLORATION_ALLOWED, promotion_guard
from .research_memory import (RUN_KINDS, agenda, append, digest_for_llm, experiment_record,
                              experiments, jaccard, memory_kind, novelty, read_memory,
                              rejected_record, tip)
from .research_plan import PlanError, validate_plan

CYCLE_VERSION = 3   # v3: per-cycle LLM provenance (model, tokens, plan funnel, origins)
LLM_ORIGINS = ('LLM_LIVE', 'RESPONSE_FILE_NOT_LIVE_LLM', 'SIMULATED_LLM')
# Operational memory only accepts hypotheses from a real bounded call or the offline proposer.
ORIGINS_ALLOWED = {'OPERATIONAL': ('LLM_LIVE',),
                   'DEMONSTRATION': ('RESPONSE_FILE_NOT_LIVE_LLM', 'SIMULATED_LLM'),
                   'TEST': LLM_ORIGINS}
VAR_OUTCOMES = {'TOTAL': ['OVER_2_5', 'BTTS_YES'], 'ANY': ['OVER_2_5'], 'CROSS': ['OVER_2_5'],
                'CONTEXT': ['OVER_2_5'], '1X2': ['HOME_WIN', 'AWAY_WIN'], 'AH': ['AH_HOME_COVER']}
MARKET_OF = {o: m for m, outs in OUTCOMES.items() for o in outs}


def _quantiles(values):
    xs = sorted(values)
    if len(xs) < 12:
        return None
    return xs[len(xs) // 3], xs[(2 * len(xs)) // 3]


def candidate_plans(rows):
    """Outcome-blind candidate grid from catalogue variables and their tertiles."""
    out = []
    for name, (typ, market, desc) in sorted(VARIABLES.items()):
        vals = [r['variables'][name] for r in rows if r['variables'].get(name) is not None]
        conds = []
        if typ == 'bool':
            if sum(bool(v) for v in vals) >= 10:
                conds.append(({'var': name}, '%s verdadeiro' % desc))
        else:
            q = _quantiles(vals)
            if q and q[0] < q[1]:
                conds.append(({'op': 'ge', 'args': [{'var': name}, {'const': q[1]}]},
                              '%s no terço superior (>= %s)' % (desc, round(q[1], 4))))
                conds.append(({'op': 'le', 'args': [{'var': name}, {'const': q[0]}]},
                              '%s no terço inferior (<= %s)' % (desc, round(q[0], 4))))
        for cond, label in conds:
            for outcome in VAR_OUTCOMES[market]:
                out.append({'question': ('%s altera %s face ao baseline do mercado?' % (label, outcome))[:400],
                            'hypothesis': ('Jogos com %s têm %s diferente do esperado pelo mercado.'
                                           % (label, outcome))[:600],
                            'null_hypothesis': 'Não há diferença face ao baseline (ou frequência) do controlo.',
                            'market': MARKET_OF[outcome], 'outcome': outcome, 'condition': cond,
                            'rationale': 'Proposta offline determinística (tercis sem resultados).'})
    return out


def rank_offline(rows, memory, dataset_digest, budget, *, exclude=()):
    """Explicit scoring; reads ft_status (availability), never outcome values."""
    ft_rows = [r for r in rows if r['ft_status'] == 'VERIFIED_FT']
    scored = []
    for raw in candidate_plans(rows):
        try:
            plan = validate_plan(raw)
        except PlanError:
            continue
        if plan['fingerprint'] in exclude:
            continue
        nov = novelty(plan, memory, dataset_digest)
        if nov['grade'] == 'DUPLICATE':
            continue
        g = c = 0
        for r in ft_rows:
            m = membership(plan, r)[0]
            if m is True:
                g += 1
            elif m is False:
                c += 1
        known = sum(membership(plan, r)[0] is not None for r in rows)
        testability = min(1.0, min(g, c) / 30.0)
        availability = known / len(rows) if rows else 0.0
        novelty_w = {'NEW': 1.0, 'VARIANT': 0.6, 'RETEST_NEW_DATA': 0.5}[nov['grade']]
        informativeness = 1.0 if OUTCOMES[plan['market']][plan['outcome']] else 0.7
        score = novelty_w * testability * availability * informativeness
        if score <= 0:
            continue
        scored.append((score, plan, nov, {'novelty': novelty_w, 'testability': round(testability, 4),
                                          'availability': round(availability, 4),
                                          'informativeness': informativeness}))
    scored.sort(key=lambda x: (-round(x[0], 9), x[1]['fingerprint']))
    chosen, closures = [], []
    from .research_memory import _vars
    prior = [set(r['plan']['variables_closure']) for r in experiments(memory)]
    per_outcome_cap = max(3, budget // 4)   # market diversity, fixed a priori
    taken = {}
    for score, plan, nov, parts in scored:
        if len(chosen) >= budget:
            break
        if taken.get(plan['outcome'], 0) >= per_outcome_cap:
            continue
        taken[plan['outcome']] = taken.get(plan['outcome'], 0) + 1
        vs = _vars(plan)
        same_outcome = [c for c, o in closures if o == plan['outcome']]
        red = max([jaccard(vs, c) for c in same_outcome] + [0.0])
        final = score * (1 - 0.5 * red) * (1 - 0.2 * max([jaccard(vs, p) for p in prior] + [0.0]))
        parts.update(redundancy=round(red, 4), score=round(final, 6))
        chosen.append((final, plan, nov, parts))
        closures.append((vs, plan['outcome']))
    chosen.sort(key=lambda x: (-round(x[0], 9), x[1]['fingerprint']))
    return [(p, n, s) for _, p, n, s in chosen]


def run_cycle(*, gate, dataset, memory_path, now, run_kind, cycle_label='offline', llm=None,
              offline_budget=None, write=True):
    """Run one cycle. ``llm``: None or {'plans','rejected','new_questions','origin', ...}."""
    if now.tzinfo is None:
        raise ValueError('AWARE_NOW_REQUIRED')
    if run_kind not in RUN_KINDS:
        raise ValueError('RUN_KIND_REQUIRED')
    if gate['state'] != EXPLORATION_ALLOWED:
        return {'status': 'NOT_RUN', 'reason': gate['state'], 'experiments': 0, 'written': 0}
    cfg = gate['config']
    for op in ('odds_trajectories', 'ft_outcomes'):
        if op not in gate.get('allowed_operations', []):
            return {'status': 'NOT_RUN', 'reason': op.upper() + '_BLOCKED', 'experiments': 0, 'written': 0}
    if not cfg.get('offline_cycle_enabled') and not llm:
        return {'status': 'NOT_RUN', 'reason': 'OFFLINE_CYCLE_DISABLED', 'experiments': 0, 'written': 0}
    budget = cfg['max_experiments_per_cycle'] if offline_budget is None else min(
        offline_budget, cfg['max_experiments_per_cycle'])
    memory = read_memory(memory_path)
    if memory and memory_kind(memory) != run_kind:
        return {'status': 'NOT_RUN', 'reason': 'MEMORY_RUN_KIND_MISMATCH', 'experiments': 0, 'written': 0}
    base_tip = tip(memory)
    rows = dataset['rows']
    cycle_id = 'C' + hashlib.sha256((now.isoformat() + dataset['digest'] + cycle_label).encode()).hexdigest()[:15]
    ft_now = sum(r['ft_status'] == 'VERIFIED_FT' for r in rows)
    work, records, skipped = [], [], {'duplicates': 0}
    seen = set()
    if llm:
        origin = llm.get('origin')
        if origin not in ORIGINS_ALLOWED[run_kind]:
            raise ValueError('LLM_ORIGIN_NOT_ALLOWED_FOR_%s:%s' % (run_kind, origin))
        for rej in llm.get('rejected', []):
            records.append(rejected_record(rej['index'], rej['reason'], origin=origin,
                                           cycle_id=cycle_id, now=now, field=rej.get('field'),
                                           detail=rej.get('detail')))
        for plan in llm.get('plans', [])[:cfg['max_llm_plans_per_call']]:
            nov = novelty(plan, memory, dataset['digest'])
            if nov['grade'] == 'DUPLICATE' or plan['fingerprint'] in seen:
                skipped['duplicates'] += 1
                continue
            seen.add(plan['fingerprint'])
            work.append((plan, nov, origin, None))
    offline_ranked = []
    if cfg.get('offline_cycle_enabled') and budget > len(work):
        offline_ranked = rank_offline(rows, memory, dataset['digest'], budget - len(work), exclude=seen)
        for plan, nov, parts in offline_ranked:
            work.append((plan, nov, 'OFFLINE_PROPOSER', parts))
    results = [execute(plan, rows) for plan, _, _, _ in work]
    prior_tests = sum(1 for r in experiments(memory) if r['results'].get('p_value') is not None)
    assign_states(results, prior_tests=prior_tests)
    sources = gate.get('source_sha256', {})
    for (plan, nov, origin, parts), res in zip(work, results):
        res['verified_ft_in_dataset'] = ft_now
        if parts:
            res['priority'] = parts
        rec = experiment_record(plan, res, origin=origin, cycle_id=cycle_id, dataset=dataset,
                                sources_sha256=sources, now=now, nov=nov)
        promotion_guard(rec, gate['scientific_validation_gate'])
        records.append(rec)
    exp_records = [r for r in records if r['record_type'] == 'EXPERIMENT']
    states = {}
    for r in exp_records:
        states[r['state']] = states.get(r['state'], 0) + 1
    future = agenda(memory + exp_records, dataset)
    llm_funnel = llm_provenance(llm, exp_records, skipped['duplicates'])
    cycle = {'record_type': 'CYCLE', 'recorded_at': now.isoformat(), 'cycle_id': cycle_id,
             'cycle_version': CYCLE_VERSION, 'label': cycle_label,
             'llm_origin': (llm or {}).get('origin'),
             'reference_time': now.isoformat(),
             'llm_calls': (llm or {}).get('llm_calls', 0),
             'llm_packet_sha256': (llm or {}).get('packet_sha256'),
             'new_questions_from_llm': (llm or {}).get('new_questions', []),
             'memory_records_before': len(memory),
             'experiments_run': len(exp_records), 'plans_rejected': len(records) - len(exp_records),
             'duplicates_skipped': skipped['duplicates'], 'states': states,
             'dataset_sha256': dataset['digest'], 'verified_ft_in_dataset': ft_now,
             'exploration_gate': gate['state'],
             'scientific_validation_gate': gate['scientific_validation_gate']['state'],
             'next_priorities': future[:20],
             'scientific_status': 'EXPLORATORY_NOT_VALIDATED'}
    cycle.update(llm_funnel)
    records.append(cycle)
    sealed = (append(memory_path, records, run_kind=run_kind, expected_tip=base_tip)
              if write else records)
    return {'status': 'RUN', 'cycle_id': cycle_id, 'experiments': len(exp_records),
            'rejected_plans': len(records) - len(exp_records) - 1, 'states': states,
            'written': len(sealed) if write else 0, 'records': sealed,
            'memory_records_before': len(memory)}


def llm_provenance(llm, exp_records, duplicates):
    """Cycle-level provenance (v3). Distinguishes what the model proposed from what the
    deterministic offline proposer contributed, so a call is never mistaken for research."""
    llm = llm or {}
    from_llm = sum(1 for r in exp_records if r['origin'] in LLM_ORIGINS)
    reasons = {}
    for rej in llm.get('rejected', []):
        reasons[rej['reason']] = reasons.get(rej['reason'], 0) + 1
    usage = llm.get('usage') or {}
    tokens = usage.get('tokens') if isinstance(usage.get('tokens'), dict) else {}
    received = llm.get('received')
    if received is None and llm:
        received = len(llm.get('plans', [])) + len(llm.get('rejected', []))
    return {
        'llm_model': llm.get('model') if llm else None,
        'llm_response_sha256': llm.get('response_sha256'),
        'llm_tokens': {k: v for k, v in tokens.items()
                       if k in ('prompt_tokens', 'completion_tokens', 'total_tokens')} or None,
        'llm_tokens_measurement': usage.get('measurement') if llm else None,
        'llm_contract_version': llm.get('contract_version'),
        'llm_json_mode': llm.get('json_mode'),
        'llm_neurons_bound': llm.get('neurons_bound'),
        'llm_neurons_from_tokens': llm.get('neurons_from_tokens'),
        'llm_plans_received': received or 0,
        'llm_plans_accepted': len(llm.get('plans', [])),
        'llm_plans_rejected': len(llm.get('rejected', [])),
        'llm_rejection_reasons': dict(sorted(reasons.items())),
        'llm_plans_duplicate_skipped': duplicates if llm else 0,
        'experiments_from_llm': from_llm,
        'experiments_from_offline': sum(1 for r in exp_records if r['origin'] == 'OFFLINE_PROPOSER'),
    }


def llm_packet(gate, dataset, memory, max_plans=3, *, budget_bytes=None):
    from .research_context import trajectory_examples
    from .research_llm import PACKET_BUDGET_BYTES, build_packet
    return build_packet(gate=gate, dataset_description=describe(dataset),
                        variable_catalogue=catalogue(dataset['rows']),
                        memory_digest=digest_for_llm(memory), agenda_items=agenda(memory, dataset),
                        max_plans=max_plans, budget_bytes=budget_bytes or PACKET_BUDGET_BYTES,
                        trajectory_examples=trajectory_examples(dataset, gate.get('source_sha256')))


# ---------------------------------------------------------------------------
# Public panel (presentation data only; derived from memory + gates)

def _card(r):
    res = r['results']
    return {'experiment_id': r['experiment_id'], 'recorded_at': r['recorded_at'],
            'origin': r['origin'], 'question': r['question'], 'hypothesis': r['hypothesis'],
            'market': r['plan']['market'], 'outcome': r['plan']['outcome'],
            'variables': r['plan']['variables_closure'],
            'new_indicators': [{'name': i['name'], 'description': i['description']}
                               for i in r['plan']['indicators']],
            'group_n': (res.get('group') or {}).get('n'), 'control_n': (res.get('control') or {}).get('n'),
            'group_rate': (res.get('group') or {}).get('observed_rate'),
            'control_rate': (res.get('control') or {}).get('observed_rate'),
            'effect': res.get('effect'), 'effect_ci95': res.get('effect_ci95_day_bootstrap'),
            'primary_statistic': res.get('primary_statistic'), 'p_value': res.get('p_value'),
            'q_value': res.get('q_value_bh_cycle'), 'checks': res.get('checks'),
            'missing': res.get('missing', []), 'limitations': r['limitations'],
            'state': r['state'], 'novelty': r['novelty'], 'version': r['version'],
            'next_question': r['next_question'], 'scientific_status': r['scientific_status']}


PROVENANCE_NOTE = {
    'OPERATIONAL': 'Investigação operacional: ciclos executados pelo sistema sobre os dados publicados.',
    'DEMONSTRATION': ('DEMONSTRAÇÃO: fotografia de referência gerada para revisão. Não é investigação '
                      'autónoma atual; as hipóteses "LLM" vieram de um ficheiro ou de um LLM simulado, '
                      'sem chamadas reais a fornecedores.'),
    'TEST': ('TESTE: verificação automática, nunca publicada como investigação; pode usar dados '
             'reais do repositório ou sintéticos e hipóteses simuladas.'),
}


MODEL_NOT_RECORDED = 'NAO_REGISTADO_CICLO_ANTERIOR_A_PROVENIENCIA_V3'
# Legacy cycles did not record the model. This is presentation-only knowledge taken from
# the code of the commit the run executed (GitHub Actions run 42021728675, head
# 71d00ffb51192a26800ef09d3c7e0d1447dd91c2, scripts/lab_research_cycle.py MODEL). It is
# shown as INFERRED, never written into the memory.
LEGACY_MODEL_FROM_CODE = {
    'Ceede16a74f0ae09': {'model': '@cf/meta/llama-3.1-8b-instruct-fast', 'run_id': 42021728675,
                         'source': 'scripts/lab_research_cycle.py@71d00ffb51192a26800ef09d3c7e0d1447dd91c2'},
}


def cycle_funnels(memory):
    """Per-cycle LLM funnel. v3 cycles carry it; for older cycles it is DERIVED from the
    records of that cycle (PLAN_REJECTED / EXPERIMENT origins) without rewriting them."""
    by_cycle = {}
    for r in memory:
        if r.get('record_type') in ('EXPERIMENT', 'PLAN_REJECTED'):
            by_cycle.setdefault(r.get('cycle_id'), []).append(r)
    out = []
    for c in (r for r in memory if r.get('record_type') == 'CYCLE'):
        recs = by_cycle.get(c['cycle_id'], [])
        exps = [r for r in recs if r['record_type'] == 'EXPERIMENT']
        rejs = [r for r in recs if r['record_type'] == 'PLAN_REJECTED']
        from_llm = sum(1 for r in exps if r['origin'] in LLM_ORIGINS)
        offline = sum(1 for r in exps if r['origin'] == 'OFFLINE_PROPOSER')
        reasons = {}
        for r in rejs:
            reasons[r['reason']] = reasons.get(r['reason'], 0) + 1
        dup = c.get('duplicates_skipped', 0) if c.get('llm_origin') else 0
        v3 = c.get('cycle_version', 0) >= 3
        out.append({
            'cycle_id': c['cycle_id'], 'recorded_at': c['recorded_at'], 'label': c.get('label'),
            'llm_origin': c.get('llm_origin'),
            'model': c.get('llm_model') if v3 else (MODEL_NOT_RECORDED if c.get('llm_origin') else None),
            'model_inferred_from_code': None if v3 else LEGACY_MODEL_FROM_CODE.get(c['cycle_id']),
            'provenance_source': 'CYCLE_RECORD_V3' if v3 else 'DERIVED_FROM_RECORDS_LEGACY_CYCLE',
            'llm_calls': c.get('llm_calls', 0),
            'tokens': c.get('llm_tokens') if v3 else None,
            'plans_received': (c.get('llm_plans_received', 0) if v3
                               else (len(rejs) + from_llm + dup if c.get('llm_origin') else 0)),
            'plans_accepted': c.get('llm_plans_accepted', 0) if v3 else from_llm + dup,
            'plans_rejected': len(rejs),
            'rejection_reasons': dict(sorted(reasons.items())),
            'plans_duplicate_skipped': dup,
            'experiments_from_llm': from_llm,
            'experiments_from_offline': offline,
        })
    return out


def provenance(memory):
    kind = memory_kind(memory) or 'OPERATIONAL'
    cycles = [r for r in memory if r.get('record_type') == 'CYCLE']
    origins = sorted({c.get('llm_origin') or 'OFFLINE_PROPOSER_ONLY' for c in cycles})
    real_calls = sum(c.get('llm_calls', 0) for c in cycles if c.get('llm_origin') == 'LLM_LIVE')
    live_exps = sum(1 for r in experiments(memory) if r['origin'] == 'LLM_LIVE')
    return {'kind': kind, 'note': PROVENANCE_NOTE[kind],
            'reference_time': cycles[-1]['recorded_at'] if cycles else None,
            'first_cycle_at': cycles[0]['recorded_at'] if cycles else None,
            'cycle_origins': origins, 'real_llm_calls': real_calls,
            'experiments_from_live_llm': live_exps,
            'experiments_from_offline': sum(1 for r in experiments(memory) if r['origin'] == 'OFFLINE_PROPOSER'),
            'simulated_or_file_llm_cycles': sum(1 for c in cycles if c.get('llm_origin') not in (None, 'LLM_LIVE')),
            # A real call that produced no executed plan is not autonomous research.
            'is_current_autonomous_research': kind == 'OPERATIONAL' and real_calls > 0 and live_exps > 0}


DETERMINISTIC_LIMITATIONS = [
    'Hipóteses geradas por uma grelha fixa de tercis das variáveis do catálogo, sem uso de resultados.',
    'Não formula relações novas nem explicações alternativas: é uma varredura determinística.',
    'Muitos testes por ciclo: os resultados dependem da correção de testes múltiplos e continuam exploratórios.',
]


def research_split(memory, cards):
    """Autonomous (model-proposed) vs deterministic (offline grid) research, never merged."""
    funnels = cycle_funnels(memory)
    llm_cycles = [f for f in funnels if f['llm_origin']]
    llm_cards = [c for c in cards if c['origin'] in LLM_ORIGINS]
    off_cards = [c for c in cards if c['origin'] == 'OFFLINE_PROPOSER']
    states = {}
    for c in off_cards:
        states[c['state']] = states.get(c['state'], 0) + 1
    models = sorted({f['model'] for f in llm_cycles if f['model']})
    total = lambda k: sum(f[k] for f in llm_cycles)
    return {
        'autonomous': {
            'models': models,
            'cycles': llm_cycles[-20:],
            'real_llm_calls': sum(f['llm_calls'] for f in llm_cycles if f['llm_origin'] == 'LLM_LIVE'),
            'plans_received': total('plans_received'), 'plans_accepted': total('plans_accepted'),
            'plans_rejected': total('plans_rejected'),
            'plans_duplicate_skipped': total('plans_duplicate_skipped'),
            'experiments_executed': total('experiments_from_llm'),
            'distinct_questions': len(llm_cards),
            'note': ('Planos propostos pelo modelo, validados pela DSL e executados pelo Python. '
                     'Um plano aceite é apenas executável, não uma hipótese demonstrada.'),
        },
        'deterministic': {
            'proposer': 'OFFLINE_PROPOSER',
            'experiments_executed': sum(f['experiments_from_offline'] for f in funnels),
            'distinct_questions': len(off_cards),
            'states': dict(sorted(states.items())),
            'limitations': DETERMINISTIC_LIMITATIONS,
        },
    }


def build_panel(memory, gate, *, now):
    latest = {}
    for r in experiments(memory):
        latest[r['fingerprint']] = r
    cards = sorted((_card(r) for r in latest.values()),
                   key=lambda c: (c['recorded_at'], c['experiment_id']), reverse=True)
    cycles = [r for r in memory if r.get('record_type') == 'CYCLE']
    rejected_plans = [r for r in memory if r.get('record_type') == 'PLAN_REJECTED']
    last = cycles[-1] if cycles else None
    by = lambda *states: [c for c in cards if c['state'] in states]
    return {
        'schema_version': 2, 'generated_at': now.astimezone(timezone.utc).isoformat(),
        'status': 'EXPLORATORY_RESEARCH_NOT_VALIDATION',
        'provenance': provenance(memory),
        'gates': {'exploration': gate['state'],
                  'scientific_validation': gate['scientific_validation_gate']['state'],
                  'limitations': gate.get('limitations', [])},
        'research_split': research_split(memory, cards),
        'memory': {'records': len(memory), 'experiments': len(experiments(memory)),
                   'distinct_questions': len(latest), 'cycles': len(cycles),
                   'last_sha256': memory[-1]['sha256'] if memory else None},
        'last_cycle': last and dict({k: last[k] for k in ('cycle_id', 'recorded_at', 'label', 'llm_calls',
                                                          'experiments_run', 'plans_rejected', 'states',
                                                          'verified_ft_in_dataset')},
                                    funnel=cycle_funnels(memory)[-1]),
        'investigating': (last or {}).get('next_priorities', [])[:20],
        'discovered': by('PROMISING_EXPLORATORY')[:30],
        'rejected': by('NO_SUPPORT_IN_DATA', 'FALSIFIED_EXPLORATORY')[:40],
        'rejected_plans': [dict({'recorded_at': r['recorded_at'], 'origin': r['origin'], 'reason': r['reason'],
                                 'cycle_id': r.get('cycle_id'), 'plan_index': r.get('plan_index')},
                                **{k: r[k] for k in ('field', 'detail') if k in r})
                           for r in rejected_plans[-20:]],
        'needs_more_data': by('INSUFFICIENT_DATA', 'INCONCLUSIVE')[:40],
        'validated': [],
        'validated_note': ('Nenhuma estratégia validada. A validação exige pré-registo, jogos futuros '
                           'independentes e o gate científico (>=99% de cobertura, cronologia, '
                           '>=1000 FT fora da amostra). A investigação exploratória nunca valida.'),
    }


def write_panel(path, panel):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(panel, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False)
    if len(data.encode()) > 2_000_000:
        raise ValueError('PANEL_TOO_LARGE')
    tmp = path.with_suffix('.tmp')
    tmp.write_text(data + '\n', encoding='utf-8')
    tmp.replace(path)
