"""LLM -> Python contract after the first live call (run 42021728675: 3 plans, 0 accepted).

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
from h1lab.research_llm import (MAX_REQUEST_BYTES, SYSTEM, build_packet, contract_spec,  # noqa: E402
                                invoke_once, parse_response, response_example, verified_example)
from h1lab.research_memory import read_memory  # noqa: E402
from h1lab.research_plan import REQUIRED, STRATA, base_types, validate_plan  # noqa: E402

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


def through_model(content):
    """Simulated model through the REAL request path (invoke_once) and parser."""
    packet = small_packet()
    opener = FakeOpener(content)
    out = invoke_once(packet, endpoint='https://simulated.invalid/v1/chat/completions', model='SIM', opener=opener)
    assert len(opener.calls) == 1
    return parse_response(out['content'], example_fingerprints=packet['response_example_fingerprints']), opener


class ContractSentToModel(unittest.TestCase):
    def test_example_in_packet_is_accepted_by_the_real_validator(self):
        ex, fp = verified_example()
        plan = validate_plan(copy.deepcopy(ex))
        self.assertEqual(plan['fingerprint'], fp)
        # Every indicator of the example is referenced (the rule the live model broke).
        used = json.dumps([plan['condition'], plan['control_condition']])
        for i in plan['indicators']:
            self.assertIn('"%s"' % i['name'], used)
        packet = small_packet()
        for raw in packet['response_example']['experiments']:
            validate_plan(copy.deepcopy(raw))
        self.assertEqual(packet['response_example_fingerprints'], [fp])

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

    def test_system_prompt_states_the_rules_that_caused_the_rejections(self):
        self.assertIn('MAIUSCULAS', SYSTEM)
        self.assertIn('TODO o indicador definido tem de aparecer', SYSTEM)
        self.assertIn('variables[].name', SYSTEM)
        self.assertIn('nao o copies', SYSTEM)

    def test_contract_is_sent_and_request_stays_bounded(self):
        opener = FakeOpener(reply(*VALID))
        invoke_once(small_packet(), endpoint='https://simulated.invalid/v1', model='SIM', opener=opener)
        body = json.loads(opener.calls[0].data)
        user = json.loads(body['messages'][1]['content'])
        self.assertIn('contract', user)
        self.assertNotIn('response_example_fingerprints', user, 'internal guard not sent to the model')
        self.assertLessEqual(len(opener.calls[0].data), MAX_REQUEST_BYTES)


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

    def test_verbatim_copy_of_the_example_is_not_the_models_hypothesis(self):
        out, _ = through_model(reply(response_example()))
        self.assertEqual(out['accepted'], 0)
        self.assertEqual(out['rejected'][0]['reason'], 'COPIED_RESPONSE_EXAMPLE')

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
            opener = FakeOpener(reply(VALID[0], VALID[2], UNUSED))
            env = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
                   'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
                   'MASTER_BRAIN_LLM_API_KEY': 'not-a-real-key', 'RESEARCH_PRIOR_LLM_ATTEMPTS': '0'}
            mem, panel, audit = Path(t) / 'scratch.jsonl', Path(t) / 'panel.json', Path(t) / 'audit.json'
            code = main(['--root', str(root), '--mode', 'llm-live', '--allow-network', '--memory', str(mem),
                         '--panel', str(panel), '--budget', '0', '--llm-audit', str(audit)], env=env, opener=opener)
            self.assertEqual(code, 0)
            self.assertEqual(len(opener.calls), 1, 'exactly one (fake) request')
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
            self.assertEqual(cyc['llm_tokens']['total_tokens'], 150)
            sci = exploration_gate(root)['scientific_validation_gate']
            self.assertEqual(verify_extension(b'', mem.read_bytes(), sci)['llm_calls'], 1)
            p = json.loads(panel.read_text())
            auto = p['research_split']['autonomous']
            self.assertEqual((auto['models'], auto['plans_accepted'], auto['experiments_executed']), ([MODEL], 2, 2))
            self.assertTrue(p['provenance']['is_current_autonomous_research'])
            self.assertEqual(p['validated'], [])
            a = json.loads(audit.read_text())
            self.assertEqual(a['parsed']['accepted'], 2)
            self.assertEqual(a['content'], json.loads(opener.body)['choices'][0]['message']['content'])
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
