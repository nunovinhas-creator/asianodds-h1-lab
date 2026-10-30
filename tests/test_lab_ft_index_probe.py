import copy
import unittest
from datetime import datetime,timezone,timedelta
from h1lab.lab_api_football import APIFootballResults
from h1lab.lab_ft_day_identity import build_index
from h1lab.lab_ft_index_probe import plan_index_ids,IndexProbe
from test_lab_api_football import S,game

NOW=datetime(2026,10,30,12,tzinfo=timezone.utc)

def fixture():
    ev=game();ev['league']={'id':9,'name':'Test League'};return ev

def setup():
    ev=fixture();index=build_index({'schema_version':1,'days':{}},{'2026-10-27':[ev]},NOW)
    matches={S['match_key']:{**S,'status':'PENDING'}}
    return ev,index,matches

class StrictIndexProbeTests(unittest.TestCase):
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
