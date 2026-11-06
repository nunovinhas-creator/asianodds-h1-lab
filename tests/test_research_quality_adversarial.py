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

    def test_explicit_false_alternatives_survive_nested_expansion(self):
        goal = cmp('ge', 'lambda_net', .1)
        line = cmp('ge', 'total_line_net', .25)
        for false in (const(False), op('not', const(True)),
                      op('not', op('not', const(False)))):
            for args in ((goal, false), (false, goal)):
                for expr in (op('or', *args), op('and', goal, op('or', line, false)),
                             op('or', line, op('and', goal, op('or', line, false)))):
                    for arm in ('signal', 'control'):
                        with self.subTest(expr=expr, arm=arm):
                            p = (self.plan_with(expr) if arm == 'signal' else
                                 self.plan_with(cmp('le', 'lambda_net', -.1), control_condition=expr))
                            q = self.quality(p)
                            self.assertEqual(q['design_quality_status'], 'REJECTED')
                            self.assertIn('CONTRADICTORY_SIGNAL_PATH', q['reasons'])
        neutral = op('between', var('lambda_net'), const(-.02), const(.02))
        q = self.quality(self.plan_with(goal, control_condition=op('or', neutral, const(False))))
        self.assertIn('CONTRADICTORY_SIGNAL_PATH', q['reasons'])
        self.assertEqual(_design(neutral, material=False), (set(), set()))

    def test_true_identities_and_demorgan_preserve_valid_paths(self):
        goal = cmp('ge', 'lambda_net', .1)
        line = cmp('ge', 'total_line_net', .25)
        for expr in (op('and', goal, const(True)), op('and', const(True), goal),
                     op('and', goal, op('not', const(False))),
                     op('not', op('and', op('not', goal), op('not', line))),
                     op('not', op('or', op('not', goal), const(False))),
                     op('or', goal, op('and', line, const(True)))):
            self.assertEqual(_design(expr), (set(), set()), expr)

    def test_p2_proven_physical_domains_in_both_arms(self):
        for expr in (cmp('le', 'lambda_abs_path', -.2),
                     cmp('ge', 'p_home_net', 5), cmp('lt', 'p_draw_net', -1),
                     cmp('gt', 'p_away_net', 1),
                     op('gt', const(-.2), var('lambda_abs_path'))):
            for material in (False, True):
                self.assertIn('CONTRADICTORY_SIGNAL_PATH', _design(expr, material=material)[0])
            self.assertIn('CONTRADICTORY_SIGNAL_PATH',
                          _design(op('or', cmp('ge', 'lambda_net', .1), expr))[0])
        for expr in (cmp('ge', 'lambda_abs_path', .1), cmp('ge', 'p_home_net', .05),
                     cmp('eq', 'p_home_net', 1), cmp('le', 'p_home_net', -1)):
            self.assertEqual(_design(expr), (set(), set()), expr)

    def test_p2_legitimate_dimensionless_ratios_defer_without_false_rejection(self):
        # Equal dimensions cancel, but unit compatibility is not proof of
        # compound feasibility or a nonzero divisor. No scientific acceptance.
        from h1lab.research_quality import _dimensions
        expr = op('ge', op('div', var('lambda_net'), var('lambda_first')),
                  op('div', var('p_home_net'), var('p_home_last')))
        self.assertIs(evaluate(expr, {'lambda_net': .2, 'lambda_first': 2,
                                     'p_home_net': .01, 'p_home_last': .5}), True)
        rejected, deferred = _dimensions(expr)
        self.assertEqual(rejected, set())
        self.assertIn('COMPOUND_UNITS_REVIEW', deferred)
        rejected, deferred = _design(expr)
        self.assertEqual(rejected, set())
        self.assertIn('SATISFIABILITY_UNPROVEN', deferred)
        self.assertNotIn('MIXED_MOVEMENT_UNITS', _dimensions(
            op('ge', op('div', var('lambda_net'), const(2)), const(.1)))[0])
        # Ratios with incompatible dimensions remain rejected.
        self.assertIn('MIXED_MOVEMENT_UNITS', _dimensions(
            op('ge', op('div', var('lambda_net'), var('p_home_last')), const(.1)))[0])

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
        # Independent finite witness oracle on a signed catalogue variable,
        # including near-equality floats. Physical levels cannot be negative.
        predicates = [cmp(operator, 'lambda_unobserved_net', value)
                      for operator in ('gt', 'ge', 'lt', 'le', 'eq', 'ne')
                      for value in (-2, -1, 0, 1, 2)]
        samples = [value+delta for value in (-3, -2, -1, 0, 1, 2, 3)
                   for delta in (-1.5e-9, -.5e-9, 0, .5e-9, 1.5e-9)]
        for a, b in itertools.product(predicates, repeat=2):
            expr = op('and', cmp('ge', 'lambda_net', .1), a, b)
            if any(evaluate(expr, {'lambda_net': .2, 'lambda_unobserved_net': x}) is True
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
            row['decision_at'] = (datetime.fromisoformat(row['kickoff_utc'])-timedelta(minutes=30)).isoformat()
            row['feature_frozen_at'] = row['decision_at']
            row['feature_observed_at'] = dict.fromkeys(row['variables'], row['decision_at'])
            row['variables'].update(lambda_net=.2 if i % 2 else -.2,
                                    total_line_last=2.5, lead_first_min=60,
                                    ctx_cup=False, ctx_youth_reserve=False, ctx_league_other=True)
        return self.plan_with(cmp('ge', 'lambda_net', .1), confounders=[stratum])

    def assert_excluded(self, plan, metadata, reason, status, excluded=600):
        before = copy.deepcopy(metadata)
        q = self.quality(plan, m=metadata)
        self.assertEqual(q['design_quality_status'], status)
        self.assertIn(reason, q['reasons'])
        self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])
        self.assertIn('TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE', q['reasons'])
        self.assertFalse(q['promotion_eligible'])
        metrics = q['metrics']
        self.assertEqual((metrics['rows'], metrics['group'], metrics['control']), (600, 300, 300))
        self.assertEqual(metrics['strata_excluded'], excluded)
        self.assertEqual(metrics['group_eligible'] + metrics['control_eligible'], 600-excluded)
        self.assertEqual(sum(metrics['oos'].values()), 600-excluded)
        self.assertEqual(len(metrics['strata_exclusions']), excluded)
        self.assertEqual(len({x['match_key'] for x in metrics['strata_exclusions']}), excluded)
        self.assertTrue(all(any(i['reason'] == reason for i in x['issues'])
                            for x in metrics['strata_exclusions']))
        # Values, including NaN, must remain untouched (identity for NaN avoids
        # making float NaN equality an assertion about the production contract).
        self.assertEqual(repr(metadata), repr(before))
        return q

    def test_claude_invalid_strata_counterexamples(self):
        for stratum, changes, reason in (
            ('competition_type', dict(ctx_cup=False, ctx_youth_reserve=False, ctx_league_other=False),
             'CONFOUNDER_COMPETITION_CONTRADICTION'),
            ('competition_type', dict(ctx_cup=True, ctx_league_other=True),
             'CONFOUNDER_COMPETITION_CONTRADICTION'),
            ('lead_bin', dict(lead_first_min=-30), 'CONFOUNDER_VALUE_OUT_OF_DOMAIN'),
            ('line_bin', dict(total_line_last=float('nan')), 'CONFOUNDER_VALUE_NONFINITE')):
            with self.subTest(stratum=stratum, changes=changes):
                p = self.prepare(stratum)
                for row in self.meta:
                    row['variables'].update(changes)
                self.assert_excluded(p, self.meta, reason, 'REJECTED')

    def test_strata_numeric_types_nonfinite_and_missing(self):
        for stratum, variable in (('lead_bin', 'lead_first_min'), ('line_bin', 'total_line_last')):
            for value, reason, status in (
                (None, 'CONFOUNDER_DATA_MISSING', 'INSUFFICIENT_DATA'),
                ('2.5', 'CONFOUNDER_VALUE_TYPE_INVALID', 'REJECTED'),
                (True, 'CONFOUNDER_VALUE_TYPE_INVALID', 'REJECTED'),
                (False, 'CONFOUNDER_VALUE_TYPE_INVALID', 'REJECTED'),
                ([], 'CONFOUNDER_VALUE_TYPE_INVALID', 'REJECTED'),
                ({}, 'CONFOUNDER_VALUE_TYPE_INVALID', 'REJECTED'),
                (float('nan'), 'CONFOUNDER_VALUE_NONFINITE', 'REJECTED'),
                (float('inf'), 'CONFOUNDER_VALUE_NONFINITE', 'REJECTED'),
                (-float('inf'), 'CONFOUNDER_VALUE_NONFINITE', 'REJECTED'),
                (-.01, 'CONFOUNDER_VALUE_OUT_OF_DOMAIN', 'REJECTED')):
                with self.subTest(stratum=stratum, value=value):
                    p = self.prepare(stratum)
                    for row in self.meta:
                        row['variables'][variable] = value
                    self.assert_excluded(p, self.meta, reason, status)
            p = self.prepare(stratum)
            for row in self.meta:
                del row['variables'][variable]
            self.assert_excluded(p, self.meta, 'CONFOUNDER_DATA_MISSING', 'INSUFFICIENT_DATA')

    def test_competition_strict_one_hot_partial_unknown_and_contradictions(self):
        for variable in ('ctx_cup', 'ctx_youth_reserve', 'ctx_league_other'):
            for value in (0, 1, 'false', 'true', [], {}, float('nan'), float('inf')):
                p = self.prepare('competition_type')
                for row in self.meta:
                    row['variables'][variable] = value
                self.assert_excluded(p, self.meta, 'CONFOUNDER_VALUE_TYPE_INVALID', 'REJECTED')
            for remove in (False, True):
                p = self.prepare('competition_type')
                for row in self.meta:
                    if remove:
                        del row['variables'][variable]
                    else:
                        row['variables'][variable] = None
                self.assert_excluded(p, self.meta, 'CONFOUNDER_DATA_MISSING', 'INSUFFICIENT_DATA')
        for selected in itertools.product((False, True), repeat=3):
            p = self.prepare('competition_type')
            for row in self.meta:
                row['variables'].update(zip(('ctx_cup', 'ctx_youth_reserve', 'ctx_league_other'), selected))
            if sum(selected) == 1:
                self.assertEqual(self.quality(p)['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')
            else:
                self.assert_excluded(p, self.meta, 'CONFOUNDER_COMPETITION_CONTRADICTION', 'REJECTED')
        p = self.prepare('competition_type')
        for row in self.meta:
            row['variables'].update(ctx_cup=True, ctx_youth_reserve=True, ctx_league_other=None)
        q = self.assert_excluded(p, self.meta, 'CONFOUNDER_COMPETITION_CONTRADICTION', 'REJECTED')
        self.assertIn('CONFOUNDER_DATA_MISSING', q['reasons'])

    def test_invalid_rows_in_either_arm_cannot_supply_support_or_oos(self):
        for side in (0, 1):
            p = self.prepare('line_bin')
            for row in self.meta[side::2]:
                row['variables']['total_line_last'] = float('nan')
            q = self.assert_excluded(p, self.meta, 'CONFOUNDER_VALUE_NONFINITE', 'REJECTED', 300)
            arm = 'control' if side == 0 else 'group'
            self.assertEqual(q['metrics'][arm + '_eligible'], 0)
            self.assertEqual(q['metrics'][arm + '_strata_excluded'], 300)
            self.assertEqual(q['metrics']['oos']['train_' + arm], 0)
            self.assertEqual(q['metrics']['oos']['test_' + arm], 0)
        p = self.prepare('line_bin')
        self.meta[0]['variables']['total_line_last'] = float('nan')
        self.assert_excluded(p, self.meta, 'CONFOUNDER_VALUE_NONFINITE', 'REJECTED', 1)

    def test_malformed_stratum_used_in_signal_keeps_all_row_accounting(self):
        self.prepare('line_bin')
        expr = op('and', cmp('ge', 'lambda_net', .1), cmp('ge', 'total_line_last', 0))
        p = self.plan_with(expr, confounders=['line_bin'])
        for side in (0, 1):
            m = copy.deepcopy(self.meta)
            m[side]['variables']['total_line_last'] = []
            q = self.quality(p, m=m)
            self.assertIn('CONFOUNDER_VALUE_TYPE_INVALID', q['reasons'])
            self.assertNotIn('QUALITY_INPUT_INVALID', q['reasons'])
            self.assertEqual(q['metrics']['rows'], 600)
            self.assertEqual(q['metrics']['unknown'], 1)
            self.assertEqual(q['metrics']['group'] + q['metrics']['control'], 599)
            self.assertEqual(q['metrics']['group_eligible'] + q['metrics']['control_eligible'], 599)
            self.assertEqual(q['metrics']['strata_exclusions'][0]['match_key'], m[side]['match_key'])

    def test_joint_strata_unknown_does_not_hide_proven_invalid_value(self):
        self.prepare('lead_bin')
        p = self.plan_with(cmp('ge', 'lambda_net', .1),
                           confounders=['competition_type', 'lead_bin', 'line_bin'])
        for row in self.meta:
            row['variables'].update(ctx_cup=None, lead_first_min=-30, total_line_last=float('inf'))
        q = self.assert_excluded(p, self.meta, 'CONFOUNDER_VALUE_NONFINITE', 'REJECTED')
        self.assertIn('CONFOUNDER_VALUE_OUT_OF_DOMAIN', q['reasons'])
        self.assertIn('CONFOUNDER_DATA_MISSING', q['reasons'])

    def test_b1_bins_match_executor_only_for_valid_selected_values(self):
        from h1lab.research_executor import _bins
        from h1lab.research_quality import _stratum_cell
        self.prepare('lead_bin')
        for lead, line, ctx in itertools.product((0, 359.9, 360, 1440, 1440.1, 5000),
                                                (0, 2.25, 2.5, 3.25, 5), range(3)):
            row = copy.deepcopy(self.meta[0])
            row['variables'].update(lead_first_min=lead, total_line_last=line,
                                    ctx_cup=ctx == 0, ctx_youth_reserve=ctx == 1, ctx_league_other=ctx == 2)
            selected = ['lead_bin', 'line_bin', 'competition_type']
            cell, issues = _stratum_cell(row['variables'], selected)
            self.assertEqual(issues, [])
            self.assertEqual(cell, tuple(_bins(row)[s] for s in selected))
        # An unused malformed value must never be sent through shared _bins.
        p = self.prepare('lead_bin')
        for row in self.meta:
            row['variables']['total_line_last'] = 'unused'
        self.assertEqual(self.quality(p)['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')

    def test_p2_large_first_lead_with_late_final_observation_is_possible(self):
        from h1lab.research_dataset import trajectory_variables
        p = self.prepare('lead_bin')
        for row in self.meta:
            ko = datetime.fromisoformat(row['kickoff_utc'])
            events = [{'observed_at': (ko-timedelta(minutes=lead)).isoformat(), 'snapshots': {}}
                      for lead in (5000, 10)]
            computed = trajectory_variables(events, ko, 'League')
            self.assertEqual((computed['lead_first_min'], computed['lead_last_min'], computed['span_min']),
                             (5000, 10, 4990))
            row['variables']['lead_first_min'] = computed['lead_first_min']
            row['decision_at'] = events[-1]['observed_at']
            row['feature_frozen_at'] = row['decision_at']
            row['feature_observed_at'] = dict.fromkeys(row['variables'], row['decision_at'])
        self.assertEqual(self.quality(p)['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')

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
        initial = self.quality(p)
        self.assertTrue(initial['metrics']['common_support']['pregame'])
        self.assertTrue(initial['metrics']['common_support']['eligible'])
        self.assertIn('COMMON_STRATUM_PERIOD_SUPPORT_MISSING', initial['reasons'])
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
