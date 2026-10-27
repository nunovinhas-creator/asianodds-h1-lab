import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from h1lab.shadow_formats import inspect,store

class FormatShadowTests(unittest.TestCase):
    def test_no_raw_message_persisted(self):
        raw="Club Secret vs Away Secret\nTotal: 2.5 ↑ 2.75\nWas 2.5 1.8 2.0\nNow 2.75 1.9 1.9\nhttps://asianodds.com/match"
        item=inspect(raw,datetime(2026,10,27,tzinfo=timezone.utc),5,99,True)
        txt=str(item)
        self.assertNotIn("Club Secret",txt)
        self.assertNotIn("asianodds.com",txt)
        self.assertIn("total",item["markets_mentioned"])
    def test_idempotent_month_partition(self):
        item=inspect("BTTS Yes No",datetime(2026,10,27,tzinfo=timezone.utc),5,99,False)
        with tempfile.TemporaryDirectory() as root:
            store(root,[item,item]);store(root,[item])
            lines=(Path(root)/"data/lab/formats-2026-10.jsonl").read_text().splitlines()
            self.assertEqual(len(lines),1)
    def test_unknown_preserved_as_shape(self):
        x=inspect("Unrecognized market",datetime.now(timezone.utc),1,2,False)
        self.assertEqual(x["markets_mentioned"],[])
        self.assertFalse(x["legacy_parsed"])
if __name__=="__main__":unittest.main()
