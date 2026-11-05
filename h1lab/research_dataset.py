"""Exploratory per-match research dataset built from real odds trajectories.

Separation of concerns (anti-leakage by construction):

* ``variables``  - computed ONLY from Telegram/V4 snapshots observed strictly before
  kickoff (and never after the decision time). This is the only thing the indicator
  language (``research_dsl``) can read.
* ``baselines``  - market probabilities from the last usable pre-decision quote.
* ``outcome``    - verified FT score and derived targets, kept in a separate field that
  the DSL cannot reach. Missing/unverified FT is ``None`` (pending, never a loss).

No interpolation: changes between two messages are counted as *unobserved* gaps.
Bookmaker identity and in-play quotes are not present in the sources, so the
corresponding phenomena are declared UNAVAILABLE instead of being invented.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone

from .market_math import fair_probs, implied_lambda, one_x_two_probs, prob_total_over
from .timeline import match_timeline
from .v6_shadow import utc, quality, _competition_type

DATASET_VERSION = 1
LAMBDA_EPS = 0.05
PROB_EPS = 0.01


# name -> (type, market, description). Types: 'num' or 'bool'.
VARIABLES = {
    # ---- Time / sequence
    'n_messages': ('num', 'ANY', 'Mensagens antes do início'),
    'n_episodes': ('num', 'ANY', 'Episódios de movimento distintos antes do início'),
    'lead_first_min': ('num', 'ANY', 'Minutos entre a 1.ª mensagem e o início'),
    'lead_last_min': ('num', 'ANY', 'Minutos entre a última mensagem pré-início e o início'),
    'span_min': ('num', 'ANY', 'Minutos entre a 1.ª e a última mensagem pré-início'),
    'max_gap_min': ('num', 'ANY', 'Maior intervalo sem observação entre mensagens (min)'),
    'kickoff_hour_utc': ('num', 'ANY', 'Hora UTC do início'),
    # ---- Total: line and implied goals (lambda)
    'total_msgs': ('num', 'TOTAL', 'Mensagens com o mercado Total'),
    'total_line_first': ('num', 'TOTAL', 'Linha Total na 1.ª observação'),
    'total_line_last': ('num', 'TOTAL', 'Linha Total na última observação'),
    'total_line_net': ('num', 'TOTAL', 'Variação líquida da linha Total'),
    'total_line_ups': ('num', 'TOTAL', 'Subidas de linha Total observadas numa mensagem'),
    'total_line_downs': ('num', 'TOTAL', 'Descidas de linha Total observadas numa mensagem'),
    'lambda_first': ('num', 'TOTAL', 'Golos implícitos na 1.ª observação'),
    'lambda_last': ('num', 'TOTAL', 'Golos implícitos na última observação'),
    'lambda_net': ('num', 'TOTAL', 'Variação líquida dos golos implícitos'),
    'lambda_abs_path': ('num', 'TOTAL', 'Soma das variações absolutas observadas dos golos implícitos'),
    'lambda_sd': ('num', 'TOTAL', 'Desvio-padrão dos golos implícitos observados (estabilidade)'),
    'lambda_moves_up': ('num', 'TOTAL', 'Mensagens com golos implícitos a subir >= 0,05'),
    'lambda_moves_down': ('num', 'TOTAL', 'Mensagens com golos implícitos a descer >= 0,05'),
    'lambda_reversals': ('num', 'TOTAL', 'Inversões de sentido entre movimentos sucessivos'),
    'lambda_max_run': ('num', 'TOTAL', 'Maior sequência de movimentos consecutivos no mesmo sentido'),
    'lambda_last_dir': ('num', 'TOTAL', 'Sentido do último movimento (-1, 0, 1)'),
    'lambda_first_dir': ('num', 'TOTAL', 'Sentido do primeiro movimento (-1, 0, 1)'),
    'lambda_velocity_h': ('num', 'TOTAL', 'Variação líquida dos golos implícitos por hora'),
    'lambda_accel_h': ('num', 'TOTAL', 'Velocidade 2.ª metade menos 1.ª metade (por hora)'),
    'total_unobserved_changes': ('num', 'TOTAL', 'Mudanças de cotação entre mensagens não observadas'),
    'lambda_unobserved_net': ('num', 'TOTAL', 'Variação dos golos implícitos em intervalos não observados'),
    'line_up_then_lambda_down': ('bool', 'TOTAL', 'Subida de linha seguida de descida posterior dos golos implícitos'),
    'line_down_then_lambda_up': ('bool', 'TOTAL', 'Descida de linha seguida de subida posterior dos golos implícitos'),
    'total_overround_last': ('num', 'TOTAL', 'Margem do último preço Over/Under'),
    # ---- 1X2
    'x12_msgs': ('num', '1X2', 'Mensagens com 1X2'),
    'p_home_first': ('num', '1X2', 'Prob. sem margem da casa na 1.ª observação'),
    'p_home_last': ('num', '1X2', 'Prob. sem margem da casa na última observação'),
    'p_home_net': ('num', '1X2', 'Variação da probabilidade da casa'),
    'p_draw_net': ('num', '1X2', 'Variação da probabilidade do empate'),
    'p_away_net': ('num', '1X2', 'Variação da probabilidade do visitante'),
    'x12_reversals': ('num', '1X2', 'Inversões de sentido da probabilidade da casa (>=1 pp)'),
    # ---- Asian handicap (home line; more negative = home more favoured)
    'ah_msgs': ('num', 'AH', 'Mensagens com handicap asiático'),
    'ah_line_first': ('num', 'AH', 'Linha AH (casa) na 1.ª observação'),
    'ah_line_last': ('num', 'AH', 'Linha AH (casa) na última observação'),
    'ah_line_net': ('num', 'AH', 'Variação líquida da linha AH'),
    'ah_line_moves': ('num', 'AH', 'Alterações de linha AH observadas numa mensagem'),
    # ---- Cross-market
    'total_ah_same_msg': ('num', 'CROSS', 'Mensagens com Total e AH ao mesmo tempo'),
    'total_1x2_same_msg': ('num', 'CROSS', 'Mensagens com Total e 1X2 ao mesmo tempo'),
    'trigger_total_share': ('num', 'CROSS', 'Fração de alertas disparados pelo Total'),
    # ---- Context (heuristic label, never a proven division)
    'ctx_cup': ('bool', 'CONTEXT', 'Competição com nome de taça'),
    'ctx_youth_reserve': ('bool', 'CONTEXT', 'Competição jovem/reservas'),
    'ctx_league_other': ('bool', 'CONTEXT', 'Outra competição (liga)'),
}
UNAVAILABLE_PHENOMENA = {
    'bookmaker_divergence': 'Identidade do operador não existe nas fontes; não comparável.',
    'live_in_play': 'Sem cotações temporais em jogo; só pré-início.',
    'btts_market_price': 'Preço Ambas Marcam não é capturado (campo não verificado no V4).',
}
# market -> outcome -> baseline key (None = no market baseline available)
OUTCOMES = {
    'TOTAL_GOALS': {'OVER_2_5': 'p_over_2_5'},
    'BTTS': {'BTTS_YES': None},
    '1X2': {'HOME_WIN': 'p_home', 'DRAW': 'p_draw', 'AWAY_WIN': 'p_away'},
    'ASIAN_HANDICAP': {'AH_HOME_COVER': 'p_ah_home'},
}


def _sign(x, eps):
    return 1 if x > eps else -1 if x < -eps else 0


def _runs(dirs):
    """(reversals, longest same-direction run) over non-zero directions."""
    nz = [d for d in dirs if d]
    rev = sum(1 for a, b in zip(nz, nz[1:]) if a != b)
    best = cur = 0
    prev = 0
    for d in nz:
        cur = cur + 1 if d == prev else 1
        prev = d
        best = max(best, cur)
    return rev, best


def _lam(side):
    if not isinstance(side, dict):
        return None
    return implied_lambda(side.get('line'), side.get('over_price'), side.get('under_price'))


def _ah_home_prob(side):
    if not isinstance(side, dict):
        return None
    fp = fair_probs(side.get('home_price'), side.get('away_price'))
    return None if fp is None else fp[0]


def ah_home_result(home, away, line):
    """Cover share for the home side at a home handicap line (quarter lines split).

    1 full win, 0.75 half win, 0.5 push, 0.25 half loss, 0 loss.
    """
    if line is None:
        return None
    twice = round(line * 4)
    if abs(line * 4 - twice) > 1e-9:
        return None
    parts = [line] if twice % 2 == 0 else [line - 0.25, line + 0.25]
    score = 0.0
    for p in parts:
        d = home - away + p
        score += 1.0 if d > 1e-9 else 0.5 if abs(d) <= 1e-9 else 0.0
    return score / len(parts)


def trajectory_variables(events, ko, competition):
    """All research variables from PRE-KICKOFF events only (input already filtered)."""
    v = {k: None for k in VARIABLES}
    n = len(events)
    v['n_messages'] = n
    times = [utc(e['observed_at']) for e in events]
    v['lead_first_min'] = round((ko - times[0]).total_seconds() / 60, 1)
    v['lead_last_min'] = round((ko - times[-1]).total_seconds() / 60, 1)
    v['span_min'] = round((times[-1] - times[0]).total_seconds() / 60, 1)
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
    v['max_gap_min'] = round(max(gaps), 1) if gaps else 0.0
    v['kickoff_hour_utc'] = ko.hour
    triggers = Counter(e.get('trigger_market') for e in events)
    v['trigger_total_share'] = round(triggers.get('total', 0) / n, 4)
    # ---- Total
    tot = [(t, e['snapshots']['total']) for t, e in zip(times, events)
           if (e.get('snapshots') or {}).get('total')]
    v['total_msgs'] = len(tot)
    if tot:
        lines_b = [s['before']['line'] for _, s in tot]
        lines_a = [s['after']['line'] for _, s in tot]
        v['total_line_first'] = lines_b[0]
        v['total_line_last'] = lines_a[-1]
        v['total_line_net'] = round(lines_a[-1] - lines_b[0], 4)
        v['total_line_ups'] = sum(a > b for a, b in zip(lines_a, lines_b))
        v['total_line_downs'] = sum(a < b for a, b in zip(lines_a, lines_b))
        lb = [_lam(s['before']) for _, s in tot]
        la = [_lam(s['after']) for _, s in tot]
        q = quality(tot[-1][1])
        v['total_overround_last'] = (q.get('after') or {}).get('margin')
        if all(x is not None for x in lb + la):
            pts = []
            for x, y in zip(lb, la):
                pts += [x, y]
            v['lambda_first'] = round(lb[0], 4)
            v['lambda_last'] = round(la[-1], 4)
            v['lambda_net'] = round(la[-1] - lb[0], 4)
            moves = [y - x for x, y in zip(lb, la)]
            dirs = [_sign(m, LAMBDA_EPS) for m in moves]
            v['lambda_abs_path'] = round(sum(abs(m) for m in moves), 4)
            mean = sum(pts) / len(pts)
            v['lambda_sd'] = round(math.sqrt(sum((p - mean) ** 2 for p in pts) / len(pts)), 4)
            v['lambda_moves_up'] = dirs.count(1)
            v['lambda_moves_down'] = dirs.count(-1)
            v['lambda_reversals'], v['lambda_max_run'] = _runs(dirs)
            nz = [d for d in dirs if d]
            v['lambda_first_dir'] = nz[0] if nz else 0
            v['lambda_last_dir'] = nz[-1] if nz else 0
            unobs = [lb[i + 1] - la[i] for i in range(len(tot) - 1)]
            v['lambda_unobserved_net'] = round(sum(unobs), 4)
            v['total_unobserved_changes'] = sum(
                1 for i in range(len(tot) - 1)
                if tot[i][1]['after'] != {k: tot[i + 1][1]['before'][k] for k in tot[i][1]['after']})
            hours = (tot[-1][0] - tot[0][0]).total_seconds() / 3600
            v['lambda_velocity_h'] = round(v['lambda_net'] / hours, 4) if hours > 0 else None
            if len(tot) >= 3:
                mid = len(tot) // 2
                h1 = (tot[mid][0] - tot[0][0]).total_seconds() / 3600
                h2 = (tot[-1][0] - tot[mid][0]).total_seconds() / 3600
                if h1 > 0 and h2 > 0:
                    v['lambda_accel_h'] = round((la[-1] - la[mid]) / h2 - (la[mid] - lb[0]) / h1, 4)
            up_line = [i for i, (a, b) in enumerate(zip(lines_a, lines_b)) if a > b]
            down_line = [i for i, (a, b) in enumerate(zip(lines_a, lines_b)) if a < b]
            v['line_up_then_lambda_down'] = bool(up_line) and any(
                dirs[j] == -1 for j in range(up_line[0] + 1, len(dirs)))
            v['line_down_then_lambda_up'] = bool(down_line) and any(
                dirs[j] == 1 for j in range(down_line[0] + 1, len(dirs)))
    # ---- 1X2
    x12 = [e['snapshots']['one_x_two'] for e in events if (e.get('snapshots') or {}).get('one_x_two')]
    v['x12_msgs'] = len(x12)
    if x12:
        first = one_x_two_probs({k: x12[0][k]['before'] for k in ('1', 'X', '2')})
        last = one_x_two_probs({k: x12[-1][k]['after'] for k in ('1', 'X', '2')})
        if first and last:
            v['p_home_first'], v['p_home_last'] = first['1'], last['1']
            v['p_home_net'] = round(last['1'] - first['1'], 4)
            v['p_draw_net'] = round(last['X'] - first['X'], 4)
            v['p_away_net'] = round(last['2'] - first['2'], 4)
        dirs = []
        for s in x12:
            b = one_x_two_probs({k: s[k]['before'] for k in ('1', 'X', '2')})
            a = one_x_two_probs({k: s[k]['after'] for k in ('1', 'X', '2')})
            if a and b:
                dirs.append(_sign(a['1'] - b['1'], PROB_EPS))
        v['x12_reversals'] = _runs(dirs)[0]
    # ---- AH
    ah = [e['snapshots']['asian_handicap'] for e in events
          if (e.get('snapshots') or {}).get('asian_handicap')]
    v['ah_msgs'] = len(ah)
    if ah:
        v['ah_line_first'] = ah[0]['before']['line']
        v['ah_line_last'] = ah[-1]['after']['line']
        v['ah_line_net'] = round(v['ah_line_last'] - v['ah_line_first'], 4)
        v['ah_line_moves'] = sum(s['after']['line'] != s['before']['line'] for s in ah)
    snaps = [e.get('snapshots') or {} for e in events]
    v['total_ah_same_msg'] = sum(bool(s.get('total') and s.get('asian_handicap')) for s in snaps)
    v['total_1x2_same_msg'] = sum(bool(s.get('total') and s.get('one_x_two')) for s in snaps)
    ctype = _competition_type(competition)
    if ctype != 'UNKNOWN':
        v['ctx_cup'] = ctype == 'CUP'
        v['ctx_youth_reserve'] = ctype == 'YOUTH_RESERVE'
        v['ctx_league_other'] = ctype == 'LEAGUE_OTHER'
    return v


def compact_trajectory(events, ko):
    """Pre-kickoff observed quotes only (no outcome, no names). Values as published."""
    out = []
    for e in events:
        s = e.get('snapshots') or {}
        m = {'event_id': e['event_id'],
             'minutes_to_kickoff': round((ko - utc(e['observed_at'])).total_seconds() / 60, 1),
             'trigger': e.get('trigger_market')}
        if s.get('total'):
            t = s['total']
            m['total'] = {side: [t[side]['line'], t[side]['over_price'], t[side]['under_price']]
                          for side in ('before', 'after')}
            lb, la = _lam(t['before']), _lam(t['after'])
            m['implied_goals'] = [None if lb is None else round(lb, 3), None if la is None else round(la, 3)]
        if s.get('asian_handicap'):
            a = s['asian_handicap']
            m['asian_handicap'] = {side: [a[side]['line'], a[side]['home_price'], a[side]['away_price']]
                                   for side in ('before', 'after')}
        if s.get('one_x_two'):
            p = one_x_two_probs({k: s['one_x_two'][k]['after'] for k in ('1', 'X', '2')})
            if p:
                m['p_1x2_after'] = [p['1'], p['X'], p['2']]
        out.append(m)
    return out


def baselines_from(events):
    out = {'p_over_2_5': None, 'p_home': None, 'p_draw': None, 'p_away': None,
           'p_ah_home': None, 'ah_line_at_decision': None}
    for e in events:
        s = e.get('snapshots') or {}
        if s.get('total'):
            q = quality(s['total'])
            out['p_over_2_5'] = q['p_over_2_5'] if q['status'] == 'USABLE' else None
        if s.get('one_x_two'):
            p = one_x_two_probs({k: s['one_x_two'][k]['after'] for k in ('1', 'X', '2')})
            if p:
                out['p_home'], out['p_draw'], out['p_away'] = p['1'], p['X'], p['2']
        if s.get('asian_handicap'):
            out['p_ah_home'] = _ah_home_prob(s['asian_handicap']['after'])
            out['ah_line_at_decision'] = s['asian_handicap']['after']['line']
    return out


def outcome_from(ft_row, ah_line):
    """Targets from a VERIFIED regulation score; anything else is None (pending)."""
    if not ft_row or ft_row.get('ft_status') != 'VERIFIED_FT' or not ft_row.get('score'):
        return None
    h, a = ft_row['score']
    return {'home': h, 'away': a, 'total_goals': h + a,
            'OVER_2_5': int(h + a > 2), 'BTTS_YES': int(h > 0 and a > 0),
            'HOME_WIN': int(h > a), 'DRAW': int(h == a), 'AWAY_WIN': int(h < a),
            'AH_HOME_COVER': ah_home_result(h, a, ah_line),
            'ft_verified_at': ft_row.get('ft_verified_at'),
            'ft_sha256': ft_row.get('ft_sha256')}


def build_row(timeline, competition, ft_attach):
    """One match. ``ft_attach(row)`` fills ft_status/score (existing V6 rules)."""
    ident = timeline.get('identity') or {}
    if not ident.get('team_names_consistent', True) or ident.get('per_message_conflicts'):
        return None, 'identity_conflict'
    kos = ident.get('kickoff_utc') or []
    if len(kos) != 1 or utc(kos[0]) is None:
        return None, 'kickoff_unknown_or_conflicting'
    ko = utc(kos[0])
    pre = []
    for e in timeline['events']:
        obs = utc(e.get('observed_at'))
        if obs and obs < ko:
            if 'identity_conflict' in e or any(
                    x.get('status') == 'DIFFER' for x in (e.get('v4_vs_h1_record') or {}).values()):
                return None, 'source_identity_or_quote_conflict'
            pre.append(e)
    if not pre:
        return None, 'no_prekickoff_message'
    pre.sort(key=lambda e: (e['observed_at'], e.get('message_id') or 0, e['event_id']))
    t = match_timeline(timeline['match_key'], [dict(e) for e in pre], near_seconds=120,
                       identities=[{'kickoff_utc': kos[0]}])
    variables = trajectory_variables(pre, ko, competition)
    variables['n_episodes'] = len(t['movement_episodes'])
    decision = pre[-1]['observed_at']
    base = baselines_from(pre)
    row = {'match_key': timeline['match_key'], 'kickoff_utc': kos[0], 'decision_at': decision,
           'variables': variables, 'baselines': base,
           'source_event_ids': [e['event_id'] for e in pre],
           'trajectory': compact_trajectory(pre, ko)}
    ft = {'kickoff_utc': kos[0], 'decision_at': decision}
    ft_attach(ft)
    row['ft_status'] = ft.get('ft_status')
    row['outcome'] = outcome_from(ft, base['ah_line_at_decision'])
    return row, None


def dataset_digest(rows):
    core = [{'k': r['match_key'], 'v': r['variables'], 'b': r['baselines'],
             'o': r['outcome'] and {k: r['outcome'][k] for k in
                                    ('home', 'away', 'ft_sha256')}} for r in rows]
    return hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False).encode()).hexdigest()


def build_dataset(root, *, now):
    """Real dataset from tracked files (read-only). Deterministic for a fixed tree+now."""
    from .timeline import read_sources, collect_timelines
    from .v6_ft_events import read_events
    from .v6_offline_statistics import attach_ft
    if now.tzinfo is None:
        raise ValueError('AWARE_NOW_REQUIRED')
    alerts, markets, errors = read_sources(root)
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    blocking = [i for i in issues if i.get('type') != 'excluded_unusable_identity_or_time']
    if blocking:
        raise ValueError('SOURCE_INTEGRITY_ERRORS:' + json.dumps(blocking)[:300])
    competitions = {}
    for a in alerts:
        if isinstance(a, dict) and a.get('match_key') and a.get('competition'):
            competitions.setdefault(a['match_key'], a['competition'])
    ft = read_events(root)
    latest = {e['match_key']: e for e in ft if utc(e['recorded_at']) <= now}
    rows, reasons = [], Counter()
    for tl in sorted(timelines, key=lambda t: t['match_key']):
        def attach(r, key=tl['match_key']):
            r['match_key'] = key
            attach_ft(r, latest.get(key), now)
        row, why = build_row(tl, competitions.get(tl['match_key']), attach)
        if why:
            reasons[why] += 1
            continue
        if utc(row['decision_at']) > now:
            reasons['future_observation'] += 1
            continue
        rows.append(row)
    return {'version': DATASET_VERSION, 'rows': rows, 'excluded': dict(reasons),
            'excluded_source_events': len(excluded), 'digest': dataset_digest(rows),
            'as_of': now.astimezone(timezone.utc).isoformat()}


def catalogue(rows):
    """Variable catalogue with availability; no outcome values are read."""
    n = len(rows) or 1
    out = []
    for name, (typ, market, desc) in VARIABLES.items():
        known = sum(r['variables'].get(name) is not None for r in rows)
        out.append({'name': name, 'type': typ, 'market': market, 'description': desc,
                    'availability': round(known / n, 4)})
    return out


def describe(dataset):
    rows = dataset['rows']
    ft = [r for r in rows if r['outcome']]
    per = {}
    for market, outs in OUTCOMES.items():
        for outcome, base in outs.items():
            per[outcome] = {'market': market, 'with_ft': sum(r['outcome'].get(outcome) is not None for r in ft),
                            'with_ft_and_baseline': sum(
                                r['outcome'].get(outcome) is not None and base is not None
                                and r['baselines'].get(base) is not None for r in ft),
                            'baseline': base or 'UNAVAILABLE'}
    days = sorted({r['kickoff_utc'][:10] for r in rows})
    return {'matches': len(rows), 'verified_ft': len(ft), 'outcomes': per,
            'first_day': days[0] if days else None, 'last_day': days[-1] if days else None,
            'excluded': dataset['excluded'], 'unavailable_phenomena': UNAVAILABLE_PHENOMENA}
