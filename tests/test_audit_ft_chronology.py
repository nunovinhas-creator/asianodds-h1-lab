"""Issue #107: a valid hash does not prove chronological validity."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from h1lab.v6_ft_events import synchronize,read_events,event_hash

class ChronologyAuditTests(unittest.TestCase):
    def test_backwards_clock_rejected_before_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=datetime(2026,10,29,12,tzinfo=timezone.utc)
            row={'status':'PENDING','home':'A','away':'B','kickoff_utc':'2026-10-28T12:00:00+00:00','reason':'awaiting_ft'}
            ledger={'schema_version':1,'matches':{'a':row}}
            synchronize(tmp,ledger,now)
            p=next(Path(tmp).rglob('*.jsonl'));original=p.read_bytes()
            row['reason']='changed'
            with self.assertRaisesRegex(ValueError,'chronolog'):
                synchronize(tmp,ledger,now-timedelta(hours=1))
            self.assertEqual(p.read_bytes(),original)

    def test_rehashed_backdated_event_rejected_on_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=datetime(2026,10,29,12,tzinfo=timezone.utc)
            row={'status':'PENDING','home':'A','away':'B','reason':'first'}
            ledger={'schema_version':1,'matches':{'a':row}}
            synchronize(tmp,ledger,now);row['reason']='second';synchronize(tmp,ledger,now)
            p=next(Path(tmp).rglob('*.jsonl'));events=read_events(tmp)
            events[-1]['recorded_at']=(now-timedelta(hours=1)).isoformat()
            events[-1]['sha256']=event_hash(events[-1])
            p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            with self.assertRaisesRegex(ValueError,'chronolog'):read_events(tmp)
