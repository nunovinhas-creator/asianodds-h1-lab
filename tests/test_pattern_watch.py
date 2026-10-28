"""V5 prospective movement watch: regression without HTTP, H1 edits or FT."""
import copy
import unittest
from datetime import datetime, timezone, timedelta

from h1lab.pattern_watch import build, classify, inspect

NOW = datetime(2026, 10, 28, 12, 16, 30, tzinfo=timezone.utc)
KICKOFF = "2026-10-28T19:00:00+00:00"


def metric(d):
    return {"dlam": d}


def event(event_id, observed_at, over_before=1.95, over_after=1.78, total=True):
    snapshots = {}
    if total:
        snapshots["total"] = {
            "before": {"line": 2.75, "over_price": over_before, "under_price": 1.85},
            "after": {"line": 2.75, "over_price": over_after, "under_price": 2.05},
            "origin": "V4_EXPLICIT",
        }
    return {
        "event_id": event_id, "observed_at": observed_at,
        "minutes_to_kickoff": (datetime.fromisoformat(KICKOFF) -
                              datetime.fromisoformat(observed_at)).total_seconds() / 60,
        "snapshots": snapshots,
    }


def timeline(key="2026-10-28,30,40", duplicate=False, no_total=False, future_event=False):
    items = [
        event("abc:1", "2026-10-28T10:00:00+00:00"),
        event("abc:2", "2026-10-28T11:30:00+00:00",
              over_before=1.94, over_after=1.80, total=not no_total),
    ]
    if future_event:
        items.append(event("abc:3", "2026-10-28T12:30:00+00:00"))
    return {"match_key": key, "match_label": "Test Home vs Test Away",
            "identity": {"kickoff_utc": [KICKOFF], "kickoff_consistent": True,
                         "team_names_consistent": True, "per_message_conflicts": []},
            "events": items,
            "movement_episodes": ([["abc:1", "abc:2"], ["abc:3"]]
                                  if duplicate else [["abc:1"], ["abc:2"], ["abc:3"]])}


class WatchTests(unittest.TestCase):
    def test_classification_boundary(self):
        self.assertEqual(classify([metric(.10), metric(.05)], [1,2])["category"],
                         "RISING_EACH_EPISODE")
        self.assertEqual(classify([metric(.10), metric(-.01)], [1,2])["category"],
                         "RISING_WITH_FLAT")
        self.assertEqual(classify([metric(.01), metric(-.049)], [1,2])["category"],
                         "FLAT_EACH_EPISODE")
        c=classify([metric(.12), metric(-.05)], [1,2])
        self.assertEqual(c["category"], "OPPOSING_DIRECTIONS")
        self.assertFalse(c["original"])
        c=classify([metric(.10),metric(.11)], [1,1])
        self.assertEqual(c["category"], "POSSIBLE_DUPLICATE")
        self.assertTrue(c["original"])
        self.assertFalse(c["strict"])
        c=classify([metric(.1), metric(None)], [1,2])
        self.assertEqual(c["category"], "INCOMPLETE_TOTAL")
        self.assertTrue(c["original"])   # original V5 silently treats None as no DOWN
        self.assertFalse(c["strict"])

    def test_reuse_v5_lambda_and_no_future_information(self):
        t=timeline(future_event=True)
        row=inspect(t, NOW)
        self.assertEqual(row["messages"],2)
        self.assertEqual(row["episodes"],2)
        self.assertTrue(row["strict_condition"])
        self.assertEqual(row["category"],"RISING_EACH_EPISODE")
        self.assertEqual(row["v4_total_count"],2)
        self.assertEqual(row["total_line_before"], 2.75)
        self.assertEqual(row["total_line_after"], 2.75)
        self.assertEqual(row["total_line_origin"], "V4_EXPLICIT")
        self.assertEqual(len(row["observations"]),2)
        self.assertTrue(all(x["delta_lambda"] is not None for x in row["observations"]))
        self.assertTrue(all(datetime.fromisoformat(x["observed_at"]) <= NOW for x in row["observations"]))

    def test_total_line_from_last_known_snapshot_and_not_future_message(self):
        t = timeline(future_event=True)
        # The latest message available before NOW changes the Asian Total line.
        t["events"][1]["snapshots"]["total"]["before"]["line"] = 2.5
        # This later message is not known yet and must not influence the alert.
        t["events"][2]["snapshots"]["total"]["after"]["line"] = 4.0
        row = inspect(t, NOW)
        self.assertTrue(row["strict_condition"])
        self.assertEqual(row["total_line_before"], 2.5)
        self.assertEqual(row["total_line_after"], 2.75)

    def test_missing_total_line_stays_unknown(self):
        t = timeline()
        t["events"][-1]["snapshots"].pop("total")
        row = inspect(t, NOW)
        self.assertFalse(row["strict_condition"])
        self.assertIsNone(row["total_line_after"])

    def test_group_duplicates_and_missing_total(self):
        duplicate=inspect(timeline(duplicate=True),NOW)
        self.assertEqual(duplicate["category"],"POSSIBLE_DUPLICATE")
        self.assertFalse(duplicate["strict_condition"])
        missing=inspect(timeline(no_total=True),NOW)
        self.assertEqual(missing["category"],"INCOMPLETE_TOTAL")
        self.assertFalse(missing["strict_condition"])

    def test_invalid_identity_and_future_gate(self):
        t=timeline()
        t["identity"]["team_names_consistent"]=False
        self.assertIsNone(inspect(t,NOW))
        self.assertIsNone(inspect(timeline(),datetime(2026,10,28,20,tzinfo=timezone.utc)))

    def test_first_detection_is_immutable_after_new_preko_message(self):
        t=timeline()
        first, history=build([t],NOW)
        self.assertEqual(first["summary"]["strict_eligible"],1)
        self.assertEqual(len(history["entries"]),1)
        frozen=copy.deepcopy(history["entries"][0])
        t["events"].append(event("abc:4","2026-10-28T12:45:00+00:00"))
        t["movement_episodes"].append(["abc:4"])
        _,later=build([t],NOW + timedelta(hours=1),history)
        self.assertEqual(later["entries"],history["entries"])
        self.assertEqual(later["entries"][0],frozen)

    def test_observation_only_and_no_histories_from_non_strict(self):
        t=timeline(duplicate=True)
        report,hist=build([t],NOW)
        self.assertEqual(report["status"],"PROSPECTIVE_OBSERVATION_NOT_VALIDATED_NOT_BETTING")
        self.assertEqual(report["summary"]["original_condition"],1)
        self.assertEqual(report["summary"]["strict_eligible"],0)
        self.assertEqual(report["summary"]["possible_duplicate_or_incomplete"],1)
        self.assertEqual(hist["entries"],[])
        for prohibited in ("pick", "ev", "roi", "odds", "profit"):
            self.assertNotIn(prohibited, report["summary"])

    def test_synthetic_date_replay_does_not_include_matches_not_yet_observed(self):
        t=timeline(future_event=True)
        report,_=build([t],NOW)
        observations=report["future_strict"][0]["observations"]
        self.assertEqual([e["event_id"] for e in observations],["abc:1","abc:2"])


if __name__ == "__main__":
    unittest.main()
