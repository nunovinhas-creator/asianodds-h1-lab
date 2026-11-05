"""Pre-activation hardening: concurrency, crashes, provenance, LLM context, simulated
LLM proof, prepared workflow migration and isolation (offline; no provider calls)."""
import copy
import json
import multiprocessing
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_fixtures import LLM_PLAN, NOW, dataset, gate  # noqa: E402

from h1lab import research_memory as rm  # noqa: E402
from h1lab.research_cycle import build_panel, llm_packet, rank_offline, run_cycle  # noqa: E402
from h1lab.research_llm import invoke_once, parse_response  # noqa: E402
from h1lab.research_simulated_llm import SimulatedLLMOpener  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _has_yaml():
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


def _writer(path, n, tag, q):
    try:
        for i in range(n):
            rm.append(path, [{'record_type': 'NOTE', 'writer': tag, 'i': i}], run_kind='TEST')
        q.put(('ok', tag))
    except Exception as exc:  # pragma: no cover - reported to parent
        q.put(('err', repr(exc)))


class ConcurrentMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'mem.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_processes_appending_concurrently_keep_one_valid_chain(self):
        ctx = multiprocessing.get_context('fork')
        q = ctx.Queue()
        procs = [ctx.Process(target=_writer, args=(self.path, 25, t, q)) for t in ('A', 'B')]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        results = [q.get(timeout=5) for _ in procs]
        self.assertEqual(sorted(r[0] for r in results), ['ok', 'ok'], results)
        recs = rm.read_memory(self.path)
        self.assertEqual(len(recs), 50)
        self.assertEqual([r['seq'] for r in recs], list(range(1, 51)))
        self.assertEqual(sum(r['writer'] == 'A' for r in recs), 25)

    def test_stale_reader_cannot_append_lost_update(self):
        rm.append(self.path, [{'record_type': 'NOTE', 'x': 1}], run_kind='TEST')
        stale_tip = rm.tip(rm.read_memory(self.path))
        rm.append(self.path, [{'record_type': 'NOTE', 'x': 2}], run_kind='TEST')   # other cycle wins
        before = self.path.read_bytes()
        with self.assertRaises(rm.MemoryConflict):
            rm.append(self.path, [{'record_type': 'NOTE', 'x': 3}], run_kind='TEST', expected_tip=stale_tip)
        self.assertEqual(before, self.path.read_bytes())

    def test_cycle_detects_memory_changed_during_cycle(self):
        ds = dataset(effect=0.3)
        real = rm.read_memory

        def racing(path):
            out = real(path)
            if not getattr(racing, 'done', False):
                racing.done = True
                rm.append(path, [{'record_type': 'NOTE', 'by': 'other-process'}], run_kind='TEST')
            return out
        with mock.patch('h1lab.research_cycle.read_memory', racing):
            with self.assertRaises(rm.MemoryConflict):
                run_cycle(gate=gate(), dataset=ds, memory_path=self.path, now=NOW, run_kind='TEST',
                          offline_budget=3)
        self.assertEqual(len(rm.read_memory(self.path)), 1, 'only the other writer persisted')

    def test_lock_timeout_fails_instead_of_hanging(self):
        with rm._locked(self.path):
            pid = os.fork()
            if pid == 0:  # child: must give up within the bound
                try:
                    rm.append(self.path, [{'record_type': 'NOTE'}], run_kind='TEST', lock_timeout=0.2)
                    os._exit(3)
                except rm.MemoryError_ as exc:
                    os._exit(0 if 'LOCK_TIMEOUT' in str(exc) else 4)
            _, status = os.waitpid(pid, 0)
        self.assertEqual(os.WEXITSTATUS(status), 0)
        self.assertFalse(self.path.exists())

    def test_crash_during_write_leaves_previous_file_intact(self):
        rm.append(self.path, [{'record_type': 'NOTE', 'x': 1}], run_kind='TEST')
        before = self.path.read_bytes()
        with mock.patch('h1lab.research_memory.os.replace', side_effect=OSError('power loss')):
            with self.assertRaises(OSError):
                rm.append(self.path, [{'record_type': 'NOTE', 'x': 2}], run_kind='TEST')
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([p.name for p in self.path.parent.iterdir() if '.tmp-' in p.name], [])
        self.assertEqual(len(rm.read_memory(self.path)), 1)

    def test_torn_tail_detected_and_only_explicitly_recovered(self):
        rm.append(self.path, [{'record_type': 'NOTE', 'x': i} for i in range(3)], run_kind='TEST')
        with open(self.path, 'ab') as fh:              # foreign interrupted write
            fh.write(b'{"record_type": "NOTE", "seq": 4, "sha2')
        with self.assertRaises(rm.MemoryTornTail):
            rm.read_memory(self.path)
        with self.assertRaises(rm.MemoryTornTail):     # writers refuse too
            rm.append(self.path, [{'record_type': 'NOTE'}], run_kind='TEST')
        rep = rm.recover_torn_tail(self.path)
        self.assertEqual(rep['status'], 'TORN_TAIL_QUARANTINED')
        self.assertEqual(rep['records'], 3)
        self.assertTrue((self.path.parent / rep['quarantine']).read_bytes().startswith(b'{"record_type"'))
        self.assertEqual(len(rm.read_memory(self.path)), 3)

    def test_mid_file_corruption_is_never_repaired(self):
        rm.append(self.path, [{'record_type': 'NOTE', 'x': i} for i in range(3)], run_kind='TEST')
        lines = self.path.read_bytes().split(b'\n')
        lines[1] = lines[1][:-5] + b'oops}'
        self.path.write_bytes(b'\n'.join(lines)[:-3])  # also torn
        with self.assertRaises(rm.MemoryError_):
            rm.recover_torn_tail(self.path)

    def test_run_kinds_never_mix_in_one_file(self):
        rm.append(self.path, [{'record_type': 'NOTE'}], run_kind='DEMONSTRATION')
        with self.assertRaises(rm.MemoryError_):
            rm.append(self.path, [{'record_type': 'NOTE'}], run_kind='OPERATIONAL')
        res = run_cycle(gate=gate(), dataset=dataset(), memory_path=self.path, now=NOW, run_kind='OPERATIONAL')
        self.assertEqual(res['reason'], 'MEMORY_RUN_KIND_MISMATCH')


class Provenance(unittest.TestCase):
    def test_operational_memory_refuses_simulated_or_file_hypotheses(self):
        with tempfile.TemporaryDirectory() as t:
            plans = parse_response(json.dumps({'schema_version': 1, 'experiments': [LLM_PLAN]}))
            for origin in ('SIMULATED_LLM', 'RESPONSE_FILE_NOT_LIVE_LLM', 'LLM_FAKE', None):
                with self.subTest(origin=origin), self.assertRaises(ValueError):
                    run_cycle(gate=gate(), dataset=dataset(), memory_path=Path(t) / 'm.jsonl', now=NOW,
                              run_kind='OPERATIONAL', llm=dict(plans, origin=origin))
            self.assertFalse((Path(t) / 'm.jsonl').exists())
            with self.assertRaises(ValueError):
                run_cycle(gate=gate(), dataset=dataset(), memory_path=Path(t) / 'd.jsonl', now=NOW,
                          run_kind='DEMONSTRATION', llm=dict(plans, origin='LLM_LIVE'))

    def test_demo_panel_is_labelled(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'm.jsonl'
            plans = parse_response(json.dumps({'schema_version': 1, 'experiments': [LLM_PLAN]}))
            run_cycle(gate=gate(), dataset=dataset(), memory_path=path, now=NOW, run_kind='DEMONSTRATION',
                      llm=dict(plans, origin='SIMULATED_LLM', llm_calls=0), offline_budget=1)
            p = build_panel(rm.read_memory(path), gate(), now=NOW)['provenance']
        self.assertEqual(p['kind'], 'DEMONSTRATION')
        self.assertIn('DEMONSTRAÇÃO', p['note'])
        self.assertEqual(p['real_llm_calls'], 0)
        self.assertFalse(p['is_current_autonomous_research'])
        self.assertEqual(p['reference_time'], NOW.isoformat())
        self.assertIn('SIMULATED_LLM', p['cycle_origins'])

    def test_tracked_demo_and_operational_files_never_mix(self):
        """Before the first real cycle the operational files are absent; after it (on main)
        they must be a valid OPERATIONAL chain with nothing validated and real calls <= 1/cycle."""
        mem_path = ROOT / 'data/research/memory.jsonl'
        panel_path = ROOT / 'docs/research/autonomous-research.json'
        self.assertEqual(mem_path.exists(), panel_path.exists(), 'memory and panel are published together')
        if mem_path.exists():
            op = rm.read_memory(mem_path)            # strict hash chain
            self.assertEqual(rm.memory_kind(op), 'OPERATIONAL')
            for r in op:
                self.assertIn(r.get('scientific_status'), (None, 'EXPLORATORY_NOT_VALIDATED'))
                if r['record_type'] == 'CYCLE':
                    self.assertLessEqual(r.get('llm_calls', 0), 1)
                    self.assertIn(r.get('llm_origin'), (None, 'LLM_LIVE'))
                if r['record_type'] == 'EXPERIMENT':
                    self.assertIn(r['origin'], ('LLM_LIVE', 'OFFLINE_PROPOSER'))
                    self.assertFalse(r.get('results', {}).get('promotion_eligible', False))
            op_panel = json.loads(panel_path.read_text())
            self.assertEqual(op_panel['provenance']['kind'], 'OPERATIONAL')
            self.assertEqual(op_panel['validated'], [])
        demo = rm.read_memory(ROOT / 'docs/research/demo/memory.jsonl')
        self.assertEqual(rm.memory_kind(demo), 'DEMONSTRATION')
        panel = json.loads((ROOT / 'docs/research/demo/panel.json').read_text())
        self.assertEqual(panel['provenance']['kind'], 'DEMONSTRATION')
        self.assertEqual(panel['provenance']['real_llm_calls'], 0)
        self.assertTrue(all(c.get('llm_calls', 0) == 0 for c in demo if c['record_type'] == 'CYCLE'))


class TrajectoryContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from h1lab.research_dataset import build_dataset
        from h1lab.research_gates import exploration_gate
        cls.gate = exploration_gate(ROOT)
        cls.ds = build_dataset(ROOT, now=datetime.now(timezone.utc))

    def test_real_examples_bounded_pseudonymised_outcome_free(self):
        from h1lab.research_context import MAX_BYTES, MAX_EXAMPLES, MAX_MESSAGES, trajectory_examples
        te = trajectory_examples(self.ds, self.gate['source_sha256'])
        self.assertTrue(1 <= len(te['examples']) <= MAX_EXAMPLES)
        raw = json.dumps(te['examples'], ensure_ascii=False)
        self.assertLessEqual(len(raw.encode()), MAX_BYTES)
        keys = {r['match_key'] for r in self.ds['rows']}
        for ex in te['examples']:
            self.assertLessEqual(len(ex['messages']), MAX_MESSAGES)
            self.assertNotIn(ex['ref'], keys)
            for m in ex['messages']:
                self.assertGreater(m['minutes_to_kickoff'], 0, 'pre-kickoff only')
                self.assertFalse({'score', 'outcome', 'ft_status', 'home', 'away', 'event_id'} & set(m))
        for forbidden in ('"score"', '"outcome"', 'ft_status', '2026-1', 'VERIFIED_FT'):
            self.assertNotIn(forbidden, raw)
        self.assertTrue(te['source_files_sha256'])

    def test_example_selection_ignores_outcomes(self):
        from h1lab.research_context import trajectory_examples
        a = trajectory_examples(self.ds)['examples']
        ds = copy.deepcopy(self.ds)
        for r in ds['rows']:
            r['outcome'], r['ft_status'] = None, 'PENDING'
        self.assertEqual(a, trajectory_examples(ds)['examples'])

    def test_packet_within_limits_with_examples(self):
        from h1lab.research_llm import PACKET_BUDGET_BYTES
        p = llm_packet(self.gate, self.ds, [])
        self.assertTrue(p['trajectory_examples']['examples'])
        self.assertLessEqual(len(json.dumps(p, ensure_ascii=False).encode()), PACKET_BUDGET_BYTES + 200)


class SimulatedLLMProof(unittest.TestCase):
    """SIMULATED LLM: plans come from the packet through the real request path."""

    def test_executor_runs_what_the_model_chose_and_memory_feeds_back(self):
        ds = dataset(effect=0.25)
        g = gate()
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'm.jsonl'
            fixtures = {json.dumps(LLM_PLAN['condition'], sort_keys=True)}
            offline = {p['fingerprint'] for p, _, _ in rank_offline(ds['rows'], [], ds['digest'], 200)}
            chosen_by_cycle = []
            for k in range(2):
                packet = llm_packet(g, ds, rm.read_memory(path))
                sim = SimulatedLLMOpener()
                reply = invoke_once(packet, endpoint='https://simulated-llm.invalid/v1', model='SIM', opener=sim)
                self.assertEqual(len(sim.calls), 1)
                llm = parse_response(reply['content'])
                self.assertEqual(llm['rejected'], [])
                model_fps = [p['fingerprint'] for p in llm['plans']]
                llm.update(origin='SIMULATED_LLM', llm_calls=0)
                run_cycle(gate=g, dataset=ds, memory_path=path, now=NOW + timedelta(hours=k), run_kind='TEST',
                          llm=llm, offline_budget=0)
                exps = [r for r in rm.read_memory(path) if r['record_type'] == 'EXPERIMENT'
                        and r['cycle_id'] == rm.read_memory(path)[-1]['cycle_id']]
                self.assertEqual([r['fingerprint'] for r in exps], model_fps, 'Python ran exactly the model plans')
                for r in exps:
                    self.assertEqual(r['origin'], 'SIMULATED_LLM')
                    self.assertNotIn(r['fingerprint'], offline, 'not an offline-proposer plan')
                    self.assertNotIn(json.dumps(r['plan']['condition'], sort_keys=True), fixtures)
                    self.assertTrue(r['plan']['indicators'], 'model defined its own indicator')
                chosen_by_cycle.append(set(model_fps))
            # Second cycle saw the first cycle in memory and chose different pairs.
            self.assertFalse(chosen_by_cycle[0] & chosen_by_cycle[1])

    def test_cli_simulated_mode_on_real_data(self):
        from scripts.lab_research_cycle import main
        with tempfile.TemporaryDirectory() as t:
            mem, panel = Path(t) / 'm.jsonl', Path(t) / 'p.json'
            self.assertEqual(main(['--mode', 'llm-simulated', '--run-kind', 'TEST', '--memory', str(mem),
                                   '--panel', str(panel), '--budget', '0'], env={}), 0)
            recs = rm.read_memory(mem)
            exps = [r for r in recs if r['record_type'] == 'EXPERIMENT']
            self.assertTrue(exps)
            self.assertTrue(all(r['origin'] == 'SIMULATED_LLM' for r in exps))
            self.assertEqual(recs[-1]['llm_calls'], 0)
            self.assertEqual(json.loads(panel.read_text())['provenance']['kind'], 'TEST')
            # simulated/file modes are refused for operational memory
            self.assertEqual(main(['--mode', 'llm-simulated', '--memory', str(Path(t) / 'o.jsonl'),
                                   '--panel', str(panel)], env={}), 2)


class LiveMigration(unittest.TestCase):
    def test_live_authorisation_mirrors_old_workflow(self):
        from scripts.lab_research_cycle import SCHEDULE, live_authorisation
        ok = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
              'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'GITHUB_RUN_ID': '999', 'RESEARCH_PRIOR_LLM_ATTEMPTS': '0'}
        self.assertEqual(live_authorisation(ok, [], '2026-11-04'), 'schedule')
        for change in ({'GITHUB_REF': 'refs/heads/x'}, {'GITHUB_RUN_ATTEMPT': '2'},
                       {'GITHUB_EVENT_SCHEDULE': '* * * * *'}, {'GITHUB_EVENT_NAME': 'push'},
                       {'GITHUB_EVENT_NAME': 'workflow_dispatch'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                live_authorisation(dict(ok, **change), [], '2026-11-04')
        used = [{'record_type': 'CYCLE', 'llm_origin': 'LLM_LIVE', 'llm_calls': 1,
                 'recorded_at': '2026-11-04T%02d:43:00+00:00' % h} for h in (1, 7, 13, 19)]
        self.assertEqual(live_authorisation(ok, used, '2026-11-04'), 'schedule')
        self.assertEqual(live_authorisation(ok, used, '2026-11-05'), 'schedule')

    def test_event_authorisation_does_not_trust_old_environment_counter(self):
        from scripts.lab_research_cycle import SCHEDULE, live_authorisation
        ok = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
              'GITHUB_EVENT_SCHEDULE': SCHEDULE}
        for value in ('', '-1', '4', '9999'):
            self.assertEqual(live_authorisation(dict(ok, RESEARCH_PRIOR_LLM_ATTEMPTS=value), [], '2026-11-04'),
                             'schedule')
        # This checks event authorization only. Controller.reserve is mandatory in llm-live;
        # durable admission and failure injection are exercised in test_research_quota.

    def test_live_mode_one_call_into_scratch_memory_when_enabled(self):
        """Full llm-live path with config enabled on a COPY of the repo inputs; simulated opener."""
        import shutil
        from scripts.lab_research_cycle import SCHEDULE, main
        from test_research_gates import copy_sources
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / 'repo'
            copy_sources(root)
            cfg = root / 'config/research-autonomy.json'
            c = json.loads(cfg.read_text())
            c['llm_live_enabled'] = True
            c['llm_schedule_live_enabled'] = True  # cron path explicitly re-enabled in fixture
            cfg.write_text(json.dumps(c))
            sim = SimulatedLLMOpener()
            env = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
                   'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
                   'MASTER_BRAIN_LLM_API_KEY': 'not-a-real-key', 'GITHUB_RUN_ID': '999', 'RESEARCH_PRIOR_LLM_ATTEMPTS': '0'}
            mem, panel = Path(t) / 'scratch.jsonl', Path(t) / 'panel.json'
            code = main(['--root', str(root), '--mode', 'llm-live', '--allow-network', '--memory', str(mem),
                         '--panel', str(panel), '--budget', '0'], env=env, opener=sim, quota_factory=__import__('quota_fixtures').factory)
            self.assertEqual(code, 0)
            self.assertEqual(len(sim.calls), 1)
            self.assertTrue(sim.calls[0]['url'].startswith('https://api.cloudflare.com/'))
            # The publisher accepts this as a strict extension of an empty operational memory...
            from scripts.lab_research_publish import verify_extension
            from h1lab.research_gates import exploration_gate
            sci = exploration_gate(root)['scientific_validation_gate']
            summary = verify_extension(b'', mem.read_bytes(), sci)
            self.assertEqual(summary['llm_calls'], 1)
            # ...and rejects rewrites, demo content and torn candidates.
            with self.assertRaises(ValueError):
                verify_extension(mem.read_bytes()[:-10] + b'x' * 10, mem.read_bytes(), sci)
            with self.assertRaises(ValueError):
                verify_extension(b'', mem.read_bytes()[:-1], sci)
            with self.assertRaises(ValueError):
                verify_extension(mem.read_bytes(), mem.read_bytes(), sci)
            shutil.rmtree(root)

    def test_migrated_workflow_is_the_single_active_llm_schedule(self):
        """The prepared file replaced the old one in place (not added next to it)."""
        wf_path = ROOT / '.github/workflows/v6-llm-autonomous.yml'
        self.assertFalse((ROOT / '.github/proposed-workflows/v6-llm-autonomous.research.yml').exists(),
                         'prepared copy removed: no second source of truth')
        self.assertFalse((ROOT / '.github/workflows/v6-llm-autonomous.research.yml').exists())
        text = wf_path.read_text()
        self.assertIn('python -m scripts.lab_research_cycle --mode llm-live --allow-network', text)
        self.assertNotIn('scripts.lab_v6_llm_autonomous', text, 'retired candidate-pool path no longer wired')
        self.assertNotIn('|| true', text)
        self.assertNotIn('continue-on-error', text)
        live = [w.name for w in (ROOT / '.github/workflows').glob('*.y*ml')
                if 'lab_research_cycle --mode llm-live' in w.read_text()]
        self.assertEqual(live, ['v6-llm-autonomous.yml'])
        self.assertFalse(json.loads((ROOT / 'config/research-autonomy.json').read_text())['llm_live_enabled'])

    @unittest.skipIf(os.environ.get('RESEARCH_PREFLIGHT') == '1' and not _has_yaml(),
                     'pre-call preflight in the secret job has no PyYAML; enforced by PR CI')
    def test_migrated_workflow_structure_keeps_slots_group_and_secret_split(self):
        import yaml
        wf = yaml.safe_load((ROOT / '.github/workflows/v6-llm-autonomous.yml').read_text())
        on = wf.get('on', wf.get(True))
        self.assertEqual(on['schedule'], [{'cron': '43 1,7,13,19 * * *'}])
        self.assertEqual(wf['concurrency'], {'group': 'v6-llm-global', 'cancel-in-progress': False})
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        jobs = wf['jobs']
        self.assertEqual(set(jobs), {'discover', 'publish'})
        # Secrets: only the single live step of discover.
        for name, job in jobs.items():
            for i, step in enumerate(job['steps']):
                has = 'secrets.' in yaml.dump(step)
                is_live = name == 'discover' and 'LLM call' in step.get('name', '')
                with self.subTest(job=name, step=i):
                    self.assertEqual(has, is_live)
        self.assertNotIn('secrets.', yaml.dump(jobs['publish']), 'publisher holds no LLM secrets')
        self.assertEqual(jobs['discover']['permissions'], {'contents': 'write', 'actions': 'read'})
        self.assertEqual(jobs['publish']['permissions'], {'contents': 'write'})
        self.assertEqual(jobs['publish']['needs'], 'discover')
        self.assertLessEqual(jobs['discover']['timeout-minutes'], 10)
        # The ledger feeds the live step; exactly one live step, one invocation.
        live = [s for s in jobs['discover']['steps'] if 'LLM call' in s.get('name', '')]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]['env']['GH_TOKEN'], '${{ github.token }}')
        self.assertEqual(live[0]['run'].count('lab_research_cycle'), 1)
        # Checkouts: secret job never persists a token; both use the branch tip after the lock.
        co = [s for s in jobs['discover']['steps'] if str(s.get('uses', '')).startswith('actions/checkout')]
        self.assertEqual(co[0]['with']['persist-credentials'], False)
        self.assertEqual(co[0]['with']['ref'], '${{ github.ref }}')
        # Publisher stages exactly the two operational files.
        pub = '\n'.join(s.get('run', '') for s in jobs['publish']['steps'])
        adds = re.findall(r'^\s*git add (.+)$', pub, re.M)
        self.assertEqual(adds, ['data/research/memory.jsonl docs/research/autonomous-research.json'])
        self.assertIn("github.ref == 'refs/heads/main'", jobs['publish']['if'])


class Ownership(unittest.TestCase):
    def test_research_paths_have_exactly_one_owner_kept_by_all_publishers(self):
        from scripts import publication_ownership as own
        self.assertEqual(own.owner_of('data/research/memory.jsonl'), own.LLM)
        self.assertEqual(own.owner_of('docs/research/autonomous-research.json'), own.LLM)
        for name in ('memory.jsonl', 'panel.json', 'hand-authored-response-2026-11-05.json'):
            self.assertEqual(own.owner_of('docs/research/demo/' + name), own.SITE)
        self.assertIsNone(own.owner_of('data/research/other.jsonl'), 'no blanket ownership')
        from scripts import collect_publish_safe, lab_v4_publish_safe
        for keep in (collect_publish_safe.KEEP_OWNERS, lab_v4_publish_safe.KEEP_OWNERS):
            self.assertIn(own.LLM, keep)
            self.assertIn(own.SITE, keep)


class Isolation(unittest.TestCase):
    def test_no_existing_module_imports_research_and_cycle_keeps_tree(self):
        from scripts.research_isolation_check import cycle_leaves_tree_intact, foreign_imports
        self.assertEqual(foreign_imports(), [])
        r = cycle_leaves_tree_intact()
        self.assertTrue(r['tracked_files_unchanged'])
        self.assertTrue(r['scientific_gate_unchanged'])


if __name__ == '__main__':
    unittest.main()

