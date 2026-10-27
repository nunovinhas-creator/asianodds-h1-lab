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
    def test_structural_v2(self):
        raw=("Team A vs Team B\n🏆 League\n🕒 28 Oct 18:00 UTC\n"
             "Total: 2.5 ↑ 2.75\nWas 2.5 1.9 1.9\nNow 2.75 1.8 2.0🔴\n"
             "1 → 1.8\nX 3.1 → 3.2\n2 4.2 → 4.5\nhttps://asianodds.com/fixture")
        item=inspect(raw,datetime(2026,10,27,tzinfo=timezone.utc),8,99,True)
        self.assertEqual(item["schema_version"],2)
        self.assertEqual(item["line_classes"],["VS","TROPHY","CLOCK",
            "HDR_TOTAL_UP","WAS:3","NOW:3","ARROW_ROW","ARROW_ROW","ARROW_ROW","URL"])
        self.assertNotIn("League",str(item))
        self.assertNotIn("Team A",str(item))
    def test_direction_and_emoji_shape(self):
        item=inspect("Total: 3.0 ↓ 2.75\n🔴 🔵",datetime(2026,10,27,tzinfo=timezone.utc),9,99,False)
        self.assertEqual(item["line_classes"],["HDR_TOTAL_DOWN","EMOJI"])

    def test_family_ignores_total_arrow(self):
        t=datetime(2026,10,27,tzinfo=timezone.utc)
        up=inspect("Total: 2.5 ↑ 2.75",t,41,99,True)
        down=inspect("Total: 2.5 ↓ 2.25",t,42,99,True)
        self.assertNotEqual(up["format_id"],down["format_id"])
        self.assertEqual(up["format_family_id"],down["format_family_id"])

    def test_unknown_preserved_as_shape(self):
        x=inspect("Unrecognized market",datetime.now(timezone.utc),1,2,False)
        self.assertEqual(x["markets_mentioned"],[])
        self.assertFalse(x["legacy_parsed"])
if __name__=="__main__":unittest.main()
