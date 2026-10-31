import copy
import unittest
from datetime import datetime,timezone,timedelta
from h1lab.lab_api_football import APIFootballResults
from h1lab.lab_ft_day_identity import build_index
from h1lab.lab_ft_index_probe import plan_index_ids,IndexProbe
from h1lab.lab_api_football_errors import APIRequestFailure
from test_lab_api_football import S,game

NOW=datetime(2026,10,30,12,tzinfo=timezone.utc)

def fixture():
    ev=game();ev['league']={'id':9,'name':'Test League'};return ev

def setup():
    ev=fixture();index=build_index({'schema_version':1,'days':{}},{'2026-10-27':[ev]},NOW)
    matches={S['match_key']:{**S,'status':'PENDING'}}
    return ev,index,matches

class StrictIndexProbeTests(unittest.TestCase):
    def test_failed_batch_is_unavailable_for_every_target_never_missing(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        second=dict(S,match_key='second')
        targets['second']=dict(targets[S['match_key']],match_key='second')
        calls=[]
        def fail(ids,key):
            calls.append(ids)
            raise APIRequestFailure('PROVIDER_ERRORS',http_status=200,
                errors={'plan':'Free plan does not allow this endpoint'})
        a=APIFootballResults('test',allowed_days=[],id_fetch=fail)
        probe=IndexProbe(a,targets)
        for signal in (S,second):
            self.assertEqual(probe.lookup(signal)[1],'api_football_index_id_unavailable')
            self.assertEqual(a.reviewed_error_details[signal['match_key']]['category'],
                             'PROVIDER_ERRORS')
        self.assertEqual(len(calls),1)

    def test_failed_id_can_use_authorized_date_within_shared_budget(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        calls=[]
        def fail(ids,key):
            calls.append('id');raise OSError('unavailable')
        def date(day,key):calls.append(day);return [ev]
        a=APIFootballResults('test',allowed_days=['2026-10-27'],id_fetch=fail,fetch=date)
        probe=IndexProbe(a,targets)
        self.assertIsNotNone(probe.lookup(S)[0])
        self.assertIsNotNone(probe.lookup(S)[0])
        self.assertEqual(calls,['id','2026-10-27'])
        self.assertEqual(a.summary()['requests'],2)
        self.assertEqual(probe.outcomes[S['match_key']],'api_football_index_id_unavailable')
        self.assertEqual(probe.fallback_outcomes[S['match_key']],'verified_api_football_ft')

    def test_rate_limit_or_daily_quota_never_triggers_date_fallback(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        for failure in (APIRequestFailure('HTTP_ERROR',http_status=429),
                APIRequestFailure('PROVIDER_ERRORS',http_status=200,
                                  errors={'requests':'Daily limit reached'})):
            def fail(ids,key):raise failure
            def date(day,key):raise AssertionError('quota must not trigger more HTTP')
            a=APIFootballResults('test',allowed_days=['2026-10-27'],id_fetch=fail,fetch=date)
            p=IndexProbe(a,targets)
            self.assertIsNone(p.lookup(S)[0]);self.assertEqual(a.summary()['requests'],1)

    def test_failed_id_fallback_cannot_exceed_remaining_request_slots(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        def fail(ids,key):raise OSError('unavailable')
        def date(day,key):raise AssertionError('shared ceiling exhausted')
        a=APIFootballResults('test',allowed_days=['2026-10-27'],id_fetch=fail,fetch=date)
        a.requests=2
        p=IndexProbe(a,targets)
        self.assertIsNone(p.lookup(S)[0]);self.assertEqual(a.summary()['requests'],3)

    def test_reviewed_first_failure_is_shared_with_index_and_later_reviewed(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        def fail(ids,key):raise APIRequestFailure('HTTP_ERROR',http_status=403,
            errors={'plan':'Free plan denies ID access'})
        a=APIFootballResults('test',allowed_days=[],id_fetch=fail,
            reviewed_targets={'reviewed':{'provider_fixture_id':1002}})
        p=IndexProbe(a,targets)
        self.assertEqual(a.lookup({'match_key':'reviewed'})[1],
                         'api_football_reviewed_id_unavailable')
        self.assertEqual(p.lookup(S)[1],'api_football_index_id_unavailable')
        self.assertEqual(a.lookup({'match_key':'reviewed'})[1],
                         'api_football_reviewed_id_unavailable')
        self.assertEqual(a.summary()['requests'],1)

    def test_known_strict_identity_uses_single_shared_id_without_date_request(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        calls=[]
        a=APIFootballResults('test',allowed_days=[],id_fetch=lambda ids,key:(calls.append(ids) or {1000:ev}))
        probe=IndexProbe(a,targets)
        self.assertIsNotNone(probe.lookup(S)[0]);self.assertIsNotNone(probe.lookup(S)[0])
        self.assertEqual(calls,[[1000]]);self.assertEqual(a.summary()['requests'],1)
        self.assertEqual(a.requests,0);self.assertEqual(a.id_requests,1)
        self.assertEqual(probe.days,a.days)

    def test_refuses_changed_identity_ids_competition_status_and_score(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        mutations=[lambda e:e['teams']['home'].update(id=99),
                   lambda e:e['league'].update(id=10),
                   lambda e:e['fixture'].update(date='2026-10-27T13:01:00Z'),
                   lambda e:e['teams']['away'].update(name='Other Club'),
                   lambda e:e['fixture']['status'].update(short='AET'),
                   lambda e:e['goals'].update(home=2)]
        for mutate in mutations:
            bad=copy.deepcopy(ev);mutate(bad)
            a=APIFootballResults('test',id_fetch=lambda ids,key:{1000:bad})
            self.assertIsNone(IndexProbe(a,targets).lookup(S)[0])

    def test_queue_selection_cooldowns_and_finals_cannot_be_bypassed(self):
        ev,index,matches=setup();key=S['match_key']
        self.assertEqual(plan_index_ids([],matches,index,NOW),{})
        for extra in ({'status':'FINAL'},{'queue_visited_at':NOW.isoformat()},
                      {'evidence_checked_at':NOW.isoformat()},
                      {'kickoff_utc':(NOW-timedelta(hours=2)).isoformat()}):
            rows=copy.deepcopy(matches);rows[key].update(extra)
            self.assertEqual(plan_index_ids([key],rows,index,NOW),{})
        self.assertEqual(plan_index_ids([key],matches,index,NOW,reserved=[1000]),{})

    def test_incomplete_duplicate_or_category_mismatch_never_creates_locator(self):
        ev,index,matches=setup();key=S['match_key']
        incomplete=copy.deepcopy(index);incomplete['days']['2026-10-27']['status']='INCOMPLETE'
        self.assertEqual(plan_index_ids([key],matches,incomplete,NOW),{})
        rows=copy.deepcopy(matches);rows['duplicate']=dict(rows[key])
        self.assertEqual(plan_index_ids([key],rows,index,NOW),{})
        rows=copy.deepcopy(matches);rows[key]['home']+=' U21'
        self.assertEqual(plan_index_ids([key],rows,index,NOW),{})

    def test_ninety_minute_name_collision_and_six_minute_shift_are_rejected(self):
        ev,index,matches=setup();key=S['match_key']
        other=copy.deepcopy(ev);other['fixture']['id']=1001
        other['fixture']['date']='2026-10-27T13:30:00Z'
        other['teams']['home']['id']=991;other['teams']['away']['id']=992
        dup=build_index({'schema_version':1,'days':{}},{'2026-10-27':[ev,other]},NOW)
        self.assertEqual(plan_index_ids([key],matches,dup,NOW),{})
        ev['fixture']['date']='2026-10-27T13:06:00Z'
        shifted=build_index({'schema_version':1,'days':{}},{'2026-10-27':[ev]},NOW)
        self.assertEqual(plan_index_ids([key],matches,shifted,NOW),{})

    def test_three_request_limit_and_failed_id_batch_never_retried_in_run(self):
        ev,index,matches=setup();targets=plan_index_ids(list(matches),matches,index,NOW)
        calls=[]
        def fail(ids,key):calls.append(ids);raise OSError('network')
        a=APIFootballResults('test',id_fetch=fail);a.requests=3
        p=IndexProbe(a,targets);self.assertIsNone(p.lookup(S)[0]);self.assertEqual(calls,[])
        a.requests=0
        self.assertIsNone(p.lookup(S)[0]);self.assertIsNone(p.lookup(S)[0]);self.assertEqual(len(calls),1)

    def test_real_index_produces_only_score_free_locators_and_preserves_all_finals(self):
        import json
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        ledger=json.loads((root/'data/lab/ft-ledger.json').read_text())['matches']
        index=json.loads((root/'data/lab/ft-api-football-day-index.json').read_text())
        before=copy.deepcopy(ledger)
        targets=plan_index_ids(list(ledger),ledger,index,NOW+timedelta(hours=11))
        self.assertGreater(len(targets),0)
        self.assertEqual(ledger,before)
        self.assertLessEqual(len(targets),20)
        for key,row in targets.items():
            self.assertNotEqual(ledger[key]['status'],'FINAL')
            self.assertNotIn('score',json.dumps(row))
