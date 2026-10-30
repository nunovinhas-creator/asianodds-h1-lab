"""Human-reviewed V6 LLM research dossiers; isolated from forecasts and alerts.

Reads only published aggregate reports. No producer, result ledger, immutable memory,
Telegram message or betting output is read or modified by this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SCHEMA = 1
MAX_SOURCE_BYTES = 250_000
MAX_RESPONSE_BYTES = 80_000
SOURCES = (
    'docs/lab/v6-p0-gates.json',
    'docs/lab/v6-falsification.json',
    'docs/lab/v6-readiness.json',
    'docs/lab/v6-weekly-drift.json',
    'docs/lab/pattern-research.json',
)
TOPICS = (
    {'id': 'T01', 'family': 'TOTAL_1X2',
     'question': 'A co-observacao de movimentos Total e 1X2 acrescenta informacao sobre o resultado alem do baseline do mercado?',
     'control': 'Comparar jogos com mesmo baseline e antecedencia; separar mensagens distintas de co-observacao.'},
    {'id': 'T02', 'family': 'REPEATED_ALERTS',
     'question': 'Episodios repetidos de alertas melhoram a informacao previsional face ao primeiro alerta?',
     'control': 'Unidade jogo, nao mensagem; estratificar por numero de episodios e qualidade do preco.'},
    {'id': 'T03', 'family': 'TOTAL_AH',
     'question': 'Movimentos de Total e Handicap Asiatico observados juntos diferem de movimentos isolados?',
     'control': 'Separar alteracoes na mesma mensagem de intervalos sem observacao; controlar competicao e linha.'},
    {'id': 'T04', 'family': 'LEAD_TIME',
     'question': 'A antecedencia do primeiro sinal modifica a qualidade do baseline do mercado?',
     'control': 'Separar categorias de antecedencia predefinidas e comparar com jogos sem o padrao.'},
)
SYSTEM = (
    'Es investigador de hipoteses EM SOMBRA do MASTER BRAIN V6. Devolve APENAS um objeto JSON valido. '
    'Nao recomendes apostas, valores, alertas ou mudancas de producao. '
    'Nao afirmes edge, ROI, rentabilidade, causalidade ou significancia estatistica. '
    'Usa apenas factos agregados e as definicoes no feature_catalogue; nao inventes resultados nem valores. '
    'Gera exatamente UMA proposta TESTAVEL que combine 2 ou 3 feature_codes exatos de familias DISTINTAS do catalogo. '
    'Mantem outcome OVER_2_5, baseline MARKET_MODEL_OVER25 e metric BRIER_SCORE ou LOG_LOSS. '
    'Baseline e uma probabilidade derivada do Asian Total por Poisson, NAO uma odd transacionavel. '
    'A unidade estatistica e MATCH: uma partida, nao uma mensagem. '
    'Especifica control_group, data_needed e test_design com todos os feature_codes por escrito. '
    'Desenha comparacao prospetiva fora da amostra vs baseline, controlos e criterios de falsificacao, '
    'incluindo falta de FT, qualidade do preco, selecao multipla e teste temporal. '
    'Nomes source_refs indicam PROVENIENCIA de definicoes/relatorios, nunca prova de efeito. '
    'A resposta tem APENAS schema_version=1 e proposals=[uma proposta DRAFT]; sem wrappers nem markdown. '
    'O modelo so sugere hipoteses por avaliar; nao ativa nenhuma estrategia.'
)


def _reject_constant(value):
    raise ValueError('Non-finite constant in research source')


def _finite_float(value):
    n = float(value)
    if not math.isfinite(n):
        raise ValueError('Non-finite numeric source value')
    return n


def strict_json(raw):
    return json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float)


def _number(value, name, *, whole=False):
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        raise ValueError('Invalid metric: ' + name)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid metric: ' + name)
    return value


def _load(root, name):
    path = Path(root) / name
    if not path.is_file() or path.is_symlink():
        raise ValueError('Missing or unsafe source: ' + name)
    if path.stat().st_size > (600_000 if name == SOURCES[4] else MAX_SOURCE_BYTES):
        raise ValueError('Unbounded source: ' + name)
    raw = path.read_bytes()
    data = strict_json(raw.decode('utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Invalid research source schema: ' + name)
    return data, hashlib.sha256(raw).hexdigest()


def build_packet(root):
    source_data = {}
    digests = {}
    for name in SOURCES:
        source_data[name], digests[name] = _load(root, name)
    gates = source_data[SOURCES[0]]
    fals = source_data[SOURCES[1]]
    readiness = source_data[SOURCES[2]]
    drift = source_data[SOURCES[3]]
    research = source_data[SOURCES[4]]
    catalogue = research.get('pattern_catalogue')
    if not isinstance(catalogue, dict) or not catalogue:
        raise ValueError('Missing V5 feature catalogue')
    features = []
    for code, details in sorted(catalogue.items()):
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,60}', code):
            raise ValueError('Unsafe feature code')
        if not isinstance(details, dict) or not isinstance(details.get('family'), str) or not isinstance(details.get('description'), str):
            raise ValueError('Invalid feature catalogue entry')
        family = details['family']
        description = details['description']
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9_]{1,30}', family) or len(description) > 140 or any(ord(c) < 32 for c in description):
            raise ValueError('Unsafe feature description')
        features.append({'code': code, 'family': family, 'description': description})
    if len(features) > 60:
        raise ValueError('Unexpected unbounded feature catalogue')
    if gates.get('scientific_state') != 'INCONCLUSIVO' or fals.get('overall') != 'INCONCLUSIVO':
        raise ValueError('Unexpected scientific state; review this version before using LLM')
    seven = gates['gates']['7_days']
    fourteen = gates['gates']['14_days']
    for gate in (seven, fourteen):
        if gate.get('status') not in ('WARMUP', 'INSUFFICIENT_N', 'BLOCKED') or gate.get('scientific_acceptance') != 'BLOCKED':
            raise ValueError('Scientific gate requires explicit human review')
    ratio = _number(seven['ratio'], 'coverage ratio')
    if ratio > 1:
        raise ValueError('Coverage over 100%')
    denominator = _number(seven['source_eligible'], 'eligible', whole=True)
    frozen = _number(seven['frozen_pre_kickoff'], 'frozen', whole=True)
    missing = _number(seven['missing_count'], 'missing', whole=True)
    if denominator != frozen + missing:
        raise ValueError('Inconsistent prospective coverage')
    counts = gates['ft_knowledge_timeline']['counts']
    facts = {
        'scientific_state': 'INCONCLUSIVO',
        'gate_7_days': seven['status'],
        'gate_14_days': fourteen['status'],
        'source_eligible': denominator,
        'frozen_pre_kickoff': frozen,
        'source_coverage_ratio': ratio,
        'missing_capture': missing,
        'ft_chronology_consistent_not_independently_proven': _number(counts['confirmed_event_chronology_consistent_not_independently_proven'], 'ft chronologic', whole=True),
        'ft_chronology_invalid': _number(counts['confirmed_event_chronology_invalid'], 'ft invalid', whole=True),
        'eligible_without_confirmed_ft': _number(counts['eligible_match_without_confirmed_ft'], 'ft missing', whole=True),
        'falsification_screens': {k: _number(v, k, whole=True) for k, v in fals['check_result_counts'].items() if k in ('PASS', 'FAIL', 'INSUFFICIENT_N')},
        'falsification_overall': 'INCONCLUSIVO',
        'readiness_state': str(readiness.get('status', 'UNKNOWN'))[:90],
        'weekly_drift_state': str(drift.get('latest', {}).get('overall', 'UNKNOWN'))[:90],
        'note': 'Source coverage is not proof of timely ingestion; ledger FT chronology is not independent provider proof.'
    }
    packet = {
        'schema_version': SCHEMA,
        'status': 'SHADOW_RESEARCH_DOSSIER_NOT_VALIDATION',
        'readonly': True,
        'source_sha256': digests,
        'facts': facts,
        'topics': list(TOPICS),
        'feature_catalogue': features,
        'instructions': SYSTEM,
        'response_schema': {
            'schema_version': 1,
            'proposals': [{
                'status': 'DRAFT', 'topic_id': 'T02',
                'feature_codes': ['G_MULTI_ALERT', 'M_IMPLIED_GOALS_FLAT'],
                'outcome': 'OVER_2_5', 'baseline': 'MARKET_MODEL_OVER25', 'metric': 'BRIER_SCORE',
                'hypothesis': 'A combinacao de alertas repetidos com golos implicitos estaveis pode melhorar o baseline.',
                'null_hypothesis': 'A combinacao nao melhora o Brier score relativamente ao baseline.',
                'control_group': 'Jogos futuros com probabilidade inicial e antecedencia comparaveis sem este cruzamento.',
                'test_design': 'Congelar G_MULTI_ALERT e M_IMPLIED_GOALS_FLAT antes do KO e comparar Brier score por jogo OOS.',
                'falsification': 'Rejeitar se o Brier score OOS nao melhorar face ao baseline em teste prospetivo.',
                'data_needed': ['Capturas das duas variaveis feitas antes do KO', 'FT regulamentar confirmado com carimbo'],
                'confounders': ['Antecedencia', 'Competicao'],
                'source_refs': [SOURCES[4]],
            }]
        },
        'limitations': [
            'No model training, betting recommendation, promotion or hypothesis registration.',
            'No raw Telegram messages, immutable journals or secrets are sent.',
            'The LLM does not judge statistical significance or prove any FT.',
            'All topics are prereview questions, not new observed findings.',
        ]
    }
    return packet


def validate_proposals(packet, response):
    if not isinstance(response, dict) or set(response) != {'schema_version', 'proposals'} or response.get('schema_version') != 1:
        # Log only boolean schema diagnostics, never model text.
        flags = ('object=' + str(isinstance(response, dict)) +
                 ', version_1=' + str(isinstance(response, dict) and response.get('schema_version') == 1) +
                 ', proposals_present=' + str(isinstance(response, dict) and 'proposals' in response) +
                 ', unexpected_keys=' + str(isinstance(response, dict) and bool(set(response) - {'schema_version', 'proposals'})))
        raise ValueError('Unexpected model response schema (' + flags + ')')
    proposals = response['proposals']
    if not isinstance(proposals, list) or not (1 <= len(proposals) <= 4):
        raise ValueError('Unbounded or empty proposals')
    expected = {'status', 'topic_id', 'feature_codes', 'outcome', 'baseline', 'metric',
                'hypothesis', 'null_hypothesis', 'control_group', 'test_design',
                'falsification', 'data_needed', 'confounders', 'source_refs'}
    allowed_topics = {t['id'] for t in packet['topics']}
    allowed_refs = set(packet['source_sha256'])
    feature_families = {f['code']: f['family'] for f in packet['feature_catalogue']}
    used = set()
    for p in proposals:
        if not isinstance(p, dict) or set(p) != expected or p['status'] != 'DRAFT':
            raise ValueError('Invalid proposal contract')
        if not isinstance(p['topic_id'], str) or p['topic_id'] not in allowed_topics or p['topic_id'] in used:
            raise ValueError('Unrecognized or duplicated topic')
        used.add(p['topic_id'])
        codes = p['feature_codes']
        if (not isinstance(codes, list) or not 2 <= len(codes) <= 3
                or any(not isinstance(code, str) or code not in feature_families for code in codes)
                or len(set(codes)) != len(codes)
                or len({feature_families[code] for code in codes}) < 2):
            raise ValueError('Invalid feature combination: require 2-3 actual codes from distinct families')
        if (p['outcome'] != 'OVER_2_5' or p['baseline'] != 'MARKET_MODEL_OVER25'
                or p['metric'] not in ('BRIER_SCORE', 'LOG_LOSS')):
            raise ValueError('Unsupported outcome, market baseline or metric')
        if not all(code in p['test_design'] for code in codes):
            raise ValueError('Test design does not mention all selected feature codes')
        for k in ('hypothesis', 'null_hypothesis', 'control_group', 'test_design', 'falsification'):
            if not isinstance(p[k], str) or not (10 <= len(p[k]) <= 1200):
                raise ValueError('Invalid proposal text: ' + k)
        if not isinstance(p['confounders'], list) or not (1 <= len(p['confounders']) <= 8) or any(not isinstance(s, str) or not 2 <= len(s) <= 200 for s in p['confounders']):
            raise ValueError('Invalid confounders')
        if not isinstance(p['data_needed'], list) or not (1 <= len(p['data_needed']) <= 5) or any(not isinstance(s, str) or not 10 <= len(s) <= 200 for s in p['data_needed']):
            raise ValueError('Invalid data requirements')
        if not isinstance(p['source_refs'], list) or not p['source_refs'] or any(not isinstance(s, str) for s in p['source_refs']) or not set(p['source_refs']) <= allowed_refs or SOURCES[4] not in p['source_refs']:
            raise ValueError('Unsupported references')
    return {'status': 'DRAFT_UNVALIDATED_HUMAN_REVIEW_REQUIRED',
            'source_sha256': packet['source_sha256'], 'proposals': proposals,
            'notice': 'Untrusted LLM text; contract validation is not factual validation. No effects on V6 or bets.'}


def invoke(packet, *, endpoint, model, api_key='', opener=urlopen):
    """One explicitly requested, bounded request. Never called by repo workflows."""
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('An explicit HTTPS endpoint is required')
    if not isinstance(model, str) or not (1 <= len(model) <= 100):
        raise ValueError('An explicit model is required')
    # Keep the example and validated packet contract in sync.
    example = packet['response_schema']
    messages = [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': json.dumps({'facts': packet['facts'], 'topics': packet['topics'],
                                              'source_sha256': packet['source_sha256'],
                                              'feature_catalogue': packet['feature_catalogue'],
                                              'response_schema': packet['response_schema'],
                                              'exact_output_example': example,
                                              'instruction': 'Devolve UMA proposta com feature_codes reais de pelo menos duas familias, metric e control_group. Segue as chaves exatas do exemplo.'}, ensure_ascii=False)}
    ]
    body = json.dumps({'model': model, 'messages': messages, 'temperature': 0,
                       'max_tokens': 1600, 'response_format': {'type': 'json_object'}}).encode('utf-8')
    if len(body) > 20_000:
        raise ValueError('Oversized research request')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'User-Agent': 'master-brain-v6-research-manual/1'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = Request(endpoint, data=body, headers=headers, method='POST')
    with opener(req, timeout=30) as resp:
        if resp.status != 200:
            raise ValueError('LLM endpoint returned a non-success status')
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError('Oversized LLM response')
    envelope = strict_json(raw.decode('utf-8'))
    content = envelope['choices'][0]['message']['content']
    if not isinstance(content, str) or len(content) > MAX_RESPONSE_BYTES:
        raise ValueError('Invalid LLM content')
    parsed_content = strict_json(content)
    try:
        return validate_proposals(packet, parsed_content)
    except (ValueError, KeyError, TypeError) as exc:
        # No model-generated strings are shown in failures.
        finish_reason = envelope.get('choices', [{}])[0].get('finish_reason', 'unknown')
        finish_reason = finish_reason if finish_reason in ('stop', 'length', 'content_filter') else 'other'
        raise ValueError('LLM_RESPONSE_REJECTED: finish_reason=' + str(finish_reason) + '; ' + str(exc)) from None
