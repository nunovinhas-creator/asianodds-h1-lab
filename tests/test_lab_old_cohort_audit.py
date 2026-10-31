import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.lab_old_cohort_audit import audit


class OldCohortAuditTests(unittest.TestCase):
    def test_every_frozen_fixture_is_reported_without_invented_coverage_or_http(self):
        root=Path(__file__).resolve().parents[1]
        c=json.loads((root/'reports/ft-old-cohort-180.json').read_text())
        r=audit(root,c,datetime(2026,10,31,14,tzinfo=timezone.utc))
        self.assertEqual(len(r['games']),180)
        self.assertEqual({g['match_key'] for g in r['games']},set(c['match_keys']))
        self.assertEqual(r['still_pending']+r['certified_since_baseline'],180)
        self.assertEqual(sum(r['obstacles'].values()),180)
        self.assertEqual(sum(x['cohort'] for x in r['by_competition'].values()),180)
        self.assertEqual(r['demonstrably_irrecoverable'],0)
        self.assertEqual(r['proven_cross_provider_competition_bindings'],0)
        for g in r['games']:
            self.assertEqual(len(g['providers']),9)
            self.assertTrue(all(p['fixture_http_attribution']=='UNKNOWN_UNLESS_SEPARATELY_LOGGED' for p in g['providers']))
        c['match_keys'][0]=c['match_keys'][1]
        with self.assertRaises(ValueError):audit(root,c,datetime(2026,10,31,14,tzinfo=timezone.utc))
