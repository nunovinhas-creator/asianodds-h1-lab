"""B1 adversarial acceptance; no network or experiment execution."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from h1lab.research_quality import evaluate_quality, shadow_report, raw_plan
from h1lab.research_plan import validate_plan
from research_fixtures import LLM_PLAN, rows


class QualityTest(unittest.TestCase):
    def setUp(self):
        self.plan = validate_plan(LLM_PLAN)
        self.meta = []
        for r in rows(n=600, ft_share=1):
            self.meta.append({k: copy.deepcopy(r[k]) for k in
                              ('match_key', 'variables', 'decision_at', 'kickoff_utc', 'source_event_ids')})
            m = self.meta[-1]
            m.update(feature_observed_at={v: r['decision_at'] for v in r['variables']},
                     feature_frozen_at=r['decision_at'], ft_verified=True, ft_source_verified=True,
                     baseline_available={k: True for k in r['baselines']})
        self.design = {'threshold_origin': 'APRIORI', 'frozen_at': '2026-10-01T00:00:00+00:00'}

    def quality(self, p=None, m=None, **kw):
        return evaluate_quality(p or self.plan, self.meta if m is None else m,
                                design=kw.pop('design', self.design), **kw)

    def plan_with(self, expr, **kw):
        raw = dict(LLM_PLAN, indicators=[], condition=expr, **kw)
        return validate_plan(raw)

    def test_positive_and_boolean_context(self):
        for row in self.meta:
            row['variables']['total_line_last'] = 2.5
        self.assertEqual(self.quality()['design_quality_status'], 'SCIENTIFICALLY_TESTABLE')
        p = self.plan_with({'var': 'ctx_cup'})
        self.assertEqual(self.quality(p)['quality_status'], 'INSUFFICIENT_DATA')

    def test_zero_micro_and_correct_units(self):
        for var, floor in [('p_home_net', .05), ('lambda_net', .1), ('total_line_net', .25), ('ah_line_net', .25)]:
            for bound in (0, .00001, floor/2):
                p = self.plan_with({'op': 'gt', 'args': [{'var': var}, {'const': bound}]})
                self.assertIn('IMMATERIAL_MOVEMENT', self.quality(p)['reasons'])
            p = self.plan_with({'op': 'ge', 'args': [{'var': var}, {'const': floor}]})
            self.assertNotIn('IMMATERIAL_MOVEMENT', self.quality(p)['reasons'])

    def test_dimension_arithmetic_and_indicator_inline(self):
        p = self.plan_with({'op': 'gt', 'args': [
            {'op': 'add', 'args': [{'var': 'p_home_net'}, {'var': 'lambda_net'}]}, {'const': .1}]})
        self.assertIn('MIXED_MOVEMENT_UNITS', self.quality(p)['reasons'])
        raw = copy.deepcopy(LLM_PLAN)
        raw['indicators'][0]['expr']['args'][1]['const'] = 0
        self.assertIn('IMMATERIAL_MOVEMENT', self.quality(validate_plan(raw))['reasons'])

    def test_mixed_units_in_levels_and_compound_expressions(self):
        p = self.plan_with({'op': 'gt', 'args': [
            {'op': 'add', 'args': [{'var': 'p_home_last'}, {'var': 'total_line_last'}]},
            {'const': .1}]})
        self.assertIn('MIXED_MOVEMENT_UNITS', self.quality(p)['reasons'])
        p = self.plan_with({'op': 'gt', 'args': [
            {'op': 'mul', 'args': [{'var': 'p_home_last'}, {'var': 'p_home_last'}]},
            {'const': .1}]})
        self.assertIn('COMPOUND_UNITS_REVIEW', self.quality(p)['reasons'])

    def test_overlap_constant_unknown_and_small_sample(self):
        p = self.plan_with({'var': 'ctx_cup'}, control_condition={'var': 'ctx_league_other'})
        self.meta[0]['variables'].update(ctx_cup=True, ctx_league_other=True)
        self.assertIn('GROUP_CONTROL_OVERLAP', self.quality(p)['reasons'])
        self.assertIn('CONSTANT_CONDITION', self.quality(self.plan_with({'const': True}))['reasons'])
        self.assertIn('MIN_N_NOT_MET', self.quality(m=self.meta[:3])['reasons'])
        for m in self.meta:
            m['variables']['lambda_net'] = None
        q = self.quality()
        self.assertEqual(q['metrics']['unknown'], 600)
        self.assertEqual(q['quality_status'], 'INSUFFICIENT_DATA')

    def test_missing_availability_and_temporal_proofs(self):
        for key, value, reason in [
            ('ft_verified', False, 'VERIFIED_FT_PROVENANCE_MISSING'),
            ('ft_source_verified', False, 'VERIFIED_FT_PROVENANCE_MISSING'),
            ('baseline_available', {}, 'BASELINE_MISSING'),
            ('feature_observed_at', {}, 'FEATURE_WINDOW_UNPROVEN'),
            ('feature_frozen_at', None, 'FEATURE_FREEZE_UNPROVEN'),
            ('kickoff_utc', None, 'DECISION_WINDOW_UNPROVEN')]:
            m = copy.deepcopy(self.meta)
            for r in m:
                r[key] = value
            self.assertIn(reason, self.quality(m=m)['reasons'])
        self.assertIn('THRESHOLD_PROVENANCE_MISSING', self.quality(design={})['reasons'])

    def test_leakage_duplicates_and_oos(self):
        m = copy.deepcopy(self.meta)
        m[0]['decision_at'] = m[0]['kickoff_utc']
        self.assertIn('POST_KICKOFF_INFORMATION', self.quality(m=m)['reasons'])
        m = copy.deepcopy(self.meta)
        m[0]['feature_observed_at']['lambda_net'] = m[0]['kickoff_utc']
        self.assertIn('POST_KICKOFF_INFORMATION', self.quality(m=m)['reasons'])
        self.assertIn('DUPLICATE_MATCH_UNIT', self.quality(m=self.meta+[self.meta[0]])['reasons'])
        self.assertIn('DUPLICATE_QUESTION', self.quality(prior_plans=[self.plan])['reasons'])
        d = dict(self.design, threshold_origin='DISCOVERY', discovery_end='2026-11-01T00:00:00+00:00')
        self.assertIn('DISCOVERY_HOLDOUT_CONTAMINATION', self.quality(design=d)['reasons'])
        self.assertIn('CHRONOLOGICAL_OOS_INSUFFICIENT', self.quality(m=self.meta[:2])['reasons'])

    def test_unavailable_narrative_and_no_outcome_reads(self):
        p = self.plan_with({'var': 'ctx_cup'}, hypothesis='Operator live score guarantees a signal')
        self.assertIn('UNOBSERVED_CONCEPT', self.quality(p)['reasons'])
        class Poison:
            def __bool__(self):
                raise AssertionError('outcome read')
        m = copy.deepcopy(self.meta)
        m[0]['outcome'] = Poison()
        self.assertIn('OUTCOME_METADATA_FORBIDDEN', self.quality(m=m)['reasons'])

    def test_shadow_read_only_deterministic_and_fail_closed(self):
        before = copy.deepcopy(self.meta)
        with patch('h1lab.research_executor.execute', side_effect=AssertionError('execution')):
            a = shadow_report([LLM_PLAN], self.meta, design=self.design)
            b = shadow_report([LLM_PLAN], self.meta, design=self.design)
        self.assertEqual(a, b)
        self.assertEqual(before, self.meta)
        self.assertEqual(a['funnel']['executed'], 0)
        self.assertEqual(a['validated'], [])
        self.assertEqual(evaluate_quality({}, [])['quality_status'], 'REJECTED')
        self.assertEqual(shadow_report([{}], [])['funnel']['structurally_valid'], 0)

    def test_identical_control_units_direction_and_mutated_input(self):
        raw = dict(LLM_PLAN, control_condition=LLM_PLAN['condition'])
        self.assertEqual(shadow_report([raw], self.meta)['funnel']['structurally_valid'], 0)
        raw = dict(LLM_PLAN, unexpected='not accepted')
        self.assertEqual(shadow_report([raw], self.meta)['funnel']['structurally_valid'], 0)
        p = self.plan_with({'op': 'lt', 'args': [{'var': 'lambda_net'}, {'const': .2}]})
        self.assertIn('MATERIAL_DIRECTION_UNPROVEN', self.quality(p)['reasons'])
        raw = copy.deepcopy(self.plan)
        raw['condition'] = {'const': True}
        self.assertIn('QUALITY_INPUT_INVALID', self.quality(raw)['reasons'])
        p = self.plan_with({'var': 'ctx_cup'})
        other = self.plan_with({'op': 'not', 'args': [{'var': 'ctx_cup'}]})
        self.assertIn('NEAR_DUPLICATE_REVIEW', self.quality(p, prior_plans=[other])['reasons'])

    def test_committed_replay_hashes_and_membership_parity(self):
        import json
        from pathlib import Path
        from h1lab.research_quality import sha
        report = json.loads(Path('evidence/b1/replay.json').read_text())
        recorded_hash = report.pop('output_sha256')
        self.assertEqual(recorded_hash, sha(report))
        proof = json.loads(Path('evidence/b1/real-plans.json').read_text())
        self.assertEqual(report['provenance']['proof_sha256'], sha(proof))
        self.assertEqual(report['provenance']['original_dataset_sha256'],
                         report['provenance']['replayed_dataset_sha256'])
        self.assertEqual(report['funnel']['quality'], {'REJECTED': 3})
        self.assertEqual(report['funnel']['executed'], 0)
        for after, before in zip(report['agenda'], report['before']):
            for key in ('rows', 'group', 'control', 'unknown', 'overlap'):
                self.assertEqual(after['metrics'][key], before['counts'][key])
            for side in ('group', 'control'):
                self.assertEqual(after['metrics'][side + '_ft_present'],
                                 before['counts'][side] - before['counts'][side + '_pending_ft'])

    def test_evidence_is_manual_review_owned(self):
        from scripts.publication_ownership import B1_AUDIT_FILES, MANUAL_REVIEW, owner_of
        for path in B1_AUDIT_FILES:
            self.assertEqual(owner_of(path), MANUAL_REVIEW)
        self.assertIsNone(owner_of('evidence/unregistered.json'))

    def test_original_real_records(self):
        import json
        from pathlib import Path
        proof = json.loads(Path('evidence/b1/real-plans.json').read_text())
        from h1lab.research_memory import _hash
        for record in proof['records']:
            self.assertEqual(_hash(record), record['sha256'])
            raw = dict(record['plan'], question=record['question'], hypothesis=record['hypothesis'],
                       null_hypothesis=record['null_hypothesis'])
            p = validate_plan(raw_plan(raw))
            self.assertEqual(p['fingerprint'], record['fingerprint'])
            q = self.quality(p, m=[])
            self.assertEqual(q['quality_status'], 'REJECTED')
            self.assertIn('IMMATERIAL_MOVEMENT', q['reasons'])


class WorkRevisionTests(unittest.TestCase):
    setUp = QualityTest.setUp
    quality = QualityTest.quality
    plan_with = QualityTest.plan_with
    def test_logic_paths(self):
        strong = {'op': 'ge', 'args': [{'var': 'lambda_net'}, {'const': .1}]}
        weak = {'op': 'gt', 'args': [{'var': 'lambda_net'}, {'const': 0}]}
        from h1lab.research_quality import _design
        self.assertEqual(_design({'op': 'and', 'args': [strong, weak]}), (set(), set()))
        self.assertEqual(_design({'op': 'and', 'args': [strong, {'const': True}]}), (set(), set()))
        self.assertIn('CONTRADICTORY_SIGNAL_PATH',
                      _design({'op': 'or', 'args': [strong, {'const': False}]})[0])
        self.assertIn('MATERIALITY_UNPROVEN', _design({'op': 'or', 'args': [strong, {'var': 'ctx_cup'}]})[1])
        self.assertEqual(_design({'op': 'or', 'args': [strong, strong]}), (set(), set()))

    def test_or_materiality_per_path(self):
        from h1lab.research_quality import _design
        goals = {'op': 'ge', 'args': [{'var': 'lambda_net'}, {'const': .1}]}
        line = {'op': 'ge', 'args': [{'var': 'total_line_net'}, {'const': .25}]}
        self.assertEqual(_design({'op': 'or', 'args': [goals, line]}), (set(), set()))
        line['args'][1]['const'] = .02
        self.assertIn('IMMATERIAL_MOVEMENT', _design({'op': 'or', 'args': [goals, line]})[0])
        contradiction = {'op': 'lt', 'args': goals['args']}
        dead = {'op': 'and', 'args': [goals, contradiction]}
        self.assertIn('CONTRADICTORY_SIGNAL_PATH',
                      _design({'op': 'or', 'args': [dead, goals]})[0])

    def test_neutral_control_and_equivalent_complement(self):
        for i, row in enumerate(self.meta):
            row['variables'].update(lambda_net=.2 if i < 182 else 0, total_line_last=2.5)
        group = {'op': 'ge', 'args': [{'var': 'lambda_net'}, {'const': .1}]}
        neutral = {'op': 'between', 'args': [
            {'var': 'lambda_net'}, {'const': -.02}, {'const': .02}]}
        explicit = self.quality(self.plan_with(group, control_condition=neutral), m=self.meta[:282])
        implicit = self.quality(self.plan_with(group), m=self.meta[:282])
        self.assertEqual((explicit['metrics']['group'], explicit['metrics']['control']), (182, 100))
        self.assertNotIn('IMMATERIAL_MOVEMENT', explicit['reasons'])
        self.assertIn('TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE', explicit['reasons'])
        for key in ('quality_status', 'design_quality_status', 'reasons', 'metrics'):
            self.assertEqual(explicit[key], implicit[key], key)

    def test_work_controls_and_support(self):
        invalid = {'op': 'gt', 'args': [{'op': 'add', 'args': [
            {'var': 'lambda_net'}, {'var': 'total_line_last'}]}, {'const': 0}]}
        p = self.plan_with({'op': 'ge', 'args': [{'var': 'lambda_net'}, {'const': .1}]},
                           control_condition=invalid)
        self.assertIn('MIXED_MOVEMENT_UNITS', self.quality(p)['reasons'])
        p = self.plan_with({'var': 'ctx_cup'}, control_condition={'var': 'ctx_league_other'},
                           confounders=['competition_type'])
        self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', self.quality(p)['reasons'])
        self.assertNotEqual(self.quality(p)['quality_status'], 'SCIENTIFICALLY_TESTABLE')

    def test_work_182_418_and_182_43(self):
        for i, row in enumerate(self.meta):
            row['variables']['lambda_net'] = .2 if i < 182 else -.2
            row['variables']['ctx_cup'] = 182 <= i < 225
        group = {'op': 'ge', 'args': [{'var': 'lambda_net'}, {'const': .1}]}
        q = self.quality(self.plan_with(group))
        self.assertEqual((q['metrics']['group'], q['metrics']['control']), (182, 418))
        q = self.quality(self.plan_with(group, control_condition={'var': 'ctx_cup'},
                                       confounders=['competition_type']))
        self.assertEqual((q['metrics']['group'], q['metrics']['control']), (182, 43))
        self.assertIn('COMMON_STRATUM_SUPPORT_MISSING', q['reasons'])

    def test_freeze_order_and_untrusted_flags(self):
        self.assertIn('TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE', self.quality()['reasons'])
        self.meta[0]['feature_frozen_at'] = '2026-10-01T00:00:00+00:00'
        self.assertIn('OBSERVATION_AFTER_FREEZE', self.quality()['reasons'])

    def test_secure_exclusive_output(self):
        import tempfile
        from pathlib import Path
        from scripts import lab_research_quality as cli
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli, 'ROOT', Path(tmp)):
            for name in ('/tmp/escape.json', '../escape.json', 'data/a.json', 'a/../b.json'):
                with self.assertRaises(ValueError): cli.write_diagnostic(name, {})
            import os
            cwd = os.getcwd()
            try:
                os.chdir('/tmp')
                cli.write_diagnostic('new.json', {})
            finally:
                os.chdir(cwd)
            target = Path(tmp)/'work/b1-diagnostics/new.json'
            original = target.read_bytes()
            with self.assertRaises(FileExistsError): cli.write_diagnostic('new.json', {'bad': True})
            self.assertEqual(target.read_bytes(), original)
            link = target.with_name('link.json')
            link.symlink_to(target)
            with self.assertRaises(OSError): cli.write_diagnostic('link.json', {})
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli, 'ROOT', Path(tmp)):
            (Path(tmp)/'work').symlink_to('/tmp', target_is_directory=True)
            with self.assertRaises(OSError): cli.write_diagnostic('escape.json', {})

    def test_history_tampering_fails_before_dataset(self):
        import json
        from pathlib import Path
        from scripts.lab_research_quality import verify_history
        proof = json.loads(Path('evidence/b1/real-plans.json').read_text())
        import subprocess
        check = subprocess.run(['git', 'cat-file', '-e', proof['source_commit']], capture_output=True)
        if check.returncode:
            self.skipTest('Historical Git objects unavailable in shallow checkout; CLI fails closed')
        self.assertEqual(verify_history(proof)[1], proof['source_commit'])
        import os
        with patch.dict(os.environ, {'GIT_DIR': '/nonexistent', 'GIT_WORK_TREE': '/nonexistent'}):
            self.assertEqual(verify_history(proof)[1], proof['source_commit'])
        for field, value in [('source_commit', 'a'*40), ('run_id', 123), ('memory_sha256', '0'*64)]:
            bad = copy.deepcopy(proof); bad[field] = value
            with self.assertRaises(ValueError): verify_history(bad)
        bad = copy.deepcopy(proof); bad['records'][0]['results']['counts']['group'] += 1
        with self.assertRaises(ValueError): verify_history(bad)
