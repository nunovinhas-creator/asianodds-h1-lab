"""Tests for V6F2 features, source chronology and V5 hash compatibility."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from h1lab import pattern_engine, pattern_features
from h1lab.v6_features_v2 import build, verify, _handicap, FEATURE_VERSION
from h1lab.v6_shadow import captures, read_journal, append_journal
from h1lab.v6_science_memory import synchronize, rebuild, read_stream


KO = "2026-11-01T18:00:00+00:00"
KNOWN = "2026-11-01T16:00:00+00:00"
NOW = datetime(2026,11,1,16,tzinfo=timezone.utc)


def total(line1=2.5, line2=2.75, before_o=1.9, after_o=1.83):
    return {"origin":"V4_EXPLICIT",
            "before":{"line":line1,"over_price":before_o,"under_price":1.9},
            "after":{"line":line2,"over_price":after_o,"under_price":2.01}}


def ah(line1=-.75,line2=-1.0):
    return {"origin":"V4_EXPLICIT",
            "before":{"line":line1,"home_price":1.91,"away_price":1.91},
            "after":{"line":line2,"home_price":1.95,"away_price":1.88}}


def one():
    return {"origin":"V4_EXPLICIT",
            "1":{"before":1.99,"after":1.85},
            "X":{"before":3.80,"after":3.90},
            "2":{"before":4.00,"after":4.25}}


def event(id, observed, snaps):
    return {"event_id":id,"observed_at":observed,
            "minutes_to_kickoff":120, "snapshots":snaps}


def timeline(events, relations=()):
    return {"match_key":"demo","match_label":"A vs B",
        "identity":{"kickoff_utc":[KO],"kickoff_consistent":True,
                    "team_names_consistent":True,"per_message_conflicts":[]},
        "events":events,"related_messages":list(relations),
        "movement_episodes":[[e["event_id"]] for e in events]}


class V2SourceTests(unittest.TestCase):
    def test_signed_ah_and_joint_total_1x2_snapshot(self):
        a=event("t:1","2026-11-01T14:00:00+00:00",
                {"total":total(),"one_x_two":one(),"asian_handicap":ah()})
        d=build(timeline([a]),[a],known_at=KNOWN,competition="Portugal Cup")
        self.assertTrue(verify(d))
        self.assertEqual(d["version"],2)
        self.assertEqual(d["namespace"],"V6F2")
        self.assertEqual(d["last_observed"]["asian_handicap"]["towards"],"HOME")
        self.assertEqual(d["last_observed"]["asian_handicap"]["status"],"USABLE")
        self.assertEqual(d["competition"]["category_heuristic"],"CUP")
        self.assertEqual(d["total_1x2_relation"],"SAME_MESSAGE")
        self.assertEqual(d["coverage"]["co_observed_total_one_x_two"],1)
        self.assertIsNotNone(d["messages"][0]["total_1x2"]["one_x_two_delta_draw"])
        self.assertIsNone(d["messages"][0]["total_1x2"].get("prediction"))

    def test_separate_messages_never_claim_joint_quote(self):
        a=event("t:1","2026-11-01T14:00:00+00:00",{"total":total()})
        b=event("t:2","2026-11-01T15:00:00+00:00",{"one_x_two":one()})
        d=build(timeline([a,b]),[a,b],known_at=KNOWN)
        self.assertEqual(d["total_1x2_relation"],"SEPARATE_MESSAGES_ONLY")
        self.assertEqual(d["coverage"]["unobserved_inter_message_intervals"],1)
        self.assertEqual(d["inter_message_total"][0]["classification"],"MISSING_TOTAL_AT_BOUNDARY")
        self.assertIsNone(d["inter_message_total"][0]["inferred_movement"])
        self.assertEqual(d["competition"]["category_heuristic"],"UNKNOWN")

    def test_cross_line_repeated_price_unknown_not_fake_lambda(self):
        a=event("t:1","2026-11-01T14:00:00+00:00",
                {"total":total(before_o=1.9,after_o=1.9)})
        d=build(timeline([a]),[a],known_at=KNOWN)
        self.assertEqual(d["messages"][0]["total"]["status"],"CROSS_LINE_REPEATED_PRICE_SUSPECT")
        self.assertIsNone(d["messages"][0]["total"]["delta_lambda"])

    def test_unobserved_line_gap_never_interpolated(self):
        a=event("t:1","2026-11-01T13:00:00+00:00",{"total":total(2.5,2.5)})
        b=event("t:2","2026-11-01T15:00:00+00:00",{"total":total(3.0,3.25)})
        d=build(timeline([a,b]),[a,b],known_at=KNOWN)
        self.assertEqual(d["inter_message_total"][0]["classification"],"UNOBSERVED_LINE_GAP")
        self.assertIsNone(d["inter_message_total"][0]["inferred_movement"])

    def test_future_messages_rejected_without_any_backdating(self):
        a=event("t:1","2026-11-01T14:00:00+00:00",{"total":total()})
        future=event("t:2","2026-11-01T17:00:00+00:00",{"one_x_two":one()})
        with self.assertRaises(ValueError):
            build(timeline([a,future]),[a,future],known_at=KNOWN)
        # Captures itself must filter future message and related episodes.
        t=timeline([a,future],[{"events":["t:1","t:2"],"evidence":"link"}])
        rows=captures([t],NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["feature_context_v2"]["source_event_ids"],["t:1"])
        self.assertEqual(rows[0]["feature_context_v2"]["coverage"]["with_one_x_two"],0)

    def test_invalid_or_unknown_handicap_never_misclassified(self):
        bad=ah()
        bad["after"]["home_price"]=2.7
        bad["after"]["away_price"]=2.7
        self.assertEqual(_handicap(bad)["status"],"INCOMPLETE_OR_SUSPECT_QUOTE")
        self.assertEqual(_handicap(bad)["towards"],"UNKNOWN")
        self.assertEqual(_handicap(ah(-.5,-.75))["towards"],"HOME")

    def test_v5_feature_version_and_hash_not_changed(self):
        self.assertEqual(FEATURE_VERSION,2)
        self.assertEqual(pattern_features.FEATURE_VERSION,1)
        h={"op":"HAS","a":"G_MULTI_ALERT"}
        self.assertEqual(pattern_engine.hypothesis_id(h),
                         pattern_engine.hypothesis_id(h,feature_version=1))
        self.assertNotEqual(pattern_engine.definition_sha(h,feature_version=1),
                            pattern_engine.definition_sha(h,feature_version=2))

    def test_v2_hash_detects_tampering(self):
        a=event("t:1","2026-11-01T14:00:00+00:00",{"total":total()})
        d=build(timeline([a]),[a],known_at=KNOWN)
        d["coverage"]["with_total"]=100
        self.assertFalse(verify(d))

    def test_new_v2_in_memory_rebuild_old_without_v2_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old={
                "event_id":"t:old","match_key":"old","match_label":"Old",
                "known_at":"2026-10-28T15:00:00+00:00",
                "observed_at":"2026-10-28T14:00:00+00:00",
                "kickoff_utc":"2026-10-28T18:00:00+00:00",
                "price_quality":{"status":"USABLE"},"pattern_original_posthoc":False,
                "pattern_strict_posthoc":False,"market_probability_over_2_5":.5
            }
            append_journal(root,datetime(2026,10,28,15,tzinfo=timezone.utc),[old])
            a=event("t:1","2026-11-01T14:00:00+00:00",{"total":total()})
            rows=captures([timeline([a])],NOW)
            append_journal(root,NOW,rows)
            view,_=synchronize(root,NOW)
            self.assertEqual(view["stream_records"]["patterns"],2)
            patterns=read_stream(root,"patterns")
            self.assertNotIn("feature_context_v2_sha256",patterns[0]["event"])
            self.assertEqual(patterns[1]["event"]["feature_context_v2_sha256"],
                             read_journal(root)[1]["feature_context_v2"]["sha256"])
            self.assertEqual(view,rebuild(root))
            # source and summary remain identical on a second run
            again,changes=synchronize(root,NOW)
            self.assertEqual(view,again)
            self.assertTrue(all(n==0 for n in changes.values()))


if __name__=="__main__":
    unittest.main()
