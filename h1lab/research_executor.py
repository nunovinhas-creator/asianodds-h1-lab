"""Deterministic exploratory experiment executor. Python computes; the LLM never does.

For a validated plan (``research_plan.validate_plan``) and a dataset
(``research_dataset``), it computes:

* effective sample sizes (group / control / unknown / with FT / with baseline);
* observed frequencies with Wilson intervals and a Newcombe interval for the difference;
* market baseline comparison: residual (y - p) by group, Brier and log-loss of the
  baseline, and the difference-in-residuals (the part NOT already priced by the market);
* a day-stratified permutation test of the primary statistic (deterministic seed);
* a chronological out-of-sample split (train days -> test days), period stability,
  and stratified (lead time, line, competition type) confounding sensitivity;
* explicit falsification checks, multiplicity correction and an exploratory state.

Anti-leakage: membership is computed from ``row['variables']`` only (pre-kickoff),
before any outcome is touched; outcomes are read afterwards. Missing FT is excluded,
never counted as a loss. Insufficient data returns INSUFFICIENT_DATA with reasons.

Nothing here can produce a validated strategy: ``scientific_status`` is always
EXPLORATORY_NOT_VALIDATED and promotion requires preregistration + prospective data.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict

from .lab_stats import bh_qvalues, fisher, newcombe_diff, wilson
from .research_dataset import OUTCOMES
from .research_dsl import evaluate
from .v6_shadow import utc

EXECUTOR_VERSION = 'RX1'
MIN_N = 15
PERMUTATIONS = 2000
BOOTSTRAP = 1000
OOS_TRAIN_SHARE = 0.7
SHRINK = 20
ALPHA = 0.05
Q_MAX = 0.10


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def membership(plan, row):
    """(in_group, in_control) from PRE-KICKOFF variables only. None = unknown."""
    env = dict(row['variables'])
    for ind in plan['indicators']:
        env[ind['name']] = evaluate(ind['expr'], env)
    g = evaluate(plan['condition'], env)
    if plan.get('control_condition') is None:
        return (None, None) if g is None else (g, not g)
    c = evaluate(plan['control_condition'], env)
    if g is None or c is None:
        return None, None
    if g and c:
        return 'OVERLAP', 'OVERLAP'
    return g, c


def _bins(row):
    v = row['variables']
    lead = v.get('lead_first_min')
    line = v.get('total_line_last')
    ctx = ('CUP' if v.get('ctx_cup') else 'YOUTH_RESERVE' if v.get('ctx_youth_reserve')
           else 'LEAGUE_OTHER' if v.get('ctx_league_other') else 'UNKNOWN')
    return {'lead_bin': None if lead is None else ('LT_6H' if lead < 360 else
                                                   '6_24H' if lead <= 1440 else 'GT_24H'),
            'line_bin': None if line is None else ('LOW' if line <= 2.25 else
                                                   'HIGH' if line >= 3.25 else 'MID'),
            'competition_type': ctx}


def _logloss(y, p):
    p = min(1 - 1e-6, max(1e-6, p))
    return -(y * math.log(p) + (1 - y) * math.log1p(-p))


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _stat(group, control, use_baseline):
    """Primary statistic: difference in mean residual (baseline) or in frequency."""
    if not group or not control:
        return None
    if use_baseline:
        return _mean([y - p for y, p, _ in group]) - _mean([y - p for y, p, _ in control])
    return _mean([y for y, _, _ in group]) - _mean([y for y, _, _ in control])


def _seed(plan, salt):
    return int(hashlib.sha256((plan['fingerprint'] + salt).encode()).hexdigest()[:12], 16)


def permutation_p(group, control, use_baseline, seed):
    """Two-sided, labels permuted WITHIN calendar day (keeps day-level dependence)."""
    obs = _stat(group, control, use_baseline)
    if obs is None:
        return None
    by_day = defaultdict(list)
    for item in group:
        by_day[item[2]].append((item, True))
    for item in control:
        by_day[item[2]].append((item, False))
    days = [v for _, v in sorted(by_day.items())]
    rng = random.Random(seed)
    hits = 0
    for _ in range(PERMUTATIONS):
        g, c = [], []
        for items in days:
            labels = [lab for _, lab in items]
            rng.shuffle(labels)
            for (it, _), lab in zip(items, labels):
                (g if lab else c).append(it)
        s = _stat(g, c, use_baseline)
        if s is not None and abs(s) >= abs(obs) - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def bootstrap_ci(group, control, use_baseline, seed):
    """Day-cluster bootstrap 95% interval of the primary statistic."""
    by_day = defaultdict(lambda: ([], []))
    for it in group:
        by_day[it[2]][0].append(it)
    for it in control:
        by_day[it[2]][1].append(it)
    days = sorted(by_day)
    if len(days) < 2:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(BOOTSTRAP):
        g, c = [], []
        for _ in days:
            d = by_day[days[rng.randrange(len(days))]]
            g += d[0]
            c += d[1]
        s = _stat(g, c, use_baseline)
        if s is not None:
            stats.append(s)
    if len(stats) < BOOTSTRAP * 0.9:
        return None
    stats.sort()
    return [_r(stats[int(0.025 * len(stats))]), _r(stats[int(0.975 * len(stats)) - 1])]


def _summary(items, use_baseline, binary):
    n = len(items)
    if not n:
        return {'n': 0}
    ys = [y for y, _, _ in items]
    out = {'n': n, 'observed_rate': _r(_mean(ys)), 'days': len({d for _, _, d in items})}
    if binary:
        k = int(round(sum(ys)))
        out['hits'] = k
        ci = wilson(k, n)
        out['observed_rate_ci95'] = [_r(ci[0]), _r(ci[1])] if ci else None
    if use_baseline:
        ps = [p for _, p, _ in items]
        out['market_probability_mean'] = _r(_mean(ps))
        out['residual_mean'] = _r(_mean([y - p for y, p, _ in items]))
        out['baseline_brier'] = _r(_mean([(y - p) ** 2 for y, p, _ in items]))
        out['baseline_log_loss'] = _r(_mean([_logloss(y, p) for y, p, _ in items]))
    return out


def _split_days(items):
    days = sorted({d for _, _, d in items})
    if len(days) < 4:
        return None, days
    cut = days[min(len(days) - 1, max(1, int(len(days) * OOS_TRAIN_SHARE)))]
    return cut, days


def execute(plan, rows, *, min_n=MIN_N):
    """Run one validated plan over the dataset rows. Pure function; no writes."""
    base_key = OUTCOMES[plan['market']][plan['outcome']]
    use_baseline = base_key is not None
    binary = plan['outcome'] != 'AH_HOME_COVER'
    counts = {'rows': len(rows), 'group': 0, 'control': 0, 'unknown': 0, 'overlap': 0,
              'group_pending_ft': 0, 'control_pending_ft': 0,
              'group_without_baseline': 0, 'control_without_baseline': 0}
    assigned = []
    for row in rows:
        if utc(row['decision_at']) is None or utc(row['decision_at']) >= utc(row['kickoff_utc']):
            raise ValueError('LEAKAGE_DECISION_NOT_BEFORE_KICKOFF')
        g, c = membership(plan, row)
        if g is None:
            counts['unknown'] += 1
            continue
        if g == 'OVERLAP':
            counts['overlap'] += 1
            continue
        if not g and not c:
            continue
        side = 'group' if g else 'control'
        counts[side] += 1
        assigned.append((side, row))
    # ---- outcomes are only touched from here on
    items = {'group': [], 'control': []}
    for side, row in assigned:
        out = row['outcome']
        y = out.get(plan['outcome']) if out else None
        if y is None:
            counts[side + '_pending_ft'] += 1
            continue
        p = row['baselines'].get(base_key) if use_baseline else 0.0
        if p is None:
            counts[side + '_without_baseline'] += 1
            continue
        items[side].append((float(y), float(p), row['kickoff_utc'][:10]))
    G, C = items['group'], items['control']
    result = {'executor_version': EXECUTOR_VERSION, 'counts': counts,
              'baseline': base_key or 'UNAVAILABLE',
              'primary_statistic': ('DIFFERENCE_IN_MEAN_RESIDUAL_VS_MARKET' if use_baseline
                                    else 'DIFFERENCE_IN_OBSERVED_FREQUENCY_NO_MARKET_BASELINE'),
              'group': _summary(G, use_baseline, binary),
              'control': _summary(C, use_baseline, binary)}
    limitations = []
    if not use_baseline:
        limitations.append('Sem preço de mercado para %s: comparação apenas de frequências; '
                           'não mede informação além do mercado.' % plan['outcome'])
    if counts['unknown']:
        limitations.append('%d jogos com variáveis desconhecidas excluídos (nunca usados como controlo).'
                           % counts['unknown'])
    if counts['group_pending_ft'] + counts['control_pending_ft']:
        limitations.append('%d jogos sem FT verificado excluídos (pendente, não derrota).'
                           % (counts['group_pending_ft'] + counts['control_pending_ft']))
    if not binary:
        limitations.append('AH: resultado como fração de cobertura (meia vitória=0,75, push=0,5).')
    missing = []
    if len(G) < min_n:
        missing.append('Grupo precisa de >= %d jogos com FT verificado%s; tem %d.'
                       % (min_n, ' e baseline' if use_baseline else '', len(G)))
    if len(C) < min_n:
        missing.append('Controlo precisa de >= %d jogos com FT verificado%s; tem %d.'
                       % (min_n, ' e baseline' if use_baseline else '', len(C)))
    if missing:
        result.update(state='INSUFFICIENT_DATA', missing=missing, checks={},
                      limitations=limitations, p_value=None)
        return result
    stat = _stat(G, C, use_baseline)
    result['effect'] = _r(stat)
    result['effect_ci95_day_bootstrap'] = bootstrap_ci(G, C, use_baseline, _seed(plan, 'boot'))
    if binary:
        kg, kc = int(sum(y for y, _, _ in G)), int(sum(y for y, _, _ in C))
        nd = newcombe_diff(kg, len(G), kc, len(C))
        result['frequency_difference_ci95'] = [_r(nd[0]), _r(nd[1])] if nd else None
        result['fisher_p_descriptive'] = _r(fisher(kg, len(G), kc, len(C)), 6)
    p = permutation_p(G, C, use_baseline, _seed(plan, 'perm'))
    result['p_value'] = _r(p, 6)
    result['p_value_method'] = 'DAY_STRATIFIED_PERMUTATION_%d' % PERMUTATIONS
    # ---- chronological out-of-sample
    cut, days = _split_days(G + C)
    oos = {'split_day': cut, 'train_share_of_days': OOS_TRAIN_SHARE}
    if cut:
        gtr = [x for x in G if x[2] < cut]
        ctr = [x for x in C if x[2] < cut]
        gte = [x for x in G if x[2] >= cut]
        cte = [x for x in C if x[2] >= cut]
        oos.update(train={'group_n': len(gtr), 'control_n': len(ctr),
                          'effect': _r(_stat(gtr, ctr, use_baseline))},
                   test={'group_n': len(gte), 'control_n': len(cte),
                         'effect': _r(_stat(gte, cte, use_baseline))})
        if use_baseline and gtr and gte:
            offset = sum(y - q for y, q, _ in gtr) / (len(gtr) + SHRINK)
            base_ll = _mean([_logloss(y, q) for y, q, _ in gte])
            model_ll = _mean([_logloss(y, min(1, max(0, q + offset))) for y, q, _ in gte])
            oos['group_offset_from_train'] = _r(offset)
            oos['test_group_log_loss'] = {'market_baseline': _r(base_ll), 'train_offset_model': _r(model_ll)}
    result['out_of_sample'] = oos
    # ---- period stability (first vs second half of calendar days)
    all_days = sorted({d for _, _, d in G + C})
    half = all_days[len(all_days) // 2] if len(all_days) >= 2 else None
    periods = {}
    if half:
        for name, sel in (('first_half', lambda d: d < half), ('second_half', lambda d: d >= half)):
            g = [x for x in G if sel(x[2])]
            c = [x for x in C if sel(x[2])]
            periods[name] = {'group_n': len(g), 'control_n': len(c),
                             'effect': _r(_stat(g, c, use_baseline))}
    result['periods'] = periods
    # ---- confounding sensitivity: stratum-weighted effect
    strata = {}
    lookup = {}
    for side, row in assigned:
        lookup[id(row)] = _bins(row)
    for stratum in plan['confounders']:
        cells = defaultdict(lambda: ([], []))
        for side, row in assigned:
            out = row['outcome']
            y = out.get(plan['outcome']) if out else None
            q = row['baselines'].get(base_key) if use_baseline else 0.0
            if y is None or q is None:
                continue
            key = lookup[id(row)][stratum]
            cells[key][0 if side == 'group' else 1].append((float(y), float(q), row['kickoff_utc'][:10]))
        num = den = 0.0
        detail = {}
        for key, (g, c) in sorted(cells.items(), key=lambda kv: str(kv[0])):
            detail[str(key)] = {'group_n': len(g), 'control_n': len(c),
                                'effect': _r(_stat(g, c, use_baseline))}
            if len(g) >= 2 and len(c) >= 2:
                w = len(g) * len(c) / (len(g) + len(c))
                num += w * _stat(g, c, use_baseline)
                den += w
        strata[stratum] = {'adjusted_effect': _r(num / den) if den else None, 'cells': detail}
    result['confounding'] = strata
    # ---- falsification checks (F5 multiplicity is added by assign_states)
    checks = {}
    checks['F1_PERMUTATION'] = 'PASS' if p is not None and p < ALPHA else 'FAIL'
    te = (oos.get('test') or {}).get('effect')
    tr = (oos.get('train') or {}).get('effect')
    if te is None or tr is None or min(oos['test']['group_n'], oos['test']['control_n']) < 5:
        checks['F2_OUT_OF_SAMPLE_SIGN'] = 'NOT_APPLICABLE'
    else:
        checks['F2_OUT_OF_SAMPLE_SIGN'] = 'PASS' if (te > 0) == (stat > 0) and (tr > 0) == (stat > 0) and te != 0 else 'FAIL'
    pe = [v['effect'] for v in periods.values() if v['effect'] is not None and min(v['group_n'], v['control_n']) >= 5]
    if len(pe) < 2:
        checks['F3_PERIOD_STABILITY'] = 'NOT_APPLICABLE'
    else:
        checks['F3_PERIOD_STABILITY'] = 'PASS' if all((e > 0) == (stat > 0) and e != 0 for e in pe) else 'FAIL'
    adj = [v['adjusted_effect'] for v in strata.values() if v['adjusted_effect'] is not None]
    if not adj or stat == 0:
        checks['F4_CONFOUNDING'] = 'NOT_APPLICABLE'
    else:
        checks['F4_CONFOUNDING'] = 'PASS' if all((a > 0) == (stat > 0) and abs(a) >= 0.5 * abs(stat) for a in adj) else 'FAIL'
    result['checks'] = checks
    result['limitations'] = limitations
    result['state'] = None  # assigned after multiplicity correction
    return result


def assign_states(results, prior_tests=0):
    """Multiplicity (BH within cycle; Bonferroni over cumulative family) and states.

    ``prior_tests``: experiments already executed in earlier cycles (from memory), so
    repeated searching is penalised rather than forgotten.
    """
    idx = [i for i, r in enumerate(results) if r.get('p_value') is not None and r['state'] is None]
    qs = bh_qvalues([results[i]['p_value'] for i in idx])
    family = len(idx) + max(0, prior_tests)
    for i, q in zip(idx, qs):
        r = results[i]
        r['q_value_bh_cycle'] = _r(q, 6)
        r['p_bonferroni_cumulative'] = _r(min(1.0, r['p_value'] * family), 6)
        r['multiplicity_family_size'] = family
        r['checks']['F5_MULTIPLICITY'] = 'PASS' if q < Q_MAX else 'FAIL'
        c = r['checks']
        if c['F1_PERMUTATION'] == 'FAIL':
            r['state'] = 'NO_SUPPORT_IN_DATA'
        elif 'FAIL' in (c['F2_OUT_OF_SAMPLE_SIGN'], c['F3_PERIOD_STABILITY'], c['F4_CONFOUNDING']):
            r['state'] = 'FALSIFIED_EXPLORATORY'
        elif c['F5_MULTIPLICITY'] == 'FAIL' or 'NOT_APPLICABLE' in c.values():
            r['state'] = 'INCONCLUSIVE'
        else:
            r['state'] = 'PROMISING_EXPLORATORY'
    for r in results:
        if r['state'] is None:
            r['state'] = 'INCONCLUSIVE'
        r['scientific_status'] = 'EXPLORATORY_NOT_VALIDATED'
        r['promotion_eligible'] = False
        r['requires_for_validation'] = [
            'Pré-registo do plano antes de novos jogos',
            'Avaliação em jogos futuros independentes (fora da amostra prospetiva)',
            'SCIENTIFIC_VALIDATION_GATE autorizado (cobertura >=99%, cronologia, >=1000 FT OOS)']
    return results
