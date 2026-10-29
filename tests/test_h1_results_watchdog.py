import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from scripts import h1_results_watchdog as w

NOW = datetime(2026, 10, 29, 18, tzinfo=timezone.utc)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'data/results.csv').write_text('match_key,status,home_goals,away_goals,source\nx,FINAL,1,0,test\n')
        (self.root / 'data/result_audit.json').write_text('{}')
        self.env = dict(GITHUB_WORKFLOW=w.SOURCE_WORKFLOW, GITHUB_REF='refs/heads/main',
                        GITHUB_REPOSITORY=w.OWNER_REPO, GITHUB_EVENT_NAME='workflow_dispatch',
                        GITHUB_TOKEN='test-secret')

    def entry(self, minutes=100, status='completed'):
        return dict(created_at=(NOW-timedelta(minutes=minutes)).isoformat(), status=status)

    def test_dispatch_only_when_overdue_and_no_active_run(self):
        self.assertTrue(w.plan([], NOW)['dispatch'])
        self.assertTrue(w.plan([self.entry()], NOW)['dispatch'])
        for minutes in (0, 89):
            self.assertFalse(w.plan([self.entry(minutes)], NOW)['dispatch'])
        for status in ('queued', 'in_progress', 'waiting', None):
            self.assertFalse(w.plan([self.entry(1000, status)], NOW)['dispatch'])
        self.assertFalse(w.plan([], NOW, timedelta(minutes=89))['dispatch'])

    def test_bad_api_data_fails_closed(self):
        for runs in (None, [{}], [self.entry(-10)], ['bad']):
            with self.subTest(runs=runs), self.assertRaises((ValueError, TypeError)):
                w.plan(runs, NOW)

    def test_receipt_is_bound_to_outputs_and_clock(self):
        self.assertIsNone(w.receipt_age(self.root, NOW))
        w.write_receipt(self.root, NOW)
        self.assertEqual(w.receipt_age(self.root, NOW), timedelta(0))
        self.assertIsNone(w.receipt_age(self.root, NOW-timedelta(seconds=1)))
        (self.root / 'data/results.csv').write_text('changed')
        self.assertIsNone(w.receipt_age(self.root, NOW))

    def test_partial_outputs_never_get_receipt(self):
        for content in ('', 'match_key,status\nx\n', 'match_key,status\nx,FINAL,extra\n'):
            (self.root / 'data/results.csv').write_text(content)
            with self.assertRaises(ValueError):
                w.write_receipt(self.root, NOW)
            self.assertFalse((self.root / w.RECEIPT).exists())

    def test_corrupt_and_naive_receipts_are_not_fresh(self):
        w.write_receipt(self.root, NOW)
        target = self.root / w.RECEIPT
        document = json.loads(target.read_text())
        for content in ('{', 'null', json.dumps({**document, 'completed_at': '2026-10-29T18:00:00'})):
            target.write_text(content)
            self.assertIsNone(w.receipt_age(self.root, NOW))

    def test_no_network_for_fresh_receipt_or_wrong_context(self):
        opener = Mock(side_effect=AssertionError('network called'))
        w.write_receipt(self.root, NOW)
        self.assertFalse(w.run(env=self.env, now=NOW, root=self.root, opener=opener)['dispatch'])
        for key in ('GITHUB_WORKFLOW', 'GITHUB_REF', 'GITHUB_REPOSITORY', 'GITHUB_TOKEN'):
            self.assertFalse(w.run(env={**self.env, key: ''}, now=NOW, root=self.root, opener=opener)['dispatch'])
        opener.assert_not_called()

    def test_dispatch_contract_and_api_failure(self):
        calls = []
        class Response:
            def __init__(self, status, body=b''):
                self.status, self.body = status, body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return self.body
        def opener(request, timeout):
            calls.append(request)
            return Response(204) if request.get_method() == 'POST' else Response(200, b'{"workflow_runs": []}')
        outcome = w.run(env=self.env, now=NOW, root=self.root, opener=opener)
        self.assertEqual(outcome['reason'], 'DISPATCH_ACCEPTED')
        self.assertEqual(len(calls), 2)
        self.assertIn('results.yml/runs?branch=main', calls[0].full_url)
        self.assertEqual(json.loads(calls[1].data), {'ref':'main','inputs':{'trigger_source':'h1-results-watchdog'}})
        outcome = w.run(env=self.env, now=NOW, root=self.root, opener=Mock(side_effect=OSError('secret')))
        self.assertEqual(outcome, {'dispatch':False, 'reason':'GITHUB_UNAVAILABLE'})


if __name__ == '__main__':
    unittest.main()
