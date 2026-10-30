import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from scripts.audit_health import check, latest_result_checked_at, verify_ft_backlog

class HealthTests(unittest.TestCase):
    def test_missing_outputs_never_healthy(self):
        with tempfile.TemporaryDirectory() as t:
            r=check(t,datetime(2026,10,29,tzinfo=timezone.utc))
            self.assertEqual(r['status'],'FAILED')
            self.assertTrue(any(x['status']=='UNKNOWN' for x in r['checks']))
    def test_real_snapshot_detects_stale_h1_independently_of_fresh_collector(self):
        # Test semantic classification at a clock derived from the snapshot,
        # rather than hard-coding production timestamps.
        root=Path(__file__).resolve().parents[1]
        now=datetime.fromisoformat(json.loads((root/'docs/data.json').read_text())['generated_at'])
        r=check(root,now)
        statuses={x['name']:x['status'] for x in r['checks']}
        self.assertEqual(statuses['ft_counts'],'OK')
        self.assertEqual(statuses['h1_replay'],'OK')
        self.assertEqual(statuses['collector'],'OK')

    def test_old_result_activity_detected_even_when_recollection_is_fresh(self):
        from datetime import timedelta
        from h1lab.core import empty_state,public_data
        from h1lab.v6_ft_events import synchronize
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);now=datetime(2026,10,29,18,tzinfo=timezone.utc)
            def write(path,data):
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data))
            state=empty_state();state['collector']={'last_poll_at':now.isoformat()}
            write('data/state.json',state);write('docs/data.json',public_data(state,{},now))
            write('data/result_audit.json',{'a':{'checked_at':(now-timedelta(hours=6)).isoformat()}})
            write('data/lab/ft-ledger.json',{'schema_version':1,'matches':{}})
            write('docs/lab/ft-results.json',{'matches':0,'final_recorded':0,'unverified':0,'timing_counts':{},'last_updated_at':now.isoformat()})
            for name in ['pattern-research','pattern-watch','v4-audit']:
                write('docs/lab/'+name+'.json',{'generated_at':now.isoformat()})
            result=check(root,now)
            statuses={x['name']:x['status'] for x in result['checks']}
            self.assertEqual(statuses['collector'],'OK')
            self.assertEqual(statuses['h1_result_activity'],'STALE')
            self.assertEqual(result['status'],'DEGRADED')

            ft=json.loads((root/'docs/lab/ft-results.json').read_text())
            ft['execution_health']={'status':'DEGRADED','unexpected_errors':2}
            write('docs/lab/ft-results.json',ft)
            result=check(root,now)
            statuses={x['name']:x['status'] for x in result['checks']}
            self.assertEqual(statuses['ft_execution'],'DEGRADED')
            self.assertNotEqual(result['status'],'OK')

    def test_activity_chooses_latest_absolute_instant_not_largest_clock_string(self):
        # The 12:10+02 event is 10:10 UTC, older than 11:30Z.
        audit = {
            'older_later_local': {'checked_at': '2026-10-30T12:10:00+02:00'},
            'newer_utc': {'checked_at': '2026-10-30T11:30:00Z'},
        }
        latest, invalid = latest_result_checked_at(audit)
        self.assertEqual(latest, '2026-10-30T11:30:00+00:00')
        self.assertEqual(invalid, 0)

    def test_malformed_and_naive_result_timestamps_are_exposed(self):
        audit = {
            'valid': {'checked_at': '2026-10-30T11:30:00+00:00'},
            'naive': {'checked_at': '2026-10-30T13:00:00'},
            'bad': {'checked_at': 'not-a-time'},
            'wrong_type': {'checked_at': 12345},
            'missing': {'checked_at': None},
        }
        latest, invalid = latest_result_checked_at(audit)
        self.assertEqual(latest, '2026-10-30T11:30:00+00:00')
        self.assertEqual(invalid, 3)

    def test_bad_checkpoint_timestamp_degrades_health_even_with_fresh_activity(self):
        from datetime import timedelta
        from h1lab.core import empty_state, public_data
        from h1lab.v6_ft_events import synchronize
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);now=datetime(2026,10,30,12,tzinfo=timezone.utc)
            def write(path,data):
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data))
            state=empty_state();state['collector']={'last_poll_at':now.isoformat()}
            write('data/state.json',state);write('docs/data.json',public_data(state,{},now))
            write('data/result_audit.json',{
                'valid':{'checked_at':(now-timedelta(minutes=20)).isoformat()},
                'malformed':{'checked_at':'bad_timestamp'},
            })
            write('data/lab/ft-ledger.json',{'schema_version':1,'matches':{}})
            write('docs/lab/ft-results.json',{
                'matches':0,'final_recorded':0,'unverified':0,
                'timing_counts':{},'last_updated_at':now.isoformat()})
            for name in ['pattern-research','pattern-watch','v4-audit']:
                write('docs/lab/'+name+'.json',{'generated_at':now.isoformat()})
            health=check(root,now)
            states={x['name']:x['status'] for x in health['checks']}
            self.assertEqual(states['h1_result_activity'],'OK')
            self.assertEqual(states['h1_result_timestamp_integrity'],'DEGRADED')
            self.assertEqual(health['status'],'DEGRADED')

    def test_backlog_overdue_subsets_do_not_double_count(self):
        # 2 verified + 2 overdue, of which 1 has never had a genuine
        # evidence check. The subtotal must NOT be added to the universe.
        ledger={'matches':{
            'a':{'status':'FINAL'}, 'b':{'status':'FINAL'},
            'c':{'status':'PENDING'}, 'd':{'status':'PENDING'},
        }}
        ft={'matches':4,'final_recorded':2,
            'last_updated_at':'2026-10-30T12:50:00+00:00',
            'coverage_diagnostics':{'past_unverified_eligible':2}}
        backlog={'schema_version':1,'status':'FT_BACKLOG_AUDIT_OBSERVATION_ONLY',
            'measured_at':'2026-10-30T12:51:00Z','total_matches':4,
            'classification':{
                'verified_ft':2,'past_due_unverified':2,'past_due_never_checked':1},
            'overdue_games':[{'match_key':'c'},{'match_key':'d'}],
            'overdue_omitted':0,
            'queue_plan':{'eligible':2,'selected':1,'deferred_by_capacity':1}}
        self.assertEqual(verify_ft_backlog(ledger,ft,backlog),
                         {'matches':4,'final':2,'overdue':2,'never_checked_subset':1,'omitted':0})

    def test_backlog_detects_a_missing_final_or_partially_published_bundle(self):
        from copy import deepcopy
        ledger={'matches':{
            'a':{'status':'FINAL'},'b':{'status':'PENDING'}}}
        ft={'matches':2,'final_recorded':1,
            'last_updated_at':'2026-10-30T12:50:00Z',
            'coverage_diagnostics':{'past_unverified_eligible':1}}
        backlog={'schema_version':1,'status':'FT_BACKLOG_AUDIT_OBSERVATION_ONLY',
            'measured_at':'2026-10-30T12:50:00Z','total_matches':2,
            'classification':{'verified_ft':1,'past_due_unverified':1,
                              'past_due_never_checked':1},
            'overdue_games':[{'match_key':'b'}],'overdue_omitted':0,
            'queue_plan':{'eligible':1,'selected':1,'deferred_by_capacity':0}}
        self.assertEqual(verify_ft_backlog(ledger,ft,backlog)['overdue'],1)
        scenarios=[]
        wrong=deepcopy(backlog);wrong['classification']['verified_ft']=0;scenarios.append(wrong)
        wrong=deepcopy(backlog);wrong['classification']['past_due_never_checked']=2;scenarios.append(wrong)
        wrong=deepcopy(backlog);wrong['overdue_games']=[{'match_key':'a'}];scenarios.append(wrong)
        wrong=deepcopy(backlog);wrong['overdue_games']=[{'match_key':'b'},{'match_key':'b'}];scenarios.append(wrong)
        wrong=deepcopy(backlog);wrong['measured_at']='2026-10-30T12:00:00Z';scenarios.append(wrong)
        wrong=deepcopy(backlog);wrong['queue_plan']['eligible']=10;scenarios.append(wrong)
        wrong=deepcopy(backlog);wrong['classification']['verified_ft']=True;scenarios.append(wrong)
        for altered in scenarios:
            with self.subTest(altered=altered),self.assertRaises(ValueError):
                verify_ft_backlog(ledger,ft,altered)

    def test_missing_ft_backlog_is_unknown_not_false_zero(self):
        from datetime import timedelta
        from h1lab.core import empty_state,public_data
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);now=datetime(2026,10,30,13,tzinfo=timezone.utc)
            def write(path,value):
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(value))
            state=empty_state();state['collector']={'last_poll_at':now.isoformat()}
            write('data/state.json',state)
            write('docs/data.json',public_data(state,{},now))
            write('data/result_audit.json',{'a':{'checked_at':now.isoformat()}})
            write('data/lab/ft-ledger.json',{'schema_version':1,'matches':{}})
            write('docs/lab/ft-results.json',{'matches':0,'final_recorded':0,
                'unverified':0,'timing_counts':{},'last_updated_at':now.isoformat()})
            for name in ('pattern-research','pattern-watch','v4-audit'):
                write('docs/lab/'+name+'.json',{'generated_at':now.isoformat()})
            statuses={c['name']:c['status'] for c in check(root,now)['checks']}
            self.assertEqual(statuses['ft_counts'],'OK')
            self.assertEqual(statuses['ft_backlog'],'UNKNOWN')
