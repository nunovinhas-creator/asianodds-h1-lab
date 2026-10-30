"""Offline queue invariants; reuse bounded source fixtures."""
import json
from tests import test_v6_llm_investigator as fixtures
from h1lab.v6_discovery_planner import plan, candidate_id
import unittest


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.InvestigatorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def test_distinct_families_replay_and_no_writes(self):
        before = self.fixture.snapshot()
        a = plan(self.root, limit=100)
        self.assertEqual(a, plan(self.root, limit=100))
        self.assertEqual(a['llm_calls'], 0)
        self.assertEqual(a['empirical_tests_performed'], 0)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(a['distinct_family_space'], {'2': 9, '3': 7})
        families = {'G_MULTI_ALERT': 'SEQ', 'G_SINGLE_ALERT': 'SEQ',
                    'M_IMPLIED_GOALS_FLAT': 'IMP', 'M_TOTAL_LINE_UP': 'TOT',
                    'G_FIRST_LEAD_LT_6H': 'TIME'}
        for x in a['queue']:
            self.assertEqual(len(x['feature_codes']), len({families[c] for c in x['feature_codes']}))

    def test_dedup_uses_archive_not_truncated_index(self):
        a = plan(self.root)
        codes = a['queue'][0]['feature_codes']
        archive = self.root / 'docs/lab/llm-investigator-runs'
        archive.mkdir(parents=True)
        (archive / '1.json').write_text(json.dumps({'schema_version': 1,
            'state': 'SHADOW_DRAFT_NOT_EMPIRICALLY_VALIDATED', 'proposals': [{
            'feature_codes': list(reversed(codes)), 'outcome': 'OVER_2_5',
            'baseline': 'MARKET_MODEL_OVER25'}]}))
        b = plan(self.root)
        self.assertEqual(b['remaining'], a['remaining'] - 1)
        self.assertNotIn(candidate_id(codes), [c['candidate_id'] for c in b['queue']])
        (archive / '1.json').write_text('{}')
        with self.assertRaises(ValueError): plan(self.root)


if __name__ == '__main__':
    unittest.main()
