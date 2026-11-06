"""Incident 42181923012 and conservative admission, without Telegram or providers."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import core, e5_notify
from h1lab.fixture_identity import blocked_keys, validate
from h1lab.timeline import collect_timelines
from scripts.collect_publish_safe import verify_state
from scripts.git_selective_publish import PublicationRefused
from scripts.lab_ft_publish_safe import stable_fixtures

FIXTURE = Path(__file__).parent / 'fixtures/collector-identity-2026-11-06.json'
NOW = datetime(2026, 11, 6, 8, 9, 19, tzinfo=timezone.utc)


def raw(state):
    return json.dumps(state).encode()


class FixtureQuarantine(unittest.TestCase):
    def setUp(self):
        fixture = json.loads(FIXTURE.read_text())
        self.old, self.new = fixture['old_alert'], fixture['new_alert']
        self.before = core.empty_state()
        self.before.update(last_id=53069, alerts=[self.old])

    def admitted(self):
        state = copy.deepcopy(self.before)
        self.assertEqual(core.incorporate(state, [self.new], NOW), 1)
        state['last_id'] = 53130
        return state

    def test_real_source_pair_previously_refused_and_now_quarantined(self):
        broken = copy.deepcopy(self.before)
        broken['alerts'].append(self.new)
        self.assertFalse(stable_fixtures(raw(self.before), raw(broken)))
        with self.assertRaisesRegex(PublicationRefused, 'Fixture identity rewritten'):
            verify_state(raw(self.before), raw(broken))
        state = self.admitted()
        q = state['fixture_quarantine'][0]
        self.assertEqual(q['alert'], self.new)
        self.assertEqual(q['against_event_ids'], [self.old['event_id']])
        self.assertEqual(q['known_at'], NOW.isoformat())
        self.assertEqual(state['alerts'], self.before['alerts'])
        self.assertEqual(state['signals'], [])
        self.assertTrue(stable_fixtures(raw(self.before), raw(state)))
        self.assertEqual(verify_state(raw(self.before), raw(state))['last_id'], 53130)
        validate(state)

    def test_repoll_and_roundtrip_are_idempotent(self):
        state = json.loads(raw(self.admitted()))
        snapshot = copy.deepcopy(state)
        self.assertEqual(core.incorporate(state, [self.old, self.new, self.new], NOW), 0)
        self.assertEqual(snapshot, state)

    def test_unrelated_observation_continues_but_conflicting_h1_never_bets(self):
        other = {**self.new, 'event_id': 'c:99', 'message_id': 99,
                 'match_key': 'different', 'h1': True}
        conflict = {**self.new, 'h1': True}
        state = copy.deepcopy(self.before)
        core.incorporate(state, [conflict, other], NOW)
        self.assertEqual([s['match_key'] for s in state['signals']], ['different'])
        verify_state(raw(self.before), raw(state))

    def test_new_key_conflicts_within_one_batch_before_signal_creation(self):
        state = core.empty_state()
        core.incorporate(state, [{**self.old, 'h1': True}, {**self.new, 'h1': True}], NOW)
        self.assertEqual(state['signals'], [])
        self.assertEqual(len(state['fixture_quarantine']), 1)

    def test_id_reuse_with_different_teams_is_also_quarantined(self):
        state = copy.deepcopy(self.before)
        changed = {**self.new, 'home': 'Another club', 'kickoff_utc': self.old['kickoff_utc']}
        core.incorporate(state, [changed], NOW)
        self.assertEqual(state['fixture_quarantine'][0]['alert'], changed)

    def test_reverting_clock_does_not_release_key_or_create_triples(self):
        state = self.admitted()
        revert = {**self.old, 'event_id': 'c:100', 'message_id': 100, 'h1': True}
        core.incorporate(state, [revert], NOW)
        self.assertEqual(state['signals'], [])
        state['signals'] = [dict(signal_id='s'+str(i), match_key=k,
            kickoff_utc=self.old['kickoff_utc'], observed_at=self.old['observed_at'],
            line=2.5, under_odds=1.9) for i, k in enumerate([self.old['match_key'], 'x', 'y'])]
        original = copy.deepcopy(state['signals'])
        core.make_triples(state, NOW)
        self.assertEqual(state['tickets'], [])
        self.assertEqual(state['signals'], original)

    def test_quarantine_cannot_be_removed_modified_or_promoted(self):
        before = self.admitted()
        for mutate in [lambda s: s.pop('fixture_quarantine'),
                       lambda s: s['fixture_quarantine'][0]['alert'].update(home='wrong'),
                       lambda s: s['alerts'].append(self.new)]:
            after = copy.deepcopy(before)
            mutate(after)
            with self.assertRaises(PublicationRefused):
                verify_state(raw(before), raw(after))

    def test_published_history_cannot_be_moved_to_quarantine(self):
        state = self.admitted()
        state['alerts'] = []
        with self.assertRaises(PublicationRefused):
            verify_state(raw(self.before), raw(state))

    def test_guard_rejects_new_bet_on_blocked_key(self):
        state = self.admitted()
        state['signals'].append(dict(signal_id='s', match_key=self.old['match_key']))
        with self.assertRaisesRegex(PublicationRefused, 'New H1 signal'):
            verify_state(raw(self.before), raw(state))

    def test_e5_blocks_even_when_v4_is_absent_or_later_reverts(self):
        state = self.admitted()
        key = self.old['match_key']
        with tempfile.TemporaryDirectory() as tmp:
            core.dump_json(Path(tmp)/'data/state.json', state)
            # Simulate an otherwise eligible downstream evaluation. Permanent
            # quarantine must dominate it, including an already-sent withdrawal.
            with patch('h1lab.e5_notify.evaluate_all', return_value=[{
                    'match_key': key, 'state': e5_notify.ELIGIBLE, 'reason': 'E5'}]):
                rows, _, _ = e5_notify.load_rows(tmp, NOW)
            self.assertEqual(rows[0]['state'], e5_notify.EXCLUDED)
            self.assertEqual(rows[0]['reason'], 'IDENTIDADE_EM_QUARENTENA')
        timelines, _, _ = collect_timelines([self.old, self.new], [])
        self.assertFalse(timelines[0]['identity']['kickoff_consistent'])
        self.assertEqual(blocked_keys(state), {key})


if __name__ == '__main__':
    unittest.main()
