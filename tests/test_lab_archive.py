"""P2#14: byte-bounded rollover, SHA continuity, recovery and sealed-month checks."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import lab_archive as a


def obj(i, size=55):
    return json.dumps({"event_id":str(i),"payload":"X"*size},sort_keys=True)+"\n"


class MonthlyArchiveTests(unittest.TestCase):
    def test_monthly_append_rotates_without_rewriting_legacy_bytes(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a,"MAX_BYTES",200):
            root=Path(d)
            before=[obj(i) for i in range(2)]
            a.append_monthly(root,"discovery-events","2026-10",before)
            original=(root/"data/lab/discovery-events-2026-10.jsonl").read_bytes()
            a.append_monthly(root,"discovery-events","2026-10",[obj(i) for i in range(2,8)])
            files=a.monthly_paths(root,"discovery-events")
            self.assertGreater(len(files),1)
            self.assertEqual(files[0].read_bytes(),original)
            self.assertTrue(all(p.stat().st_size<=200 for p in files))
            combined=[json.loads(line) for f in files for line in f.read_text().splitlines()]
            self.assertEqual([r["event_id"] for r in combined],[str(i) for i in range(8)])
            # Repeated verification is nondestructive.
            self.assertEqual(files,a.monthly_paths(root,"discovery-events"))

    def test_truncated_tail_unknown_name_and_missing_part_fail_closed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a,"MAX_BYTES",120):
            root=Path(d)
            a.append_monthly(root,"discovery-events","2026-10",[obj(i,20) for i in range(4)])
            files=a.monthly_paths(root,"discovery-events")
            self.assertGreater(len(files),1)
            files[-1].rename(files[-1].with_name("discovery-events-2026-10-part0003.jsonl"))
            with self.assertRaisesRegex(ValueError,"Missing"):
                a.monthly_paths(root,"discovery-events")
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=root/"data/lab/discovery-events-2026-10.jsonl"
            p.parent.mkdir(parents=True)
            p.write_text('{"event_id":"one"}',encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Truncated"):
                a.append_monthly(root,"discovery-events","2026-10",[obj(2)])
            p.with_name("discovery-events-2026-10-partone.jsonl").write_text("{}\n")
            with self.assertRaisesRegex(ValueError,"Unknown"):
                a.monthly_paths(root,"discovery-events")

    def test_mutable_view_can_split_update_and_shrink_without_orphans(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a,"MAX_BYTES",170):
            root=Path(d)
            rows=[obj(i,40) for i in range(9)]
            paths=a.write_monthly_view(root,"markets","2026-10",rows)
            self.assertGreater(len(paths),1)
            self.assertEqual([line for path in a.monthly_paths(root,"markets")
                              for line in path.read_text().splitlines()],
                             [r.rstrip("\n") for r in rows])
            newer=[obj(0,40),obj(1,40),obj(2,41)]
            a.write_monthly_view(root,"markets","2026-10",newer)
            current=a.monthly_paths(root,"markets")
            self.assertEqual(len(current),2 if sum(map(lambda x:len(x.encode()),newer))>170 else 1)
            self.assertEqual([json.loads(line)["event_id"] for f in current
                              for line in f.read_text().splitlines()],["0","1","2"])

    def test_v6_memory_sha_chain_survives_month_parts(self):
        from h1lab.v6_science_memory import append_events, read_stream, fact
        with tempfile.TemporaryDirectory() as d, patch.object(a,"MAX_BYTES",700):
            root=Path(d)
            now=datetime(2026,10,28,17,tzinfo=timezone.utc)
            candidates=[fact("patterns","PAT:"+str(i),{"id":i,"condition":"G_MULTI_ALERT",
                       "observed_at":now.isoformat()}) for i in range(6)]
            self.assertEqual(append_events(root,"patterns",now,candidates),6)
            files=a.monthly_paths(root,"v6-memory-patterns")
            self.assertGreater(len(files),1)
            first=read_stream(root,"patterns")
            self.assertEqual(len(first),6)
            self.assertEqual(append_events(root,"patterns",now,candidates),0)
            self.assertEqual(first,read_stream(root,"patterns"))
            first_part=files[0].read_bytes()
            self.assertEqual(first_part,files[0].read_bytes())

    def test_seal_month_replay_then_tamper_missing_or_correction_fails(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a,"_replay",return_value={"verified":True}):
            root=Path(d)
            a.append_monthly(root,"discovery-events","2026-09",[obj(1),obj(2)])
            now=datetime(2026,10,28,tzinfo=timezone.utc)
            initial=a.build(root,now)
            self.assertEqual(initial["sealed_parts"],1)
            self.assertEqual(initial["scientific_state"],"INCONCLUSIVO")
            self.assertEqual(a.build(root,now,verify_only=True),initial)
            old=(root/"data/lab/discovery-events-2026-09.jsonl")
            before=old.read_bytes()
            old.write_bytes(before.replace(b'"1"',b'"9"'))
            with self.assertRaisesRegex(ValueError,"SEALED_MONTH_MUTATED"):
                a.build(root,now)
            old.write_bytes(before)
            self.assertEqual(a.build(root,now,verify_only=True),initial)
            old.unlink()
            with self.assertRaisesRegex(ValueError,"SEALED_MONTH_MUTATED"):
                a.build(root,now)

    def test_large_mutable_lab_state_aborts_not_truncates(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a,"MAX_BYTES",200), patch.object(
                a,"_replay",return_value={}):
            root=Path(d)
            ledger=root/"data/lab/ft-ledger.json"
            ledger.parent.mkdir(parents=True)
            ledger.write_bytes(b"0"*201)
            with self.assertRaisesRegex(ValueError,"LAB_FILE_OVER_20_MB"):
                a.build(root,datetime(2026,10,28,tzinfo=timezone.utc))
            self.assertEqual(ledger.read_bytes(),b"0"*201)
