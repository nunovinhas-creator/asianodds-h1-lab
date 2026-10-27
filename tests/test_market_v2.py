import unittest
from h1lab.market_v2 import normalize_alert,summary

class MarketV2Tests(unittest.TestCase):
    def test_total_cross_line_is_flagged(self):
        e=normalize_alert({"market":"total","total_before":2.5,"total_after":2.75,
                           "over_before":1.7,"over_after":1.9})
        self.assertTrue(e["total"]["cross_line_odds_not_comparable"])
        self.assertIsNone(e["btts"])
    def test_one_x_two_and_ah(self):
        e=normalize_alert({"market":"1x2","one_x_two":{"X":{"before":3.4,"after":3.0}},
             "asian_handicap":{"before":{"line":-0.5,"home_odds":1.9},"after":{"line":-0.75,"home_odds":1.8}}})
        self.assertEqual(e["one_x_two"]["X"]["direction"],"down")
        self.assertEqual(e["handicap"]["line"]["delta"],-0.25)
    def test_unknown_not_relabelled_as_total(self):
        e=normalize_alert({"market":"unknown","total_before":2,"total_after":3})
        self.assertIsNone(e["total"])
    def test_dedup_and_unique_games(self):
        s=summary([{"event_id":"a","match_key":"g","market":"total"},
                   {"event_id":"b","match_key":"g","market":"1x2"}],
                  [{"event_id":"a","format_id":"f","legacy_parsed":True},
                   {"event_id":"a","format_id":"f","legacy_parsed":True}])
        self.assertEqual(s["unique_games"],1)
        self.assertEqual(s["format_observations"],1)
