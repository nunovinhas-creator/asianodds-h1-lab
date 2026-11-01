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
        for minutes in (0, 44, 64):
            self.assertFalse(w.plan([self.entry(minutes)], NOW)['dispatch'])
        for status in ('queued', 'in_progress', 'waiting', None):
            self.assertFalse(w.plan([self.entry(1000, status)], NOW)['dispatch'])
        self.assertFalse(w.plan([], NOW, timedelta(minutes=64))['dispatch'])
        # The collector fallback can recover a skipped hourly cron sooner,
        # without increasing the verified H1 per-cycle 20-fixture quota.
        self.assertTrue(w.plan([], NOW, timedelta(minutes=65))['dispatch'])
        self.assertFalse(w.plan([self.entry(64)], NOW)['dispatch'])
        self.assertTrue(w.plan([self.entry(65)], NOW)['dispatch'])

    def test_proven_noop_does_not_reset_65_minute_receipt_timer(self):
        noop = {**self.entry(5), 'verified_noop': True}
        self.assertTrue(w.plan([noop], NOW, timedelta(minutes=70))['dispatch'])
        self.assertFalse(w.plan([self.entry(5)], NOW, timedelta(minutes=70))['dispatch'])
        self.assertFalse(w.plan([noop], NOW, timedelta(minutes=64))['dispatch'])
        self.assertFalse(w.plan([noop, self.entry(10, 'in_progress')],
                                NOW, timedelta(minutes=70))['dispatch'])
        self.assertFalse(w.plan([noop, self.entry(10)], NOW,
                                timedelta(minutes=70))['dispatch'])

    def test_noop_requires_all_skipped_effects_and_successful_due_gate(self):
        names = [
            'Import confirmed LAB FT into H1 without changing signal rules',
            'Check BSD and TheSportsDB results with strict FT validation',
            'Rebuild ROI for singles and triples',
            'Record completed result cycle (not a coverage certificate)',
            'Publish confirmed finals and audit',
        ]
        def response(outcome='skipped', job_status='success'):
            return {'jobs': [{'name': 'results', 'status': 'completed',
                              'conclusion': job_status, 'steps': [
                                  {'name': 'Avoid duplicate queued result cycles',
                                   'conclusion': 'success'},
                                  *[{'name': n, 'conclusion': outcome} for n in names],
                              ]}]}
        self.assertTrue(w.proven_noop_jobs(response()))
        for payload in (
            {}, {'jobs': []}, {'jobs': [{'name': 'results'}]},
            response('success'), response('skipped', 'failure'),
            {'jobs': [*response()['jobs'], *response()['jobs']]},
            {'jobs': [{**response()['jobs'][0], 'steps': [
                {'name': 'Avoid duplicate queued result cycles',
                 'conclusion': 'success'}]}]},
        ):
            with self.subTest(payload=payload):
                self.assertFalse(w.proven_noop_jobs(payload))

    def test_noop_job_evidence_requires_real_github_metadata(self):
        class Response:
            status=200
            def __init__(self, body): self.body=body
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, n): return self.body
        calls=[]
        good_steps = [
            {'name': 'Avoid duplicate queued result cycles', 'conclusion': 'success'},
            *[{'name': n, 'conclusion': 'skipped'} for n in (
                'Import confirmed LAB FT into H1 without changing signal rules',
                'Check BSD and TheSportsDB results with strict FT validation',
                'Rebuild ROI for singles and triples',
                'Record completed result cycle (not a coverage certificate)',
                'Publish confirmed finals and audit')],
        ]
        def opener(req, timeout):
            calls.append(req.full_url)
            return Response(json.dumps({'jobs': [{
                'name': 'results', 'status': 'completed', 'conclusion': 'success',
                'steps':good_steps}]}).encode())
        runs=[{**self.entry(5), 'id': 12345, 'conclusion': 'success'}]
        url='https://api.github.com/repos/example/repo/actions/workflows/results.yml'
        update=w.annotate_recent_noops(runs,NOW,url,{},opener)
        self.assertTrue(update[0]['verified_noop'])
        self.assertNotIn('verified_noop',runs[0])
        self.assertEqual(calls,[
            'https://api.github.com/repos/example/repo/actions/runs/12345/jobs?per_page=10'
        ])
        # Failed and unknown jobs are NOT silently classified as no-ops.
        bad=[{**self.entry(5),'id':12345,'conclusion':'failure'}]
        self.assertFalse(w.annotate_recent_noops(bad,NOW,url,{},opener)[0]['verified_noop'])
        with self.assertRaises(ValueError):
            w.annotate_recent_noops([self.entry(5)],NOW,url,{},opener)
        with self.assertRaises(ValueError):
            w.annotate_recent_noops([{**self.entry(5),'id':n} for n in range(1,6)],
                                    NOW,url,{},opener)

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
