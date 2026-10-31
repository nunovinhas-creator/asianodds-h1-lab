import copy
import unittest
from datetime import datetime, timedelta, timezone
from h1lab.lab_ft_recovery_turn import plan_exact_goal_ids, recovery_turn, goal_id_rotation
from h1lab.lab_goal_id_probe import plan_goal_id
from h1lab.lab_goal import GoalResults
from h1lab.lab_results import reconcile

NOW = datetime(2026, 10, 31, 15, tzinfo=timezone.utc)
K = '2026-10-29,1,2'
ROW = {'match_key': K, 'home': 'FC Noah', 'away': 'Syunik', 'status': 'PENDING',
       'kickoff_utc': '2026-10-29T15:00:00+00:00', 'lookup_source_version': 11,
       'queue_visited_at': '2026-10-31T08:41:23+00:00'}
C = {'provider': 'goal', 'provider_event_id': '858889', 'provider_home': 'Noah',
     'provider_away': 'Syunik', 'provider_competition': 'Cup',
     'provider_kickoff_utc': ROW['kickoff_utc'], 'last_seen_at': '2026-10-30T23:16:24+00:00',
     'reference_url': 'https://api.goal-api.com/v1/fixtures/858889',
     'match_strength': 'STRONG', 'orientation': 'SAME_ORDER', 'review_only': True}
E = {'apiId': '858889', 'homeTeamName': 'Noah', 'awayTeamName': 'Syunik',
     'kickoffUtc': ROW['kickoff_utc'], 'league': {'name': 'Cup'},
     'matchStatus': 'FINISHED', 'matchPeriod': 'FINISHED',
     'homeTeamFtScore': '2', 'awayTeamFtScore': '1', 'homeTeamScore': '2', 'awayTeamScore': '1'}


def review():
    return {'schema_version': 1, 'games': [{**ROW, 'possible_duplicates': [], 'candidates': [dict(C)]}]}


class RecoveryTurnTests(unittest.TestCase):
    def test_last_daily_slot_is_substituted_not_overspent_or_wasted(self):
        from h1lab.lab_ft_rotation import advance
        for used in (78, 79):
            dates=goal_id_rotation(['2026-10-29'],used)
            p=GoalResults('synthetic',getter=lambda d,k: [],max_days=1,allowed_days=dates,
                          target_ids={K:'858889'},id_getter=lambda i,k:dict(E))
            p.lookup(ROW);p.lookup(dict(ROW,match_key='another'))
            self.assertEqual(p.summary()['requests'],80-used)
            previous={'schema_version':1,'providers':{},'usage':{'goal':{'2026-10-31':used}}}
            out=advance(previous,{'goal':dates},{'goal':list(p.cache)},NOW,
                        extra_requests={'goal':p.id_requests})
            self.assertEqual(out['usage']['goal']['2026-10-31'],80)
        self.assertIsNone(goal_id_rotation(['2026-10-29'],80))

    def test_reproduces_unchecked_exact_id_excluded_by_old_planner(self):
        self.assertEqual(plan_goal_id([K], {K: ROW}, review(), NOW), {})
        targets = plan_exact_goal_ids({K: ROW}, review(), NOW)
        self.assertEqual(targets[K]['provider_fixture_id'], '858889')
        self.assertNotIn('home_goals', targets[K])
        self.assertNotIn('competition_verified', targets[K])

    def test_current_valid_ft_and_cached_date_substitution_share_two_request_ceiling(self):
        targets = plan_exact_goal_ids({K: ROW}, review(), NOW)
        calls = []
        p = GoalResults('synthetic', getter=lambda d,k: [], max_days=1,
                        allowed_days=['2026-10-29'], target_ids={K: '858889'}, exact_targets=targets,
                        id_getter=lambda i,k: (calls.append(i) or dict(E)))
        found, why = p.lookup(ROW)
        self.assertEqual(why, 'verified_goal_ft')
        self.assertEqual((found['home_goals'], found['away_goals']), (2, 1))
        p.lookup(dict(ROW, match_key='other'))
        p.lookup(ROW)
        self.assertEqual(calls, ['858889'])
        self.assertEqual(p.summary()['requests'], 2)

    def test_current_identity_changes_and_invalid_ft_never_certify(self):
        targets = plan_exact_goal_ids({K: ROW}, review(), NOW)
        for change in ({'league': {'name': 'Another Cup'}}, {'homeTeamName': 'AS Noah'},
                       {'awayTeamName': 'Syunik Women'}, {'apiId': '999999'},
                       {'kickoffUtc': '2026-10-29T15:01:00Z'}, {'matchStatus': 'LIVE'},
                       {'homeTeamFtScore': None}, {'homeTeamScore': '9'}):
            with self.subTest(change=change):
                p = GoalResults('synthetic', allowed_days=[], max_days=1,
                                target_ids={K: '858889'}, exact_targets=targets,
                                id_getter=lambda i,k: dict(E, **change))
                self.assertIsNone(p.lookup(ROW)[0])

    def test_weak_core_stale_category_and_inverted_candidates_stay_pending(self):
        for change in ({'provider_home': 'AS Noah'}, {'provider_home': 'Noah B'},
                       {'provider_away': 'Syunik U21'}, {'provider_away': 'Syunik Women'},
                       {'match_strength': 'WEAK_REVIEW_ONLY'}, {'orientation': 'REVERSED'},
                       {'last_seen_at': '2026-09-01T00:00:00Z'},
                       {'provider_kickoff_utc': '2026-10-29T15:06:00Z'},
                       {'reference_url': 'https://example.invalid/858889'}):
            with self.subTest(change=change):
                r = review(); r['games'][0]['candidates'][0].update(change)
                self.assertEqual(plan_exact_goal_ids({K: ROW}, r, NOW), {})

    def test_conflict_and_hold_and_duplicate_id_cannot_be_bypassed(self):
        for reason in ('goal_identity_side_collision', 'goal_ambiguous_fixture',
                       'goal_reversed_orientation', 'goal_score_conflict'):
            row = dict(ROW, last_provider_visit={'reasons': {'goal': reason}})
            self.assertEqual(plan_exact_goal_ids({K: row}, review(), NOW), {})
        self.assertEqual(plan_exact_goal_ids({K: ROW}, review(), NOW, reserved_keys={K}), {})
        r = review(); r['games'].append({**r['games'][0], 'match_key': 'duplicate'})
        self.assertEqual(plan_exact_goal_ids({K: ROW}, r, NOW), {})
        final = dict(ROW, status='FINAL', result={'evidence': 'goal_only',
                    'source': C['reference_url'], 'home_goals': 2, 'away_goals': 1})
        self.assertEqual(plan_exact_goal_ids({K: ROW, 'final': final}, review(), NOW), {})

    def test_all_existing_cooldowns_and_first_day_grace_remain(self):
        for change in ({'goal_id_last_attempt_at': NOW.isoformat()},
                       {'queue_visited_at': NOW.isoformat()},
                       {'evidence_checked_at': (NOW-timedelta(hours=5)).isoformat(), 'stable_confirmations': 2},
                       {'kickoff_utc': (NOW-timedelta(hours=23)).isoformat()},
                       {'status': 'SCORE_CONFLICT'}):
            row = dict(ROW, **change)
            r = review(); r['games'][0].update(row)
            self.assertEqual(plan_exact_goal_ids({K: row}, r, NOW), {})

    def test_one_turn_preserves_29_general_slots_and_preview_equals_real(self):
        alerts = [{**ROW, 'match_key': str(i), 'home': 'Home '+str(i), 'away': 'Away '+str(i),
                   'kickoff_utc': '2026-10-28T10:00:00Z'} for i in range(35)] + [dict(ROW)]
        previous = {'schema_version': 1, 'matches': {K: dict(ROW)}}
        def run(limit, **kwargs):
            return reconcile({'alerts': alerts}, [], previous, now=NOW, max_checks=limit,
                bsd_lookup=lambda s:(None, 'no_match'), tsdb_lookup=lambda s:(None, 'no_match'),
                evidence_retry=True, lookup_source_version=11, **kwargs)
        _, baseline, _ = run(30)
        self.assertNotIn(K, baseline['ft_queue']['selected_keys'])
        _, preview, _ = run(0, recovery_keys={K})
        _, real, count = run(30, recovery_keys={K})
        selected = real['ft_queue']['selected_keys']
        self.assertEqual(selected[0], K)
        self.assertEqual(len(selected), 30)
        self.assertEqual(count, 30)
        self.assertEqual(selected, preview['ft_queue']['deferred_keys'][:30])
        self.assertEqual(selected[1:], baseline['ft_queue']['selected_keys'][:29])
        with self.assertRaises(ValueError): run(30, recovery_keys={K, 'other'})
        previous['matches'][K]['queue_visited_at'] = NOW.isoformat()
        _, blocked, _ = run(30, recovery_keys={K})
        self.assertNotIn(K, blocked['ft_queue']['selected_keys'])

    def test_turn_rotates_by_real_id_attempt_without_rewriting_journal(self):
        rows = {K: dict(ROW, goal_id_last_attempt_at='2026-10-29T00:00:00Z'),
                'second': dict(ROW, match_key='second', goal_id_last_attempt_at='2026-10-30T00:00:00Z')}
        before = copy.deepcopy(rows)
        self.assertEqual(recovery_turn({}, {K: {}, 'second': {}}, rows), {K})
        self.assertEqual(rows, before)
        rows[K]['goal_id_last_attempt_at'] = NOW.isoformat()
        self.assertEqual(recovery_turn({}, {K: {}, 'second': {}}, rows), {'second'})
