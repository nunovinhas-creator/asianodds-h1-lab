"""PR A - EXPLORATION_GATE vs SCIENTIFIC_VALIDATION_GATE (no network, no writes)."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from h1lab import v6_llm_investigator as investigator
from h1lab.research_gates import (EXPLORATION_ALLOWED, EXPLORATION_BLOCKED, EXPLORATION_DISABLED,
                                  PromotionForbidden, exploration_gate, load_config,
                                  promotion_guard, scientific_validation_gate)

ROOT = Path(__file__).resolve().parents[1]


def tree_hash(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for top in ('data', 'docs/lab', 'config') for p in sorted((root / top).rglob('*'))
            if p.is_file()}


def copy_sources(dst):
    """Minimal copy of the real inputs the gates read."""
    for rel in ['data/state.json', 'data/lab/ft-ledger.json', 'config/research-autonomy.json',
                *investigator.SOURCES]:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst / rel)
    for pat in ('markets-*.jsonl', 'v6-ft-events-*.jsonl'):
        for p in (ROOT / 'data/lab').glob(pat):
            shutil.copy2(p, dst / 'data/lab' / p.name)


class RealRepositoryGates(unittest.TestCase):
    def test_exploration_allowed_while_science_blocked_below_99(self):
        before = tree_hash(ROOT)
        g = exploration_gate(ROOT, env={})
        self.assertEqual(g['state'], EXPLORATION_ALLOWED)
        self.assertIn('odds_trajectories', g['allowed_operations'])
        sci = g['scientific_validation_gate']
        # Science is still governed by the existing gate and is NOT relaxed.
        gates = json.loads((ROOT / 'docs/lab/v6-p0-gates.json').read_text())['gates']
        if any(v['status'] in investigator.SCIENTIFICALLY_BLOCKED_GATE_STATES for v in gates.values()):
            self.assertEqual(sci['state'], 'SCIENTIFICALLY_BLOCKED')
            self.assertTrue(any('BELOW_99' in x or 'SCIENTIFICALLY_BLOCKED' in x for x in g['limitations']))
        self.assertFalse(sci['promotion_allowed'])
        self.assertEqual(before, tree_hash(ROOT), 'gates must never write')

    def test_existing_scientific_path_still_blocks(self):
        # build_packet (old autonomous path) keeps its contract untouched.
        state = investigator.scientific_gate(ROOT)['state']
        if state == 'SCIENTIFICALLY_BLOCKED':
            with self.assertRaises(investigator.ScientificGateBlocked):
                investigator.build_packet(ROOT)
        self.assertFalse(scientific_validation_gate(ROOT)['promotion_allowed'])


class SyntheticCorruption(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        copy_sources(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def markets(self):
        return sorted((self.root / 'data/lab').glob('markets-*.jsonl'))[0]

    def test_copy_is_allowed(self):
        self.assertEqual(exploration_gate(self.root, env={})['state'], EXPLORATION_ALLOWED)

    def test_corrupt_jsonl_blocks_trajectories(self):
        with open(self.markets(), 'a') as fh:
            fh.write('{not json\n')
        g = exploration_gate(self.root, env={})
        self.assertEqual(g['state'], EXPLORATION_BLOCKED)
        self.assertIn('odds_trajectories', g['blocked_operations'])
        self.assertIn('CORRUPT_JSONL_LINE', {p['code'] for p in g['problems']})

    def test_missing_provenance_blocks(self):
        with open(self.markets(), 'a') as fh:
            fh.write(json.dumps({'observed_at': '2026-11-01T00:00:00+00:00'}) + '\n')
        g = exploration_gate(self.root, env={})
        self.assertEqual(g['state'], EXPLORATION_BLOCKED)
        self.assertIn('MISSING_PROVENANCE_ID', {p['code'] for p in g['problems']})

    def test_duplicate_id_blocks(self):
        first = self.markets().read_text().splitlines()[0]
        with open(self.markets(), 'a') as fh:
            fh.write(first + '\n')
        self.assertEqual(exploration_gate(self.root, env={})['state'], EXPLORATION_BLOCKED)

    def test_corrupt_ft_blocks_only_ft_operation(self):
        p = sorted((self.root / 'data/lab').glob('v6-ft-events-*.jsonl'))[0]
        with open(p, 'a') as fh:
            fh.write('garbage\n')
        g = exploration_gate(self.root, env={})
        self.assertIn('ft_outcomes', g['blocked_operations'])
        self.assertNotIn('odds_trajectories', g['blocked_operations'])

    def test_missing_state_blocks(self):
        (self.root / 'data/state.json').unlink()
        self.assertEqual(exploration_gate(self.root, env={})['state'], EXPLORATION_BLOCKED)

    def test_corrupt_scientific_source_is_reported_not_hidden(self):
        (self.root / investigator.SOURCES[0]).write_text('{bad')
        g = exploration_gate(self.root, env={})
        self.assertEqual(g['scientific_validation_gate']['state'], 'SCIENTIFIC_SOURCES_INVALID')
        self.assertIn('scientific_context', g['blocked_operations'])
        self.assertFalse(g['scientific_validation_gate']['promotion_allowed'])

    def test_kill_switch_config_and_env(self):
        self.assertEqual(exploration_gate(self.root, env={'MASTER_BRAIN_EXPLORATION': 'off'})['state'],
                         EXPLORATION_DISABLED)
        cfg = self.root / 'config/research-autonomy.json'
        data = json.loads(cfg.read_text())
        data['exploration_enabled'] = False
        cfg.write_text(json.dumps(data))
        self.assertEqual(exploration_gate(self.root, env={})['state'], EXPLORATION_DISABLED)

    def test_missing_or_corrupt_config_fails_safe(self):
        cfg = self.root / 'config/research-autonomy.json'
        cfg.write_text('{oops')
        self.assertFalse(load_config(self.root, env={})['exploration_enabled'])
        cfg.unlink()
        self.assertEqual(exploration_gate(self.root, env={})['state'], EXPLORATION_DISABLED)

    def test_config_cannot_raise_llm_budget(self):
        cfg = self.root / 'config/research-autonomy.json'
        data = json.loads(cfg.read_text())
        data.update(max_llm_calls_per_cycle=50, max_llm_plans_per_call=99, max_experiments_per_cycle=10 ** 6)
        cfg.write_text(json.dumps(data))
        c = load_config(self.root, env={})
        self.assertEqual(c['max_llm_calls_per_cycle'], 1)
        self.assertEqual(c['max_llm_plans_per_call'], 3)
        self.assertEqual(c['max_experiments_per_cycle'], 200)


class PromotionGuard(unittest.TestCase):
    def test_exploratory_never_validated(self):
        blocked = {'state': 'SCIENTIFICALLY_BLOCKED', 'promotion_allowed': False}
        authorised_but_closed = {'state': 'AUTHORISED', 'promotion_allowed': False}
        rec = {'scientific_status': 'EXPLORATORY_NOT_VALIDATED', 'state': 'PROMISING_EXPLORATORY'}
        self.assertEqual(promotion_guard(rec, blocked), 'EXPLORATORY_NOT_VALIDATED')
        for g in (blocked, authorised_but_closed):
            with self.assertRaises(PromotionForbidden):
                promotion_guard(dict(rec, scientific_status='VALIDATED'), g)
        with self.assertRaises(PromotionForbidden):
            promotion_guard(dict(rec, state='VALIDATED_STRATEGY'), blocked)
        with self.assertRaises(PromotionForbidden):
            promotion_guard({'scientific_status': 'PROVEN'}, blocked)


if __name__ == '__main__':
    unittest.main()
