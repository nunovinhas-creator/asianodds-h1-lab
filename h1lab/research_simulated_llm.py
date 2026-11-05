"""SIMULATED LLM for offline proofs. Not a model, never a provider call.

It plugs into ``research_llm.invoke_once`` as the HTTP opener, receives the exact
request body the real provider would receive, and derives its plans ONLY from that
packet: the variable catalogue (availability), the real pre-kickoff trajectory
examples (thresholds), and the memory digest (it avoids variable pairs already
investigated). This proves that Python executes what the "model" chose, end to end,
instead of hand-written fixtures. Every artefact it produces is labelled
``SIMULATED_LLM`` and is only accepted in DEMONSTRATION/TEST memories.
"""
from __future__ import annotations

import hashlib
import json
from statistics import median

ORIGIN = 'SIMULATED_LLM'
SIGNED = ('total_line_net', 'lambda_net', 'lambda_velocity_h', 'lambda_accel_h',
          'lambda_unobserved_net', 'p_home_net', 'p_draw_net', 'p_away_net', 'ah_line_net')
OUTCOME_FOR = {'AH': ('ASIAN_HANDICAP', 'AH_HOME_COVER'), '1X2': ('1X2', 'HOME_WIN'),
               'TOTAL': ('TOTAL_GOALS', 'OVER_2_5')}


def _vars_in(expr, out):
    if isinstance(expr, dict):
        if 'var' in expr:
            out.add(expr['var'])
        for a in expr.get('args', []):
            _vars_in(a, out)
    return out


def _example_stats(examples):
    """Thresholds from REAL pre-kickoff examples (no outcomes are present there)."""
    nets, lasts = [], []
    for ex in examples:
        goals = [m['implied_goals'] for m in ex['messages'] if m.get('implied_goals')
                 and None not in m['implied_goals']]
        if goals:
            nets.append(abs(goals[-1][1] - goals[0][0]))
            lasts.append(goals[-1][1])
    return {'abs_lambda_net_median': round(median(nets), 3) if nets else 0.1,
            'lambda_last_median': round(median(lasts), 3) if lasts else 2.7,
            'examples_used': len(nets)}


def _catalogue(variables):
    """Accepts the v1/v2 list catalogue and the v3 compact {'num': {...}, 'bool': {...}} form."""
    if isinstance(variables, list):
        return {v['name']: v for v in variables}
    out = {}
    for typ in ('num', 'bool'):
        for name, text in (variables.get(typ) or {}).items():
            parts = [x.strip() for x in text.split('|')]
            avail = 1.0
            if len(parts) > 2 and parts[2].startswith('disponivel em '):
                avail = float(parts[2][len('disponivel em '):].rstrip('%')) / 100
            out[name] = {'name': name, 'type': typ, 'market': parts[0], 'availability': avail}
    return out


def decide(packet_user):
    """Deterministic 'model' policy: packet in, response JSON out."""
    catalogue = _catalogue(packet_user['variables'])
    used_pairs = set()
    for m in packet_user.get('memory', []):
        names = set()
        for key in ('condition', 'control_condition'):
            _vars_in(m.get(key), names)
        for ind in m.get('indicators', []):
            _vars_in(ind.get('expr'), names)
        used_pairs.add(frozenset(n for n in names if not n.startswith('X_')))
    stats = _example_stats(packet_user.get('trajectory_examples', {}).get('examples', []))
    seed = hashlib.sha256(json.dumps(packet_user['data'], sort_keys=True).encode()).hexdigest()
    signed = [n for n in SIGNED if n in catalogue and catalogue[n]['availability'] >= 0.3]
    pairs = []
    for a in signed:
        for b in signed:
            ma, mb = catalogue[a]['market'], catalogue[b]['market']
            if a < b and ma != mb and not any({a, b} <= u for u in used_pairs):
                pairs.append((hashlib.sha256((seed + a + b).encode()).hexdigest(), a, b))
    pairs.sort()
    experiments = []
    for _, a, b in pairs[:2]:
        target = catalogue[b]['market'] if catalogue[b]['market'] in OUTCOME_FOR else catalogue[a]['market']
        market, outcome = OUTCOME_FOR.get(target, OUTCOME_FOR['TOTAL'])
        name = 'X_COMOVE_' + (a[:12] + '_' + b[:12]).upper()
        experiments.append({
            'question': 'Movimentos opostos de %s e %s antes do início comportam-se de forma diferente de movimentos no mesmo sentido em %s?' % (a, b, outcome),
            'hypothesis': 'Quando %s e %s se movem em sentidos opostos, o mercado incorpora pior a informação.' % (a, b),
            'null_hypothesis': 'O resíduo face ao mercado é igual para movimentos opostos e no mesmo sentido.',
            'market': market, 'outcome': outcome,
            'indicators': [{'name': name, 'description': 'Produto dos sinais de %s e %s' % (a, b),
                            'expr': {'op': 'mul', 'args': [{'op': 'sign', 'args': [{'var': a}]},
                                                           {'op': 'sign', 'args': [{'var': b}]}]}}],
            'condition': {'op': 'lt', 'args': [{'var': name}, {'const': 0}]},
            'control_condition': {'op': 'gt', 'args': [{'var': name}, {'const': 0}]},
            'rationale': 'Escolha do LLM SIMULADO: par de mercados distintos ainda não investigado na memória.',
            'alternative_explanations': ['Movimentos opostos podem concentrar-se em jogos com mais mensagens'],
            'confounders': ['lead_bin', 'line_bin', 'competition_type'],
        })
    thr = stats['abs_lambda_net_median']
    last = stats['lambda_last_median']
    # Threshold templates; the first whose variables are not yet in memory is proposed.
    templates = [
        ('X_BIG_TOTAL_ONLY_MOVE', 'Variação absoluta de golos implícitos acima de %s' % thr,
         {'op': 'ge', 'args': [{'op': 'abs', 'args': [{'var': 'lambda_net'}]}, {'const': thr}]},
         {'op': 'eq', 'args': [{'var': 'x12_msgs'}, {'const': 0}]}, {'lambda_net', 'x12_msgs'},
         'Uma variação de golos implícitos acima da mediana dos exemplos reais, sem 1X2 observado, altera o Over 2,5 face ao mercado?'),
        ('X_HIGH_LATE_EXPECTATION', 'Golos implícitos finais acima de %s' % last,
         {'op': 'ge', 'args': [{'var': 'lambda_last'}, {'const': last}]},
         {'op': 'le', 'args': [{'var': 'lead_last_min'}, {'const': 120}]}, {'lambda_last', 'lead_last_min'},
         'Uma expectativa de golos alta (acima da mediana dos exemplos) confirmada perto do início altera o Over 2,5 face ao mercado?'),
        ('X_LONG_SILENCE', 'Maior intervalo sem observação acima de 6 h',
         {'op': 'ge', 'args': [{'var': 'max_gap_min'}, {'const': 360}]},
         {'op': 'ge', 'args': [{'op': 'abs', 'args': [{'var': 'lambda_unobserved_net'}]}, {'const': thr}]},
         {'max_gap_min', 'lambda_unobserved_net'},
         'Uma mudança grande de golos implícitos escondida num intervalo longo sem observação altera o Over 2,5?'),
    ]
    for name, desc, expr, extra, varset, question in templates:
        if any(varset <= u for u in used_pairs):
            continue
        experiments.append({
            'question': question,
            'hypothesis': 'Este padrão de trajetória reflete informação que o preço final ainda não incorpora.',
            'null_hypothesis': 'Sem diferença de resíduo Over face aos restantes jogos.',
            'market': 'TOTAL_GOALS', 'outcome': 'OVER_2_5',
            'indicators': [{'name': name, 'description': desc, 'expr': expr}],
            'condition': {'op': 'and', 'args': [{'var': name}, extra]},
            'rationale': 'Limiar derivado dos exemplos de trajetórias do pacote (mediana %s / %s).' % (thr, last),
            'alternative_explanations': ['Concentração em competições menores ou com menos mensagens'],
            'confounders': ['lead_bin', 'competition_type'],
        })
        break
    return {'schema_version': 1, 'experiments': experiments[:3],
            'new_questions': ['Os intervalos sem observação escondem inversões entre mensagens?']}


class _Resp:
    def __init__(self, body):
        self.body, self.status = body, 200

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SimulatedLLMOpener:
    """Drop-in for urlopen. Reads the real request body; records every call."""

    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode('utf-8'))
        user = json.loads(body['messages'][1]['content'])
        self.calls.append({'url': req.full_url, 'bytes': len(req.data)})
        content = json.dumps(decide(user), ensure_ascii=False)
        usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        if '/ai/run/' in req.full_url:   # native Workers AI envelope (JSON Mode returns an object)
            env = {'result': {'response': json.loads(content), 'usage': usage}, 'success': True,
                   'errors': [], 'messages': []}
        else:
            env = {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}], 'usage': usage}
        return _Resp(json.dumps(env).encode())
