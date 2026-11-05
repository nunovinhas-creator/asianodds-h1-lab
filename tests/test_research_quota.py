"""Offline fault-injection of durable quota admission, accounting and HTTP boundary."""
import base64
import copy
import hashlib
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from quota_fixtures import Store
from h1lab.research_quota import Controller, GitHubStore, append, summary, validate
from h1lab.research_llm import neurons_from_usage

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
MODEL = '@cf/meta/llama-3.3-70b-instruct-fp8-fast'


class Quota(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.now = NOW
        self.calls = 0

    def controller(self):
        return Controller(self.store, clock=lambda: self.now)

    def send(self):
        self.calls += 1
        return 'reply'

    def reserve(self, rid):
        q = self.controller()
        q.reserve(str(rid), MODEL, 900)
        return q

    def test_eight_unmetered_reservations_ninth_blocked(self):
        for i in range(8):
            self.reserve(i).send(self.send)
        with self.assertRaisesRegex(ValueError, 'EXHAUSTED'):
            self.reserve(9)
        self.assertEqual(self.calls, 8)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 8000)

    def test_metered_estimates_allow_more_than_eight_no_daily_exception(self):
        for i in range(15):
            q = self.reserve(i)
            q.send(self.send)
            q.settle(500)
        with self.assertRaisesRegex(ValueError, 'EXHAUSTED'):
            self.reserve(16)  # 7500 + conservative 1000 exceeds budget
        self.assertEqual(self.calls, 15)
        self.assertEqual(len(self.store.state['events']), 30)
        self.assertFalse(summary(self.store.state, self.now)['account_quota_verified'])
        self.assertIsNone(summary(self.store.state, self.now)['cloudflare_remaining_neurons'])

    def test_timeout_keeps_full_reservation_and_no_retry(self):
        q = self.reserve(1)
        def timeout():
            self.calls += 1
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            q.send(timeout)
        with self.assertRaises(ValueError):
            q.send(self.send)
        self.assertEqual(self.calls, 1)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)

    def test_duplicate_run_across_objects_attempts_and_days_refused(self):
        self.reserve(1)
        for days in (0, 1, 30):
            self.now = NOW + timedelta(days=days)
            with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
                self.reserve(1)

    def test_competing_writers_only_one_reserves(self):
        self.store.before_cas = lambda: self.reserve(2).send(self.send)
        with self.assertRaisesRegex(ValueError, 'CAS_CONFLICT'):
            self.reserve(1)
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(self.store.state['events']), 1)

    def test_lost_write_ack_never_calls_and_reservation_remains(self):
        self.store.lose_ack = True
        with self.assertRaisesRegex(ValueError, 'LOST_ACK'):
            self.reserve(1)
        self.assertEqual(self.calls, 0)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)

    def test_unavailable_or_corrupt_state_no_call(self):
        for failure in ('fail_read', 'fail_write'):
            with self.subTest(failure=failure):
                setattr(self.store, failure, True)
                with self.assertRaises(ValueError):
                    self.reserve(1)
                setattr(self.store, failure, False)
        self.reserve(1)
        self.store.state['events'][0]['reserved'] = 0
        with self.assertRaisesRegex(ValueError, 'CHAIN'):
            self.reserve(2)
        self.assertEqual(self.calls, 0)

    def test_midnight_cannot_reuse_old_reservation(self):
        self.now = NOW.replace(hour=23, minute=59, second=59)
        q = self.reserve(1)
        self.now += timedelta(seconds=2)
        with self.assertRaisesRegex(ValueError, 'STALE'):
            q.send(self.send)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)
        self.assertEqual(self.calls, 0)

    def test_unresolved_carry_and_completed_reset(self):
        self.reserve(1).send(self.send)
        q = self.reserve(2)
        q.send(self.send)
        q.settle(200)
        self.now += timedelta(days=1)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)
        self.assertEqual(len(self.store.state['events']), 3)

    def test_call_spanning_midnight_charged_on_both_days(self):
        q = self.reserve(1)
        q.send(self.send)
        self.now += timedelta(days=1)
        q.settle(450)
        for date in (NOW, self.now):
            self.assertEqual(summary(self.store.state, date)['charged_estimated_neurons'], 450)

    def test_stale_and_backward_clocks_fail_closed(self):
        for delta in (61, -1):
            self.setUp()
            q = self.reserve(1)
            self.now += timedelta(seconds=delta)
            with self.assertRaisesRegex(ValueError, 'STALE'):
                q.send(self.send)
            self.assertEqual(self.calls, 0)

    def test_missing_usage_not_zero_and_settlement_conflict_safe(self):
        q = self.reserve(1)
        q.send(self.send)
        q.settle(None)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)
        self.store.fail_write = True
        with self.assertRaises(ValueError):
            q.settle(100)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)

    def test_excess_metering_latches_future_calls_closed(self):
        q = self.reserve(1)
        q.send(self.send)
        with self.assertRaisesRegex(ValueError, 'EXCEEDS_BOUND'):
            q.settle(1001)
        self.now += timedelta(days=10)
        with self.assertRaisesRegex(ValueError, 'EXCEEDS_BOUND'):
            self.reserve(2)

    def test_bad_bounds_never_reserve(self):
        for bound in (None, True, -1, 0, 1001, float('nan'), float('inf')):
            with self.subTest(bound=bound), self.assertRaises(ValueError):
                self.controller().reserve('1', MODEL, bound)
        self.assertEqual(self.store.state['events'], [])

    def test_history_import_is_append_only_deduplicated_and_blocks_duplicates(self):
        legacy = {'kind': 'historical', 'id': 'legacy:1:2:3', 'run_id': '1', 'at': NOW.isoformat(),
                  'end': NOW.isoformat(), 'reserved': 1000, 'workflow': 'v6-llm-autonomous.yml'}
        self.store.records = [legacy, legacy]
        self.reserve(2)
        first = copy.deepcopy(self.store.state['events'])
        self.reserve(3)
        self.assertEqual(self.store.state['events'][:2], first)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 3000)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            self.reserve(1)

    def test_controlled_run_not_counted_again_as_historical_step(self):
        self.reserve(1)
        self.store.records = [{'kind': 'historical', 'id': 'legacy:1:2:3', 'run_id': '1',
                               'at': NOW.isoformat(), 'end': NOW.isoformat(), 'reserved': 1000}]
        self.reserve(2)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 2000)

    def test_old_history_expires_but_records_are_preserved(self):
        old = NOW - timedelta(days=3)
        self.store.records = [{'kind': 'historical', 'id': 'legacy:1:2:3', 'run_id': '1',
                               'at': old.isoformat(), 'end': old.isoformat(), 'reserved': 1000}]
        self.reserve(2)
        self.assertEqual(len(self.store.state['events']), 2)
        self.assertEqual(summary(self.store.state, self.now)['charged_estimated_neurons'], 1000)

    def test_double_settlement_refused(self):
        q = self.reserve(1)
        q.send(self.send)
        q.settle(500)
        with self.assertRaises(ValueError):
            q.settle(0)

    def test_partial_or_malformed_usage_is_unknown(self):
        for tokens in (None, {}, {'prompt_tokens': 2}, {'prompt_tokens': -1, 'completion_tokens': 1},
                       {'prompt_tokens': True, 'completion_tokens': 1}, {'prompt_tokens': 0, 'completion_tokens': 0}):
            self.assertIsNone(neurons_from_usage(MODEL, tokens))
        self.assertEqual(neurons_from_usage(MODEL, {'prompt_tokens': 1, 'completion_tokens': 1}), 1)


class Api(unittest.TestCase):
    def test_redirects_never_forward_or_replay_credentials(self):
        from h1lab.research_quota import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://other.invalid'))

    def test_cas_payload_and_ack_checked(self):
        calls = []
        class Resp(io.BytesIO):
            status = 200
        def opener(req, timeout):
            calls.append(req)
            obj = json.loads(req.data)
            raw = base64.b64decode(obj['content'])
            digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            return Resp(json.dumps({'content': {'sha': digest}}).encode())
        s = GitHubStore('o/r', 'fake', opener)
        old = {'schema_version': 1, 'events': []}
        new = copy.deepcopy(old)
        append(new, {'kind': 'reserve', 'id': 'run:1', 'at': NOW.isoformat(), 'reserved': 1000})
        s.cas(old, new, 'a' * 40)
        payload = json.loads(calls[0].data)
        self.assertEqual(payload['sha'], 'a' * 40)
        self.assertEqual(payload['branch'], 'llm-quota-ledger')
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            s.cas(new, old, 'a' * 40)

    def test_missing_state_never_becomes_empty(self):
        class Resp(io.BytesIO):
            status = 200
        for value in ({}, {'encoding': 'base64', 'sha': 'a' * 40, 'content': base64.b64encode(b'{}').decode()}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GitHubStore('o/r', 'fake', lambda *a, **kw: Resp(json.dumps(value).encode())).read()



class HistoricalApi(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.runs = [{'id': 99, 'run_attempt': 1, 'updated_at': NOW.isoformat()},
                     {'id': 1, 'run_attempt': 2, 'created_at': '2020-01-01T00:00:00Z',
                      'updated_at': NOW.isoformat()}]
        self.jobs = [{'id': 10, 'steps': [{'name': 'ONE LLM call', 'number': 1,
                       'status': 'completed', 'conclusion': 'failure',
                       'started_at': NOW.isoformat(), 'completed_at': NOW.isoformat()}]}]
        self.force_total = None

    def store(self):
        class Resp(io.BytesIO):
            status = 200
        def opener(req, timeout):
            self.calls.append(req.full_url)
            if '/jobs?' in req.full_url:
                obj = {'total_count': len(self.jobs), 'jobs': self.jobs}
            else:
                runs = self.runs if 'autonomous' in req.full_url else []
                obj = {'total_count': self.force_total if self.force_total is not None else len(runs),
                       'workflow_runs': runs}
            return Resp(json.dumps(obj).encode())
        return GitHubStore('o/r', 'fake', opener, clock=lambda: NOW)

    def test_old_created_rerun_failure_imported_all_attempts(self):
        self.jobs.append(dict(self.jobs[0], id=11))
        rows = self.store().history('99')
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r['id'] for r in rows}), 2)
        self.assertTrue(any('filter=all' in p for p in self.calls))
        self.assertFalse(any('created=' in p for p in self.calls))

    def test_skipped_and_queued_steps_not_charged(self):
        for change in ({'conclusion': 'skipped'}, {'status': 'queued', 'started_at': None, 'completed_at': None}):
            self.jobs[0]['steps'][0].update(change)
            self.assertEqual(self.store().history('99'), [])

    def test_inflight_unknown_other_run_blocks(self):
        self.jobs[0]['steps'][0]['completed_at'] = None
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED'):
            self.store().history('99')

    def test_rerunning_current_run_blocks_even_without_local_reservation(self):
        self.runs[0]['run_attempt'] = 2
        with self.assertRaisesRegex(ValueError, 'RERUN'):
            self.store().history('99')

    def test_missing_current_run_blocks(self):
        with self.assertRaisesRegex(ValueError, 'NOT_VISIBLE'):
            self.store().history('999')

    def test_duplicate_run_and_missing_steps_fail_closed(self):
        self.runs.append(self.runs[1])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            self.store().history('99')
        self.runs.pop()
        self.jobs[0].pop('steps')
        with self.assertRaisesRegex(ValueError, 'STEPS_MISSING'):
            self.store().history('99')

    def test_incomplete_pagination_fails_closed(self):
        self.force_total = 3
        with self.assertRaises(ValueError):
            self.store().history('99')

    def test_http_boundary_cannot_consume_twice(self):
        q = Controller(Store(), clock=lambda: NOW)
        q.reserve('1', MODEL, 900)
        q.send(lambda: q.consume_http(MODEL, 1000))
        with self.assertRaisesRegex(ValueError, 'ALREADY_USED'):
            q.consume_http(MODEL, 1000)


class LedgerSeedOwnership(unittest.TestCase):
    """The main-branch seed is human-merged code: no main publisher may stage or rewrite it."""

    def test_seed_is_program_owned(self):
        from scripts import publication_ownership as own
        from h1lab import research_quota
        self.assertEqual(own.QUOTA_LEDGER_SEED, research_quota.PATH)
        self.assertEqual(own.owner_of(research_quota.PATH), own.PROGRAM)
        self.assertNotEqual(research_quota.BRANCH, 'main')

    def test_seed_is_empty_and_valid(self):
        from h1lab import research_quota
        root = Path(__file__).resolve().parents[1]
        seed = json.loads((root / research_quota.PATH).read_text(encoding='utf-8'))
        self.assertEqual(seed, {'schema_version': 1, 'events': []})
        validate(seed)

    def test_no_workflow_stages_the_ledger_on_main(self):
        root = Path(__file__).resolve().parents[1]
        for wf in sorted((root / '.github/workflows').glob('*.yml')):
            text = wf.read_text(encoding='utf-8')
            with self.subTest(workflow=wf.name):
                self.assertNotRegex(text, r'git add[^\n]*(?:quota-ledger|data/research/\*|data/research/?\s)')


if __name__ == '__main__':
    unittest.main()
