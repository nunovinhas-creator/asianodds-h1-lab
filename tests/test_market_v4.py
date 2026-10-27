import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from h1lab.market_v4 import parse, store

WHEN=datetime(2026,10,27,16,15,tzinfo=timezone.utc)
TOTAL_UP="""🔵 Kaizer Chiefs FC vs TS Galaxy FC
🏆 South Africa Telkom Knockout Cup
🕒 27 Oct 17:00 UTC
Total: 2.25 ↑ 2.50
⏱ last 2 min
Line   O   U
Was 2.25 1.83 2.02
Now 2.50 1.83 1.81🔴
"""
TOTAL_DOWN="""🔴 Al Shamal SC vs Al Hilal (KSA)
🏆 AFC Asian Champions League
🕒 27 Oct 18:15 UTC
Total: 3.50 ↓ 3.25
⏱ last 2 min
Line O U
Was 3.50 2.06 1.92
Now 3.25 1.88🔴 1.92
"""
MIXED="""🔴 FK Fakel Voronezh vs FK Akhmat Grozny
🏆 Russia Cup
🕒 27 Oct 15:00 UTC
1x2 (2): 2.46 ↓ 2.28 (-12.3%)
⏱ last 2 min
1 3.25 → 3.40🔵
X 3.25 → 3.26🔵
2 2.46 → 2.28🔴
Line H A
Was +0.25 1.86 2.08
Now +0.25 1.93🔵 1.96🔴
Line O U
Was 2.25 1.83 2.05
Now 2.25 1.82🔴 2.07🔵
"""

class MarketV4Tests(unittest.TestCase):
    def test_total_up(self):
        e=parse(TOTAL_UP,WHEN,10,33)
        self.assertEqual(e["trigger_market"],"total")
        self.assertEqual(e["markets"]["total"]["after"]["line"],2.5)
        self.assertFalse(e["markets"]["total"]["cross_line_prices_comparable"])
    def test_total_down(self):
        e=parse(TOTAL_DOWN,WHEN,11,33)
        self.assertEqual(e["markets"]["total"]["before"]["line"],3.5)
        self.assertEqual(e["markets"]["total"]["after"]["under_price"],1.92)
    def test_mixed_market(self):
        e=parse(MIXED,WHEN,12,33)
        self.assertEqual(set(e["markets"]),{"total","asian_handicap","one_x_two"})
        self.assertEqual(e["markets"]["one_x_two"]["2"]["after"],2.28)
        self.assertEqual(e["markets"]["asian_handicap"]["after"]["away_price"],1.96)
    def test_does_not_guess_missing_data(self):
        self.assertIsNone(parse("No odds here",WHEN,1,33))
        e=parse("Line O U\nWas 2.25 1.9 2.0\nNow 2.25 1.8 1.9",WHEN,2,33)
        self.assertNotIn("one_x_two",e["markets"])
        self.assertEqual(e["trigger_market"],"unknown")
    def test_monthly_idempotence(self):
        with tempfile.TemporaryDirectory() as d:
            e=parse(MIXED,WHEN,12,33)
            store(d,[e,e]);store(d,[e])
            dest=Path(d)/"data/lab/markets-2026-10.jsonl"
            lines=dest.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines),1)
            self.assertEqual(json.loads(lines[0])["schema_version"],4)
    def test_invalid_price_does_not_publish_table(self):
        text="Line O U\nWas 2.25 1.0 2.0\nNow 2.25 1.8 1.9"
        self.assertIsNone(parse(text,WHEN,14,33))
if __name__=="__main__":unittest.main()
