"""Independent finite producer oracle and admission properties for B1."""
from copy import deepcopy
from itertools import product
import unittest

from h1lab.research_dataset import trajectory_variables
from h1lab.research_dsl import evaluate
from h1lab.research_quality import _arm_separation, _design, evaluate_quality, raw_plan, shadow_report
from test_research_quality_adversarial import cmp, const, op, var
import test_research_quality_blockers as fixtures


class StructuralTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.BlockerTests()
        fixture.setUp()
        self.fixture = fixture

    def card(self, expression, *, control=None, rows=None):
        f = self.fixture
        plan = f.plan_with(expression, control_condition=control, confounders=['line_bin'])
        return f.quality(plan, m=rows)

    def test_intersections_match_independent_grid_oracle(self):
        # With finite bounded arms, every admissible lambda is enumerated
        # independently in four-decimal units, including strict boundaries.
        windows = [(.1000, .1003), (.1002, .1005), (.1003, .1006), (.1007, .1009)]
        for a, b in product(windows, repeat=2):
            left = op('and', cmp('ge', 'lambda_net', a[0]), cmp('lt', 'lambda_net', a[1]))
            right = op('and', cmp('gt', 'lambda_net', b[0]), cmp('le', 'lambda_net', b[1]))
            overlap = any(evaluate(left, {'lambda_net': k/10000}) and
                          evaluate(right, {'lambda_net': k/10000}) for k in range(1000, 1010))
            expected = 'LOGICAL_GROUP_CONTROL_OVERLAP' if overlap else None
            self.assertEqual(_arm_separation(left, right, {'lambda_net'}), expected)
            self.assertEqual(_arm_separation(right, left, {'lambda_net'}), expected)

    def test_latent_overlap_and_opaque_disjointness_are_different(self):
        a = fixtures.A
        control = op('or', cmp('le', 'lambda_net', .05),
                     op('between', var('lambda_net'), const(.26), const(.28)))
        q = self.card(a, control=control)
        self.assertEqual(q['design_quality_status'], 'REJECTED')
        self.assertIn('LOGICAL_GROUP_CONTROL_OVERLAP', q['reasons'])
        self.assertEqual(q['metrics']['overlap'], 0)
        opaque = op('ge', op('add', var('lambda_net'), const(.01)), const(.1))
        q = self.card(a, control=opaque)
        self.assertIn('CONTROL_DISJOINTNESS_UNPROVEN', q['reasons'])
        self.assertNotIn('LOGICAL_GROUP_CONTROL_OVERLAP', q['reasons'])

    def test_actual_trajectory_and_joint_counterfactuals(self):
        from datetime import datetime, timezone
        kickoff = datetime(2026, 1, 1, 15, tzinfo=timezone.utc)
        quote_a = {'line': 2.5, 'over_price': 2.4, 'under_price': 1.6}
        quote_b = {'line': 2.5, 'over_price': 1.7, 'under_price': 2.2}
        event = {'observed_at': '2026-01-01T12:00:00Z',
                 'snapshots': {'total': {'before': quote_a, 'after': quote_b}}}
        v = trajectory_variables([event], kickoff, 'League')
        terms = [cmp('eq', k, v[k]) for k in ('lambda_first', 'lambda_last', 'lambda_net')]
        self.assertIs(evaluate(op('and', *terms), v), True)
        rejected, _ = _design(op('and', *terms), material=False)
        self.assertEqual(rejected, set())
        terms[-1] = cmp('eq', 'lambda_net', round(v['lambda_net']+.0001, 4))
        for branch in (terms, terms[::-1]):
            expression = op('or', fixtures.A, op('and', *branch))
            self.assertIn('CONTRADICTORY_SIGNAL_PATH', _design(expression, material=False)[0])
        for branch in (
            op('and', cmp('eq', 'total_msgs', 3), cmp('eq', 'lambda_moves_up', 2),
               cmp('eq', 'lambda_moves_down', 2)),
            op('and', cmp('eq', 'ah_msgs', 1), cmp('eq', 'total_ah_same_msg', 2)),
            op('and', cmp('eq', 'lambda_last_dir', -1), cmp('eq', 'lambda_moves_down', 0)),
            op('and', cmp('ge', 'lead_last_min', 90), cmp('le', 'lead_first_min', 60)),
            op('and', fixtures.A, cmp('ge', 'lambda_first', 11.99)),
            op('and', cmp('eq', 'n_messages', 2), cmp('eq', 'lambda_moves_up', 2),
               cmp('ge', 'lambda_moves_down', 1)),
        ):
            self.assertIn('CONTRADICTORY_SIGNAL_PATH',
                          _design(op('or', fixtures.A, branch), material=False)[0])

    def test_identity_prior_and_fail_closed_in_both_apis(self):
        f = self.fixture
        plan = f.plan
        a = shadow_report([plan], f.meta, design=f.design)
        b = shadow_report([plan], f.meta, design=f.design, prior_plans=[plan])
        self.assertNotEqual(a['input_sha256'], b['input_sha256'])
        self.assertIn('DUPLICATE_QUESTION', b['agenda'][0]['reasons'])
        prior = dict(plan, variables_used=tuple(reversed(plan['variables_used'])))
        self.assertEqual(b, shadow_report([plan], f.meta, design=f.design, prior_plans=(prior,)))
        for value in (float('nan'), {'nested': [float('inf')]}, object()):
            rows = deepcopy(f.meta[:16])
            rows[1]['extra'] = value
            report = shadow_report([plan], rows, design=f.design)
            self.assertIsNone(report['input_sha256'])
            direct = evaluate_quality(plan, rows, design=f.design)
            card = report['agenda'][0]
            self.assertEqual(card['metrics'], direct['metrics'])
            self.assertEqual(card['reasons'], direct['reasons'])
            metrics = direct['metrics']
            self.assertEqual((metrics['rows'], metrics['group_eligible'], metrics['control_eligible']), (16, 0, 0))
            self.assertFalse(metrics['common_support']['eligible'])
            self.assertEqual(metrics['exclusions'][0]['match_key'], rows[1]['match_key'])
        forged = dict(plan, fingerprint='forged')
        self.assertIn('NONCANONICAL_PLAN', shadow_report([forged], f.meta[:4], design=f.design)['agenda'][0]['reasons'])

    def test_temporal_inputs_cannot_increase_eligibility(self):
        f = self.fixture
        baseline = f.quality()
        for field in ('decision_at', 'feature_frozen_at', 'kickoff_utc', 'lambda_net'):
            rows = deepcopy(f.meta)
            row = rows[1]
            if field == 'lambda_net':
                row['feature_observed_at'][field] = row['decision_at'].replace('+00:00', '.0000001+00:00')
            else:
                row[field] = row[field].replace('+00:00', ',0000001+00:00')
            q = f.quality(m=rows)
            self.assertIn('TIMESTAMP_PRECISION_UNSUPPORTED', q['reasons'])
            self.assertEqual(q['metrics']['group_eligible'], baseline['metrics']['group_eligible'] - 1)
            self.assertEqual(q['metrics']['control_eligible'], baseline['metrics']['control_eligible'])
        for field, value, reason in (
            ('lead_last_min', 0, 'LEAD_LAST_AFTER_DECISION_AT'),
            ('kickoff_hour_utc', 23, 'KICKOFF_HOUR_MISMATCH'),
        ):
            rows = deepcopy(f.meta)
            for row in rows:
                row['variables'][field] = value
                row['feature_observed_at'][field] = row['decision_at']
            q = self.card(op('and', fixtures.A, op('is_known', var(field))), rows=rows)
            self.assertIn(reason, q['reasons'])
            self.assertEqual(q['metrics']['group_eligible'], 0)

    def test_tautological_bound_keeps_material_signal(self):
        a = fixtures.A
        self.assertEqual(_design(a), _design(op('and', cmp('ge', 'lambda_abs_path', 0), a)))
        self.assertEqual(_design(a), _design(op('and', a, op('le', const(0), var('lambda_abs_path')))))
