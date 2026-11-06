"""Independent counterexamples for B1 path and stratification admission only."""
import copy
import itertools
import unittest
from datetime import datetime, timedelta

from h1lab.research_dsl import evaluate
from h1lab.research_quality import _design
import test_research_quality as quality_fixture


def var(name):
    return {'var': name}


def const(value):
    return {'const': value}


def op(name, *args):
    return {'op': name, 'args': list(args)}


def cmp(name, variable, value):
    return op(name, var(variable), const(value))


class IndependentPathTests(unittest.TestCase):
    setUp = quality_fixture.QualityTest.setUp
    quality = quality_fixture.QualityTest.quality
    plan_with = quality_fixture.QualityTest.plan_with

    def test_audit_counterexamples_in_both_arms_and_orders(self):
        goal = cmp('ge', 'lambda_net', .1)
        line = cmp('ge', 'total_line_net', .25)
        conflicts = [
            (const(False),),
            (op('gt', op('add', var('lambda_first'), const(1)), const(2)),
             op('not', op('gt', op('add', var('lambda_first'), const(1)), const(2)))),
            (var('ctx_cup'), op('not', var('ctx_cup'))),
            (cmp('eq', 'lambda_first', 1), cmp('eq', 'lambda_first', 2)),
            (cmp('eq', 'lambda_first', 1), cmp('ne', 'lambda_first', 1)),
            (cmp('eq', 'lambda_first', 1), cmp('gt', 'lambda_first', 2)),
            (cmp('eq', 'lambda_first', 1), cmp('le', 'lambda_first', 0)),
            (op('between', var('lambda_first'), const(1), const(2)),
             cmp('eq', 'lambda_first', 3)),
            (cmp('ge', 'lambda_first', 1), cmp('le', 'lambda_first', 1),
             cmp('ne', 'lambda_first', 1)),
            (op('not', cmp('ne', 'lambda_first', 1)), cmp('eq', 'lambda_first', 2)),
            (op('lt', const(2), var('lambda_first')), cmp('le', 'lambda_first', 2)),
            (op('not', op('or', var('ctx_cup'), var('ctx_league_other'))),
             var('ctx_league_other')),
        ]
        for conflict in conflicts:
            for terms in itertools.permutations((line, *conflict)):
                dead = op('and', *terms)
                for alternatives in ((goal, dead), (dead, goal)):
                    expr = op('or', *alternatives)
                    for arm in ('signal', 'control'):
                        with self.subTest(conflict=conflict, terms=terms, arm=arm):
                            if arm == 'signal':
                                plan = self.plan_with(expr)
                            else:
                                plan = self.plan_with(cmp('le', 'lambda_net', -.1),
                                                      control_condition=expr)
                            q = self.quality(plan)
                            self.assertEqual(q['design_quality_status'], 'REJECTED')
                            self.assertIn('CONTRADICTORY_SIGNAL_PATH', q['reasons'])
                            self.assertFalse(q['promotion_eligible'])

    def test_satisfiable_constraints_have_witnesses(self):
        goal = cmp('ge', 'lambda_net', .1)
        cases = [
            (cmp('eq', 'lambda_first', 1), cmp('eq', 'lambda_first', 1+1.5e-9), 1+.75e-9),
            (cmp('eq', 'lambda_first', 1), cmp('ne', 'lambda_first', 1+1.5e-9), 1-.75e-9),
            (cmp('eq', 'lambda_first', 1), cmp('gt', 'lambda_first', 1), 1+.5e-9),
            (cmp('ge', 'lambda_first', 1), cmp('le', 'lambda_first', 1), 1),
            (op('between', var('lambda_first'), const(1), const(2)),
             cmp('ne', 'lambda_first', 1), 1.5),
            (var('ctx_cup'), op('not', op('not', var('ctx_cup'))), 1),
        ]
        for a, b, witness in cases:
            for terms in itertools.permutations((goal, a, b)):
                expr = op('and', *terms)
                env = {'lambda_net': .2, 'lambda_first': witness, 'ctx_cup': True}
                self.assertIs(evaluate(expr, env), True)
                self.assertEqual(_design(expr), (set(), set()), expr)
        self.assertEqual(_design(op('or', goal, cmp('ge', 'total_line_net', .25))),
                         (set(), set()))
        self.assertEqual(_design(op('and', goal, cmp('gt', 'lambda_net', 0))),
                         (set(), set()))

    def test_interpreter_witnesses_never_rejected_as_contradictory(self):
        # Independent finite witness oracle, including near-equality floats.
        predicates = [cmp(operator, 'lambda_first', value)
                      for operator in ('gt', 'ge', 'lt', 'le', 'eq', 'ne')
                      for value in (-2, -1, 0, 1, 2)]
        samples = [value+delta for value in (-3, -2, -1, 0, 1, 2, 3)
                   for delta in (-1.5e-9, -.5e-9, 0, .5e-9, 1.5e-9)]
        for a, b in itertools.product(predicates, repeat=2):
            expr = op('and', cmp('ge', 'lambda_net', .1), a, b)
            if any(evaluate(expr, {'lambda_net': .2, 'lambda_first': x}) is True
                   for x in samples):
                self.assertNotIn('CONTRADICTORY_SIGNAL_PATH', _design(expr)[0], expr)

    def test_unproved_context_algebra_requires_manual_review(self):
        expr = op('and', cmp('ge', 'lambda_net', .1),
                  op('gt', op('mul', var('lambda_first'), var('lambda_first')), const(1)))
        for arm in ('signal', 'control'):
            p = (self.plan_with(expr) if arm == 'signal' else
                 self.plan_with(cmp('le', 'lambda_net', -.1), control_condition=expr))
            q = self.quality(p)
            self.assertIn('SATISFIABILITY_UNPROVEN', q['reasons'])
            self.assertNotEqual(q['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')


class IndependentStrataTests(unittest.TestCase):
    setUp = quality_fixture.QualityTest.setUp
    quality = quality_fixture.QualityTest.quality
    plan_with = quality_fixture.QualityTest.plan_with

    def prepare(self, stratum):
        for i, row in enumerate(self.meta):
            row['variables'].update(lambda_net=.2 if i % 2 else -.2,
                                    total_line_last=2.5, lead_first_min=60,
                                    ctx_cup=False, ctx_youth_reserve=False, ctx_league_other=True)
        return self.plan_with(cmp('ge', 'lambda_net', .1), confounders=[stratum])

    def test_all_selected_strata_variables_and_arms(self):
        dependencies = {'line_bin': ['total_line_last'], 'lead_bin': ['lead_first_min'],
                        'competition_type': ['ctx_cup', 'ctx_youth_reserve', 'ctx_league_other']}
        for stratum, variables in dependencies.items():
            p = self.prepare(stratum)
            self.assertEqual(self.quality(p)['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')
            for variable, side, boundary in itertools.product(variables, (0, 1), ('freeze', 'decision', 'kickoff')):
                m = copy.deepcopy(self.meta)
                for row in m[side::2]:
                    if boundary == 'freeze':
                        # Observation remains before decision, but misses the freeze.
                        row['feature_frozen_at'] = (datetime.fromisoformat(row['decision_at'])-
                                                    timedelta(seconds=2)).isoformat()
                        for v in row['feature_observed_at']:
                            row['feature_observed_at'][v] = row['feature_frozen_at']
                        t = datetime.fromisoformat(row['feature_frozen_at'])+timedelta(seconds=1)
                    else:
                        key = 'decision_at' if boundary == 'decision' else 'kickoff_utc'
                        t = datetime.fromisoformat(row[key])+timedelta(seconds=1)
                    row['feature_observed_at'][variable] = t.isoformat()
                with self.subTest(stratum=stratum, variable=variable, side=side, boundary=boundary):
                    q = self.quality(p, m=m)
                    self.assertEqual(q['design_quality_status'], 'REJECTED')
                    self.assertIn('OBSERVATION_AFTER_FREEZE', q['reasons'])
                    self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])
                    self.assertEqual(q['metrics']['group'], 300)
                    self.assertEqual(q['metrics']['control'], 300)
                    self.assertEqual(q['metrics']['control_eligible' if side == 0 else 'group_eligible'], 0)
                    self.assertIn('TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE', q['reasons'])

    def test_one_control_one_second_late_cannot_complete_common_support(self):
        p = self.prepare('line_bin')
        for row in self.meta[:4]:
            row['variables']['total_line_last'] = 4
        self.assertEqual(self.quality(p)['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')
        row = self.meta[0]  # control; only two controls in this selected cell
        row['feature_observed_at']['total_line_last'] = (
            datetime.fromisoformat(row['decision_at'])+timedelta(seconds=1)).isoformat()
        q = self.quality(p)
        self.assertEqual(q['design_quality_status'], 'REJECTED')
        self.assertIn('OBSERVATION_AFTER_FREEZE', q['reasons'])
        self.assertIn('POST_KICKOFF_INFORMATION', q['reasons'])
        self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])
        self.assertEqual(q['metrics']['control_eligible'], 299)

    def test_unknown_time_differs_from_proven_late_time(self):
        for stratum, variable in [('line_bin', 'total_line_last'), ('lead_bin', 'lead_first_min'),
                                  ('competition_type', 'ctx_cup')]:
            p = self.prepare(stratum)
            for side in (0, 1):
                for missing in (None, 'invalid', '2026-10-01T00:00:00'):
                    m = copy.deepcopy(self.meta)
                    for row in m[side::2]:
                        row['feature_observed_at'][variable] = missing
                    q = self.quality(p, m=m)
                    self.assertEqual(q['design_quality_status'], 'INSUFFICIENT_DATA')
                    self.assertIn('FEATURE_WINDOW_UNPROVEN', q['reasons'])
                    self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])
                    self.assertNotIn('OBSERVATION_AFTER_FREEZE', q['reasons'])
                    self.assertNotIn('POST_KICKOFF_INFORMATION', q['reasons'])

    def test_late_fact_rejected_even_with_another_boundary_unknown(self):
        p = self.prepare('line_bin')
        for missing in ('decision_at', 'kickoff_utc'):
            m = copy.deepcopy(self.meta)
            m[0]['feature_observed_at']['total_line_last'] = m[0]['kickoff_utc']
            m[0][missing] = None
            q = self.quality(p, m=m)
            self.assertEqual(q['design_quality_status'], 'REJECTED')
            self.assertIn('POST_KICKOFF_INFORMATION', q['reasons'])

    def test_unselected_stratum_does_not_influence_comparison(self):
        p = self.prepare('lead_bin')
        for row in self.meta:
            row['feature_observed_at'].pop('total_line_last')
        self.assertEqual(self.quality(p)['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')


if __name__ == '__main__':
    unittest.main()
