"""One dated exception to the daily LLM attempt limit: 5 attempts on 2026-11-05 only.

Offline only: fake GitHub API, no provider call.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h1lab import research_daily_limit as dl  # noqa: E402
from h1lab import research_llm  # noqa: E402
from scripts import lab_research_budget as budget  # noqa: E402
from scripts.lab_research_cycle import MODEL, SCHEDULE, live_authorisation  # noqa: E402

LIVE = 'ONE bounded LLM call into a scratch copy of the operational memory, no retries'
OK = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
      'RESEARCH_LLM_CONFIRMATION': 'INVESTIGAR_UMA_VEZ', 'GITHUB_EVENT_SCHEDULE': SCHEDULE}


def _env(prior, **kw):
    return dict(OK, RESEARCH_PRIOR_LLM_ATTEMPTS=str(prior), **kw)


def _used(day, n):
    return [{'record_type': 'CYCLE', 'llm_origin': 'LLM_LIVE', 'llm_calls': 1,
             'recorded_at': '%sT%02d:43:00+00:00' % (day, h)} for h in (1, 7, 13, 19, 20, 21)[:n]]


class DailyLimitFunction(unittest.TestCase):
    def test_exception_is_exactly_one_day(self):
        self.assertEqual(dl.daily_llm_attempt_limit('2026-11-05'), 5)
        for day in ('2026-11-04', '2026-11-06', '2026-11-07', '2026-12-05', '2027-11-05', '2026-11-05T00:00',
                    ' 2026-11-05', '', None, 20261105):
            with self.subTest(day=day):
                self.assertEqual(dl.daily_llm_attempt_limit(day), 4)

    def test_only_one_exception_and_within_neuron_budget(self):
        self.assertEqual(dl.DAILY_LLM_ATTEMPT_EXCEPTIONS, {'2026-11-05': 5})
        self.assertEqual(dl.BASE_DAILY_LLM_ATTEMPTS, 4)
        self.assertEqual(dl.HARD_MAX_DAILY_LLM_ATTEMPTS,
                         research_llm.DAILY_NEURON_BUDGET // research_llm.MAX_NEURONS_PER_CALL)
        self.assertLessEqual(dl.HARD_MAX_DAILY_LLM_ATTEMPTS * research_llm.MAX_NEURONS_PER_CALL,
                             research_llm.FREE_NEURONS_PER_DAY)
        # Neuron limits themselves are unchanged.
        self.assertEqual((research_llm.FREE_NEURONS_PER_DAY, research_llm.DAILY_NEURON_BUDGET,
                          research_llm.MAX_NEURONS_PER_CALL, research_llm.MAX_CALLS_PER_DAY),
                         (10_000, 5_000, 1_000, 4))


class LiveAuthorisationOnExceptionDay(unittest.TestCase):
    DAY = '2026-11-05'

    def test_fifth_attempt_allowed_with_four_already_counted(self):
        self.assertEqual(live_authorisation(_env(4), [], self.DAY), 'workflow_dispatch')
        self.assertEqual(live_authorisation(_env(4), _used(self.DAY, 4), self.DAY), 'workflow_dispatch')

    def test_sixth_attempt_refused_by_ledger_or_memory(self):
        for prior, used in ((5, 0), (6, 0), (0, 5), (4, 5), (5, 5)):
            with self.subTest(prior=prior, used=used), self.assertRaisesRegex(ValueError, 'LIVE_DAILY_LIMIT'):
                live_authorisation(_env(prior), _used(self.DAY, used), self.DAY)

    def test_other_protections_unchanged_on_exception_day(self):
        for change in ({'GITHUB_REF': 'refs/heads/x'}, {'GITHUB_RUN_ATTEMPT': '2'},
                       {'RESEARCH_LLM_CONFIRMATION': ''}, {'GITHUB_EVENT_NAME': 'push'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                live_authorisation(dict(_env(4), **change), [], self.DAY)
        with self.assertRaisesRegex(ValueError, 'LIVE_LEDGER_MISSING'):
            live_authorisation(dict(OK), [], self.DAY)

    def test_limit_back_to_four_from_next_day(self):
        for day in ('2026-11-06', '2026-11-07', '2026-11-04'):
            with self.subTest(day=day):
                self.assertEqual(live_authorisation(_env(3), [], day), 'workflow_dispatch')
                with self.assertRaisesRegex(ValueError, 'LIVE_DAILY_LIMIT'):
                    live_authorisation(_env(4), [], day)
                with self.assertRaisesRegex(ValueError, 'LIVE_DAILY_LIMIT'):
                    live_authorisation(_env(0), _used(day, 4), day)
        # Attempts of the exception day never leak into the next day's count.
        self.assertEqual(live_authorisation(_env(0), _used(self.DAY, 5), '2026-11-06'), 'workflow_dispatch')

    def test_neuron_bound_allows_fifth_refuses_sixth(self):
        prof = research_llm.MODEL_PROFILES[MODEL]
        research_llm.neuron_bound(MODEL, prof['max_request_bytes'], prior_calls_today=4)
        with self.assertRaisesRegex(ValueError, 'DAILY_NEURON_BUDGET_EXCEEDED'):
            research_llm.neuron_bound(MODEL, prof['max_request_bytes'], prior_calls_today=5)


class LedgerReport(unittest.TestCase):
    """The ledger keeps counting all four earlier attempts and reports the dated limit."""

    def _report(self, now, runs):
        class Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=0):
            url = req.full_url
            if '/workflows/v6-llm-autonomous.yml/runs' in url:
                return Resp(json.dumps({'total_count': len(runs), 'workflow_runs': runs}).encode())
            if '/workflows/' in url:
                return Resp(json.dumps({'total_count': 0, 'workflow_runs': []}).encode())
            rid = int(url.split('/runs/')[1].split('/')[0])
            steps = [{'name': LIVE, 'status': 'completed', 'conclusion': 'failure' if rid % 2 else 'success'}]
            return Resp(json.dumps({'total_count': 1, 'jobs': [{'status': 'completed', 'conclusion': 'failure',
                                                                'steps': steps}]}).encode())

        out = io.StringIO()
        with redirect_stdout(out):
            rc = budget.main(['--repo', 'o/r', '--exclude-run', '999'], env={'GH_TOKEN': 't'}, opener=opener, now=now)
        self.assertEqual(rc, 0)
        return json.loads(out.getvalue())

    @staticmethod
    def _runs(day):
        return [{'id': i, 'event': 'workflow_dispatch', 'created_at': '%sT%02d:45:00Z' % (day, h),
                 'updated_at': '%sT%02d:49:00Z' % (day, h), 'run_started_at': '%sT%02d:45:00Z' % (day, h)}
                for i, h in zip((1, 2, 3, 4), (8, 11, 12, 13))]

    def test_four_counted_one_remaining_on_exception_day(self):
        r = self._report(datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc), self._runs('2026-11-05'))
        self.assertEqual((r['prior_llm_attempts'], r['limit'], r['remaining']), (4, 5, 1))

    def test_four_counted_zero_remaining_next_day(self):
        r = self._report(datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc), self._runs('2026-11-06'))
        self.assertEqual((r['prior_llm_attempts'], r['limit'], r['remaining']), (4, 4, 0))


if __name__ == '__main__':
    unittest.main()
