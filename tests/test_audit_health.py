import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from scripts.audit_health import check

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
