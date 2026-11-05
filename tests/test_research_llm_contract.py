"""LLM -> Python contract v3 (live runs 42021728675 and 42030138637: 6 plans, 0 accepted).

Proves, fully offline (fake HTTP openers, zero provider calls):
  * every example and rule sent to the model is accepted by the REAL validator;
  * valid model plans travel LLM(simulated) -> DSL -> executor -> memory -> panel on real data;
  * invalid plans stay blocked, with the structural field that failed;
  * new cycles record model, tokens and the plan funnel; legacy records are untouched.
No statistical result is fabricated: every number comes from the executor on repository data.
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_fixtures import NOW, FakeOpener, dataset, gate  # noqa: E402

from h1lab import research_cycle  # noqa: E402
from h1lab.research_cycle import build_panel, cycle_funnels, run_cycle  # noqa: E402
from h1lab.research_dataset import OUTCOMES, VARIABLES  # noqa: E402
from h1lab.research_dsl import NAME_RE, DSLError, validate_indicator  # noqa: E402
from h1lab import research_llm  # noqa: E402
from h1lab.research_llm import (LEGACY_EXAMPLE_V2, MAX_NEURONS_PER_CALL, MAX_REQUEST_BYTES,  # noqa: E402
                                MODEL_PROFILES, SYSTEM, build_packet, contract_spec, grammar, invoke_once,
                                neuron_bound, parse_response, plan_template, request_body, response_schema)
from h1lab.research_dsl import OPS  # noqa: E402
from h1lab.research_memory import read_memory  # noqa: E402
from h1lab.research_plan import REQUIRED, STRATA, PlanError, base_types, validate_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def ind(name, expr, desc='Indicador proposto pelo modelo'):
    return {'name': name, 'description': desc, 'expr': expr}


def v(name):
    return {'var': name}


def c(x):
    return {'const': x}


def op(o, *args):
    return {'op': o, 'args': list(args)}


BASE = {'hypothesis': 'O grupo tem residual diferente do esperado pelo mercado.',
        'null_hypothesis': 'Nao ha diferenca face ao baseline do mercado.',
        'rationale': 'Escolha do modelo.', 'alternative_explanations': ['Antecedencia diferente'],
        'confounders': ['lead_bin']}

VALID = [
    dict(BASE, question='Golos implicitos a subir com a linha Total parada diferem de subidas com a linha a mexer?',
         market='TOTAL_GOALS', outcome='OVER_2_5',
         indicators=[ind('X_LAMBDA_RISE', op('ge', v('lambda_net'), c(0.05))),
                     ind('X_LINE_STABLE', op('eq', v('total_line_net'), c(0)))],
         condition=op('and', v('X_LAMBDA_RISE'), v('X_LINE_STABLE')),
         control_condition=op('and', v('X_LAMBDA_RISE'), op('not', v('X_LINE_STABLE')))),
    dict(BASE, question='A probabilidade da casa a subir com a linha AH a mexer altera a vitoria da casa?',
         market='1X2', outcome='HOME_WIN',
         indicators=[ind('X_HOME_DRIFT', op('gt', v('p_home_net'), c(0)))],
         condition=op('and', v('X_HOME_DRIFT'), op('gt', v('ah_line_moves'), c(0)))),
    dict(BASE, question='Um movimento grande da linha AH altera a cobertura do handicap da casa?',
         market='ASIAN_HANDICAP', outcome='AH_HOME_COVER', indicators=[],
         condition=op('ge', op('abs', v('ah_line_net')), c(0.25))),
]
UNUSED = dict(BASE, question='Movimento cedo dos golos implicitos altera o Over face ao mercado?',
              market='TOTAL_GOALS', outcome='OVER_2_5',
              indicators=[ind('X_EARLY_MOVE', op('gt', v('lead_first_min'), c(600)))],
              condition=op('ge', v('lambda_net'), c(0.1)))
BAD_NAME = dict(BASE, question='Subida dos golos implicitos com nome em minusculas altera o Over?',
                market='TOTAL_GOALS', outcome='OVER_2_5',
                indicators=[ind('X_lambda_rise', op('ge', v('lambda_net'), c(0.1)))],
                condition=v('X_lambda_rise'))
UNKNOWN_VAR = dict(BASE, question='Uma variavel inexistente pode ser usada pelo modelo nesta pergunta?',
                   market='TOTAL_GOALS', outcome='OVER_2_5', condition=op('gt', v('lambda_change'), c(0)))


def reply(*plans, extra=None):
    body = {'schema_version': 1, 'experiments': [copy.deepcopy(p) for p in plans],
            'new_questions': ['O AH contrario ao Total comporta-se de forma diferente?']}
    body.update(extra or {})
    return json.dumps(body, ensure_ascii=False)


def small_packet():
    return build_packet(gate=gate(), dataset_description={'matches': 10},
                        variable_catalogue=[{'name': k, 'type': t[0], 'market': t[1], 'description': t[2],
                                             'availability': 1.0} for k, t in VARIABLES.items()],
                        memory_digest=[], agenda_items=[])


class NativeOpener:
    """Fake Workers AI native endpoint (/ai/run/{model}); JSON Mode returns the parsed object."""

    def __init__(self, content, *, as_object=True, success=True):
        from research_fixtures import FakeResponse
        self._resp = FakeResponse
        self.calls = []
        obj = json.loads(content) if as_object else content
        self.body = json.dumps({'result': {'response': obj, 'usage': {
            'prompt_tokens': 7000, 'completion_tokens': 900, 'total_tokens': 7900}},
            'success': success, 'errors': [], 'messages': []}).encode()

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        return self._resp(self.body)


def guard_kw(packet):
    return {'example_fingerprints': packet['copy_guard_fingerprints'],
            'copied_expressions': packet['copy_guard_expressions']}


def through_model(content, *, native=True):
    """Simulated model through the REAL request path (invoke_once) and parser."""
    packet = small_packet()
    if native:
        opener = NativeOpener(content) if _is_json(content) else FakeOpener(content)
        out = invoke_once(packet, endpoint='https://simulated.invalid/ai/run/M', model='M', opener=opener,
                          endpoint_kind='native', json_mode='json_schema')
    else:
        opener = FakeOpener(content)
        out = invoke_once(packet, endpoint='https://simulated.invalid/v1/chat/completions', model='SIM',
                          opener=opener)
    assert len(opener.calls) == 1
    return parse_response(out['content'], **guard_kw(packet)), opener


def _is_json(content):
    try:
        json.loads(content)
        return True
    except ValueError:
        return False


def schema_ok(value, schema):
    """Minimal JSON Schema checker for the keywords response_schema() uses (no dependency)."""
    t = schema.get('type')
    types = t if isinstance(t, list) else [t] if t else []
    pyt = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool}
    if types and not any(isinstance(value, pyt[x]) and not (x in ('integer', 'number') and isinstance(value, bool))
                         for x in types):
        return False
    if 'enum' in schema and value not in schema['enum']:
        return False
    if isinstance(value, str):
        import re
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 10 ** 9):
            return False
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            return False
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', 10 ** 9):
            return False
        if schema.get('uniqueItems') and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            return False
        return all(schema_ok(x, schema.get('items', {})) for x in value)
    if isinstance(value, dict):
        props = schema.get('properties', {})
        if any(k not in value for k in schema.get('required', [])):
            return False
        if schema.get('additionalProperties') is False and set(value) - set(props):
            return False
        return all(schema_ok(v, props[k]) for k, v in value.items() if k in props)
    return True


class ContractSentToModel(unittest.TestCase):
    def test_no_complete_example_is_sent_and_the_template_cannot_validate(self):
        packet = small_packet()
        self.assertNotIn('response_example', packet)
        body = json.loads(request_body(packet, 'M', endpoint_kind='native', json_mode='json_schema'))
        user = json.loads(body['messages'][1]['content'])
        self.assertNotIn('copy_guard_fingerprints', user, 'internal guard not sent to the model')
        tpl = plan_template()
        with self.assertRaises(PlanError):
            validate_plan(copy.deepcopy(tpl))
        self.assertFalse(schema_ok({'schema_version': 1, 'experiments': [tpl]}, response_schema()),
                         'a copied template is refused by the JSON Schema too')

    def test_grammar_is_generated_from_ops_with_exact_types(self):
        g = grammar()
        text = {'BOOL_EXPR': ' '.join(g['BOOL_EXPR']), 'NUM_EXPR': ' '.join(g['NUM_EXPR'])}
        for op, (args, out) in OPS.items():
            side = 'BOOL_EXPR' if out == 'bool' else 'NUM_EXPR'
            line = [r for r in g[side] if ('"%s"' % op in r or '|%s|' % op in r or '"%s|' % op in r
                                          or '|%s"' % op in r)]
            self.assertEqual(len(line), 1, op)
            if op in ('and', 'or', 'not'):
                self.assertIn('args": [BOOL_EXPR', line[0])
                self.assertNotIn('NUM_EXPR', line[0])
            if op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne', 'between'):
                self.assertIn('args": [NUM_EXPR', line[0])
        self.assertIn('and, or e not so aceitam BOOL_EXPR', g['type_rules'][0])
        wrong, right = g['type_fragments']['ERRADO (TYPE_ERROR)'], g['type_fragments']['CERTO']
        from h1lab.research_dsl import validate
        with self.assertRaisesRegex(DSLError, 'TYPE_ERROR:and expects bool'):
            validate(wrong, base_types(), expect='bool')
        validate(right, base_types(), expect='bool')

    def test_json_schema_accepts_valid_plans_and_mirrors_the_contract(self):
        sch = response_schema()
        self.assertTrue(schema_ok(json.loads(reply(*VALID)), sch))
        plan = sch['properties']['experiments']['items']
        self.assertEqual(set(plan['required']), REQUIRED)
        self.assertEqual(set(plan['properties']['market']['enum']), set(OUTCOMES))
        self.assertEqual(plan['properties']['indicators']['items']['properties']['name']['pattern'],
                         '^' + NAME_RE.pattern + '$')
        self.assertEqual(set(plan['properties']['condition']['properties']['op']['enum']), set(OPS))
        bad = json.loads(reply(BAD_NAME))
        self.assertFalse(schema_ok(bad, sch), 'lowercase indicator name violates the schema pattern')

    def test_contract_is_derived_from_validator_constants(self):
        k = contract_spec()
        self.assertEqual(k['indicator']['name_regex'], NAME_RE.pattern)
        self.assertEqual(set(k['plan_keys']['required']), REQUIRED)
        self.assertEqual(k['confounders_allowed'], list(STRATA))
        self.assertEqual(k['markets'], {m: sorted(o) for m, o in OUTCOMES.items()})
        for name in k['indicator']['name_valid_examples']:
            validate_indicator(ind(name, v('lambda_net')), base_types())
        for name in k['indicator']['name_invalid_examples']:
            with self.subTest(name=name), self.assertRaises(DSLError):
                validate_indicator(ind(name, v('lambda_net')), base_types())

    def test_system_prompt_is_short_and_states_the_failing_rules(self):
        self.assertLess(len(SYSTEM), 1400)
        for phrase in ('and/or/not so recebem BOOL_EXPR', 'MAIUSCULAS', 'TEM de ser usado',
                       'variables.num/variables.bool', 'textos entre < > sao instrucoes'):
            self.assertIn(phrase, SYSTEM)

    def test_native_request_is_bounded_and_carries_the_schema(self):
        opener = NativeOpener(reply(*VALID))
        invoke_once(small_packet(), endpoint='https://simulated.invalid/ai/run/M', model='M', opener=opener,
                    endpoint_kind='native', json_mode='json_schema')
        body = json.loads(opener.calls[0].data)
        self.assertNotIn('model', body, 'native endpoint names the model in the URL')
        self.assertEqual(body['response_format']['type'], 'json_schema')
        # The provider receives the reduced guidance schema (run 42038573930, HTTP 400);
        # the full contract stays in response_schema() and in the Python validator.
        self.assertEqual(body['response_format']['json_schema'], research_llm.provider_schema())
        self.assertEqual(body['max_tokens'], 2400)
        self.assertLessEqual(len(opener.calls[0].data), MAX_REQUEST_BYTES)


class ProviderEnvelope(unittest.TestCase):
    def test_native_object_and_string_responses(self):
        for as_object in (True, False):
            opener = NativeOpener(reply(VALID[0]), as_object=as_object)
            out = invoke_once(small_packet(), endpoint='https://x.invalid/ai/run/M', model='M', opener=opener,
                              endpoint_kind='native', json_mode='json_schema')
            self.assertEqual(parse_response(out['content'])['accepted'], 1)
            self.assertEqual(out['usage']['tokens']['total_tokens'], 7900)

    def test_provider_failure_is_not_retried(self):
        opener = NativeOpener(reply(VALID[0]), success=False)
        with self.assertRaisesRegex(ValueError, 'LLM_PROVIDER_ERROR'):
            invoke_once(small_packet(), endpoint='https://x.invalid/ai/run/M', model='M', opener=opener,
                        endpoint_kind='native', json_mode='json_schema')
        self.assertEqual(len(opener.calls), 1)


class NeuronBudget(unittest.TestCase):
    MODEL = '@cf/meta/llama-3.3-70b-instruct-fp8-fast'

    def test_worst_case_per_call_and_per_day_fit_the_free_allocation(self):
        prof = MODEL_PROFILES[self.MODEL]
        b = neuron_bound(self.MODEL, prof['max_request_bytes'])
        # 30,000 B / 2.0 B per token = 15,000 input tokens; 2,400 output tokens.
        expected = (15_000 * 26_668 + 2_400 * 204_805) / 1e6
        self.assertAlmostEqual(b['neurons_max'], round(expected, 1))
        self.assertLessEqual(b['neurons_max'], MAX_NEURONS_PER_CALL)
        self.assertLessEqual(4 * b['neurons_max'], research_llm.FREE_NEURONS_PER_DAY)
        self.assertLessEqual(15_000 + 2_400, prof['context_tokens'])

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, 'REQUEST_OVER_MODEL_BUDGET'):
            neuron_bound(self.MODEL, 30_001)
        with self.assertRaisesRegex(ValueError, 'MODEL_COST_UNKNOWN'):
            neuron_bound('@cf/meta/llama-3.1-8b-instruct-fast', 1_000)
        with self.assertRaisesRegex(ValueError, 'DAILY_NEURON_BUDGET_EXCEEDED'):
            neuron_bound(self.MODEL, 20_000, prior_calls_today=5)
        small = dict(MODEL_PROFILES[self.MODEL], context_tokens=8_000)
        with mock.patch.dict(MODEL_PROFILES, {self.MODEL: small}), \
                self.assertRaisesRegex(ValueError, 'CONTEXT_WINDOW_EXCEEDED'):
            neuron_bound(self.MODEL, 20_000)


class SimulatedModelReplies(unittest.TestCase):
    def test_three_valid_plans(self):
        out, _ = through_model(reply(*VALID))
        self.assertEqual((out['received'], out['accepted'], out['rejected']), (3, 3, []))

    def test_partially_valid_reply_keeps_the_valid_plan(self):
        out, _ = through_model(reply(VALID[0], UNUSED, BAD_NAME))
        self.assertEqual(out['accepted'], 1)
        self.assertEqual([r['reason'] for r in out['rejected']],
                         ['INDICATOR_DEFINED_BUT_UNUSED', 'DSL:INVALID_INDICATOR_NAME'])

    def test_three_invalid_plans_are_all_blocked(self):
        out, _ = through_model(reply(UNUSED, BAD_NAME, UNKNOWN_VAR))
        self.assertEqual(out['accepted'], 0)
        self.assertEqual(len(out['rejected']), 3)

    def test_indicator_defined_but_unused_names_the_indicator(self):
        out, _ = through_model(reply(UNUSED))
        r = out['rejected'][0]
        self.assertEqual(r['reason'], 'INDICATOR_DEFINED_BUT_UNUSED')
        self.assertEqual(r['field'], 'indicators')
        self.assertEqual(r['detail']['unused_indicators'], ['X_EARLY_MOVE'])

    def test_invalid_name_points_to_the_field_without_echoing_model_text(self):
        out, _ = through_model(reply(BAD_NAME))
        r = out['rejected'][0]
        self.assertEqual((r['reason'], r['field']), ('DSL:INVALID_INDICATOR_NAME', 'indicators[0].name'))
        self.assertNotIn('X_lambda_rise', json.dumps(r))

    def test_unknown_variable_is_blocked(self):
        out, _ = through_model(reply(UNKNOWN_VAR))
        self.assertEqual(out['rejected'][0]['reason'], 'DSL:UNKNOWN_VARIABLE:lambda_change')
        self.assertEqual(out['rejected'][0]['field'], 'condition')

    def test_invalid_json_and_schema_fail_closed(self):
        for bad in ('{"schema_version": 1, "experiments": [', 'texto livre', json.dumps({'experiments': []})):
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError):
                through_model(bad)

    def test_reply_without_hypotheses(self):
        out, _ = through_model(reply())
        self.assertEqual((out['received'], out['accepted'], out['plans']), (0, 0, []))

    def test_copies_are_not_the_models_hypotheses(self):
        # Run 42030138637: the v2 example was returned verbatim twice.
        out, _ = through_model(reply(LEGACY_EXAMPLE_V2))
        self.assertEqual((out['accepted'], out['rejected'][0]['reason']), (0, 'COPIED_RESPONSE_EXAMPLE'))
        # The structural template cannot pass the validator.
        out, _ = through_model(reply(plan_template()))
        self.assertEqual(out['rejected'][0]['reason'], 'UNSUPPORTED_MARKET_OR_OUTCOME')
        # A grammar fragment handed back as the condition is a copy, not a hypothesis.
        frag = dict(BASE, question='Pergunta que reutiliza o fragmento CERTO da gramatica como condicao?',
                    market='TOTAL_GOALS', outcome='OVER_2_5', condition=grammar()['type_fragments']['CERTO'])
        out, _ = through_model(reply(frag))
        self.assertEqual((out['rejected'][0]['reason'], out['rejected'][0]['field']),
                         ('COPIED_CONTRACT_FRAGMENT', 'condition'))
        # Same fragment hidden behind an indicator is still detected (expressions are inlined).
        hidden = dict(frag, indicators=[ind('X_FRAG', grammar()['type_fragments']['CERTO'])], condition=v('X_FRAG'))
        out, _ = through_model(reply(hidden))
        self.assertEqual(out['rejected'][0]['reason'], 'COPIED_CONTRACT_FRAGMENT')

    def test_type_errors_stay_blocked(self):
        # Run 42030138637, plan 0: DSL:TYPE_ERROR:and expects bool in indicators[0].
        bad = dict(BASE, question='Um indicador que mistura numeros dentro de and e aceite pela DSL?',
                   market='TOTAL_GOALS', outcome='OVER_2_5',
                   indicators=[ind('X_MIXED', op('and', v('lambda_net'), v('ctx_cup')))], condition=v('X_MIXED'))
        out, _ = through_model(reply(bad))
        self.assertEqual((out['rejected'][0]['reason'], out['rejected'][0]['field']),
                         ('DSL:TYPE_ERROR:and expects bool', 'indicators[0]'))
        cmp_bool = dict(bad, indicators=[], condition=op('gt', v('ctx_cup'), c(0)))
        out, _ = through_model(reply(cmp_bool))
        self.assertEqual(out['rejected'][0]['reason'], 'DSL:TYPE_ERROR:gt expects num')

    def test_validator_rules_unchanged(self):
        # The fix is in the instructions, not in a weaker validator.
        from h1lab.research_plan import PlanError
        for raw in (UNUSED, BAD_NAME, UNKNOWN_VAR):
            with self.assertRaises(PlanError):
                validate_plan(copy.deepcopy(raw))


class CycleProvenance(unittest.TestCase):
    def llm(self, content, origin='SIMULATED_LLM'):
        out, _ = through_model(content)
        out.update(origin=origin, llm_calls=0, model='SIM', response_sha256='a' * 64, contract_version=2,
                   usage={'tokens': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
                          'measurement': 'PROVIDER_TOKEN_COUNTERS'})
        return out

    def test_cycle_records_model_tokens_and_funnel(self):
        with tempfile.TemporaryDirectory() as t:
            mem = Path(t) / 'm.jsonl'
            res = run_cycle(gate=gate(), dataset=dataset(), memory_path=mem, now=NOW, run_kind='TEST',
                            llm=self.llm(reply(VALID[0], UNUSED, BAD_NAME)), offline_budget=4)
            self.assertEqual(res['status'], 'RUN')
            records = read_memory(mem)
            cyc = records[-1]
            self.assertEqual(cyc['cycle_version'], 3)
            self.assertEqual(cyc['llm_model'], 'SIM')
            self.assertEqual(cyc['llm_tokens'], {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150})
            self.assertEqual((cyc['llm_plans_received'], cyc['llm_plans_accepted'], cyc['llm_plans_rejected']), (3, 1, 2))
            self.assertEqual(cyc['llm_rejection_reasons'],
                             {'DSL:INVALID_INDICATOR_NAME': 1, 'INDICATOR_DEFINED_BUT_UNUSED': 1})
            self.assertEqual(cyc['experiments_from_llm'], 1)
            self.assertEqual(cyc['experiments_from_offline'], cyc['experiments_run'] - 1)
            rej = [r for r in records if r['record_type'] == 'PLAN_REJECTED']
            self.assertEqual(rej[0]['field'], 'indicators')
            self.assertEqual(rej[0]['detail'], {'referenced_in_conditions': [], 'unused_indicators': ['X_EARLY_MOVE']})

    def test_hypothesis_repeated_in_memory_is_not_rerun(self):
        with tempfile.TemporaryDirectory() as t:
            mem = Path(t) / 'm.jsonl'
            ds = dataset()
            run_cycle(gate=gate(), dataset=ds, memory_path=mem, now=NOW, run_kind='TEST',
                      llm=self.llm(reply(VALID[0])), offline_budget=0)
            later = NOW.replace(hour=13)
            run_cycle(gate=gate(), dataset=ds, memory_path=mem, now=later, run_kind='TEST',
                      llm=self.llm(reply(VALID[0])), offline_budget=0)
            cyc = read_memory(mem)[-1]
            self.assertEqual((cyc['llm_plans_accepted'], cyc['llm_plans_duplicate_skipped'], cyc['experiments_from_llm']),
                             (1, 1, 0))


class EndToEndOnRealData(unittest.TestCase):
    """Simulated model -> DSL -> executor on the repository's real dataset -> memory -> panel.
    Goes through the real llm-live CLI path with a fake opener: zero provider requests."""

    def test_valid_llm_plan_reaches_python_memory_and_panel(self):
        import shutil
        from scripts.lab_research_cycle import MODEL, SCHEDULE, main
        from scripts.lab_research_publish import verify_extension
        from test_research_gates import copy_sources
        from h1lab.research_gates import exploration_gate
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / 'repo'
            copy_sources(root)
            cfg = root / 'config/research-autonomy.json'
            conf = json.loads(cfg.read_text())
            conf['llm_live_enabled'] = True
            cfg.write_text(json.dumps(conf))
            opener = NativeOpener(reply(VALID[0], VALID[2], UNUSED))
            env = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
                   'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
                   'MASTER_BRAIN_LLM_API_KEY': 'not-a-real-key', 'RESEARCH_PRIOR_LLM_ATTEMPTS': '0'}
            mem, panel, audit = Path(t) / 'scratch.jsonl', Path(t) / 'panel.json', Path(t) / 'audit.json'
            code = main(['--root', str(root), '--mode', 'llm-live', '--allow-network', '--memory', str(mem),
                         '--panel', str(panel), '--budget', '0', '--llm-audit', str(audit)], env=env, opener=opener)
            self.assertEqual(code, 0)
            self.assertEqual(len(opener.calls), 1, 'exactly one (fake) request')
            self.assertTrue(opener.calls[0].full_url.endswith('/ai/run/' + MODEL))
            sent = json.loads(opener.calls[0].data)
            self.assertEqual(sent['response_format']['type'], 'json_schema')
            self.assertLessEqual(len(opener.calls[0].data), MODEL_PROFILES[MODEL]['max_request_bytes'])
            records = read_memory(mem)
            exps = [r for r in records if r['record_type'] == 'EXPERIMENT']
            self.assertEqual({r['origin'] for r in exps}, {'LLM_LIVE'})
            self.assertEqual(len(exps), 2)
            for r in exps:
                res = r['results']
                # Computed by the executor on real data (not by the model, not by the test).
                self.assertGreater((res.get('group') or {}).get('n', 0) + (res.get('control') or {}).get('n', 0), 0)
                self.assertEqual(r['scientific_status'], 'EXPLORATORY_NOT_VALIDATED')
                self.assertNotEqual(r['state'], 'VALIDATED')
            cyc = records[-1]
            self.assertEqual((cyc['llm_origin'], cyc['llm_model'], cyc['llm_calls']), ('LLM_LIVE', MODEL, 1))
            self.assertEqual((cyc['llm_plans_received'], cyc['llm_plans_accepted'], cyc['llm_plans_rejected']), (3, 2, 1))
            self.assertEqual((cyc['experiments_from_llm'], cyc['experiments_from_offline']), (2, 0))
            self.assertEqual(cyc['llm_tokens']['total_tokens'], 7900)
            self.assertEqual(cyc['llm_json_mode'], 'json_schema')
            self.assertLessEqual(cyc['llm_neurons_bound'], MAX_NEURONS_PER_CALL)
            self.assertEqual(cyc['llm_neurons_from_tokens'], round((7000 * 26668 + 900 * 204805) / 1e6, 1))
            sci = exploration_gate(root)['scientific_validation_gate']
            self.assertEqual(verify_extension(b'', mem.read_bytes(), sci)['llm_calls'], 1)
            p = json.loads(panel.read_text())
            auto = p['research_split']['autonomous']
            self.assertEqual((auto['models'], auto['plans_accepted'], auto['experiments_executed']), ([MODEL], 2, 2))
            self.assertTrue(p['provenance']['is_current_autonomous_research'])
            self.assertEqual(p['validated'], [])
            a = json.loads(audit.read_text())
            self.assertEqual(a['parsed']['accepted'], 2)
            self.assertEqual(json.loads(a['content']), json.loads(opener.body)['result']['response'])
            self.assertNotIn('not-a-real-key', audit.read_text())
            shutil.rmtree(root)

    def test_publisher_refuses_inconsistent_provenance(self):
        from scripts.lab_research_publish import verify_extension
        real = research_cycle.llm_provenance

        def lying(*a, **k):
            out = real(*a, **k)
            out['experiments_from_llm'] += 5   # claim LLM research that never ran
            return out
        with tempfile.TemporaryDirectory() as t, mock.patch.object(research_cycle, 'llm_provenance', lying):
            mem = Path(t) / 'm.jsonl'
            g = gate()
            out, _ = through_model(reply(UNUSED))
            out.update(origin='LLM_LIVE', llm_calls=1, model='M', usage={})
            run_cycle(gate=g, dataset=dataset(), memory_path=mem, now=NOW, run_kind='OPERATIONAL',
                      llm=out, offline_budget=2)
            with self.assertRaisesRegex(ValueError, 'CYCLE_PROVENANCE_INCONSISTENT'):
                verify_extension(b'', mem.read_bytes(), g['scientific_validation_gate'])


class HistoricalCycleUntouched(unittest.TestCase):
    MEMORY = ROOT / 'data/research/memory.jsonl'

    def test_first_live_cycle_is_shown_as_3_proposed_0_accepted_40_offline(self):
        before = hashlib.sha256(self.MEMORY.read_bytes()).hexdigest()
        memory = read_memory(self.MEMORY)   # strict hash-chain verification
        legacy = [f for f in cycle_funnels(memory) if f['cycle_id'] == 'Ceede16a74f0ae09']
        if not legacy:
            self.skipTest('historical cycle not in this checkout')
        f = legacy[0]
        self.assertEqual((f['plans_received'], f['plans_accepted'], f['plans_rejected'],
                          f['experiments_from_llm'], f['experiments_from_offline']), (3, 0, 3, 0, 40))
        self.assertEqual(f['rejection_reasons'], {'DSL:INVALID_INDICATOR_NAME': 1, 'INDICATOR_DEFINED_BUT_UNUSED': 2})
        self.assertEqual(f['provenance_source'], 'DERIVED_FROM_RECORDS_LEGACY_CYCLE')
        self.assertEqual(f['model_inferred_from_code']['model'], '@cf/meta/llama-3.1-8b-instruct-fast')
        from h1lab.research_gates import exploration_gate
        p = build_panel(memory, exploration_gate(ROOT), now=NOW)
        self.assertFalse(p['provenance']['is_current_autonomous_research'],
                         'a call with zero executed plans is not autonomous research')
        self.assertEqual(p['research_split']['autonomous']['experiments_executed'], 0)
        self.assertGreaterEqual(p['research_split']['deterministic']['experiments_executed'], 40)
        self.assertEqual(p['validated'], [])
        self.assertEqual(hashlib.sha256(self.MEMORY.read_bytes()).hexdigest(), before, 'memory never rewritten')
        old = [r for r in memory if r.get('cycle_id') == 'Ceede16a74f0ae09']
        self.assertTrue(all('llm_model' not in r and 'field' not in r for r in old))


if __name__ == '__main__':
    unittest.main()
