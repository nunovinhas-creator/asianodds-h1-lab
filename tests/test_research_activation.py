"""Activation of the autonomous researcher (replaces the retired V6 LLM workflow).

Everything here is offline: the "LLM" is the SIMULATED opener or a canned FakeOpener,
the GitHub API is a fake. No provider or network call is made by these tests.
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_fixtures import FakeOpener  # noqa: E402
from test_research_gates import copy_sources  # noqa: E402

from h1lab import research_memory as rm  # noqa: E402
from h1lab.research_simulated_llm import SimulatedLLMOpener  # noqa: E402
from scripts import lab_research_budget as budget  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'
NOW = datetime(2026, 11, 6, 13, 50, tzinfo=timezone.utc)


def _step(name, conclusion='success', status='completed'):
    return {'name': name, 'status': status, 'conclusion': conclusion}


def _run(rid, created, event='schedule', updated=None):
    return {'id': rid, 'event': event, 'created_at': created, 'updated_at': updated or created,
            'run_started_at': created}


LIVE = 'ONE bounded LLM call into a scratch copy of the operational memory, no retries'


class SingleActiveSchedule(unittest.TestCase):
    """Exactly one workflow can reach the LLM on a schedule; the slots are unchanged."""

    def test_exactly_one_scheduled_workflow_holds_llm_secrets(self):
        scheduled_llm = []
        cron_owners = []
        for w in sorted(WORKFLOWS.glob('*.y*ml')):
            text = w.read_text(encoding='utf-8')
            if re.search(r'^\s*schedule:', text, re.M) and 'MASTER_BRAIN_LLM_API_KEY' in text:
                scheduled_llm.append(w.name)
            if '43 1,7,13,19 * * *' in text:
                cron_owners.append(w.name)
        self.assertEqual(scheduled_llm, ['v6-llm-autonomous.yml'])
        self.assertEqual(cron_owners, ['v6-llm-autonomous.yml'])
        crons = re.findall(r"cron:\s*'([^']+)'", (WORKFLOWS / 'v6-llm-autonomous.yml').read_text())
        self.assertEqual(crons, ['43 1,7,13,19 * * *'], 'four opportunities/day, no extra entry')

    def test_every_llm_workflow_shares_the_global_group_and_is_ledgered(self):
        for w in sorted(WORKFLOWS.glob('*.y*ml')):
            text = w.read_text(encoding='utf-8')
            if 'MASTER_BRAIN_LLM_API_KEY' in text:
                with self.subTest(workflow=w.name):
                    self.assertIn('group: v6-llm-global', text)
                    self.assertIn('cancel-in-progress: false', text)
                    self.assertIn(w.name, budget.LEDGER_WORKFLOWS, 'every LLM workflow is counted')
                    self.assertTrue(any(m in text for m in budget.LLM_STEP_MARKERS),
                                    'the provider step is recognisable by the ledger')

    def test_no_proposed_copy_left_and_config_enabled_only_by_this_change(self):
        self.assertEqual(list((ROOT / '.github').glob('proposed-workflows/*')), [])
        cfg = json.loads((ROOT / 'config/research-autonomy.json').read_text())
        self.assertTrue(cfg['llm_live_enabled'])
        self.assertFalse(cfg['llm_schedule_live_enabled'])
        self.assertEqual(cfg['max_llm_calls_per_cycle'], 1)
        self.assertEqual(cfg['max_llm_plans_per_call'], 3)

    def test_request_bounds_and_model_unchanged(self):
        from h1lab import research_llm
        from scripts import lab_research_cycle as cyc
        from scripts import lab_v6_llm_autonomous as old
        # Contract v3: the model changed on purpose (the 8B alias produced 0 valid plans in
        # runs 42021728675 and 42030138637). It must be a profiled model with documented JSON
        # Mode, known neuron rates and a worst case inside the per-call neuron cap.
        self.assertNotEqual(cyc.MODEL, old.MODEL)
        prof = research_llm.MODEL_PROFILES[cyc.MODEL]
        self.assertTrue(prof['json_mode_documented'])
        self.assertEqual(prof['status'], 'RECOMMENDED')
        self.assertLessEqual(research_llm.neuron_bound(cyc.MODEL, prof['max_request_bytes'])['neurons_max'],
                             research_llm.MAX_NEURONS_PER_CALL)
        self.assertEqual(cyc.SCHEDULE, old.SCHEDULE)
        self.assertEqual(cyc.MAX_DAILY_LIVE_CALLS, 8)
        self.assertEqual(budget.MAX_DAILY_LLM_ATTEMPTS, 8)
        self.assertEqual(research_llm.MAX_REQUEST_BYTES, 48_000)
        src = Path(research_llm.__file__).read_text()
        self.assertEqual(research_llm.MAX_OUTPUT_TOKENS, 2400)
        self.assertIn("'max_tokens': MAX_OUTPUT_TOKENS", src)
        self.assertNotRegex(src, r'for .* in range\(|while .*retry', 'no retry loop around the request')


class Ledger(unittest.TestCase):
    """Pre-call attempt ledger: counts calls even when nothing was published."""

    def jobs(self, *steps):
        return [{'status': 'completed', 'conclusion': 'failure', 'steps': list(steps)}]

    def test_counts_started_llm_steps_any_conclusion_and_skips_skipped(self):
        runs = {'v6-llm-autonomous.yml': [
            _run(1, '2026-11-06T01:50:00Z'), _run(2, '2026-11-06T08:30:00Z'),
            _run(3, '2026-11-06T09:00:00Z', 'workflow_dispatch'), _run(4, '2026-11-06T10:00:00Z')]}
        jobs = {1: self.jobs(_step(LIVE, 'success')),           # published
                2: self.jobs(_step(LIVE, 'failure')),           # call made, invalid reply, NOT in memory
                3: self.jobs(_step(LIVE, 'skipped')),           # preview dispatch: free
                4: self.jobs(_step(LIVE, 'cancelled'))}         # timed out / cancelled mid-call
        total, details = budget.count_attempts(runs, jobs, now=NOW, exclude_run_id=99)
        self.assertEqual(total, 3)
        self.assertEqual(sorted(d['run_id'] for d in details), [1, 2, 4])

    def test_reruns_all_attempts_old_workflow_and_manual_investigator_count(self):
        runs = {'v6-llm-autonomous.yml': [_run(1, '2026-11-06T02:00:00Z')],
                'v6-llm-investigator.yml': [_run(2, '2026-11-06T03:00:00Z', 'workflow_dispatch'),
                                            _run(3, '2026-11-06T04:00:00Z', 'workflow_dispatch')]}
        jobs = {1: [{'steps': [_step('ONE LLM call with novel candidate pool, no retries', 'failure')]},
                    {'steps': [_step('ONE LLM call with novel candidate pool, no retries', 'failure')]}],
                2: self.jobs(_step('Cloudflare Workers AI — ONE explicit request, no retries')),
                3: self.jobs(_step('Cloudflare Workers AI — ONE explicit request, no retries', 'skipped'))}
        total, _ = budget.count_attempts(runs, jobs, now=NOW, exclude_run_id=0)
        self.assertEqual(total, 3)

    def test_utc_day_boundary_self_exclusion_and_missing_jobs(self):
        runs = {'v6-llm-autonomous.yml': [
            _run(1, '2026-11-05T19:50:00Z'),                                   # yesterday only
            _run(2, '2026-11-05T23:59:00Z', updated='2026-11-06T00:02:00Z'),   # executed today
            _run(7, '2026-11-06T13:44:00Z')]}                                  # the current run
        jobs = {1: self.jobs(_step(LIVE)), 2: self.jobs(_step(LIVE)), 7: self.jobs(_step(LIVE, None, 'in_progress'))}
        total, details = budget.count_attempts(runs, jobs, now=NOW, exclude_run_id='7')
        self.assertEqual((total, [d['run_id'] for d in details]), (1, [2]))
        with self.assertRaisesRegex(ValueError, 'LEDGER_JOBS_MISSING'):
            budget.count_attempts(runs, {1: [], 7: []}, now=NOW, exclude_run_id='7')

    def test_unknown_shapes_count_conservatively(self):
        self.assertTrue(budget.step_started({'name': LIVE}))                     # no status at all
        self.assertTrue(budget.step_started('garbage'))
        self.assertFalse(budget.step_started(_step(LIVE, None, 'queued')))       # never started
        self.assertEqual(budget.attempts_in_jobs([{'status': 'in_progress'}]), 1)

    def _fake_api(self, runs, jobs, total=None, status=200):
        calls = []

        class Resp:
            def __init__(self, body, st): self.body, self.status = body, st
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return self.body

        def opener(req, timeout=None):
            calls.append(req.full_url)
            self.assertTrue(req.full_url.startswith('https://api.github.com/repos/o/r/actions/'))
            self.assertEqual(req.get_method(), 'GET', 'ledger is read-only')
            m = re.search(r'/workflows/([^/]+)/runs', req.full_url)
            if m:
                rs = runs.get(m.group(1), [])
                body = {'total_count': len(rs) if total is None else total, 'workflow_runs': rs}
            else:
                rid = int(re.search(r'/runs/(\d+)/jobs', req.full_url).group(1))
                body = {'total_count': len(jobs[rid]), 'jobs': jobs[rid]}
            return Resp(json.dumps(body).encode(), status)
        return opener, calls

    def test_cli_writes_output_and_fails_closed(self):
        runs = {'v6-llm-autonomous.yml': [_run(5, '2026-11-06T02:00:00Z')]}
        jobs = {5: self.jobs(_step(LIVE, 'failure'))}
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / 'gh_output'
            opener, calls = self._fake_api(runs, jobs)
            code = budget.main(['--repo', 'o/r', '--exclude-run', '9', '--github-output', str(out)],
                               env={'GH_TOKEN': 'fake'}, opener=opener, now=NOW)
            self.assertEqual(code, 0)
            self.assertEqual(out.read_text(), 'prior=1\n')
            self.assertEqual(len(calls), 3)    # two workflow listings + one jobs listing
            for env, kw in (({}, {}),                                   # no token
                            ({'GH_TOKEN': 'x'}, {'total': 500}),        # cannot see every run
                            ({'GH_TOKEN': 'x'}, {'status': 500})):      # API error
                with self.subTest(env=env, kw=kw):
                    o = Path(t) / 'o2'
                    opener, _ = self._fake_api(runs, jobs, **kw)
                    self.assertEqual(budget.main(['--repo', 'o/r', '--exclude-run', '9', '--github-output', str(o)],
                                                 env=env, opener=opener, now=NOW), 2)
                    self.assertFalse(o.exists(), 'no output -> discover gets no ledger -> no call')


class OperationalLoop(unittest.TestCase):
    """The full scheduled path on a COPY of the real inputs: ledger -> one simulated call ->
    secret-free publisher -> memory feeds the next cycle -> limits hold."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / 'repo'
        copy_sources(cls.root)
        cfg = cls.root / 'config/research-autonomy.json'
        conf = json.loads(cfg.read_text())
        conf['llm_live_enabled'] = True  # isolated fixture, repository remains disabled
        conf['llm_schedule_live_enabled'] = True  # cron path explicitly re-enabled in fixture
        cfg.write_text(json.dumps(conf))
        for rel in ('docs/research/demo/memory.jsonl', 'docs/research/demo/panel.json'):
            (cls.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, cls.root / rel)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def env(self, prior, **kw):
        from scripts.lab_research_cycle import SCHEDULE
        e = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
             'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
             'MASTER_BRAIN_LLM_API_KEY': 'not-a-real-key', 'GITHUB_RUN_ID': '999', 'RESEARCH_PRIOR_LLM_ATTEMPTS': str(prior)}
        e.update(kw)
        return e

    def discover(self, env, opener):
        """Mirror of the discover job: copy tracked memory to scratch, run llm-live."""
        from scripts.lab_research_cycle import main
        scratch = Path(self.tmp.name) / ('scratch-%d' % len(list(Path(self.tmp.name).glob('scratch-*'))))
        scratch.mkdir()
        tracked = self.root / 'data/research/memory.jsonl'
        if tracked.exists():
            shutil.copy2(tracked, scratch / 'memory.jsonl')
        code = main(['--root', str(self.root), '--mode', 'llm-live', '--allow-network',
                     '--memory', str(scratch / 'memory.jsonl'), '--panel', str(scratch / 'panel.json'),
                     '--budget', '0'], env=env, opener=opener, quota_factory=__import__('quota_fixtures').factory)
        return code, scratch / 'memory.jsonl'

    def test_full_operational_sequence(self):
        from h1lab.v6_llm_investigator import scientific_gate
        from scripts.lab_research_publish import publish
        sci_before = scientific_gate(self.root)
        chosen = []
        for k in range(2):
            sim = SimulatedLLMOpener()
            code, cand = self.discover(self.env(k), sim)
            self.assertEqual(code, 0)
            self.assertEqual(len(sim.calls), 1, 'exactly one (simulated) provider request per run')
            self.assertTrue(sim.calls[0]['url'].startswith('https://api.cloudflare.com/client/v4/accounts/'))
            summary = publish(self.root, cand, now=NOW)
            self.assertEqual(summary['llm_calls'], 1)
            mem = rm.read_memory(self.root / 'data/research/memory.jsonl')
            last = mem[-1]
            self.assertEqual((last['record_type'], last['llm_origin'], last['llm_calls']), ('CYCLE', 'LLM_LIVE', 1))
            exps = [r for r in mem if r['record_type'] == 'EXPERIMENT' and r['cycle_id'] == last['cycle_id']]
            self.assertTrue(exps, 'Python executed the hypotheses the model chose')
            for r in exps:
                self.assertEqual(r['origin'], 'LLM_LIVE')
                self.assertEqual(r['scientific_status'], 'EXPLORATORY_NOT_VALIDATED')
                self.assertIs(r['results']['promotion_eligible'], False)
            chosen.append({r['fingerprint'] for r in exps})
        self.assertFalse(chosen[0] & chosen[1], 'second cycle used memory to choose new hypotheses')
        panel = json.loads((self.root / 'docs/research/autonomous-research.json').read_text())
        self.assertEqual(panel['provenance']['kind'], 'OPERATIONAL')
        self.assertTrue(panel['provenance']['is_current_autonomous_research'])
        self.assertEqual(panel['provenance']['real_llm_calls'], 2)
        self.assertEqual(panel['validated'], [])
        self.assertEqual(sci_before, scientific_gate(self.root), 'scientific gate unchanged')

        # Limits: ledger at the day's limit (4; 5 only on 2026-11-05, real UTC clock because
        # llm-live forbids --now) -> refused, no request.
        from h1lab.research_daily_limit import daily_llm_attempt_limit
        at_limit = daily_llm_attempt_limit(datetime.now(timezone.utc).date().isoformat())
        mem_before = (self.root / 'data/research/memory.jsonl').read_bytes()
        for env in (self.env(at_limit), self.env(2, GITHUB_RUN_ATTEMPT='2'),
                    self.env(0, GITHUB_EVENT_NAME='workflow_dispatch'),
                    self.env(0, GITHUB_EVENT_NAME='workflow_dispatch', RESEARCH_LLM_CONFIRMATION='sim'),
                    self.env(0, GITHUB_REF='refs/heads/claude/x'),
                    {k: v for k, v in self.env(0).items() if k != 'GITHUB_RUN_ID'}):
            with self.subTest(env={k: env.get(k) for k in ('RESEARCH_PRIOR_LLM_ATTEMPTS', 'GITHUB_RUN_ATTEMPT',
                                                         'GITHUB_EVENT_NAME', 'GITHUB_REF')}):
                op = FakeOpener('{}')
                code, _ = self.discover(env, op)
                self.assertEqual(code, 2)
                self.assertEqual(op.calls, [], 'refused before any request')
        self.assertEqual(mem_before, (self.root / 'data/research/memory.jsonl').read_bytes())

        # A rerun of the publisher with an already-published candidate adds nothing.
        with self.assertRaisesRegex(ValueError, 'NOTHING_NEW'):
            publish(self.root, self.root / 'data/research/memory.jsonl', now=NOW)

    def test_invalid_model_reply_consumes_the_attempt_but_publishes_nothing(self):
        from scripts.lab_research_publish import publish
        tracked = self.root / 'data/research/memory.jsonl'
        before = tracked.read_bytes() if tracked.exists() else None
        op = FakeOpener('not json at all')
        code, cand = self.discover(self.env(0), op)
        self.assertEqual(code, 2)
        self.assertEqual(len(op.calls), 1, 'one request, no retry after a bad reply')
        # Scratch memory gained nothing, so the publisher has nothing to publish.
        with self.assertRaises((ValueError, OSError)):
            publish(self.root, cand, now=NOW)
        self.assertEqual(before, tracked.read_bytes() if tracked.exists() else None)
        # The ledger counts this run's started LLM step even though memory never saw it.
        runs = {'v6-llm-autonomous.yml': [_run(1, '2026-11-06T02:00:00Z')]}
        total, _ = budget.count_attempts(runs, {1: [{'steps': [_step(LIVE, 'failure')]}]},
                                         now=NOW, exclude_run_id=2)
        self.assertEqual(total, 1)

    def test_now_override_forbidden_in_live_mode(self):
        from scripts.lab_research_cycle import main
        op = FakeOpener('{}')
        with tempfile.TemporaryDirectory() as t:
            code = main(['--root', str(self.root), '--mode', 'llm-live', '--allow-network', '--now',
                         '2020-01-01T00:00:00+00:00', '--memory', str(Path(t) / 'm.jsonl'),
                         '--panel', str(Path(t) / 'p.json')], env=self.env(0), opener=op)
        self.assertEqual(code, 2)
        self.assertEqual(op.calls, [])


class PublisherRejects(unittest.TestCase):
    """The secret-free publisher refuses anything but one honest OPERATIONAL cycle."""

    def build(self, records, run_kind='OPERATIONAL', base=b''):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'm.jsonl'
            if base:
                p.write_bytes(base)
            rm.append(p, records, run_kind=run_kind)
            return p.read_bytes()

    def sci(self):
        from h1lab.research_gates import exploration_gate
        return exploration_gate(ROOT)['scientific_validation_gate']

    def exp(self, **kw):
        r = {'record_type': 'EXPERIMENT', 'origin': 'LLM_LIVE', 'scientific_status': 'EXPLORATORY_NOT_VALIDATED',
             'state': 'INCONCLUSIVE', 'promotion_eligible': False}
        r.update(kw)
        return r

    def cycle(self, **kw):
        c = {'record_type': 'CYCLE', 'cycle_id': 'Cx', 'llm_origin': 'LLM_LIVE', 'llm_calls': 1,
             'recorded_at': NOW.isoformat()}
        c.update(kw)
        return c

    def test_rejections(self):
        from scripts.lab_research_publish import verify_extension
        sci = self.sci()
        ok = self.build([self.exp(), self.cycle()])
        self.assertEqual(verify_extension(b'', ok, sci)['llm_calls'], 1)
        bad = {
            'validated claim': [self.exp(scientific_status='VALIDATED'), self.cycle()],
            'validated strategy state': [self.exp(state='VALIDATED_STRATEGY'), self.cycle()],
            'simulated origin': [self.exp(origin='SIMULATED_LLM'), self.cycle()],
            'response-file origin': [self.exp(origin='RESPONSE_FILE_NOT_LIVE_LLM'), self.cycle()],
            'two calls': [self.exp(), self.cycle(llm_calls=2)],
            'two cycles': [self.exp(), self.cycle(), self.cycle(cycle_id='Cy')],
            'simulated cycle': [self.exp(), self.cycle(llm_origin='SIMULATED_LLM')],
            'no cycle': [self.exp()],
            'unknown record': [{'record_type': 'NOTE'}, self.cycle()],
        }
        for name, recs in bad.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                verify_extension(b'', self.build(recs), sci)
        with self.assertRaises(ValueError):
            verify_extension(b'', self.build([self.exp(), self.cycle()], run_kind='DEMONSTRATION'), sci)
        demo = (ROOT / 'docs/research/demo/memory.jsonl').read_bytes()
        with self.assertRaises(ValueError):
            verify_extension(b'', demo, sci)


if __name__ == '__main__':
    unittest.main()

