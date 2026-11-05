"""PR D - append-only memory, outcome-blind agenda, end-to-end cycle and panel."""
import copy
import hashlib
import json
import random
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from h1lab.research_cycle import build_panel, llm_packet, rank_offline, run_cycle
from h1lab.research_llm import invoke_once, parse_response
from h1lab.research_memory import MemoryError_, append, novelty, read_memory
from h1lab.research_plan import validate_plan
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_fixtures import LLM_PLAN, NOW, FakeOpener, dataset, gate

ROOT = Path(__file__).resolve().parents[1]


def protected_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for top in ('data', 'docs/lab') for p in sorted((ROOT / top).rglob('*')) if p.is_file()}


class Memory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'mem.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def test_chain_and_tamper_detection(self):
        append(self.path, [{'record_type': 'NOTE', 'x': i} for i in range(3)])
        append(self.path, [{'record_type': 'NOTE', 'x': 3}])
        self.assertEqual([r['seq'] for r in read_memory(self.path)], [1, 2, 3, 4])
        lines = self.path.read_text().splitlines()
        for mutate in (lambda l: [l[0], l[2], l[1], l[3]],                   # reorder
                       lambda l: l[:1] + l[2:],                               # delete
                       lambda l: [l[0].replace('"x": 0', '"x": 9')] + l[1:]):  # edit
            self.path.write_text('\n'.join(mutate(list(lines))) + '\n')
            with self.assertRaises(MemoryError_):
                read_memory(self.path)
        self.path.write_text('\n'.join(lines) + '\n')
        self.assertEqual(len(read_memory(self.path)), 4)

    def test_record_size_bound(self):
        with self.assertRaises(MemoryError_):
            append(self.path, [{'record_type': 'NOTE', 'blob': 'x' * 70000}])
        self.assertFalse(self.path.exists())


class EndToEnd(unittest.TestCase):
    """LLM proposes -> plan validated -> Python executes -> memory -> next cycle uses it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / 'research' / 'memory.jsonl'
        self.ds = dataset(effect=0.3)
        self.g = gate()   # exploration allowed, science SCIENTIFICALLY_BLOCKED (BELOW_99_PERCENT)

    def tearDown(self):
        self.tmp.cleanup()

    def llm_cycle(self, plan_json, now):
        packet = llm_packet(self.g, self.ds, read_memory(self.mem))
        opener = FakeOpener(json.dumps({'schema_version': 1, 'experiments': plan_json,
                                        'new_questions': ['E se o AH se mover contra o Total?']}))
        reply = invoke_once(packet, endpoint='https://llm.invalid/v1', model='fake', opener=opener)
        llm = parse_response(reply['content'])
        llm.update(origin='LLM_FAKE', llm_calls=reply['llm_calls'], packet_sha256=packet['packet_sha256'])
        res = run_cycle(gate=self.g, dataset=self.ds, memory_path=self.mem, now=now,
                        cycle_label='e2e', llm=llm, offline_budget=0)
        return packet, opener, res

    def test_full_loop(self):
        before = protected_hashes()
        bad = dict(LLM_PLAN, outcome='CORNERS_OVER')
        packet, opener, res = self.llm_cycle([LLM_PLAN, bad], NOW)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(res['status'], 'RUN')
        self.assertEqual(res['experiments'], 1)
        self.assertEqual(res['rejected_plans'], 1)
        mem = read_memory(self.mem)
        exp = [r for r in mem if r['record_type'] == 'EXPERIMENT'][0]
        # memory holds hypothesis, test, result and limitations
        self.assertEqual(exp['origin'], 'LLM_FAKE')
        self.assertEqual(exp['plan']['indicators'][0]['name'], 'X_STRONG_LAMBDA_RISE')
        self.assertIn('lambda_net', exp['variables'])
        self.assertEqual(exp['data']['dataset_sha256'], self.ds['digest'])
        self.assertIn('p_value', exp['results'])
        self.assertIsInstance(exp['limitations'], list)
        self.assertEqual(exp['state'], 'PROMISING_EXPLORATORY')
        self.assertEqual(exp['scientific_status'], 'EXPLORATORY_NOT_VALIDATED')
        self.assertTrue(exp['next_question'])
        self.assertTrue(any(r['record_type'] == 'PLAN_REJECTED' for r in mem))
        cyc = [r for r in mem if r['record_type'] == 'CYCLE'][0]
        self.assertEqual(cyc['llm_calls'], 1)
        self.assertEqual(cyc['scientific_validation_gate'], 'SCIENTIFICALLY_BLOCKED')
        # a later cycle reads that memory
        packet2 = llm_packet(self.g, self.ds, read_memory(self.mem))
        self.assertEqual(packet2['memory'][0]['experiment_id'], exp['experiment_id'])
        self.assertTrue(any(a['kind'] == 'NEEDS_PREREGISTRATION' for a in packet2['agenda']))
        _, _, res2 = self.llm_cycle([LLM_PLAN], NOW + timedelta(hours=6))
        self.assertEqual(res2['experiments'], 0, 'same question + same data is not repeated')
        last = read_memory(self.mem)[-1]
        self.assertEqual(last['duplicates_skipped'], 1)
        # with new data the same hypothesis is re-tested as a new version
        self.ds = dataset(effect=0.3, n=640)
        _, _, res3 = self.llm_cycle([LLM_PLAN], NOW + timedelta(hours=12))
        self.assertEqual(res3['experiments'], 1)
        v2 = [r for r in read_memory(self.mem) if r['record_type'] == 'EXPERIMENT'][-1]
        self.assertEqual(v2['version'], 2)
        self.assertEqual(v2['novelty'], 'RETEST_NEW_DATA')
        self.assertIn(exp['experiment_id'], v2['related_to'])
        # panel: discovered but never validated
        panel = build_panel(read_memory(self.mem), self.g, now=NOW)
        self.assertEqual(panel['validated'], [])
        self.assertEqual(len(panel['discovered']), 1)
        self.assertNotIn('"VALIDATED"', json.dumps(panel))
        self.assertEqual(before, protected_hashes(), 'production data untouched')

    def test_offline_cycle_many_experiments_zero_llm_calls(self):
        res = run_cycle(gate=self.g, dataset=self.ds, memory_path=self.mem, now=NOW, offline_budget=25)
        self.assertGreater(res['experiments'], 10)
        cyc = read_memory(self.mem)[-1]
        self.assertEqual(cyc['llm_calls'], 0)
        res2 = run_cycle(gate=self.g, dataset=self.ds, memory_path=self.mem, now=NOW + timedelta(hours=1),
                         offline_budget=25)
        fps = [r['fingerprint'] for r in read_memory(self.mem) if r['record_type'] == 'EXPERIMENT']
        self.assertEqual(len(fps), len(set(fps)), 'memory prevents repeats')
        self.assertEqual(res2['memory_records_before'], res['written'])

    def test_disabled_offline_cycle_writes_nothing(self):
        res = run_cycle(gate=gate(offline_cycle_enabled=False), dataset=self.ds, memory_path=self.mem, now=NOW)
        self.assertEqual(res['status'], 'NOT_RUN')
        self.assertFalse(self.mem.exists())

    def test_blocked_ft_operation_refuses_cycle(self):
        g = gate()
        g['allowed_operations'] = [o for o in g['allowed_operations'] if o != 'ft_outcomes']
        res = run_cycle(gate=g, dataset=self.ds, memory_path=self.mem, now=NOW)
        self.assertEqual(res, {'status': 'NOT_RUN', 'reason': 'FT_OUTCOMES_BLOCKED', 'experiments': 0, 'written': 0})
        self.assertFalse(self.mem.exists())

    def test_ranking_is_outcome_blind(self):
        a = [p['fingerprint'] for p, _, _ in rank_offline(self.ds['rows'], [], self.ds['digest'], 20)]
        shuffled = copy.deepcopy(self.ds['rows'])
        outs = [r['outcome'] for r in shuffled]
        random.Random(5).shuffle(outs)
        for r, o in zip(shuffled, outs):
            r['outcome'] = o if r['ft_status'] == 'VERIFIED_FT' and o is not None else r['outcome']
        b = [p['fingerprint'] for p, _, _ in rank_offline(shuffled, [], self.ds['digest'], 20)]
        self.assertEqual(a, b)

    def test_novelty_grades(self):
        p = validate_plan(copy.deepcopy(LLM_PLAN))
        self.assertEqual(novelty(p, [], 'd')['grade'], 'NEW')


class CLI(unittest.TestCase):
    def test_live_mode_refused_by_default_and_offline_runs_on_real_data(self):
        from scripts.lab_research_cycle import main
        with tempfile.TemporaryDirectory() as t:
            mem, panel = Path(t) / 'm.jsonl', Path(t) / 'p.json'
            opener = FakeOpener('{}')
            code = main(['--mode', 'llm-live', '--allow-network', '--memory', str(mem), '--panel', str(panel)],
                        env={'RESEARCH_LLM_CONFIRMATION': 'INVESTIGAR_UMA_VEZ',
                             'CLOUDFLARE_ACCOUNT_ID': 'a' * 32, 'MASTER_BRAIN_LLM_API_KEY': 'k'},
                        opener=opener)
            self.assertEqual(code, 2)
            self.assertEqual(opener.calls, [])
            self.assertFalse(mem.exists())
            before = protected_hashes()
            self.assertEqual(main(['--memory', str(mem), '--panel', str(panel), '--budget', '6'], env={}), 0)
            recs = read_memory(mem)
            self.assertEqual(sum(r['record_type'] == 'EXPERIMENT' for r in recs), 6)
            p = json.loads(panel.read_text())
            self.assertEqual(p['validated'], [])
            self.assertEqual(p['gates']['exploration'], 'EXPLORATION_ALLOWED')
            self.assertEqual(before, protected_hashes())

    def test_env_kill_switch(self):
        from scripts.lab_research_cycle import main
        with tempfile.TemporaryDirectory() as t:
            mem = Path(t) / 'm.jsonl'
            self.assertEqual(main(['--memory', str(mem), '--panel', str(Path(t) / 'p.json')],
                                 env={'MASTER_BRAIN_EXPLORATION': 'off'}), 0)
            self.assertFalse(mem.exists())


if __name__ == '__main__':
    unittest.main()
