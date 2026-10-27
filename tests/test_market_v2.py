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
    def test_invalid_odds_and_lines(self):
        from h1lab.market_v2 import move
        for value in (0.5,1.0,-2,True,float("nan"),None):
            self.assertIsNone(move(value,1.9))
        self.assertIsNone(move(2.4,2.5,"asian_total_line"))
    def test_ah_line_changes_and_missing(self):
        ah=normalize_alert({"market":"1x2","asian_handicap":{
            "before":{"line":-0.5,"home_odds":1.9},
            "after":{"line":-0.75,"home_odds":1.8}}})
        self.assertTrue(ah["handicap"]["cross_line_odds_not_comparable"])
        blank=normalize_alert({"market":"total","total_before":None,"total_after":2.5})
        self.assertIsNone(blank["total"]["cross_line_odds_not_comparable"])
    def test_kickoff_boundary(self):
        base={"market":"total","kickoff_utc":"2026-10-27T16:00:00+00:00"}
        before=normalize_alert({**base,"observed_at":"2026-10-27T15:59:00+00:00"})
        after=normalize_alert({**base,"observed_at":"2026-10-27T16:01:00+00:00"})
        self.assertTrue(before["pre_kickoff"])
        self.assertFalse(after["pre_kickoff"])

    def test_matched_coverage_never_exceeds_100(self):
        s=summary([{"event_id":"a","match_key":"g","market":"total"}],
                  [{"event_id":"a","format_id":"x"},{"event_id":"b","format_id":"y"}])
        self.assertEqual(s["alerts_with_format"],1)
        self.assertEqual(s["format_to_alert_coverage_pct"],100.0)
        s2=summary([{"event_id":"a","match_key":"g","market":"total"}],
                   [{"event_id":"b","format_id":"y"}])
        self.assertEqual(s2["format_to_alert_coverage_pct"],0.0)

    def test_old_snapshots_share_structural_family(self):
        a={"event_id":"a","format_id":"up","line_classes":["VS","HDR_TOTAL_UP","WAS:3"]}
        b={"event_id":"b","format_id":"down","line_classes":["VS","HDR_TOTAL_DOWN","WAS:3"]}
        s=summary([], [a,b])
        self.assertEqual(s["distinct_formats"],1)
        self.assertEqual(s["distinct_directional_formats"],2)

    def test_dedup_and_unique_games(self):
        s=summary([{"event_id":"a","match_key":"g","market":"total"},
                   {"event_id":"b","match_key":"g","market":"1x2"}],
                  [{"event_id":"a","format_id":"f","legacy_parsed":True},
                   {"event_id":"a","format_id":"f","legacy_parsed":True}])
        self.assertEqual(s["unique_games"],1)
        self.assertEqual(s["format_observations"],1)
