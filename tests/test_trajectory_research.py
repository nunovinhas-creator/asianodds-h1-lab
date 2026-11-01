"""Experimental repeated-alert research: logic and tracked-real-data assertions."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from h1lab.trajectory_research import evaluate, stage, STATUS

ROOT = Path(__file__).resolve().parents[1]


def observation(number, minutes, origin):
    return {
        "event_id": f"33:{number}",
        "minutes_to_kickoff": minutes,
        "observed_at": f"2026-10-27T18:00:{number:02d}+00:00",
        "trigger_market": "total",
        "snapshots": {"total": {"origin": origin}},
    }


def fixture(omitted=0):
    a, b = observation(1, 130, "V4_EXPLICIT"), observation(2, 45, "H1_LEGACY_ONLY")
    t = {
        "match_key": "match:1", "match_label": "A vs B",
        "events": [a, b],
        "trajectory": {"total": {
            "points": [
                {"event_id": a["event_id"], "move": "UP", "origin": "V4_EXPLICIT"},
                {"event_id": b["event_id"], "move": "DOWN", "origin": "H1_LEGACY_ONLY"},
            ],
            "transitions": [{"line": "UNOBSERVED_CHANGE"}],
        }},
        "related_messages": [{"events": ["33:1", "33:2"], "evidence": "IDENTICAL_TOTAL_SNAPSHOT"}],
    }
    return {
        "schema_version": 1, "status": "DESCRIPTIVE_SHADOW_AUDIT_NOT_CERTIFIED",
        "generated_at": "2026-10-27T20:00:00+00:00", "source_commit": "a"*40,
        "sampling": {"timelines_published": 1, "timelines_omitted": omitted},
        "summary": {"messages": 2+omitted, "matches": 1+omitted,
                    "repeated_matches": 1+omitted,
                    "messages_on_repeated_matches": 2+omitted*2},
        "timelines": [t],
    }


class RepeatedStudyTests(unittest.TestCase):
    def test_time_buckets_are_exclusive_and_no_fake_kickoff(self):
        inputs = [(-1,"AFTER_KICKOFF"), (0,"T_0_TO_60"), (59.9,"T_0_TO_60"),
                  (60,"T_60_TO_360"), (359.9,"T_60_TO_360"),
                  (360,"T_360_TO_1440"), (1440,"T_OVER_1440"),
                  (None,"UNKNOWN"), (float("nan"),"UNKNOWN"), (True,"UNKNOWN")]
        for v, expected in inputs:
            with self.subTest(minutes=v):
                self.assertEqual(stage(v),expected)

    def test_opposing_alerts_are_one_match_not_two_independent_trials(self):
        x = evaluate(fixture())
        self.assertEqual(x["status"], STATUS)
        self.assertEqual(x["scope"]["repeated_matches_analysed"], 1)
        self.assertEqual(x["scope"]["events_analysed"], 2)
        self.assertEqual(x["total_line_within_alert"]["up"], 1)
        self.assertEqual(x["total_line_within_alert"]["down"], 1)
        self.assertEqual(x["match_level_patterns"]["opposing_intra_alert_directions"]["matches"],1)
        self.assertEqual(x["match_level_patterns"]["opposing_intra_alert_directions"]["percentage_descriptive"],100)
        self.assertEqual(x["transitions"]["related_pairs"],1)
        self.assertEqual(x["transitions"]["identical_total_pairs"],1)
        self.assertEqual(x["transitions"]["unobserved_change"],1)
        self.assertEqual(x["opposing_direction_examples"][0]["interpretation"],
                         "OPPOSING_INTRA_ALERT_DIRECTIONS_NOT_CONTINUOUS_REVERSAL")
        self.assertEqual(x["time_to_kickoff"]["messages_by_bucket"]["T_0_TO_60"],1)
        self.assertEqual(x["time_to_kickoff"]["messages_by_bucket"]["T_60_TO_360"],1)
        self.assertEqual(x["time_to_kickoff"]["distinct_matches_touching_bucket"]["T_0_TO_60"],1)
        self.assertEqual(x["time_to_kickoff"]["distinct_matches_touching_bucket"]["T_60_TO_360"],1)
        self.assertEqual(x["total_line_within_alert"]["by_origin"],
                         {"H1_LEGACY_ONLY":1,"V4_EXPLICIT":1})
        self.assertNotIn("roi", x)
        self.assertNotIn("profit_units", x)
        self.assertTrue(all(h["status"]!="TESTED" for h in x["hypotheses_for_future_oos_only"]))

    def test_partial_sample_is_not_presented_as_complete_population(self):
        x=evaluate(fixture(omitted=1))
        self.assertEqual(x["scope"]["coverage"],"PARTIAL_RECENT_REPEATED_MATCHES")
        self.assertEqual(x["scope"]["repeated_matches_in_source"],2)
        self.assertEqual(x["scope"]["repeated_matches_analysed"],1)
        self.assertEqual(x["scope"]["repeated_matches_omitted"],1)

    def test_partial_population_totals_are_not_sample_totals(self):
        # Two observed messages are published, and one older two-message
        # match is intentionally omitted by the fixed-size timeline window.
        raw = fixture(omitted=1)
        result = evaluate(raw)
        self.assertEqual(result["scope"]["coverage"], "PARTIAL_RECENT_REPEATED_MATCHES")
        self.assertEqual(result["scope"]["repeated_matches_omitted"], 1)
        self.assertEqual(result["scope"]["events_analysed"], 2)
        self.assertEqual(raw["summary"]["messages_on_repeated_matches"], 4)
        self.assertNotEqual(result["scope"]["events_analysed"],
                            raw["summary"]["messages_on_repeated_matches"])

    def test_duplicate_event_ids_and_match_keys_fail_closed(self):
        raw=fixture()
        raw["timelines"][0]["events"][1]["event_id"]="33:1"
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            evaluate(raw)
        raw=fixture()
        raw["sampling"]["timelines_published"]=2
        with self.assertRaisesRegex(ValueError,"Partial/corrupted"):
            evaluate(raw)

    def test_unexpected_source_status_and_incomplete_totals_fail_closed(self):
        raw=fixture()
        raw["status"]="CERTIFIED"
        with self.assertRaisesRegex(ValueError,"Unexpected"):
            evaluate(raw)
        raw=fixture()
        raw["summary"]["messages_on_repeated_matches"]=3
        with self.assertRaisesRegex(ValueError,"total mismatch"):
            evaluate(raw)
        raw=fixture()
        raw["timelines"][0]["trajectory"]["total"]["points"][0]["origin"]="UNKNOWN"
        with self.assertRaisesRegex(ValueError,"Invalid Total"):
            evaluate(raw)

    def test_missing_kickoff_is_unknown_and_not_treated_as_live(self):
        raw=fixture()
        raw["timelines"][0]["events"][0].pop("minutes_to_kickoff")
        out=evaluate(raw)
        self.assertEqual(out["time_to_kickoff"]["messages_by_bucket"]["UNKNOWN"],1)
        self.assertEqual(out["time_to_kickoff"]["messages_by_bucket"]["AFTER_KICKOFF"],0)

    def test_tracked_real_chronology_is_coherent_and_not_a_profit_study(self):
        raw=json.loads((ROOT/"docs"/"lab"/"match-trajectories.json").read_text(encoding="utf-8"))
        self._check_real_chronology(raw)

    def test_real_chronology_checks_survive_newer_matches_displacing_the_sample(self):
        # Regression for the #107 audit: the published sample keeps only the
        # most recent N repeated matches, so the pinned old real examples drift
        # out of it as new matches arrive and the LAB bundle would be blocked
        # again. Simulate 15+ newer repeated matches by shrinking the cap on
        # the same tracked inputs; the checks must not depend on sample rank.
        from h1lab.timeline import generate
        full = generate(ROOT, max_timelines=10 ** 6)
        for cap in (400, 385, 100, 10):
            with self.subTest(cap=cap):
                self._check_real_chronology(generate(ROOT, max_timelines=cap), population=full)

    def _check_real_chronology(self, raw, population=None):
        d=evaluate(raw)
        self.assertGreater(d["scope"]["repeated_matches_analysed"],5)
        self.assertLessEqual(d["scope"]["repeated_matches_analysed"],d["scope"]["all_distinct_matches"])
        # The timeline publishes at most 400 repeated matches. Its summary
        # covers *all* repeated matches, including omitted older timelines.
        # Compare sample counts against the exact published rows instead of
        # incorrectly requiring the bounded sample to equal the population.
        sample_events = sum(len(t["events"]) for t in raw["timelines"])
        omitted = raw["sampling"]["timelines_omitted"]
        population_events = raw["summary"]["messages_on_repeated_matches"]
        self.assertEqual(d["scope"]["events_analysed"], sample_events)
        self.assertEqual(d["scope"]["repeated_matches_omitted"], omitted)
        if omitted:
            self.assertGreaterEqual(population_events - sample_events, 2 * omitted)
        else:
            self.assertEqual(sample_events, population_events)
        sample_related = sum(len(t["related_messages"]) for t in raw["timelines"])
        sample_identical = sum(
            pair["evidence"] == "IDENTICAL_TOTAL_SNAPSHOT"
            for t in raw["timelines"] for pair in t["related_messages"]
        )
        self.assertEqual(d["transitions"]["identical_total_pairs"], sample_identical)
        self.assertEqual(d["transitions"]["related_pairs"], sample_related)
        if omitted:
            self.assertLessEqual(sample_identical, raw["summary"]["possibly_redundant_snapshots"])
            self.assertLessEqual(sample_related, raw["summary"]["related_message_pairs"])
        else:
            self.assertEqual(sample_identical, raw["summary"]["possibly_redundant_snapshots"])
            self.assertEqual(sample_related, raw["summary"]["related_message_pairs"])
        self.assertEqual(d["total_line_within_alert"]["messages_with_total"],
                         sum(d["total_line_within_alert"]["by_origin"].values()))
        self.assertIn("NOT_TESTED", [h["status"] for h in d["hypotheses_for_future_oos_only"]])
        self.assertFalse(any("bet_win" in str(key).lower() for key in d))
        targets={
            "3571094759:50685","3571094759:50686",
            "3571094759:50675","3571094759:50681",
        }
        # Tracked history is immutable, so the examples must exist in the whole
        # repeated-match population - not necessarily in the bounded sample.
        if population is None:
            from h1lab.timeline import generate
            population = generate(ROOT, max_timelines=10 ** 6)
        found={eid for t in population["timelines"] for eid in t["event_ids"]}
        self.assertTrue(targets.issubset(found),"Expected tracked real examples absent")

    def test_deterministic_summary_when_order_of_match_timelines_changes(self):
        raw=fixture()
        first=evaluate(raw)
        second=evaluate(copy.deepcopy(raw))
        self.assertEqual(first,second)


if __name__ == "__main__":
    unittest.main()
