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
from .research_dsl import MAX_DEPTH, MAX_NODES, OPS
from .research_plan import PlanError, validate_plan
from .v6_llm_investigator import provider_usage, strict_json

PACKET_SCHEMA = 1
MAX_RESPONSE_BYTES = 60_000
MAX_REQUEST_BYTES = 48_000

SYSTEM = (
    'Es o investigador autonomo do MASTER BRAIN, em modo EXPLORATORIO. '
    'Escolhes livremente que relacoes investigar nas trajetorias de odds pre-inicio '
    '(Total, golos implicitos, 1X2, handicap asiatico, tempo, sequencias, intervalos sem observacao, contexto). '
    'Podes propor novos indicadores com a linguagem declarativa (operadores permitidos em dsl.operators), '
    'comparar explicacoes alternativas via control_condition, e usar a memoria para evitar repeticoes '
    'ou re-testar o que precisava de mais dados. '
    'NAO calculas resultados, NAO inventas numeros, NAO afirmas significancia, edge, ROI ou validacao: '
    'o Python executa as experiencias. Nao recomendes apostas. '
    'Mercados sem baseline (BTTS) so comparam frequencias. '
    'Devolve APENAS JSON: {"schema_version":1,"experiments":[ate 3 planos],"new_questions":[ate 5 textos]}. '
    'Cada plano: question, hypothesis, null_hypothesis, market, outcome, condition (expressao booleana), '
    'opcional control_condition, indicators [{name X_..., description, expr}], rationale, '
    'alternative_explanations, confounders (lead_bin, line_bin, competition_type).'
)


def dsl_spec():
    return {'operators': {k: {'args': list(v[0]), 'returns': v[1]} for k, v in OPS.items()},
            'nodes': ['{"var": name}', '{"const": number|bool}', '{"op": name, "args": [...]}'],
            'max_depth': MAX_DEPTH, 'max_nodes': MAX_NODES,
            'indicator_name': 'X_[A-Z0-9_]{2,40}; may reference catalogue variables and earlier indicators',
            'missing_values': 'unknown inputs give unknown output; such matches are excluded, never controls'}


def build_packet(*, gate, dataset_description, variable_catalogue, memory_digest, agenda_items,
                 max_plans=3):
    sci = gate.get('scientific_validation_gate', {})
    example = {
        'question': 'Uma subida da linha Total seguida de descida dos golos implicitos difere de tres movimentos consecutivos no mesmo sentido?',
        'hypothesis': 'Reversao apos subida de linha tem residual Over diferente de sequencias monotonas.',
        'null_hypothesis': 'Nao existe diferenca no residual face ao baseline do mercado.',
        'market': 'TOTAL_GOALS', 'outcome': 'OVER_2_5',
        'indicators': [{'name': 'X_THREE_SAME_DIR', 'description': 'Tres ou mais movimentos seguidos no mesmo sentido',
                        'expr': {'op': 'ge', 'args': [{'var': 'lambda_max_run'}, {'const': 3}]}}],
        'condition': {'var': 'line_up_then_lambda_down'},
        'control_condition': {'var': 'X_THREE_SAME_DIR'},
        'rationale': 'Compara duas explicacoes de movimento.',
        'alternative_explanations': ['Antecedencia diferente entre grupos'],
        'confounders': ['lead_bin', 'line_bin'],
    }
    packet = {
        'schema_version': PACKET_SCHEMA,
        'mode': 'EXPLORATORY_RESEARCH_NOT_VALIDATION',
        'gates': {'exploration': gate['state'], 'scientific_validation': sci.get('state'),
                  'limitations': gate.get('limitations', [])[:6]},
        'data': dataset_description,
        'markets': {m: {o: (b or 'NO_MARKET_BASELINE') for o, b in outs.items()} for m, outs in OUTCOMES.items()},
        'variables': variable_catalogue,
        'dsl': dsl_spec(),
        'memory': memory_digest,
        'agenda': agenda_items[:12],
        'max_experiments': max_plans,
        'response_example': {'schema_version': 1, 'experiments': [example],
                             'new_questions': ['Os movimentos AH contrarios ao Total comportam-se de forma diferente?']},
    }
    raw = json.dumps(packet, sort_keys=True, ensure_ascii=False, allow_nan=False)
    packet['packet_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    return packet


def parse_response(content, *, max_plans=3):
    """-> {'plans': [...], 'rejected': [{'index', 'reason'}], 'new_questions': [...]}."""
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
            plans.append(validate_plan(raw))
        except PlanError as exc:
            rejected.append({'index': i, 'reason': str(exc)[:160]})
    qs = data.get('new_questions', [])
    questions = []
    if isinstance(qs, list):
        for q in qs[:5]:
            if isinstance(q, str) and 10 <= len(q) <= 300:
                questions.append(''.join(c for c in q if ord(c) >= 32))
    return {'plans': plans, 'rejected': rejected, 'new_questions': questions}


def invoke_once(packet, *, endpoint, model, api_key='', opener=urlopen):
    """Exactly one request; any failure raises. No retry loop exists here."""
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('HTTPS_ENDPOINT_REQUIRED')
    if not isinstance(model, str) or not 1 <= len(model) <= 100:
        raise ValueError('MODEL_REQUIRED')
    user = {k: packet[k] for k in ('gates', 'data', 'markets', 'variables', 'dsl', 'memory',
                                   'agenda', 'max_experiments', 'response_example')}
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
