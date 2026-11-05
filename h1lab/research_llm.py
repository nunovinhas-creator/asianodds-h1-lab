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

Contract v3 (after live calls 42021728675 and 42030138637, both 0 accepted plans):
* no complete JSON example any more: the model copied it twice in the second call.
  The packet carries a STRUCTURAL template whose placeholders cannot validate;
* the DSL is described as a typed grammar (BOOL_EXPR / NUM_EXPR) generated from
  ``OPS``, so ``and``/``or``/``not`` visibly take booleans only;
* provider JSON Mode with a JSON Schema generated from the same Python contract
  (``response_schema``), for models whose JSON Mode support is documented;
* every per-model limit (context window, neuron rates) is data in MODEL_PROFILES,
  and ``neuron_bound`` refuses a request whose worst case exceeds the budget.

After live run 42038573930 (``HTTPError: HTTP Error 400: Bad Request``, provider body never read):
* a provider HTTP error now raises ``ProviderHTTPError`` carrying a bounded, redacted
  diagnostic (status, Cloudflare ``errors[].code``/``message``, body hash) - never the
  request, headers, token or account id;
* the schema SENT to the provider (``provider_schema``) keeps only the keywords used by
  the Cloudflare JSON Mode documentation plus ``enum``/``additionalProperties``; the full
  contract (``response_schema``) and the Python validator are unchanged and still decide.

After live run 42054180234 (``TimeoutError: The read operation timed out`` ~60 s after the
request started, i.e. the 60 s socket timeout expired while waiting for the reply):
* the socket timeout is ``LLM_HTTP_TIMEOUT_S`` (180 s), sized for Llama 3.3 70B producing up to
  ``MAX_OUTPUT_TOKENS`` under JSON Mode; the 10-minute job limit stays the wall-clock bound;
* a transport failure raises ``ProviderTransportError`` with a bounded diagnostic naming the
  phase (``connect_or_send`` / ``awaiting_response`` / ``reading_body``) and the kind
  (``timeout`` / ``connection``). Still exactly one request, no retries.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .research_dataset import OUTCOMES
from .research_dsl import (FORBIDDEN_NAME_SEQUENCES, FORBIDDEN_NAME_TOKENS, MAX_DEPTH, MAX_NODES, NAME_RE,
                           OPS, canonical_json)
from .research_plan import OPTIONAL, REQUIRED, STRATA, TEXT_FIELDS, PlanError, inline, validate_plan
from .v6_llm_investigator import provider_usage, strict_json

PACKET_SCHEMA = 1
CONTRACT_VERSION = 3
MAX_RESPONSE_BYTES = 60_000
MAX_REQUEST_BYTES = 48_000     # absolute ceiling for every model; profiles may be stricter
PACKET_BUDGET_BYTES = 44_000   # absolute ceiling for the user packet
MAX_INDICATORS_PER_PLAN = 3
MAX_OUTPUT_TOKENS = 2400
TEMPERATURE = 0.4
MAX_MEMORY_ITEMS = 12
MAX_AGENDA_ITEMS = 6
MAX_TRAJECTORY_EXAMPLES = 4

# ---------------------------------------------------------------------------
# Provider facts. Source: cloudflare/cloudflare-docs @ abaf629 (2026-11-05):
#   src/content/docs/workers-ai/platform/pricing.mdx      (neurons per M tokens; 10,000 free/day)
#   src/content/docs/workers-ai/features/json-mode.mdx    (JSON Mode supported-model list)
#   src/content/workers-ai-models/<model>.json            (context_window, input schema)
# Neither the account plan nor the remaining allocation can be read here
# (``account_quota_verified=false``): the bound below is on OUR worst case.
from .research_quota import FREE_NEURONS_PER_DAY, DAILY_NEURON_BUDGET, MAX_NEURONS_PER_CALL
MAX_CALLS_PER_DAY = DAILY_NEURON_BUDGET // MAX_NEURONS_PER_CALL  # unmetered capacity, not a call-count cap
# Byte-fallback tokenizers emit no more than one token per UTF-8 byte. Count
# the ENTIRE serialized request, plus 512 tokens for provider chat framing.
# This replaces the old empirical 2 bytes/token heuristic. Bound remains an
# internal conservative estimate under the pinned provider/model contract.
BYTES_PER_TOKEN_PESSIMISTIC = 1.0
PROMPT_FRAMING_TOKENS = 512

MODEL_PROFILES = {
    '@cf/meta/llama-3.3-70b-instruct-fp8-fast': {
        'endpoint': 'native',             # /ai/run/{model}: the documented JSON Mode request shape
        'json_mode': 'json_schema', 'json_mode_documented': True,
        'context_tokens': 24_000, 'max_request_bytes': 18_000,
        'neurons_per_m_input': 26_668, 'neurons_per_m_output': 204_805,
        'reasoning_tokens': False, 'status': 'RECOMMENDED',
    },
    '@cf/qwen/qwen3-30b-a3b-fp8': {
        'endpoint': 'native',
        'json_mode': 'json_schema', 'json_mode_documented': False,   # not in the JSON Mode list
        'context_tokens': 32_768, 'max_request_bytes': 30_000,
        'neurons_per_m_input': 4_625, 'neurons_per_m_output': 30_475,
        'reasoning_tokens': True,         # reasoning_content consumes the output budget
        'status': 'NOT_RECOMMENDED_JSON_MODE_UNDOCUMENTED_REASONING_MODEL',
    },
    '@cf/meta/llama-3.1-8b-instruct-fast': {
        'endpoint': 'openai', 'json_mode': 'json_object', 'json_mode_documented': False,
        'context_tokens': None, 'max_request_bytes': MAX_REQUEST_BYTES,
        'neurons_per_m_input': None, 'neurons_per_m_output': None,   # alias absent from the price table
        'reasoning_tokens': False, 'status': 'RETIRED_0_OF_6_PLANS_ACCEPTED',
    },
}


def neuron_bound(model, request_bytes, *, max_tokens=MAX_OUTPUT_TOKENS, prior_calls_today=0):
    """Worst-case neurons for ONE request; raises when any bound would be exceeded."""
    prof = MODEL_PROFILES.get(model)
    if not prof or prof['neurons_per_m_input'] is None or prof['context_tokens'] is None:
        raise ValueError('MODEL_COST_UNKNOWN')
    if request_bytes > prof['max_request_bytes']:
        raise ValueError('REQUEST_OVER_MODEL_BUDGET')
    if type(request_bytes) is not int or request_bytes <= 0 or type(max_tokens) is not int or not 0 < max_tokens <= MAX_OUTPUT_TOKENS or type(prior_calls_today) is not int or prior_calls_today < 0:
        raise ValueError('INVALID_NEURON_BOUND_INPUT')
    in_tokens = math.ceil(request_bytes / BYTES_PER_TOKEN_PESSIMISTIC) + PROMPT_FRAMING_TOKENS
    if in_tokens + max_tokens > prof['context_tokens']:
        raise ValueError('CONTEXT_WINDOW_EXCEEDED')
    neurons = (in_tokens * prof['neurons_per_m_input'] + max_tokens * prof['neurons_per_m_output']) / 1e6
    if neurons > MAX_NEURONS_PER_CALL:
        raise ValueError('NEURONS_PER_CALL_OVER_BUDGET')
    if (prior_calls_today + 1) * MAX_NEURONS_PER_CALL > DAILY_NEURON_BUDGET:
        raise ValueError('DAILY_NEURON_BUDGET_EXCEEDED')
    return {'model': model, 'request_bytes': request_bytes, 'input_tokens_max': in_tokens,
            'output_tokens_max': max_tokens, 'neurons_max': math.ceil(neurons),
            'daily_neurons_max': DAILY_NEURON_BUDGET,
            'bound_kind': 'CONSERVATIVE_TOKEN_ESTIMATE',
            'free_neurons_per_day': FREE_NEURONS_PER_DAY, 'account_quota_verified': False}


def neurons_from_usage(model, tokens):
    """Conservative integer estimate from complete metering, never account billing."""
    prof = MODEL_PROFILES.get(model) or {}
    if not isinstance(tokens, dict) or prof.get('neurons_per_m_input') is None:
        return None
    values = [tokens.get(k) for k in ('prompt_tokens', 'completion_tokens')]
    if any(type(v) is not int or v < 0 for v in values) or sum(values) == 0:
        return None
    return math.ceil((values[0] * prof['neurons_per_m_input']
                      + values[1] * prof['neurons_per_m_output']) / 1e6)


# ---------------------------------------------------------------------------
# Contract

SYSTEM = (
    'Es o investigador autonomo do MASTER BRAIN (modo EXPLORATORIO). Propoe ate max_experiments '
    'planos de experiencia ORIGINAIS sobre trajetorias de odds pre-inicio. O Python executa-os: '
    'NAO calculas resultados, NAO inventas numeros, NAO afirmas significancia, edge ou validacao, '
    'NAO recomendas apostas. trajectory_examples e memory sao contexto, nunca prova. '
    'Responde APENAS com JSON {"schema_version":1,"experiments":[...],"new_questions":[...]}. '
    'Cada plano segue contract.plan_template; os textos entre < > sao instrucoes, substitui-os. '
    'Expressoes seguem contract.grammar: and/or/not so recebem BOOL_EXPR; gt/ge/lt/le/eq/ne/between '
    'so recebem NUM_EXPR; condition e control_condition sao BOOL_EXPR. '
    'Usa so nomes de variables.num/variables.bool ou indicadores X_ que defines no proprio plano. '
    'Nome de indicador: X_ + MAIUSCULAS/digitos/_ ; cada indicador definido TEM de ser usado. '
    'Nao repitas condicoes da memory nem os fragmentos de contract.grammar. '
    'Antes de responder verifica cada plano contra contract.self_check.'
)


def _sig(op):
    args, out = OPS[op]
    return args, out


def grammar():
    """Typed grammar generated from ``OPS`` (single source of truth)."""
    kinds = {'num': 'NUM_EXPR', 'bool': 'BOOL_EXPR', 'any': 'BOOL_EXPR|NUM_EXPR'}
    groups = {}
    for op in sorted(OPS):
        args, out = _sig(op)
        if len(args) == 2 and args[1] == '*':
            shape = '[%s, %s, ...] (2 a 6 argumentos, todos %s)' % (kinds[args[0]], kinds[args[0]], kinds[args[0]])
        else:
            shape = '[' + ', '.join(kinds[a] for a in args) + ']'
        groups.setdefault((kinds[out], shape), []).append(op)
    rules = {'BOOL_EXPR': ['{"var": <nome em variables.bool, ou indicador X_ booleano>}', '{"const": true|false}'],
             'NUM_EXPR': ['{"var": <nome em variables.num, ou indicador X_ numerico>}', '{"const": <numero>}']}
    for (out, shape), ops in sorted(groups.items()):
        rules[out].append('{"op": "%s", "args": %s}' % ('|'.join(ops), shape))
    return {
        'BOOL_EXPR': rules['BOOL_EXPR'], 'NUM_EXPR': rules['NUM_EXPR'],
        'type_rules': [
            'and, or e not so aceitam BOOL_EXPR: uma variavel numerica tem de ser comparada primeiro '
            '(gt/ge/lt/le/eq/ne/between) antes de entrar em and/or/not.',
            'gt, ge, lt, le, eq, ne e between so aceitam NUM_EXPR: nunca compares uma variavel booleana.',
            'condition e control_condition sao BOOL_EXPR; um indicador pode ser NUM_EXPR ou BOOL_EXPR.',
        ],
        # Fragments, not plans: a plan whose condition equals one of these is refused as a copy.
        'type_fragments': {
            'ERRADO (TYPE_ERROR)': {'op': 'and', 'args': [{'var': 'lambda_net'}, {'var': 'ctx_cup'}]},
            'CERTO': {'op': 'and', 'args': [{'op': 'gt', 'args': [{'var': 'lambda_net'}, {'const': 0.1}]},
                                            {'var': 'ctx_cup'}]},
        },
        'limits': {'max_depth': MAX_DEPTH, 'max_nodes': MAX_NODES},
        'missing_values': 'entradas desconhecidas dao resultado desconhecido; esses jogos sao excluidos',
    }


def plan_template():
    """Structural template. Every placeholder is invalid on purpose: a verbatim copy cannot pass."""
    return {
        'question': '<pergunta tua, 10 a 400 caracteres>',
        'hypothesis': '<hipotese tua, 10 a 600 caracteres>',
        'null_hypothesis': '<hipotese nula, 10 a 600 caracteres>',
        'market': '<MARKET: uma chave de contract.markets>',
        'outcome': '<OUTCOME: um valor de contract.markets[MARKET]>',
        'indicators': [{'name': '<X_NOME_EM_MAIUSCULAS>', 'description': '<5 a 200 caracteres>',
                        'expr': '<NUM_EXPR ou BOOL_EXPR>'}],
        'condition': '<BOOL_EXPR que usa os indicadores definidos>',
        'control_condition': '<BOOL_EXPR diferente de condition, opcional>',
        'rationale': '<porque esta pergunta, ate 800 caracteres>',
        'alternative_explanations': ['<0 a 5 textos, 3 a 300 caracteres>'],
        'confounders': ['<subconjunto de contract.confounders_allowed>'],
    }


def contract_spec():
    """Machine-readable contract built from the validator's constants."""
    return {
        'version': CONTRACT_VERSION,
        'plan_template': plan_template(),
        'plan_keys': {'required': sorted(REQUIRED), 'optional': sorted(OPTIONAL - {'related_to'})},
        'text_lengths': {k: list(v) for k, v in TEXT_FIELDS.items()},
        'markets': {m: sorted(outs) for m, outs in OUTCOMES.items()},
        'confounders_allowed': list(STRATA),
        'grammar': grammar(),
        'indicator': {
            'max_per_plan': MAX_INDICATORS_PER_PLAN, 'name_regex': NAME_RE.pattern,
            'name_valid_examples': ['X_LONG_GAP', 'X_AH_TOTAL_OPPOSE', 'X_LATE_MOVE_2H'],
            'name_invalid_examples': {'X_long_gap': 'minusculas', 'X-LONG-GAP': 'hifen',
                                      'LONG_GAP': 'falta X_', 'X_A': 'curto demais',
                                      'X_FT_SIGNAL': 'contem FT (token de resultado)'},
            'forbidden_name_tokens': sorted(t.upper() for t in FORBIDDEN_NAME_TOKENS),
            'forbidden_name_sequences': sorted(t.upper() for t in FORBIDDEN_NAME_SEQUENCES),
            'must_be_used': 'cada indicador definido aparece como {"var": nome} em condition, '
                            'control_condition, ou num indicador posterior que seja usado',
        },
        'self_check': [
            'nenhum texto entre < > ficou na resposta',
            'market/outcome e um par de contract.markets',
            'cada var existe em variables.num/variables.bool ou e um X_ definido antes no plano',
            'and/or/not so com BOOL_EXPR; comparacoes so com NUM_EXPR',
            'cada nome X_ cumpre name_regex e cada indicador definido e usado',
            'condition e control_condition sao BOOL_EXPR diferentes entre si',
            'a condicao nao repete memory nem contract.grammar.type_fragments',
        ],
    }


def _expr_schema():
    # Non-recursive on purpose (portable across JSON Mode implementations); the full typed
    # check is done by the Python validator, which is never relaxed.
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'var': {'type': 'string', 'maxLength': 42},
                           'const': {'type': ['number', 'boolean']},
                           'op': {'type': 'string', 'enum': sorted(OPS)},
                           'args': {'type': 'array', 'minItems': 1, 'maxItems': 6, 'items': {'type': 'object'}}}}


def response_schema(max_plans=3):
    """JSON Schema for provider JSON Mode, generated from the Python contract."""
    def text(name):
        lo, hi = TEXT_FIELDS[name]
        return {'type': 'string', 'minLength': lo, 'maxLength': hi}
    outcomes = sorted({o for outs in OUTCOMES.values() for o in outs})
    plan = {
        'type': 'object', 'additionalProperties': False,
        'required': sorted(REQUIRED),
        'properties': {
            'question': text('question'), 'hypothesis': text('hypothesis'),
            'null_hypothesis': text('null_hypothesis'), 'rationale': text('rationale'),
            'market': {'type': 'string', 'enum': sorted(OUTCOMES)},
            'outcome': {'type': 'string', 'enum': outcomes},
            'indicators': {'type': 'array', 'maxItems': MAX_INDICATORS_PER_PLAN, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['name', 'description', 'expr'],
                'properties': {'name': {'type': 'string', 'pattern': '^' + NAME_RE.pattern + '$'},
                               'description': {'type': 'string', 'minLength': 5, 'maxLength': 200},
                               'expr': _expr_schema()}}},
            'condition': _expr_schema(), 'control_condition': _expr_schema(),
            'alternative_explanations': {'type': 'array', 'maxItems': 5,
                                         'items': {'type': 'string', 'minLength': 3, 'maxLength': 300}},
            'confounders': {'type': 'array', 'maxItems': len(STRATA), 'uniqueItems': True,
                            'items': {'type': 'string', 'enum': list(STRATA)}},
        },
    }
    return {'type': 'object', 'additionalProperties': False, 'required': ['schema_version', 'experiments'],
            'properties': {'schema_version': {'type': 'integer', 'enum': [1]},
                           'experiments': {'type': 'array', 'maxItems': max_plans, 'items': plan},
                           'new_questions': {'type': 'array', 'maxItems': 5,
                                             'items': {'type': 'string', 'minLength': 10, 'maxLength': 300}}}}


# Keywords kept in the schema sent to Workers AI JSON Mode. The Cloudflare page documents no
# list of supported keywords; its example uses type/properties/required/items only. Run
# 42038573930 was refused with HTTP 400 while sending pattern, min/maxLength, min/maxItems,
# uniqueItems and a union ``type`` list (UNPROVEN as the cause: the body was not captured).
# Everything removed here is still enforced by validate_plan / parse_response.
PROVIDER_SCHEMA_KEYWORDS = frozenset({'type', 'properties', 'required', 'items', 'enum',
                                      'additionalProperties'})


def provider_schema(max_plans=3):
    """``response_schema`` reduced to PROVIDER_SCHEMA_KEYWORDS (guidance only, not validation)."""
    def reduce(node):
        out = {}
        for k, val in node.items():
            if k not in PROVIDER_SCHEMA_KEYWORDS:
                continue
            if k == 'type' and isinstance(val, list):
                continue              # union type -> unconstrained value; Python checks the type
            if k == 'properties':
                val = {name: reduce(sub) for name, sub in val.items()}
            elif k == 'items':
                val = reduce(val)
            out[k] = val
        return out
    return reduce(response_schema(max_plans))


# Plans/conditions the model must not hand back as its own: the v2 full example (sent in
# run 42030138637 and copied twice) and the grammar fragments of this contract.
LEGACY_EXAMPLE_V2 = {
    'question': 'Uma descida dos golos implicitos apos um longo intervalo sem observacao difere de uma descida observada sem esse intervalo?',
    'hypothesis': 'Descidas de golos implicitos que surgem depois de longos periodos sem observacao tem residual Over diferente.',
    'null_hypothesis': 'Nao existe diferenca no residual face ao baseline do mercado entre os dois grupos.',
    'market': 'TOTAL_GOALS', 'outcome': 'OVER_2_5',
    'indicators': [
        {'name': 'X_LONG_GAP', 'description': 'Maior intervalo sem observacao acima de 6 horas',
         'expr': {'op': 'gt', 'args': [{'var': 'max_gap_min'}, {'const': 360}]}},
        {'name': 'X_LAMBDA_DROP', 'description': 'Golos implicitos desceram pelo menos 0.1',
         'expr': {'op': 'le', 'args': [{'var': 'lambda_net'}, {'const': -0.1}]}}],
    'condition': {'op': 'and', 'args': [{'var': 'X_LAMBDA_DROP'}, {'var': 'X_LONG_GAP'}]},
    'control_condition': {'op': 'and', 'args': [{'var': 'X_LAMBDA_DROP'},
                                                {'op': 'not', 'args': [{'var': 'X_LONG_GAP'}]}]},
    'confounders': ['lead_bin', 'line_bin'],
}


def copy_guard():
    """-> (plan fingerprints, canonical expressions) that count as copies, not hypotheses."""
    fps = {validate_plan(json.loads(json.dumps(LEGACY_EXAMPLE_V2)))['fingerprint']}
    exprs = {canonical_json(e) for e in grammar()['type_fragments'].values()}
    return sorted(fps), sorted(exprs)


# ---------------------------------------------------------------------------
# Packet

def compact_variables(catalogue):
    out = {'num': {}, 'bool': {}}
    for v in catalogue:
        text = '%s | %s' % (v['market'], v['description'])
        if v.get('availability', 1.0) < 0.95:
            text += ' | disponivel em %d%%' % round(100 * v['availability'])
        out['bool' if v['type'] == 'bool' else 'num'][v['name']] = text
    return out


def compact_memory(digest):
    return [{k: m.get(k) for k in ('experiment_id', 'market', 'outcome', 'condition', 'control_condition',
                                   'state', 'group_n', 'control_n')}
            | ({'indicators': m['indicators']} if m.get('indicators') else {})
            for m in digest[-MAX_MEMORY_ITEMS:]]


def compact_agenda(items):
    seen, out = set(), []
    for a in items:
        key = (a.get('kind'), a.get('question'))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: a[k] for k in ('kind', 'question', 'avoid_condition') if k in a})
        if len(out) >= MAX_AGENDA_ITEMS:
            break
    return out


def build_packet(*, gate, dataset_description, variable_catalogue, memory_digest, agenda_items,
                 max_plans=3, trajectory_examples=None, budget_bytes=PACKET_BUDGET_BYTES):
    sci = gate.get('scientific_validation_gate', {})
    examples = trajectory_examples or {'examples': []}
    examples = dict(examples, examples=examples.get('examples', [])[:MAX_TRAJECTORY_EXAMPLES])
    fps, exprs = copy_guard()
    packet = {
        'schema_version': PACKET_SCHEMA,
        'mode': 'EXPLORATORY_RESEARCH_NOT_VALIDATION',
        'gates': {'exploration': gate['state'], 'scientific_validation': sci.get('state'),
                  'limitations': gate.get('limitations', [])[:4]},
        'data': dataset_description,
        'markets': {m: {o: (b or 'NO_MARKET_BASELINE') for o, b in outs.items()} for m, outs in OUTCOMES.items()},
        'variables': compact_variables(variable_catalogue),
        'contract': contract_spec(),
        'memory': compact_memory(memory_digest),
        'agenda': compact_agenda(agenda_items),
        'trajectory_examples': examples,
        'max_experiments': max_plans,
        # Not sent to the model: lets parse_response refuse copies.
        'copy_guard_fingerprints': fps, 'copy_guard_expressions': exprs,
    }
    budget = min(budget_bytes, PACKET_BUDGET_BYTES)
    while _user_size(packet) > budget and packet['trajectory_examples'].get('examples'):
        packet['trajectory_examples'] = dict(packet['trajectory_examples'],
                                             examples=packet['trajectory_examples']['examples'][:-1])
    while _user_size(packet) > budget and packet['memory']:
        packet['memory'] = packet['memory'][1:]
    if _user_size(packet) > budget:
        raise ValueError('PACKET_TOO_LARGE')
    raw = json.dumps(packet, sort_keys=True, ensure_ascii=False, allow_nan=False)
    packet['packet_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    return packet


def request_overhead_bytes(model, profile, max_plans=3):
    """Bytes of the request that are NOT the user packet (system prompt, schema, envelope)."""
    empty = {k: None for k in USER_KEYS}
    return len(request_body(empty, model, endpoint_kind=profile['endpoint'], json_mode=profile['json_mode'],
                            max_plans=max_plans)) + 256


USER_KEYS = ('gates', 'data', 'markets', 'variables', 'contract', 'memory', 'agenda',
             'trajectory_examples', 'max_experiments')


def _user_size(packet):
    # The user JSON is itself a JSON string in the HTTP envelope. Count escaping
    # and non-ASCII expansion exactly, not just the inner UTF-8 payload.
    inner = json.dumps({k: packet[k] for k in USER_KEYS}, ensure_ascii=False, allow_nan=False)
    return len(json.dumps(inner).encode())


# ---------------------------------------------------------------------------
# Response

def parse_response(content, *, max_plans=3, example_fingerprints=(), copied_expressions=()):
    """-> {'plans', 'rejected': [{'index', 'reason', 'field'?, 'detail'?}], 'new_questions',
    'received', 'accepted'}. Rejections carry only structural, code-validated tokens."""
    if not isinstance(content, str) or len(content.encode()) > MAX_RESPONSE_BYTES:
        raise ValueError('LLM_RESPONSE_SIZE_INVALID')
    data = strict_json(content)
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or set(data) - {'schema_version', 'experiments', 'new_questions'}
            or not isinstance(data.get('experiments'), list)):
        raise ValueError('LLM_RESPONSE_SCHEMA_INVALID')
    copied = set(copied_expressions)
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
            # A verbatim copy of an example is not the model's own hypothesis.
            rejected.append({'index': i, 'reason': 'COPIED_RESPONSE_EXAMPLE', 'field': 'plan'})
            continue
        conds = [('condition', plan['condition']), ('control_condition', plan['control_condition'])]
        hit = [f for f, e in conds if e is not None
               and canonical_json(inline(e, plan['indicators'])) in copied]
        if hit:
            rejected.append({'index': i, 'reason': 'COPIED_CONTRACT_FRAGMENT', 'field': hit[0]})
            continue
        plans.append(plan)
    qs = data.get('new_questions', [])
    questions = []
    if isinstance(qs, list):
        for q in qs[:5]:
            if isinstance(q, str) and 10 <= len(q) <= 300:
                q = ''.join(c for c in q if ord(c) >= 32)
                if q not in questions:
                    questions.append(q)
    return {'plans': plans, 'rejected': rejected, 'new_questions': questions,
            'received': len(data['experiments']), 'accepted': len(plans)}


# ---------------------------------------------------------------------------
# Request (exactly one, no retry)

def request_body(packet, model, *, endpoint_kind='openai', json_mode='json_object', max_plans=3):
    user = {k: packet[k] for k in USER_KEYS}
    if json_mode == 'json_schema':
        response_format = {'type': 'json_schema', 'json_schema': provider_schema(max_plans)}
    else:
        response_format = {'type': 'json_object'}
    body = {'temperature': TEMPERATURE, 'max_tokens': MAX_OUTPUT_TOKENS,
            'response_format': response_format,
            'messages': [{'role': 'system', 'content': SYSTEM},
                         {'role': 'user', 'content': json.dumps(user, ensure_ascii=False)}]}
    if endpoint_kind == 'openai':
        body = {'model': model, **body}
    return json.dumps(body).encode()


def _content_and_usage(envelope):
    """OpenAI-compatible ({choices}) or native Workers AI ({result: {response, usage}})."""
    if isinstance(envelope.get('choices'), list):
        return envelope['choices'][0]['message']['content'], envelope
    result = envelope.get('result')
    if envelope.get('success') is False or not isinstance(result, dict):
        raise ValueError('LLM_PROVIDER_ERROR')
    content = result.get('response')
    if isinstance(content, (dict, list)):     # JSON Mode may return the parsed object
        content = json.dumps(content, ensure_ascii=False)
    if not isinstance(content, str):
        raise ValueError('LLM_RESPONSE_MISSING')
    return content, {'usage': result.get('usage')}


# Socket timeout for the single provider request. urllib applies it to EACH blocking socket
# operation (connect/TLS, send, waiting for the status line, every body read), not to the whole
# call. The reply is not streamed, so the wait for the status line covers the full generation:
# up to MAX_OUTPUT_TOKENS (2400) constrained by JSON Mode on a 70B model. 60 s expired in live run
# 42054180234; 180 s allows ~13 tok/s worst case. Must stay well inside the 10-minute `discover`
# job of .github/workflows/v6-llm-autonomous.yml (checked offline by the tests).
# Worst case per call is therefore a few multiples of 180 s only if EVERY phase stalls; the
# job's own `timeout-minutes` remains the hard wall-clock bound (and the ledger counts the run).
LLM_HTTP_TIMEOUT_S = 180
DISCOVER_JOB_TIMEOUT_MIN = 10     # mirrors the workflow; a test fails if they drift apart
TRANSPORT_PHASES = ('connect_or_send', 'awaiting_response', 'reading_body')

MAX_ERROR_BODY_BYTES = 8_192
MAX_ERROR_MESSAGE_CHARS = 200
MAX_ERROR_ITEMS = 3
_REDACT = [(re.compile(r'(?i)bearer\s+\S+'), 'Bearer [REDACTED]'),
           (re.compile(r'(?i)/accounts/[^/\s"\']+'), '/accounts/[REDACTED]'),
           (re.compile(r'\b[A-Fa-f0-9]{32,}\b'), '[HEX_REDACTED]'),
           (re.compile(r'[A-Za-z0-9_\-]{32,}'), '[TOKEN_REDACTED]')]


class ProviderHTTPError(ValueError):
    """HTTP status >= 400 from the provider. ``diagnostic`` is safe to publish in a log."""

    def __init__(self, diagnostic):
        super().__init__('LLM_PROVIDER_HTTP_%s' % diagnostic.get('http_status'))
        self.diagnostic = diagnostic


def _safe_text(value, secrets=()):
    if not isinstance(value, str):
        return None
    for secret in secrets:
        if secret and len(secret) >= 4:
            value = value.replace(secret, '[REDACTED]')
    for rx, rep in _REDACT:
        value = rx.sub(rep, value)
    value = ''.join(ch if ch.isprintable() else ' ' for ch in value)
    return value[:MAX_ERROR_MESSAGE_CHARS]


def provider_error_diagnostic(exc, *, secrets=()):
    """Bounded, redacted summary of an ``HTTPError`` (reads at most MAX_ERROR_BODY_BYTES).

    Kept: HTTP status, Content-Type, body size/hash, up to 3 Cloudflare ``errors`` /
    ``messages`` items as {code:int, message:<=200 redacted chars}. Never kept: request body,
    headers, URL (it holds the account id), token, or any field other than code/message."""
    try:
        raw = exc.read(MAX_ERROR_BODY_BYTES + 1) if exc.fp is not None else b''
    except (OSError, ValueError, AttributeError):
        raw = b''
    finally:
        try:
            exc.close()
        except (OSError, AttributeError):
            pass
    raw = raw or b''
    status = exc.code if isinstance(exc.code, int) else None
    ctype = (exc.headers.get('Content-Type') if exc.headers is not None else None) or ''
    diag = {'http_status': status, 'content_type': _safe_text(ctype.split(';')[0].strip()[:60]),
            'body_bytes_read': min(len(raw), MAX_ERROR_BODY_BYTES),
            'body_truncated': len(raw) > MAX_ERROR_BODY_BYTES,
            'body_sha256': hashlib.sha256(raw[:MAX_ERROR_BODY_BYTES]).hexdigest() if raw else None,
            'provider_errors': [], 'provider_body_json': False}
    try:
        env = json.loads(raw[:MAX_ERROR_BODY_BYTES].decode('utf-8')) if raw else None
    except (UnicodeDecodeError, ValueError):
        env = None
    if isinstance(env, dict):
        diag['provider_body_json'] = True
        if isinstance(env.get('success'), bool):
            diag['provider_success'] = env['success']
        items = []
        for key in ('errors', 'messages'):
            vals = env.get(key)
            if isinstance(vals, list):
                items += [(key, x) for x in vals if isinstance(x, (dict, str))]
        for key, item in items[:MAX_ERROR_ITEMS]:
            if isinstance(item, str):
                item = {'message': item}
            code = item.get('code')
            diag['provider_errors'].append({
                'source': key,
                'code': code if isinstance(code, int) and not isinstance(code, bool) else None,
                'message': _safe_text(item.get('message'), secrets)})
    return diag


class ProviderTransportError(ValueError):
    """No HTTP status was obtained (timeout / connection failure). ``diagnostic`` is log-safe."""

    def __init__(self, diagnostic):
        super().__init__('LLM_PROVIDER_%s_%s' % (diagnostic['failure'].upper(), diagnostic['phase'].upper()))
        self.diagnostic = diagnostic


def _is_timeout(exc):
    return isinstance(exc, (TimeoutError, socket.timeout))


def transport_diagnostic(exc, *, phase, elapsed_s, timeout_s, secrets=()):
    """Bounded summary of a transport failure: phase, kind, exception type names, elapsed time.

    ``phase`` follows urllib's own structure: ``URLError`` wrapping the cause = failure while
    connecting / sending the request; a bare ``TimeoutError``/``OSError`` from the opener = no
    status line yet (the provider may be generating, so the call may have been billed); from
    ``read()`` = the body was being received. Never kept: URL, headers, request, token."""
    cause = exc.reason if isinstance(exc, URLError) and isinstance(exc.reason, BaseException) else exc
    timeout = _is_timeout(cause) or _is_timeout(exc) or (isinstance(exc, URLError) and 'timed out' in str(exc.reason))
    return {'failure': 'timeout' if timeout else 'connection', 'phase': phase,
            'exception_type': type(exc).__name__, 'cause_type': type(cause).__name__,
            'message': _safe_text(str(cause), secrets),
            'elapsed_s': round(elapsed_s, 1), 'timeout_s': timeout_s,
            'request_may_have_reached_provider': phase != 'connect_or_send'}


def invoke_once(packet, *, endpoint, model, api_key='', opener=urlopen, endpoint_kind='openai',
                json_mode='json_object', max_request_bytes=MAX_REQUEST_BYTES, max_plans=3,
                timeout_s=LLM_HTTP_TIMEOUT_S, clock=time.monotonic, quota=None):
    """Exactly one request; any failure raises. No retry loop exists here."""
    if opener is urlopen and (quota is None or not quota.sent or quota.key is None):
        raise ValueError('QUOTA_DURABLE_RESERVATION_REQUIRED')
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('HTTPS_ENDPOINT_REQUIRED')
    if not isinstance(model, str) or not 1 <= len(model) <= 100:
        raise ValueError('MODEL_REQUIRED')
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not 1 <= timeout_s <= LLM_HTTP_TIMEOUT_S:
        raise ValueError('INVALID_HTTP_TIMEOUT')
    body = request_body(packet, model, endpoint_kind=endpoint_kind, json_mode=json_mode, max_plans=max_plans)
    if len(body) > min(max_request_bytes, MAX_REQUEST_BYTES):
        raise ValueError('REQUEST_TOO_LARGE')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'User-Agent': 'master-brain-research-cycle/1'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    account = re.search(r'/accounts/([^/]+)', parsed.path)
    secrets = (api_key, account.group(1) if account else '')

    def transport_error(exc, phase):
        diag = transport_diagnostic(exc, phase=phase, elapsed_s=clock() - started, timeout_s=timeout_s,
                                    secrets=secrets)
        diag.update(llm_calls=1, request_bytes=len(body), json_mode=json_mode, endpoint_kind=endpoint_kind)
        return ProviderTransportError(diag)

    if quota is not None:
        quota.consume_http(model, len(body))
    started = clock()
    try:
        resp_cm = opener(Request(endpoint, data=body, headers=headers, method='POST'), timeout=timeout_s)
    except HTTPError as exc:
        diag = provider_error_diagnostic(exc, secrets=secrets)
        diag.update(llm_calls=1, request_bytes=len(body), json_mode=json_mode, endpoint_kind=endpoint_kind,
                    schema_sha256=hashlib.sha256(canonical_json(
                        json.loads(body)['response_format']).encode()).hexdigest())
        raise ProviderHTTPError(diag) from None
    except URLError as exc:          # urllib wraps failures of connect/TLS/send in URLError
        raise transport_error(exc, 'connect_or_send') from None
    except OSError as exc:           # TimeoutError etc. while waiting for the status line
        raise transport_error(exc, 'awaiting_response') from None
    with resp_cm as resp:
        if resp.status != 200:
            raise ValueError('LLM_NON_SUCCESS_STATUS')
        try:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except OSError as exc:
            raise transport_error(exc, 'reading_body') from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError('LLM_RESPONSE_TOO_LARGE')
    envelope = strict_json(raw.decode('utf-8'))
    content, usage_env = _content_and_usage(envelope)
    return {'content': content, 'usage': provider_usage(usage_env, model), 'llm_calls': 1,
            'response_sha256': hashlib.sha256(raw).hexdigest(), 'request_bytes': len(body)}

