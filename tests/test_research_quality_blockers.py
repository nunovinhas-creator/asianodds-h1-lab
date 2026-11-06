"""B1 independent families: proofs, contamination, chronology and accounting.

The finite DSL oracle supplies witnesses; tests never assume an external solver.
Synthetic metadata is explicitly pregame and has common support in each period.
"""
import copy
import itertools
import math
import random
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from h1lab.research_dsl import evaluate
from h1lab.research_plan import validate_plan
from h1lab.research_quality import _design, shadow_report, LEAD_ROUNDING_SECONDS
from research_fixtures import LLM_PLAN
import test_research_quality as quality_fixture
from test_research_quality_adversarial import var, const, op, cmp


A = cmp('ge', 'lambda_net', .1)
X, Y = var('lambda_first'), var('lambda_last')
FLAGS = ('ctx_cup', 'ctx_youth_reserve', 'ctx_league_other')
CONTRADICTIONS = (
    op('eq', const(1), const(2)),
    op('lt', op('add', const(1), const(2)), const(3)),
    op('gt', X, X), op('ne', X, X),
    op('and', op('not', op('is_known', op('gt', X, const(1)))), op('gt', X, const(1))),
    op('and', op('gt', X, Y), op('ge', Y, X)),
)


class BlockerTests(unittest.TestCase):
    quality = quality_fixture.QualityTest.quality
    plan_with = quality_fixture.QualityTest.plan_with

    def setUp(self):
        quality_fixture.QualityTest.setUp(self)
        for i, row in enumerate(self.meta):
            row['variables'].update(lambda_net=.2 if i % 2 else 0, lead_first_min=600,
                                    total_line_last=2.5, lambda_first=2, lambda_last=3, p_home_last=.5,
                                    ctx_cup=False, ctx_youth_reserve=False, ctx_league_other=True)
        self.plan = self.plan_with(A, confounders=['line_bin'])

    def test_six_impossible_predicates_both_arms_orders_and_nested_negation(self):
        for contradiction, reverse, arm in itertools.product(CONTRADICTIONS, (False, True), ('signal', 'control')):
            dead = op('and', A, contradiction)
            alternatives = [A, dead][::(-1 if reverse else 1)]
            expr = op('or', *alternatives)
            forms = [expr]
            if contradiction != CONTRADICTIONS[4]:  # keep every canonical test within DSL depth 8
                forms.append(op('not', op('and', *[op('not', v) for v in alternatives])))
            for equivalent in forms:
                p = (self.plan_with(equivalent, confounders=['line_bin']) if arm == 'signal' else
                     self.plan_with(cmp('le', 'lambda_net', -.1), control_condition=equivalent,
                                    confounders=['line_bin']))
                q = self.quality(p)
                with self.subTest(contradiction=contradiction, reverse=reverse, arm=arm):
                    self.assertEqual(q['design_quality_status'], 'REJECTED')
                    self.assertIn('CONTRADICTORY_SIGNAL_PATH', q['reasons'])
                    self.assertFalse(q['promotion_eligible'])

    def test_one_hot_contract_all_assignments_both_arms_and_boolean_forms(self):
        for values in itertools.product((False, True), repeat=3):
            terms = [var(v) if value else op('not', var(v)) for v, value in zip(FLAGS, values)]
            forms = [op('and', A, *terms), op('and', *reversed(terms), A),
                     op('and', A, op('not', op('or', *[op('not', t) for t in terms])))]
            for dead in forms:
                for branches in ((A, dead), (dead, A)):
                    for material in (True, False):
                        reject, _ = _design(op('or', *branches), material=material, competition_type=True)
                        self.assertEqual('CONTRADICTORY_SIGNAL_PATH' in reject, sum(values) != 1)
        # A partial assignment with two positives is impossible, as is excluding all.
        for c in (op('and', var('ctx_cup'), var('ctx_league_other')),
                  op('not', op('or', *map(var, FLAGS)))):
            for arm in ('signal', 'control'):
                expr = op('or', A, op('and', A, c))
                p = (self.plan_with(expr, confounders=['competition_type']) if arm == 'signal' else
                     self.plan_with(cmp('le', 'lambda_net', -.1), control_condition=expr,
                                    confounders=['competition_type']))
                self.assertIn('CONTRADICTORY_SIGNAL_PATH', self.quality(p)['reasons'])
        # Without the selected contract do not invent exclusivity.
        self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(op('and', A, var('ctx_cup'), var('ctx_league_other')))[0])

    def test_three_value_knownness_and_nontransitive_approximate_equality(self):
        # A Boolean expression can be known through one dominating operand.
        c = op('and', op('not', op('is_known', X)), op('is_known', op('and', const(False), op('gt', X, const(1)))))
        self.assertIs(evaluate(c, {}), True)
        self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(op('and', A, c))[0])
        # Unknownness of a different total comparison still conflicts with a
        # known operand; undefined arithmetic does not.
        c = op('and', A, op('not', op('is_known', op('gt', X, const(1)))), op('ge', X, const(2)))
        self.assertIn('CONTRADICTORY_SIGNAL_PATH', _design(c)[0])
        c = op('and', A, op('not', op('is_known', op('div', X, const(0)))), op('ge', X, const(2)))
        self.assertIs(evaluate(c, {'lambda_net': .2, 'lambda_first': 2}), True)
        self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(c)[0])
        # Approximate equality is not transitive; never treat it as union/find.
        c = op('and', op('eq', X, Y), op('eq', Y, const(0)), op('ne', X, const(0)))
        self.assertIs(evaluate(c, {'lambda_first': 1.5e-9, 'lambda_last': .75e-9}), True)
        self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(op('and', A, c))[0])
        unknown = op('and', A, op('gt', op('mul', X, X), const(1)))
        self.assertIn('SATISFIABILITY_UNPROVEN', _design(unknown)[1])
        self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(unknown)[0])
        # Constant undefined arithmetic remains unknown in the interpreter.
        self.assertIsNone(evaluate(op('gt', op('div', const(1), const(0)), const(0)), {}))

    def test_finite_oracle_for_ordering_knownness_and_float_boundaries(self):
        predicates = [op(name, left, right) for name in ('gt', 'ge', 'lt', 'le', 'eq', 'ne')
                      for left, right in ((X, Y), (Y, X), (X, X))]
        samples = [0, math.nextafter(0, 1), .5e-9, 1e-9, math.nextafter(1e-9, math.inf),
                   1.5e-9, 1, math.nextafter(1, 2), 1+1e-9, 2, 1e100]
        for a, b in itertools.product(predicates, repeat=2):
            expr = op('and', A, a, b)
            if any(evaluate(expr, {'lambda_net': .2, 'lambda_first': x, 'lambda_last': y}) is True
                   for x, y in itertools.product(samples, repeat=2)):
                for material in (True, False):
                    self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(expr, material=material)[0], expr)
        # DSL witnesses, including EQ/NE tolerance endpoints, must never be a proof
        # of feasibility for a different rounded value.
        for bound in (0, 1, 9999):
            for delta in (-1e-9, 0, 1e-9):
                expression = op('and', A, cmp('eq', 'lambda_first', bound),
                                cmp('ne', 'lambda_first', bound+delta))
                r, d = _design(expression)
                if not r and not d:
                    self.assertTrue(any(evaluate(expression, {'lambda_net': .2, 'lambda_first': w}) is True
                                        for w in (bound, bound+delta/2, math.nextafter(bound-1e-9, bound),
                                                  math.nextafter(bound+1e-9, bound))))

    def test_catalogue_domains_constrain_logic_witnesses_and_row_values(self):
        impossible = [cmp('lt', 'lambda_first', -.1), cmp('gt', 'p_home_last', 1),
                      op('between', var('n_messages'), const(.1), const(.9)),
                      op('between', var('lambda_first_dir'), const(.2), const(.8)),
                      cmp('eq', 'kickoff_hour_utc', 1.5), cmp('ge', 'trigger_total_share', 2)]
        for c in impossible:
            expr = op('or', A, op('and', A, c))
            for material in (False, True):
                self.assertIn('CONTRADICTORY_SIGNAL_PATH', _design(expr, material=material)[0])
        for c in (cmp('ge', 'lambda_first', 0), cmp('eq', 'kickoff_hour_utc', 12),
                  cmp('eq', 'n_messages', 1), cmp('eq', 'lambda_first_dir', -1)):
            self.assertEqual(_design(op('and', A, c)), (set(), set()))
        # A signed movement variable remains allowed to have negative witnesses.
        self.assertEqual(_design(op('and', A, cmp('lt', 'lambda_unobserved_net', -1))), (set(), set()))

    def test_invalid_signal_inputs_never_become_control_in_any_design(self):
        plans = [self.plan, self.plan_with(A, control_condition=cmp('lt', 'lambda_net', .1), confounders=['line_bin']),
                 validate_plan(dict(LLM_PLAN, confounders=['line_bin']))]
        for plan, value in itertools.product(plans, (float('nan'), float('inf'), True, '0.2')):
            m = copy.deepcopy(self.meta)
            m[1]['variables']['lambda_net'] = value
            with patch('h1lab.research_quality.membership', wraps=__import__('h1lab.research_executor', fromlist=['membership']).membership) as calls:
                q = self.quality(plan, m=m)
                self.assertEqual(calls.call_count, 599)
            metrics = q['metrics']
            self.assertEqual((metrics['rows'], metrics['group'], metrics['control'], metrics['unknown']), (600, 299, 300, 1))
            self.assertEqual((metrics['group_eligible'], metrics['control_eligible'], metrics['rows_excluded']), (299, 300, 1))
            self.assertEqual(sum(metrics['oos'].values()), 599)
            self.assertEqual(metrics['common_support']['cells'][0]['pregame'], {'group': 299, 'control': 300})
            self.assertEqual(metrics['exclusions'][0]['match_key'], m[1]['match_key'])
            self.assertEqual(q['quality_status'], 'REJECTED')
        # A control-only dependency is validated even for a row passing the signal.
        p = self.plan_with(A, control_condition=op('and', cmp('lt', 'lambda_net', .1), cmp('gt', 'lambda_last', 1)), confounders=['line_bin'])
        self.meta[1]['variables']['lambda_last'] = '3'
        q = self.quality(p)
        self.assertEqual(q['metrics']['unknown'], 1)
        self.assertEqual(q['metrics']['control'], 300)

    def test_missing_domain_and_undefined_derived_inputs_excluded(self):
        for variable, bad in (('lambda_first', -1), ('p_home_last', 2), ('n_messages', .5),
                              ('lambda_first_dir', 2), ('lambda_abs_path', -.1), ('lambda_net', None)):
            p = self.plan_with(op('and', A, op('is_known', var(variable))), confounders=['line_bin'])
            self.meta[1]['variables'][variable] = bad
            q = self.quality(p)
            self.assertEqual(q['metrics']['unknown'], 1)
            self.assertEqual(sum(q['metrics']['oos'].values()), 599)
            self.setUp()
        # Finite raw values can overflow or divide by zero in a derived indicator.
        for calculation in (op('div', X, const(0)), op('mul', X, X)):
            p = validate_plan(dict(LLM_PLAN, confounders=['line_bin'],
                 indicators=[{'name': 'X_DERIVED', 'description': 'Derived availability diagnostic', 'expr': calculation}],
                 condition=op('and', A, op('is_known', var('X_DERIVED')))))
            if calculation['op'] == 'mul':
                self.meta[1]['variables']['lambda_first'] = 1e308
            q = self.quality(p)
            self.assertIn('SIGNAL_EXPRESSION_UNKNOWN', q['reasons'])
            self.assertLess(q['metrics']['group_eligible'] + q['metrics']['control_eligible'], 600)
            self.setUp()

    def test_lead_inferred_first_event_against_all_boundaries_and_rounding(self):
        p = self.plan_with(A, confounders=['lead_bin'])
        row = self.meta[1]
        ko = datetime.fromisoformat(row['kickoff_utc'])
        row['decision_at'] = (ko-timedelta(minutes=31)).isoformat()
        row['feature_frozen_at'] = row['decision_at']
        row['feature_observed_at'] = dict.fromkeys(row['variables'], row['decision_at'])
        for lead, valid in ((0, False), (30.94, False), (30.95, True), (31, True), (5000, True)):
            row['variables']['lead_first_min'] = lead
            q = self.quality(p)
            self.assertEqual(q['metrics']['group_eligible'], 300 if valid else 299)
            self.assertEqual('LEAD_FIRST_AFTER_DECISION_AT' in q['reasons'], not valid)
        self.assertEqual(LEAD_ROUNDING_SECONDS, 3)
        row['variables']['lead_first_min'] = 31
        row['feature_observed_at']['lead_first_min'] = (ko-timedelta(minutes=32)).isoformat()
        q = self.quality(p)
        self.assertIn('LEAD_FIRST_AFTER_FEATURE_OBSERVED_AT', q['reasons'])
        self.assertEqual(q['metrics']['exclusions'][0]['issues'][0]['variable'], 'lead_first_min')

    def test_eligible_support_ft_attrition_preserves_raw_and_pregame_arms(self):
        for row in self.meta[:4]:
            row['variables']['total_line_last'] = 4
        before = self.quality()
        self.assertTrue(before['metrics']['common_support']['eligible'])
        for row in self.meta[1:4:2]:
            row['ft_source_verified'] = False
        q = self.quality()
        metrics = q['metrics']
        self.assertEqual((metrics['group'], metrics['control']), (300, 300))
        self.assertEqual((metrics['group_pregame'], metrics['control_pregame']), (300, 300))
        self.assertEqual((metrics['group_eligible'], metrics['control_eligible']), (298, 300))
        self.assertEqual(sum(metrics['oos'].values()), 598)
        self.assertTrue(metrics['common_support']['pregame'])
        self.assertFalse(metrics['common_support']['eligible'])
        self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])
        high = next(c for c in metrics['common_support']['cells'] if c['cell'] == ['HIGH'])
        self.assertEqual(high['pregame'], {'group': 2, 'control': 2})
        self.assertEqual(high['eligible'], {'group': 0, 'control': 2})
        self.assertEqual(metrics['attrition']['group']['ft_source_missing'], 2)
        self.assertEqual(metrics['split_day'], before['metrics']['split_day'])
        # Removing entire early days of FT cannot redefine the chronological split.
        for row in self.meta:
            if datetime.fromisoformat(row['kickoff_utc']).day < 25:
                row['ft_source_verified'] = False
        self.assertEqual(self.quality()['metrics']['split_day'], before['metrics']['split_day'])

    def test_period_support_requires_comparison_inside_train_and_holdout(self):
        for row in self.meta:
            day = datetime.fromisoformat(row['kickoff_utc']).day
            group = row['variables']['lambda_net'] >= .1
            if (group and day <= 18) or (not group and day >= 26):
                row['variables']['total_line_last'] = 4
        q = self.quality()
        support = q['metrics']['common_support']
        self.assertTrue(support['pregame'])
        self.assertTrue(support['eligible'])
        self.assertFalse(support['by_period'])
        self.assertIn('COMMON_STRATUM_PERIOD_SUPPORT_MISSING', q['reasons'])
        high = next(c for c in support['cells'] if c['cell'] == ['HIGH'])
        self.assertEqual(high['oos']['train_control'], 0)
        self.assertEqual(high['oos']['test_group'], 0)
        self.assertNotEqual(q['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')

    def test_shadow_bad_values_and_shapes_account_for_every_row(self):
        mutations = [('variables', None), ('feature_observed_at', None), ('feature_observed_at', []),
                     ('feature_frozen_at', '0001-01-01T00:00:00+01:00'),
                     ('decision_at', '0001-01-01T00:00:00+01:00'),
                     ('baseline_available', 'yes'), ('ft_verified', 1),
                     ('source_event_ids', 'syn:1'), ('source_event_ids', [{}]),
                     ('source_event_ids', ['']), ('source_event_ids', ['a', 'a']),
                     ('match_key', []), ('source_event_ids', ['bad id'])]
        for name, value in mutations:
            m = copy.deepcopy(self.meta)
            m[1][name] = value
            report = shadow_report([self.plan], m, design=self.design)
            q = report['agenda'][0]
            self.assertNotEqual(q['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')
            self.assertEqual(q['metrics']['rows'], 600)
            self.assertEqual(q['metrics']['group_eligible'] + q['metrics']['control_eligible'], 599)
            self.assertEqual(q['metrics']['rows_excluded'], 1)
            self.assertEqual(len(q['metrics']['exclusions']), 1)
        m = copy.deepcopy(self.meta)
        m[1]['variables']['total_line_last'] = float('nan')
        m[3]['feature_observed_at'] = None
        m[5] = 17
        report = shadow_report([self.plan], m, design=self.design)
        self.assertIsNone(report['input_sha256'])
        self.assertEqual(report['report_status'], 'REJECTED')
        self.assertEqual(report['agenda'][0]['quality_status'], 'REJECTED')
        self.assertEqual(report['agenda'][0]['metrics']['rows_excluded'], 3)
        self.assertEqual(len(report['agenda'][0]['metrics']['exclusions']), 3)
        self.assertEqual(report['funnel']['executed'], 0)
        self.assertEqual(report['validated'], [])
        self.assertFalse(report['memory_written'])
        self.assertEqual(report, shadow_report([self.plan], m, design=self.design))
        for bad in ({1: 'numeric key'}, ('tuple',), {False: 'Boolean key'}):
            m[1]['unused_metadata'] = bad
            report = shadow_report([self.plan], m, design=self.design)
            self.assertIsNone(report['input_sha256'])
            self.assertEqual(report['report_status'], 'REJECTED')
        # Unsupported Python objects are not stringified, replaced or assigned hashes.
        m[1]['variables']['total_line_last'] = object()
        self.assertIsNone(shadow_report([self.plan], m, design=self.design)['input_sha256'])

    def test_authenticated_replay_preserves_identity_and_scientific_results(self):
        import hashlib
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from scripts.lab_research_quality import replay, git_object, INPUT_COMMIT
        from h1lab.research_quality import sha
        proof = json.loads(Path('evidence/b1/real-plans.json').read_text())
        present = subprocess.run(['git', 'cat-file', '-e', INPUT_COMMIT], capture_output=True)
        if present.returncode:
            self.skipTest('Historical Git objects unavailable in shallow checkout; replay fails closed')
        with tempfile.TemporaryDirectory() as root:
            for name in proof['records'][0]['data']['sources_sha256']:
                target = Path(root)/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(git_object(INPUT_COMMIT+':'+name))
            after = replay(root, proof)
            self.assertEqual(after, replay(root, proof))
        before = json.loads(Path('evidence/b1/replay.json').read_text())
        for key in ('provenance', 'input_sha256', 'before', 'costs', 'limits', 'funnel'):
            self.assertEqual(after[key], before[key], key)
        for old, new in zip(before['agenda'], after['agenda']):
            for key in ('fingerprint', 'quality_status', 'design_quality_status', 'promotion_eligible'):
                self.assertEqual(new[key], old[key], key)
            # All original metrics except unavailable-input diagnostics are exact.
            for key, value in old['metrics'].items():
                if key not in ('unknown', 'unassigned'):
                    self.assertEqual(new['metrics'][key], value, key)
            self.assertEqual(new['metrics']['unknown'] + new['metrics']['unassigned'],
                             old['metrics']['unknown'] + old['metrics']['unassigned'])
            self.assertEqual(set(new['reasons']) - set(old['reasons']),
                             {'BASELINE_MISSING', 'SIGNAL_DATA_MISSING', 'COMMON_STRATUM_PERIOD_SUPPORT_MISSING'})
            self.assertLessEqual(set(old['reasons']), set(new['reasons']))
        self.assertEqual(after['output_sha256'], sha({k:v for k,v in after.items() if k != 'output_sha256'}))
        self.assertEqual(hashlib.sha256(Path('evidence/b1/replay.json').read_bytes()).hexdigest(),
                         '1dd93bc1fee284f2efaed7a58e287f77f2fd9b524b39fea25fbf260e568061c5')

    def test_permutations_and_invalid_additions_cannot_create_valid_support(self):
        self.meta[1]['feature_observed_at'] = None
        self.meta[3]['variables']['lambda_net'] = True
        q = self.quality()
        shuffled = copy.deepcopy(self.meta)
        random.Random(79).shuffle(shuffled)
        self.assertEqual(q, self.quality(m=shuffled))
        duplicate = copy.deepcopy(self.meta[5])
        self.assertEqual(self.quality(m=self.meta+[duplicate]), self.quality(m=[duplicate]+self.meta))
        duplicate['feature_observed_at'] = None
        self.assertEqual(self.quality(m=self.meta+[duplicate]), self.quality(m=[duplicate]+self.meta))
        # Invalid new observations cannot fill an otherwise unsupported HIGH cell.
        valid = copy.deepcopy(self.meta[0])
        valid['variables']['total_line_last'] = 4
        valid['match_key'] = 'NEW-CONTROL'
        bad = copy.deepcopy(valid)
        bad.update(match_key='NEW-GROUP', ft_source_verified=False)
        bad['variables']['lambda_net'] = .2
        q = self.quality(m=self.meta+[valid, bad])
        self.assertFalse(q['metrics']['common_support']['eligible'])
        self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])
        # Mutation to invalid input never increases either arm's eligibility.
        for index, value in itertools.product((0, 1), (None, float('nan'), True, '0.2')):
            m = copy.deepcopy(self.meta)
            m[index]['variables']['lambda_net'] = value
            mutated = self.quality(m=m)
            for side in ('group', 'control'):
                self.assertLessEqual(mutated['metrics'][side+'_eligible'], self.quality()['metrics'][side+'_eligible'])


if __name__ == '__main__':
    unittest.main()
