import unittest
from h1lab.intelligence import movement, project, build

class IntelligenceTests(unittest.TestCase):
    def test_direction_and_invalid(self):
        self.assertEqual(movement(2.0,1.8)["direction"],"down")
        self.assertEqual(movement(2.0,2.0)["direction"],"flat")
        self.assertIsNone(movement(None,2))
    def test_isolation_and_dedupe(self):
        alert={"event_id":"c:1","match_key":"g1","observed_at":"2026-10-27T14:00:00+00:00",
               "total_before":2.5,"total_after":2.75,"over_before":1.8,"over_after":1.9}
        state={"alerts":[alert,dict(alert)],"signals":[{"a":1}],"tickets":[{"b":2}]}
        before=repr(state)
        data=build(state,{"g1":{"home_goals":2,"away_goals":1}})
        self.assertEqual(data["coverage"]["unique_alerts"],1)
        self.assertEqual(data["coverage"]["matches_with_confirmed_ft"],1)
        self.assertEqual(data["movement_counts"]["total_line:up"],1)
        self.assertEqual(repr(state),before)
    def test_1x2_handicap(self):
        a=project({"one_x_two":{"X":{"before":3.4,"after":3.1}},
          "asian_handicap":{"before":{"line":-0.5},"after":{"line":-0.75}}})
        self.assertEqual(a["one_x_two"]["X"]["direction"],"down")
        self.assertEqual(a["asian_handicap"]["line"]["direction"],"down")

if __name__=="__main__": unittest.main()
