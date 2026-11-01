import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from scripts.audit_health import (check, latest_result_checked_at, verify_ft_backlog,
                                  ft_report_generation_at, h1_first_check_coverage)

class HealthTests(unittest.TestCase):
    def test_invalid_execution_status_blocks_operational_gate(self):
        from unittest.mock import patch
        from scripts.lab_ft_operational_gate import evaluate_health
        root = Path(__file__).resolve().parents[1]
        original = Path.read_text
        now = datetime.fromisoformat(json.loads(
            (root/'docs/data.json').read_text())['generated_at'])
        for invalid in ('BROKEN_SCHEMA', None, 1, [], {}):
            with self.subTest(invalid=invalid):
                def altered(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    if path == root/'docs/lab/ft-results.json':
                        value = json.loads(text)
                        value['execution_health']['status'] = invalid
                        return json.dumps(value)
                    return text
                with patch.object(Path, 'read_text', altered):
                    result = check(root, now)
                statuses = {x['name']: x['status'] for x in result['checks']}
                self.assertEqual(statuses['ft_execution'], 'FAILED')
                self.assertEqual(evaluate_health(result)['status'], 'FAILED')

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
        self.assertEqual(statuses['ft_backlog'],'OK')
        report=json.loads((root/'docs/lab/ft-results.json').read_text())
        self.assertGreaterEqual(report['final_recorded'],364)
        self.assertEqual(report['coverage_diagnostics']['closed_unverified'],
                         report['status_counts'].get('EXPIRED_UNVERIFIED',0))
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
            ft['execution_health']={'status':'DEGRADED','unexpected_errors':2,
                                    'measured_at':now.isoformat()}
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


    def test_closed_unverified_is_terminal_and_keeps_final_immutable(self):
        from copy import deepcopy
        ledger={'matches':{
            'a':{'status':'FINAL'}, 'b':{'status':'FINAL'},
            'c':{'status':'EXPIRED_UNVERIFIED'}, 'd':{'status':'PENDING'},
        }}
        ft={'matches':4,'final_recorded':2,
            'last_updated_at':'2026-11-01T09:33:00Z',
            'coverage_diagnostics':{
                'past_unverified_eligible':1,'closed_unverified':1}}
        backlog={'schema_version':1,'status':'FT_BACKLOG_AUDIT_OBSERVATION_ONLY',
            'measured_at':'2026-11-01T09:33:00Z','total_matches':4,
            'classification':{'verified_ft':2,'closed_unverified':1,
                              'past_due_unverified':1,'past_due_never_checked':1},
            'overdue_games':[{'match_key':'d'}],'overdue_omitted':0,
            'queue_plan':{'eligible':1,'selected':0,'deferred_by_capacity':1}}
        expected=verify_ft_backlog(ledger,ft,backlog)
        self.assertEqual((expected['matches'],expected['final'],expected['overdue']),(4,2,1))
        # A closed game cannot silently re-enter the due queue or the final pool.
        wrong=deepcopy(backlog)
        wrong['overdue_games']=[{'match_key':'c'}]
        with self.assertRaisesRegex(ValueError,'terminal'):
            verify_ft_backlog(ledger,ft,wrong)
        wrong=deepcopy(backlog)
        wrong['classification']['closed_unverified']=0
        with self.assertRaises(ValueError):
            verify_ft_backlog(ledger,ft,wrong)
        wrong=deepcopy(backlog)
        wrong['classification']['closed_unverified']=2
        with self.assertRaises(ValueError):
            verify_ft_backlog(ledger,ft,wrong)
        wrong_ft=deepcopy(ft)
        wrong_ft['coverage_diagnostics']['closed_unverified']=0
        with self.assertRaisesRegex(ValueError,'closed-unverified coverage'):
            verify_ft_backlog(ledger,wrong_ft,backlog)

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

    def test_ft_generation_is_not_last_ledger_change(self):
        # Actual 30/10 production: new diagnostic report and backlog at 13:24,
        # with the ledger unchanged since 13:19. These are the SAME cycle.
        ledger={'matches':{'a':{'status':'FINAL'},'b':{'status':'PENDING'}}}
        report={'matches':2,'final_recorded':1,
                'last_updated_at':'2026-10-30T13:19:23+00:00',
                'execution_health':{
                    'status':'NOT_ATTEMPTED',
                    'measured_at':'2026-10-30T13:24:28+00:00'},
                'coverage_diagnostics':{'past_unverified_eligible':1}}
        backlog={'schema_version':1,'status':'FT_BACKLOG_AUDIT_OBSERVATION_ONLY',
                 'measured_at':'2026-10-30T13:24:28+00:00',
                 'total_matches':2,
                 'classification':{'verified_ft':1,'past_due_unverified':1,
                                   'past_due_never_checked':1},
                 'overdue_games':[{'match_key':'b'}], 'overdue_omitted':0,
                 'queue_plan':{'eligible':1,'selected':0,'deferred_by_capacity':1}}
        self.assertEqual(ft_report_generation_at(report),'2026-10-30T13:24:28+00:00')
        self.assertEqual(verify_ft_backlog(ledger,report,backlog)['overdue'],1)
        self.assertEqual(report['last_updated_at'],'2026-10-30T13:19:23+00:00')

    def test_ft_generation_mismatch_or_corrupt_runtime_stamp_fails_closed(self):
        from copy import deepcopy
        ledger={'matches':{'b':{'status':'PENDING'}}}
        report={'matches':1,'final_recorded':0,
                'last_updated_at':'2026-10-30T13:19:23+00:00',
                'execution_health':{'status':'NOT_ATTEMPTED',
                                    'measured_at':'2026-10-30T13:24:28Z'},
                'coverage_diagnostics':{'past_unverified_eligible':1}}
        backlog={'schema_version':1,'status':'FT_BACKLOG_AUDIT_OBSERVATION_ONLY',
                 'measured_at':'2026-10-30T13:24:28Z',
                 'total_matches':1,'classification':{'past_due_unverified':1,
                 'past_due_never_checked':1},
                 'overdue_games':[{'match_key':'b'}], 'overdue_omitted':0,
                 'queue_plan':{'eligible':1,'selected':0,'deferred_by_capacity':1}}
        bad=deepcopy(backlog)
        bad['measured_at']='2026-10-30T13:19:23Z'
        with self.assertRaisesRegex(ValueError,'different generations'):
            verify_ft_backlog(ledger,report,bad)
        for timestamp in ('not-a-timestamp','2026-10-30T13:24:28',None):
            mutated=deepcopy(report)
            mutated['execution_health']['measured_at']=timestamp
            with self.subTest(timestamp=timestamp),self.assertRaises(ValueError):
                ft_report_generation_at(mutated)
                verify_ft_backlog(ledger,mutated,backlog)
        legacy=deepcopy(report)
        legacy.pop('execution_health')
        self.assertEqual(ft_report_generation_at(legacy),
                         '2026-10-30T13:19:23+00:00')

    def test_h1_first_check_monitor_separates_overdue_retry_cooldown_and_expiry(self):
        from datetime import timedelta
        from unittest.mock import patch
        with patch("h1lab.results.H1_RETRY_HORIZON", timedelta(days=30)):  # legacy fixtures
            self._h1_first_check_legacy_horizon()

    def _h1_first_check_legacy_horizon(self):
        now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        def fixture(key, kickoff):
            return {"match_key":key, "kickoff_utc":kickoff}
        signals = [
            fixture("first_23h", "2026-10-31T10:00:00Z"),
            fixture("first_57h", "2026-10-30T00:00:00Z"),
            fixture("retry", "2026-10-31T20:00:00Z"),
            fixture("cooldown", "2026-11-01T05:00:00Z"),
            fixture("future", "2026-11-02T12:00:00Z"),
            fixture("expired", "2026-09-30T00:00:00Z"),
            fixture("final", "2026-10-30T00:00:00Z"),
        ]
        audit = {
            "retry": {"checked_at":"2026-10-31T21:00:00Z"},
            "cooldown": {"checked_at":"2026-11-01T11:00:00Z"},
        }
        metrics=h1_first_check_coverage(signals, {"final"}, audit, now)
        self.assertEqual(metrics["first_checks_due"], 2)
        self.assertEqual(metrics["retries_due"], 1)
        self.assertEqual(metrics["in_cooldown"], 1)
        self.assertEqual(metrics["first_overdue_12h"], 2)
        self.assertEqual(metrics["first_overdue_24h"], 1)
        self.assertEqual(metrics["expired_without_first_check"], 1)
        self.assertEqual(metrics["future_or_grace"], 1)
        self.assertEqual(metrics["oldest_first_wait_hours"], 57.0)
        self.assertEqual(metrics["first_check_cycles_at_20"], 1)
        self.assertEqual(metrics["deferred_if_one_cycle"], 0)

    def test_h1_first_check_capacity_and_duplicate_identity(self):
        now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        signals=[{"match_key":f"fixture_{i}",
                  "kickoff_utc":"2026-10-31T20:00:00Z"} for i in range(45)]
        result=h1_first_check_coverage(signals, {}, {}, now)
        self.assertEqual(result["first_checks_due"],45)
        self.assertEqual(result["first_check_cycles_at_20"],3)
        self.assertEqual(result["deferred_if_one_cycle"],25)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            h1_first_check_coverage(signals+[signals[0]], {}, {}, now)

    def test_h1_first_check_monitor_missing_audit_timestamp_is_not_evidence(self):
        now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        signals=[{"match_key":"x","kickoff_utc":"2026-10-31T18:00:00Z"}]
        for item in (None, "invalid", "2026-11-01T18:00:00Z",
                     "2026-10-31T20:00:00"):
            with self.subTest(item=item):
                result=h1_first_check_coverage(
                    signals, {}, {"x":{"checked_at":item}}, now)
                self.assertEqual(result["first_checks_due"],1)
                self.assertEqual(result["retries_due"],0)
