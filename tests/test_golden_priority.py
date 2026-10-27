import copy
import unittest
from collections import Counter

from h1lab.golden_priority import build_priority_queue, classify_event, FEATURES


def item(eid, trigger, *, ah_changed=False, total_changed=False, match=None):
    mixed = trigger != "total"
    markets = {"total": {"before": {"line": 2.5},
                         "after": {"line": 2.75 if total_changed else 2.5},
                         "line_changed": total_changed}}
    if mixed:
        markets["asian_handicap"] = {
            "before": {"line": 0.5}, "after": {"line": 0.25 if ah_changed else 0.5},
            "line_changed": ah_changed}
        markets["one_x_two"] = {"1": {"before": 1.9, "after": 2.1}}
    return {"event_id": eid, "match_key": match or "match:"+eid,
            "trigger_market": "1x2" if mixed else "total",
            "observed_at": "2026-10-27T18:20:00+00:00",
            "parser_revision": "v4-provenance-1",
            "parser_commit": "a"*40, "markets": markets,
            "trigger": {"selection": trigger if mixed else None,
                        "before": 3.3, "after": 3.5}}


def legacy(eid, kind):
    return {"event_id": eid, "home": "Home " + eid, "away": "Away",
            "competition": "League", "market": kind}


class PriorityTests(unittest.TestCase):
    def test_unobserved_selection_X_is_gap_not_fabricated_candidate(self):
        records = [item("33:1", "1"), item("33:2", "2")]
        rows = [legacy(x["event_id"], "1x2") for x in records]
        output = build_priority_queue({"alerts": rows}, [], records, [], limit=5)
        self.assertIn("1x2_selection_X", output["not_observed_in_source"])
        self.assertEqual(output["feature_coverage"]["1x2_selection_X"]["observed_events"], 0)
        self.assertTrue(output["no_reference_values_prefilled"])
        self.assertTrue(all("markets" not in c for c in output["priorities"]))

    def test_rare_ah_and_total_change_are_prioritized(self):
        records = [
            item("33:1", "1", ah_changed=True),
            item("33:2", "2", total_changed=True),
            item("33:3", "1"),
            item("33:4", "1"),
        ]
        rows = [legacy(x["event_id"], "1x2") for x in records]
        already = [("r1.json", {"event_id": "33:3", "reviewer_code": "R1"})]
        output = build_priority_queue({"alerts": rows}, [], records, already, limit=3)
        ids = [x["event_id"] for x in output["priorities"]]
        self.assertEqual(set(ids[:2]), {"33:1", "33:2"})
        self.assertNotIn("33:3", ids)
        self.assertIn("ah_line_changed_in_1x2",
                      next(x for x in output["priorities"] if x["event_id"] == "33:1")["new_coverage"])
        self.assertEqual(output["reviewed_event_count"],1)

    def test_repeated_same_match_is_visible(self):
        records = [item("33:1", "1", match="same"),
                   item("33:2", "1", match="same"),
                   item("33:3", "1", match="different")]
        c=Counter(x["match_key"] for x in records)
        self.assertIn("same_match_repeated", classify_event(records[0], c))
        self.assertNotIn("same_match_repeated", classify_event(records[2], c))
        output=build_priority_queue(
            {"alerts":[legacy(x["event_id"],"1x2") for x in records]},[],records,[])
        self.assertEqual(output["feature_coverage"]["same_match_repeated"]["observed_events"],2)

    def test_missing_fixtures_never_became_actual_events(self):
        row = item("33:7", "X")
        self.assertEqual(build_priority_queue(
            {"alerts":[]},[],[row],[])["priorities"],[])
        self.assertRaises(ValueError, build_priority_queue, {"alerts":[]}, [], [], [], limit=0)

    def test_determinism_and_no_raw_source_or_prices_in_queue(self):
        records = [item("33:1","1",ah_changed=True),
                   item("33:2","2",total_changed=True)]
        state = {"alerts": [legacy(x["event_id"],"1x2") for x in records]}
        a=build_priority_queue(state,[],records,[],limit=3)
        b=build_priority_queue(copy.deepcopy(state),[],list(reversed(records)),[],limit=3)
        self.assertEqual(a,b)
        for c in a["priorities"]:
            self.assertNotIn("source_url",c)
            self.assertNotIn("markets",c)
            self.assertNotIn("odds",c)
            self.assertNotIn("source_text",c)

if __name__ == "__main__":
    unittest.main()
