"""PR C - deterministic executor, falsification and anti-leakage (synthetic + real)."""
import copy
import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab.research_dataset import ah_home_result, build_dataset, build_row
from h1lab.research_executor import assign_states, execute, membership
from h1lab.research_plan import validate_plan
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_fixtures import LLM_PLAN, rows

ROOT = Path(__file__).resolve().parents[1]
PLAN = validate_plan(copy.deepcopy(LLM_PLAN))


def run(plan, data, prior=0):
    r = execute(plan, data)
    assign_states([r], prior_tests=prior)
    return r


class PlantedAndNull(unittest.TestCase):
    def test_planted_effect_is_found_but_never_validated(self):
        r = run(PLAN, rows(effect=0.3))
        self.assertEqual(r['state'], 'PROMISING_EXPLORATORY', r['checks'])
        self.assertGreater(r['effect'], 0.1)
        self.assertLess(r['p_value'], 0.01)
        self.assertEqual(r['scientific_status'], 'EXPLORATORY_NOT_VALIDATED')
        self.assertFalse(r['promotion_eligible'])
        self.assertTrue(r['requires_for_validation'])

    def test_null_effect_not_supported(self):
        r = run(PLAN, rows(effect=0.0, seed=11))
        self.assertIn(r['state'], ('NO_SUPPORT_IN_DATA', 'INCONCLUSIVE', 'FALSIFIED_EXPLORATORY'))
        self.assertNotEqual(r['state'], 'PROMISING_EXPLORATORY')

    def test_null_false_positive_rate_is_bounded(self):
        promising = 0
        for seed in range(20):
            r = run(PLAN, rows(n=300, effect=0.0, seed=100 + seed))
            promising += r['state'] == 'PROMISING_EXPLORATORY'
        self.assertLessEqual(promising, 2)

    def test_cumulative_multiplicity_penalises_repeated_search(self):
        r = run(PLAN, rows(effect=0.12, seed=3), prior=10 ** 6)
        self.assertEqual(r['p_bonferroni_cumulative'], 1.0)
        self.assertEqual(r['multiplicity_family_size'], 10 ** 6 + 1)

    def test_deterministic(self):
        d = rows(effect=0.2)
        self.assertEqual(run(PLAN, d), run(PLAN, copy.deepcopy(d)))


class DataHonesty(unittest.TestCase):
    def test_insufficient_data(self):
        r = run(PLAN, rows(n=40))
        self.assertEqual(r['state'], 'INSUFFICIENT_DATA')
        self.assertIsNone(r['p_value'])
        self.assertTrue(r['missing'])

    def test_pending_ft_never_counts_as_loss(self):
        d = rows(ft_share=0.5)
        r = run(PLAN, d)
        pending = r['counts']['group_pending_ft'] + r['counts']['control_pending_ft']
        self.assertEqual(pending, sum(x['outcome'] is None for x in d))
        self.assertEqual(r['group']['n'] + r['control']['n'], sum(x['outcome'] is not None for x in d))

    def test_unknown_inputs_are_not_controls(self):
        raw = copy.deepcopy(LLM_PLAN)
        raw['condition'] = {'op': 'and', 'args': [{'var': 'X_STRONG_LAMBDA_RISE'},
                                                  {'op': 'le', 'args': [{'var': 'ah_line_net'}, {'const': 0}]}]}
        plan = validate_plan(raw)
        d = rows()
        for x in d[:100]:
            x['variables']['ah_line_net'] = None
        r = run(plan, d)
        # unknown AH: flagged rows are unknown (excluded); unflagged are False by AND short-circuit
        flagged_unknown = sum(1 for x in d[:100] if x['variables']['lambda_net'] >= 0.2)
        self.assertGreaterEqual(flagged_unknown, 1)
        self.assertEqual(r['counts']['unknown'], flagged_unknown)
        self.assertEqual(r['counts']['group'] + r['counts']['control'] + r['counts']['unknown'], len(d))

    def test_btts_has_no_market_baseline(self):
        raw = copy.deepcopy(LLM_PLAN)
        raw.update(market='BTTS', outcome='BTTS_YES')
        r = run(validate_plan(raw), rows())
        self.assertEqual(r['baseline'], 'UNAVAILABLE')
        self.assertTrue(any('Sem preço de mercado' in x for x in r['limitations']))

    def test_ah_settlement(self):
        self.assertEqual(ah_home_result(1, 0, -0.5), 1.0)
        self.assertEqual(ah_home_result(1, 0, -1.0), 0.5)
        self.assertEqual(ah_home_result(1, 0, -0.75), 0.75)
        self.assertEqual(ah_home_result(1, 0, -1.25), 0.25)
        self.assertEqual(ah_home_result(0, 0, 0.25), 0.75)
        self.assertIsNone(ah_home_result(1, 0, -0.3))


class AntiLeakage(unittest.TestCase):
    def test_membership_independent_of_outcomes(self):
        d = rows()
        before = [membership(PLAN, x) for x in d]
        rng = random.Random(1)
        outs = [x['outcome'] for x in d]
        rng.shuffle(outs)
        for x, o in zip(d, outs):
            x['outcome'] = o
        self.assertEqual(before, [membership(PLAN, x) for x in d])

    def test_decision_after_kickoff_raises(self):
        d = rows(n=50)
        d[3]['decision_at'] = d[3]['kickoff_utc']
        with self.assertRaises(ValueError):
            execute(PLAN, d)

    def test_post_kickoff_messages_do_not_change_variables(self):
        ko = datetime(2026, 11, 1, 15, tzinfo=timezone.utc)

        def ev(i, minutes, line_b, line_a, ob, oa):
            return {'event_id': 'e:%d' % i, 'message_id': i, 'trigger_market': 'total',
                    'observed_at': (ko + timedelta(minutes=minutes)).isoformat(),
                    'snapshots': {'total': {'origin': 'V4_EXPLICIT',
                                            'before': {'line': line_b, 'over_price': ob, 'under_price': 1.9},
                                            'after': {'line': line_a, 'over_price': oa, 'under_price': 1.9}}}}
        pre = [ev(1, -300, 2.5, 2.75, 1.9, 1.95), ev(2, -60, 2.75, 2.75, 1.95, 2.15)]  # Over drifts out: fewer implied goals
        post = pre + [ev(3, 10, 2.75, 3.5, 1.8, 1.7), ev(4, 50, 3.5, 4.0, 1.7, 1.6)]
        tl = lambda events: {'match_key': 'K', 'identity': {'team_names_consistent': True,
                                                            'per_message_conflicts': [],
                                                            'kickoff_utc': [ko.isoformat()]},
                             'events': [dict(e) for e in events]}
        attach = lambda r: r.update(ft_status='PENDING')
        a, _ = build_row(tl(pre), 'Liga', attach)
        b, _ = build_row(tl(post), 'Liga', attach)
        self.assertEqual(a['variables'], b['variables'])
        self.assertEqual(a['baselines'], b['baselines'])
        self.assertEqual(a['decision_at'], b['decision_at'])
        self.assertTrue(a['variables']['line_up_then_lambda_down'])
        self.assertEqual(a['variables']['total_line_ups'], 1)


class RealData(unittest.TestCase):
    """Offline replay of the tracked repository data (no providers, no writes)."""

    @classmethod
    def setUpClass(cls):
        cls.ds = build_dataset(ROOT, now=datetime.now(timezone.utc))

    def test_real_rows_respect_chronology_and_separation(self):
        self.assertGreater(len(self.ds['rows']), 100)
        from h1lab.v6_shadow import utc
        for r in self.ds['rows']:
            self.assertLess(utc(r['decision_at']), utc(r['kickoff_utc']))
            self.assertFalse({'score', 'home', 'away', 'OVER_2_5'} & set(r['variables']))
            if r['outcome'] is not None:
                self.assertEqual(r['ft_status'], 'VERIFIED_FT')

    def test_real_experiment_executes(self):
        r = run(PLAN, self.ds['rows'])
        self.assertIn(r['state'], ('INSUFFICIENT_DATA', 'NO_SUPPORT_IN_DATA', 'INCONCLUSIVE',
                                   'FALSIFIED_EXPLORATORY', 'PROMISING_EXPLORATORY'))
        self.assertEqual(r['scientific_status'], 'EXPLORATORY_NOT_VALIDATED')


if __name__ == '__main__':
    unittest.main()
