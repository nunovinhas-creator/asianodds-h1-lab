"""Independent B1 producer-universe oracles, reconstructed from the user brief.

The auditor's original 52/43/10 scripts and exact 601 inputs were not supplied.
These are explicitly reconstructed tests, not a claim to literal reproduction.
The sequence oracle enumerates strings independently of the run-count solver.
"""
import copy
import itertools
import random
import unittest
from datetime import datetime, timedelta, timezone

from h1lab.research_contract import (CONTRACT_VERSION, SAT, UNSAT, UNKNOWN,
    produce_witness, summary_impossible, witness_matches)
from h1lab.research_dataset import trajectory_variables
from h1lab.research_dsl import evaluate
from h1lab.research_quality import prove_path, _design, _arm_separation, evaluate_quality
from h1lab.research_plan import validate_plan
from research_fixtures import LLM_PLAN, b1_produced_metadata


def v(name): return {'var': name}
def c(value): return {'const': value}
def cmp(name, variable, value): return {'op': name, 'args': [v(variable), c(value)]}
def join(name, *args): return {'op': name, 'args': list(args)}


A = cmp('ge', 'lambda_net', .1)
FAMILIES = {
    'F01': [cmp('eq', 'lambda_moves_up', 1), cmp('eq', 'lambda_max_run', 0)],
    'F02': [cmp('gt', 'lambda_sd', 6)],
    'F03': [cmp('eq', 'total_unobserved_changes', 0), cmp('eq', 'lambda_unobserved_net', 1)],
    'F04': [cmp('eq', 'n_messages', 2), cmp('eq', 'trigger_total_share', .3333)],
    'F05': [A, cmp('eq', 'lambda_velocity_h', 0), cmp('le', 'span_min', 60)],
    'F06': [cmp('eq', 'lead_first_min', 120), cmp('eq', 'lead_last_min', 60), cmp('eq', 'span_min', 1)],
    'F07': [cmp('eq', 'n_messages', 3), cmp('eq', 'span_min', 60), cmp('eq', 'max_gap_min', 10)],
}


def oracle_signature(sequence):
    nonzero = [d for d in sequence if d]
    groups = [list(group) for _, group in itertools.groupby(nonzero)]
    return (sequence.count(1), sequence.count(-1), max(0, len(groups)-1),
            max(map(len, groups), default=0), nonzero[0] if nonzero else 0,
            nonzero[-1] if nonzero else 0)


SEQ_FIELDS = ('lambda_moves_up', 'lambda_moves_down', 'lambda_reversals',
              'lambda_max_run', 'lambda_first_dir', 'lambda_last_dir')


def reconstructed_sequence_cases():
    rng = random.Random(601)
    cases = []
    for n in range(1, 5):
        truth = {oracle_signature(seq) for seq in itertools.product((-1, 0, 1), repeat=n)}
        for signature in sorted(truth):
            cases.append((n, signature, True))
        candidates = list(itertools.product(range(n+1), range(n+1), range(n+1),
                                           range(n+1), (-1, 0, 1), (-1, 0, 1)))
        rng.shuffle(candidates)
        cases.extend((n, signature, False) for signature in candidates[:160] if signature not in truth)
    # Include every positive first; the final count is fixed and reproducible.
    cases.sort(key=lambda entry: (not entry[2], entry[0], entry[1]))
    return cases[:601]


class JointProducerTests(unittest.TestCase):
    def test_f01_to_f07_direct_both_arms_orders_and_or_paths(self):
        for family, terms in FAMILIES.items():
            for permutation in itertools.permutations(terms):
                evidence = prove_path(list(permutation))
                self.assertEqual(evidence['status'], UNSAT, (family, evidence))
                self.assertIsNone(evidence['witness'])
                for material in (True, False):
                    self.assertIn('CONTRADICTORY_SIGNAL_PATH',
                                  _design(join('or', A, join('and', *permutation)), material=material)[0])

    def test_601_reconstructed_conjunctions_against_independent_sequence_oracle(self):
        cases = reconstructed_sequence_cases()
        self.assertEqual(len(cases), 601)
        positives = proved = 0
        for n, signature, possible in cases:
            terms = [cmp('eq', 'total_msgs', n), cmp('eq', 'n_messages', n)]
            terms += [cmp('eq', name, value) for name, value in zip(SEQ_FIELDS, signature)]
            result = prove_path(terms)
            if possible:
                positives += 1
                self.assertNotEqual(result['status'], UNSAT, (n, signature))
                if result['status'] == SAT:
                    proved += 1
                    self.assertTrue(witness_matches(result['witness'], {}, branch=terms))
            else:
                self.assertEqual(result['status'], UNSAT, (n, signature, result))
            reordered = prove_path(list(reversed(terms)))
            self.assertEqual(result, reordered)
        self.assertGreater(positives, 30)
        self.assertEqual(proved, positives, 'Short valid sequences must retain constructive SAT')

    def test_f08_separation_uses_joint_proof_and_overlap_certificate(self):
        signal = join('and', A, cmp('eq', 'total_msgs', 2), cmp('eq', 'lambda_moves_up', 2))
        control = cmp('eq', 'lambda_reversals', 1)
        self.assertIsNone(_arm_separation(signal, control, set()))
        overlap = cmp('ge', 'lambda_net', .15)
        self.assertEqual(_arm_separation(A, overlap, set()), 'LOGICAL_GROUP_CONTROL_OVERLAP')
        certificate = prove_path([A, overlap])
        self.assertEqual(certificate['status'], SAT)
        self.assertTrue(witness_matches(certificate['witness'], {}, branch=[A, overlap]))
        self.assertFalse(summary_impossible(produce_witness(certificate['witness'])))
        opaque = join('ge', join('add', v('lambda_net'), c(.01)), c(.1))
        self.assertEqual(_arm_separation(A, opaque, set()), 'CONTROL_DISJOINTNESS_UNPROVEN')

    def test_valid_neutral_and_complexity_limits(self):
        neutral = join('between', v('lambda_net'), c(-.02), c(.02))
        self.assertEqual(_design(neutral, material=False), (set(), set()))
        # DNF has 128 paths. No branch may be approved by a complexity fallback.
        branches = [join('or', A, cmp('le', 'lambda_net', -.1)) for _ in range(7)]
        self.assertIn('SATISFIABILITY_UNPROVEN', _design(join('and', *branches))[1])
        r = prove_path([cmp('eq', 'n_messages', 1000), A])
        self.assertEqual(r['status'], UNKNOWN)
        self.assertIsNone(r['witness'])

    def test_admission_quantization_time_and_full_certificate(self):
        plan = validate_plan(dict(LLM_PLAN, indicators=[], condition=A, confounders=['line_bin']))
        rows = [b1_produced_metadata(i, net=.2 if i % 2 else 0) for i in range(200)]
        design = {'threshold_origin': 'APRIORI', 'frozen_at': '2026-10-01T00:00:00+00:00'}
        baseline = evaluate_quality(plan, rows, design=design)
        self.assertEqual(baseline['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')
        no_ft = copy.deepcopy(rows)
        for row in no_ft:
            row.update(ft_verified=False, ft_source_verified=False, baseline_available={})
        withheld = evaluate_quality(plan, no_ft, design=design)
        for key in ('group', 'control', 'group_pregame', 'control_pregame', 'split_day'):
            self.assertEqual(withheld['metrics'][key], baseline['metrics'][key])
        self.assertEqual(withheld['metrics']['group_eligible'] + withheld['metrics']['control_eligible'], 0)
        mutations = [dict(lead_first_min=120, lead_last_min=60, span_min=1),
                     dict(n_messages=3, span_min=60, max_gap_min=10),
                     dict(lead_first_min=120.01), dict(lambda_moves_up=1, lambda_max_run=0),
                     dict(total_unobserved_changes=0, lambda_unobserved_net=1),
                     dict(lambda_sd=6.1), dict(trigger_total_share=.3333),
                     dict(lambda_net=.2, lambda_velocity_h=0, span_min=60), dict(ah_line_first=1e308)]
        for changes in mutations:
            altered = copy.deepcopy(rows)
            altered[1]['variables'].update(changes)
            result = evaluate_quality(plan, altered, design=design)
            self.assertEqual(result['metrics']['group_eligible'], 99, changes)
            self.assertEqual(result['metrics']['control_eligible'], 100, changes)
            self.assertEqual(result['metrics']['group_pregame'], 99, changes)
            self.assertEqual(sum(result['metrics']['oos'].values()), 199, changes)
            self.assertEqual(result['metrics']['rows'], 200)
            self.assertEqual(result['metrics']['rows_excluded'], 1)
        altered = copy.deepcopy(rows)
        del altered[1]['producer_witness']
        result = evaluate_quality(plan, altered, design=design)
        self.assertIn('OBSERVATION_PRODUCIBILITY_UNPROVEN', result['reasons'])
        self.assertEqual(result['metrics']['group_eligible'], 99)

    def test_generated_real_messages_never_rejected_by_summary_contract(self):
        # Raw quotes and timestamps are sampled independently of every corrected
        # sequence rule and witness-search candidate. No corrected solver in truth.
        rng = random.Random(259)
        ko = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
        for case in range(250):
            n = rng.randrange(1, 7)
            leads = sorted(rng.sample(range(1, 10000), n), reverse=True)
            events = []
            for i, lead in enumerate(leads):
                total = {side: {'line': rng.randrange(0, 61)/4, 'over_price': rng.uniform(1.01, 8),
                                'under_price': rng.uniform(1.01, 8)} for side in ('before', 'after')}
                events.append({'event_id': str(i), 'observed_at': (ko-timedelta(seconds=lead)).isoformat(),
                               'trigger_market': rng.choice(['total', '1x2', 'unknown']),
                               'snapshots': {'total': total}})
            witness = {'contract': CONTRACT_VERSION, 'kickoff_utc': ko.isoformat(),
                       'competition': 'League', 'events': events}
            direct = trajectory_variables(events, ko, 'League')
            generated = produce_witness(witness)
            self.assertEqual({k: x for k, x in generated.items() if k != 'n_episodes'},
                             {k: x for k, x in direct.items() if k != 'n_episodes'})
            self.assertFalse(summary_impossible(generated), (case, generated))
            self.assertTrue(witness_matches(witness, generated))
            # The same true producer tuple must never receive an impossibility
            # proof from the logical API, even if bounded reconstruction misses it.
            fields = ('n_messages', 'total_msgs', 'lambda_first', 'lambda_last',
                      'lambda_net', 'lambda_abs_path', 'lambda_sd', 'lambda_moves_up',
                      'lambda_moves_down', 'lambda_reversals', 'lambda_max_run')
            terms = [cmp('eq', name, generated[name]) for name in fields if generated[name] is not None]
            self.assertNotEqual(prove_path(terms)['status'], UNSAT, (case, generated))
