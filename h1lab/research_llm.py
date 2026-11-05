"""LLM <-> experiment-engine interface for autonomous exploratory research.

The model is free to choose WHAT to investigate: any market/outcome that exists,
any combination of catalogued pre-kickoff variables, new indicators in the safe DSL,
alternative explanations and control groups. It is not free to compute results,
run code, call tools, or declare anything validated: it only returns experiment
plans, which Python validates and executes.

Prompt-injection hygiene: the packet contains only code-defined catalogue text,
counts and Python-generated memory digests (no Telegram text, team names or
previous model prose). Model output is parsed as data, validated field by field,
never executed, and rejected plans are logged by structural reason only.
At most ONE bounded HTTPS request per call, no retries (``invoke_once``).
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .research_dataset import OUTCOMES
from .research_dsl import FORBIDDEN_NAME_SEQUENCES, FORBIDDEN_NAME_TOKENS, MAX_DEPTH, MAX_NODES, NAME_RE, OPS
from .research_plan import OPTIONAL, REQUIRED, STRATA, TEXT_FIELDS, PlanError, validate_plan
from .v6_llm_investigator import provider_usage, strict_json

PACKET_SCHEMA = 1
CONTRACT_VERSION = 2
MAX_RESPONSE_BYTES = 60_000
MAX_REQUEST_BYTES = 48_000
PACKET_BUDGET_BYTES = 44_000   # leaves room for the system prompt and envelope
MAX_INDICATORS_PER_PLAN = 3

# The first live call (run 42021728675) returned three plans and all were refused:
# twice INDICATOR_DEFINED_BUT_UNUSED and once DSL:INVALID_INDICATOR_NAME. The previous
# prompt never said that a defined indicator must be referenced, never said that names
# are UPPERCASE only, and its only example used an indicator in control_condition while
# the condition used a catalogue variable. The rules below are derived from the
# validator's own constants and the example is checked by validate_plan at build time.
SYSTEM = (
    'Es o investigador autonomo do MASTER BRAIN, em modo EXPLORATORIO. '
    'Escolhes livremente que relacoes investigar nas trajetorias de odds pre-inicio '
    '(Total, golos implicitos, 1X2, handicap asiatico, tempo, sequencias, intervalos sem observacao, contexto). '
    'Podes criar novos indicadores com a linguagem declarativa (contract e dsl), '
    'comparar explicacoes alternativas via control_condition, e usar a memoria para evitar repeticoes '
    'ou re-testar o que precisava de mais dados. '
    'NAO calculas resultados, NAO inventas numeros, NAO afirmas significancia, edge, ROI ou validacao: '
    'o Python executa as experiencias. Nao recomendes apostas. '
    'Mercados sem baseline (BTTS) so comparam frequencias. '
    'trajectory_examples sao trajetorias reais pre-inicio, pseudonimizadas e sem resultados: '
    'usa-as para entender formas de movimento, nunca como prova de efeito. '
    'Devolve APENAS JSON: {"schema_version":1,"experiments":[ate max_experiments planos],"new_questions":[ate 5 textos]}. '
    'REGRAS OBRIGATORIAS (um plano que falhe uma regra e recusado inteiro, sem correcao automatica): '
    '(1) Cada plano usa so as chaves de contract.plan_keys; market e outcome tem de ser um par de contract.markets. '
    '(2) condition e control_condition sao arvores JSON booleanas: {"var":nome}, {"const":numero|true|false} '
    'ou {"op":operador,"args":[...]} com os operadores, tipos e aridade de dsl.operators. '
    '(3) Cada {"var":nome} usa EXATAMENTE um nome de variables[].name (minusculas) ou um indicador X_ definido antes no mesmo plano. '
    '(4) Nome de indicador: comeca por X_ e depois so MAIUSCULAS A-Z, digitos 0-9 e _, entre 2 e 40 caracteres apos X_ '
    '(regex contract.indicator.name_regex). Nunca minusculas, hifens, espacos ou acentos; '
    'nunca tokens de resultado (contract.indicator.forbidden_name_tokens) nem igual a uma variavel. '
    '(5) TODO o indicador definido tem de aparecer como {"var":"X_..."} em condition, em control_condition, '
    'ou dentro de outro indicador que por sua vez seja usado. Se nao o usas, nao o definas. indicators pode ser []. '
    '(6) Maximo 3 indicadores por plano; cada um so tem name, description (5 a 200 caracteres) e expr. '
    '(7) control_condition e opcional, tem de ser diferente de condition; sem ela o controlo e o complemento. '
    '(8) confounders so pode conter lead_bin, line_bin, competition_type. '
    '(9) response_example e apenas ilustrativo: nao o copies; propoe relacoes tuas. '
    'Antes de responder, verifica cada plano contra contract.self_check.'
)


def dsl_spec():
    return {'operators': {k: {'args': list(v[0]), 'returns': v[1]} for k, v in OPS.items()},
            'nodes': ['{"var": name}', '{"const": number|bool}', '{"op": name, "args": [...]}'],
            'variadic': "args ['T', '*'] means 2 to 6 arguments of type T",
            'max_depth': MAX_DEPTH, 'max_nodes': MAX_NODES,
            'indicator_name': NAME_RE.pattern + ' (UPPERCASE only); may reference catalogue variables and earlier indicators',
            'missing_values': 'unknown inputs give unknown output; such matches are excluded, never controls'}


def contract_spec():
    """Machine-readable contract built from the validator's constants (single source of truth)."""
    return {
        'version': CONTRACT_VERSION,
        'response_keys': {'required': ['experiments', 'schema_version'], 'optional': ['new_questions']},
        'plan_keys': {'required': sorted(REQUIRED), 'optional': sorted(OPTIONAL)},
        'text_lengths': {k: list(v) for k, v in TEXT_FIELDS.items()},
        'markets': {m: sorted(outs) for m, outs in OUTCOMES.items()},
        'confounders_allowed': list(STRATA),
        'alternative_explanations': 'lista de 0 a 5 textos, cada um com 3 a 300 caracteres',
        'condition_type': 'bool',
        'indicator': {
            'keys': ['description', 'expr', 'name'],
            'max_per_plan': MAX_INDICATORS_PER_PLAN,
            'name_regex': NAME_RE.pattern,
            'name_valid_examples': ['X_LONG_GAP', 'X_LAMBDA_DROP', 'X_AH_TOTAL_OPPOSE', 'X_LATE_MOVE_2H'],
            'name_invalid_examples': {'X_long_gap': 'minusculas', 'X-LONG-GAP': 'hifen',
                                      'LONG_GAP': 'falta X_', 'X_A': 'curto demais',
                                      'X_FT_SIGNAL': 'contem FT (token de resultado)'},
            'forbidden_name_tokens': sorted(t.upper() for t in FORBIDDEN_NAME_TOKENS),
            'forbidden_name_sequences': sorted(t.upper() for t in FORBIDDEN_NAME_SEQUENCES),
            'must_be_used': ('cada indicador definido tem de ser referenciado por {"var": nome} em condition, '
                             'control_condition, ou num indicador posterior que seja usado'),
        },
        'self_check': [
            'market/outcome existe em contract.markets',
            'cada var existe em variables[].name ou e um X_ definido antes',
            'cada nome X_ cumpre name_regex (so maiusculas, digitos e _)',
            'cada indicador definido aparece em condition ou control_condition (ou num indicador usado)',
            'condition e control_condition devolvem bool e sao diferentes',
            'tipos e aridade dos operadores de dsl.operators respeitados',
            'nenhuma chave fora de contract.plan_keys',
        ],
    }


def response_example():
    """Two indicators, both referenced; condition and control isolate one explanation."""
    return {
        'question': 'Uma descida dos golos implicitos apos um longo intervalo sem observacao difere de uma descida observada sem esse intervalo?',
        'hypothesis': 'Descidas de golos implicitos que surgem depois de longos periodos sem observacao tem residual Over diferente.',
        'null_hypothesis': 'Nao existe diferenca no residual face ao baseline do mercado entre os dois grupos.',
        'market': 'TOTAL_GOALS', 'outcome': 'OVER_2_5',
        'indicators': [
            {'name': 'X_LONG_GAP', 'description': 'Maior intervalo sem observacao acima de 6 horas',
             'expr': {'op': 'gt', 'args': [{'var': 'max_gap_min'}, {'const': 360}]}},
            {'name': 'X_LAMBDA_DROP', 'description': 'Golos implicitos desceram pelo menos 0.1',
             'expr': {'op': 'le', 'args': [{'var': 'lambda_net'}, {'const': -0.1}]}},
        ],
        'condition': {'op': 'and', 'args': [{'var': 'X_LAMBDA_DROP'}, {'var': 'X_LONG_GAP'}]},
        'control_condition': {'op': 'and', 'args': [{'var': 'X_LAMBDA_DROP'},
                                                    {'op': 'not', 'args': [{'var': 'X_LONG_GAP'}]}]},
        'rationale': 'Separa o efeito da descida do efeito de nao se ter observado o mercado.',
        'alternative_explanations': ['Antecedencia diferente entre grupos', 'Competicoes com menos mensagens'],
        'confounders': ['lead_bin', 'line_bin'],
    }


def verified_example():
    """The example sent to the model MUST pass the real validator; otherwise refuse to build."""
    ex = response_example()
    try:
        plan = validate_plan(json.loads(json.dumps(ex)))
    except PlanError as exc:   # pragma: no cover - guarded by tests
        raise ValueError('RESPONSE_EXAMPLE_INVALID:' + str(exc)) from None
    return ex, plan['fingerprint']


def build_packet(*, gate, dataset_description, variable_catalogue, memory_digest, agenda_items,
                 max_plans=3, trajectory_examples=None):
    sci = gate.get('scientific_validation_gate', {})
    example, example_fp = verified_example()
    packet = {
        'schema_version': PACKET_SCHEMA,
        'mode': 'EXPLORATORY_RESEARCH_NOT_VALIDATION',
        'gates': {'exploration': gate['state'], 'scientific_validation': sci.get('state'),
                  'limitations': gate.get('limitations', [])[:6]},
        'data': dataset_description,
        'markets': {m: {o: (b or 'NO_MARKET_BASELINE') for o, b in outs.items()} for m, outs in OUTCOMES.items()},
        'variables': variable_catalogue,
        'dsl': dsl_spec(),
        'contract': contract_spec(),
        'memory': memory_digest,
        'agenda': agenda_items[:12],
        'trajectory_examples': trajectory_examples or {'examples': []},
        'max_experiments': max_plans,
        'response_example': {'schema_version': 1, 'experiments': [example],
                             'new_questions': ['Os movimentos AH contrarios ao Total comportam-se de forma diferente?']},
        # Not sent to the model: lets parse_response refuse a verbatim copy of the example.
        'response_example_fingerprints': [example_fp],
    }
    # Bound the request deterministically: shrink examples, then memory, then fail.
    while _user_size(packet) > PACKET_BUDGET_BYTES and packet['trajectory_examples'].get('examples'):
        packet['trajectory_examples'] = dict(packet['trajectory_examples'],
                                             examples=packet['trajectory_examples']['examples'][:-1])
    while _user_size(packet) > PACKET_BUDGET_BYTES and packet['memory']:
        packet['memory'] = packet['memory'][1:]
    if _user_size(packet) > PACKET_BUDGET_BYTES:
        raise ValueError('PACKET_TOO_LARGE')
    raw = json.dumps(packet, sort_keys=True, ensure_ascii=False, allow_nan=False)
    packet['packet_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    return packet


def _user_size(packet):
    return len(json.dumps(packet, ensure_ascii=False, allow_nan=False).encode())


def parse_response(content, *, max_plans=3, example_fingerprints=()):
    """-> {'plans', 'rejected': [{'index', 'reason', 'field'?, 'detail'?}], 'new_questions',
    'received', 'accepted'}. Rejections carry only structural, code-validated tokens."""
    if not isinstance(content, str) or len(content.encode()) > MAX_RESPONSE_BYTES:
        raise ValueError('LLM_RESPONSE_SIZE_INVALID')
    data = strict_json(content)
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or set(data) - {'schema_version', 'experiments', 'new_questions'}
            or not isinstance(data.get('experiments'), list)):
        raise ValueError('LLM_RESPONSE_SCHEMA_INVALID')
    plans, rejected = [], []
    for i, raw in enumerate(data['experiments']):
        if i >= max_plans:
            rejected.append({'index': i, 'reason': 'OVER_PLAN_BUDGET'})
            continue
        try:
            plan = validate_plan(raw)
        except PlanError as exc:
            rej = {'index': i, 'reason': str(exc)[:160]}
            if getattr(exc, 'field', None):
                rej['field'] = exc.field
            if getattr(exc, 'detail', None):
                rej['detail'] = exc.detail
            rejected.append(rej)
            continue
        if plan['fingerprint'] in example_fingerprints:
            # A verbatim copy of the illustrative example is not the model's own hypothesis.
            rejected.append({'index': i, 'reason': 'COPIED_RESPONSE_EXAMPLE', 'field': 'plan'})
            continue
        plans.append(plan)
    qs = data.get('new_questions', [])
    questions = []
    if isinstance(qs, list):
        for q in qs[:5]:
            if isinstance(q, str) and 10 <= len(q) <= 300:
                questions.append(''.join(c for c in q if ord(c) >= 32))
    return {'plans': plans, 'rejected': rejected, 'new_questions': questions,
            'received': len(data['experiments']), 'accepted': len(plans)}


def invoke_once(packet, *, endpoint, model, api_key='', opener=urlopen):
    """Exactly one request; any failure raises. No retry loop exists here."""
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('HTTPS_ENDPOINT_REQUIRED')
    if not isinstance(model, str) or not 1 <= len(model) <= 100:
        raise ValueError('MODEL_REQUIRED')
    user = {k: packet[k] for k in ('gates', 'data', 'markets', 'variables', 'dsl', 'contract', 'memory',
                                   'agenda', 'trajectory_examples', 'max_experiments',
                                   'response_example')}
    body = json.dumps({'model': model, 'temperature': 0.4, 'max_tokens': 2400,
                       'response_format': {'type': 'json_object'},
                       'messages': [{'role': 'system', 'content': SYSTEM},
                                    {'role': 'user', 'content': json.dumps(user, ensure_ascii=False)}]}).encode()
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError('REQUEST_TOO_LARGE')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'User-Agent': 'master-brain-research-cycle/1'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    with opener(Request(endpoint, data=body, headers=headers, method='POST'), timeout=30) as resp:
        if resp.status != 200:
            raise ValueError('LLM_NON_SUCCESS_STATUS')
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError('LLM_RESPONSE_TOO_LARGE')
    envelope = strict_json(raw.decode('utf-8'))
    content = envelope['choices'][0]['message']['content']
    return {'content': content, 'usage': provider_usage(envelope, model), 'llm_calls': 1,
            'response_sha256': hashlib.sha256(raw).hexdigest()}
