"""V6 P1 #9 — immutable FT evidence and bounded scientific lookup priority."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_ft_events import (synchronize, read_events, quality,
                                priority_hints, validate_against_ledger)
from h1lab.v6_shadow import append_journal
from h1lab.lab_results import reconcile

NOW = datetime(2026, 10, 28, 16, tzinfo=timezone.utc)
KO = "2026-10-27T12:00:00+00:00"


def game(status="PENDING", *, goals=None, evidence="api_football_only",
         reason="awaiting_ft"):
    row = {"status": status, "home":"Home", "away":"Away", "kickoff_utc": KO,
           "reason": reason, "checked_at":"2026-10-28T15:00:00+00:00",
           "attempts":3}
    if status=="FINAL":
        h,a=goals or (2,1)
        row["result"]={"home_goals":h,"away_goals":a,
                       "source":"https://example.org/final","evidence":evidence}
    return row


def ledger(**matches):
    return {"schema_version":1,"matches":matches}


class FTJournalTests(unittest.TestCase):
    def test_initial_snapshot_is_not_fake_historical_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            l=ledger(a=game("FINAL"),b=game())
            view,n=synchronize(tmp,l,NOW)
            self.assertEqual(n,2)
            self.assertEqual(view["confirmed_scores"],1)
            self.assertEqual(view["matches"],2)
            self.assertTrue(all(e["event_type"]=="INITIAL_LEDGER_OBSERVATION"
                                for e in read_events(tmp)))
            self.assertTrue(all(e["recorded_at"]==NOW.isoformat(timespec="seconds")
                                for e in read_events(tmp)))
            self.assertTrue(validate_against_ledger(read_events(tmp),l))

    def test_idempotent_and_repeated_attempts_do_not_create_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            l=ledger(a=game("FINAL"))
            synchronize(tmp,l,NOW)
            l["matches"]["a"]["attempts"]=12
            l["matches"]["a"]["checked_at"]="2026-10-28T15:55:00+00:00"
            v,n=synchronize(tmp,l,NOW)
            self.assertEqual(n,0)
            self.assertEqual(v["events_total"],1)
            same,_=synchronize(tmp,l,NOW,verify_only=True)
            self.assertEqual(v,same)

    def test_final_revision_then_quarantine_then_recovery_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            l=ledger(a=game("FINAL"))
            synchronize(tmp,l,NOW)
            first=read_events(tmp)[0]
            l["matches"]["a"]=game("FINAL",goals=(1,0))
            synchronize(tmp,l,NOW)
            l["matches"]["a"]=game("SCORE_CONFLICT",reason="conflicting_providers")
            synchronize(tmp,l,NOW)
            l["matches"]["a"]=game("FINAL",goals=(1,0),
                                   evidence="api_football_and_goal")
            report,n=synchronize(tmp,l,NOW)
            self.assertEqual(n,1)
            self.assertEqual(report["events_total"],4)
            self.assertEqual(report["confirmed_scores"],1)
            events=read_events(tmp)
            self.assertEqual(events[0],first)
            self.assertEqual([e["event_type"] for e in events],
                             ["INITIAL_LEDGER_OBSERVATION","FINAL_REVISED",
                              "RESULT_QUARANTINED","NEW_FINAL"])
            self.assertEqual(events[-1]["snapshot"]["evidence_level"],"MULTI_PROVIDER")
            self.assertEqual(events[-1]["previous_match_event_id"],events[-2]["id"])

    def test_quality_tiers_do_not_conflate_two_reviewed_urls_and_two_apis(self):
        self.assertEqual(quality(game("FINAL")),"SINGLE_PROVIDER")
        self.assertEqual(quality(game("FINAL",evidence="bsd_and_thesportsdb")),"MULTI_PROVIDER")
        reviewed=game("FINAL",evidence="reviewed_public_only")
        reviewed["reviewed_public_resolution"]={"corroboration_urls":
                                               ["https://example.org/a","https://example.org/b"]}
        self.assertEqual(quality(reviewed),"REVIEWED_PUBLIC_CORROBORATED")
        self.assertEqual(quality(game("SCORE_CONFLICT")),"QUARANTINED")

    def test_hash_or_lineage_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            l=ledger(a=game("FINAL"))
            synchronize(tmp,l,NOW)
            f=next((Path(tmp)/"data/lab").glob("v6-ft-events-*.jsonl"))
            f.write_text(f.read_text().replace("FINAL","PENDING",1),encoding="utf-8")
            with self.assertRaises(ValueError):
                read_events(tmp)

    def test_verify_only_refuses_unpublished_ledger_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            l=ledger(a=game("FINAL"))
            synchronize(tmp,l,NOW)
            l["matches"]["a"]=game("FINAL",goals=(0,0))
            with self.assertRaises(ValueError):
                synchronize(tmp,l,NOW,verify_only=True)
            self.assertEqual(len(read_events(tmp)),1)

    def test_model_hints_only_from_true_preko_frozen_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap={"match_key":"key","event_id":"v4:1",
                  "known_at":"2026-10-28T15:00:00+00:00",
                  "observed_at":"2026-10-28T14:00:00+00:00",
                  "kickoff_utc":"2026-10-28T17:00:00+00:00",
                  "price_quality":{"status":"USABLE"},
                  "pattern_original_posthoc":True,"pattern_strict_posthoc":True}
            append_journal(tmp,NOW,[snap])
            self.assertEqual(priority_hints(tmp),{"key":3})


class PriorityTests(unittest.TestCase):
    def test_priority_changes_order_not_budget_or_eligibility(self):
        st={"alerts":[{"match_key":k,"home":"H","away":"A",
                       "kickoff_utc":KO} for k in ("a","b","c")],"signals":[]}
        calls=[]
        def no_result(signal):
            calls.append(signal["match_key"])
            return None,"no_exact_match"
        kw={"now":NOW,"bsd_lookup":no_result,"tsdb_lookup":no_result,"max_checks":1}
        base,rept,n=reconcile(st,[],ledger(),**kw)
        self.assertEqual((n,calls), (1,["a","a"]))
        calls.clear()
        later,rept2,n2=reconcile(st,[],ledger(),priority_hints={"c":3},**kw)
        self.assertEqual((n2,calls), (1,["c","c"]))
        self.assertEqual(rept2["v6_ft_priority"]["hinted_selected"],1)
        self.assertEqual(rept2["v6_ft_priority"]["budget"],1)

    def test_cooldown_and_grace_cannot_be_bypassed(self):
        recent=game(status="PENDING")
        recent["checked_at"]="2026-10-28T15:59:00+00:00"
        recent["lookup_source_version"]=11
        st={"alerts":[{"match_key":"a","home":"Home","away":"Away","kickoff_utc":KO}],
            "signals":[]}
        calls=[]
        def lookup(signal):
            calls.append(signal)
            return None,"missing"
        _,_,n=reconcile(st,[],ledger(a=recent),now=NOW,bsd_lookup=lookup,
                        tsdb_lookup=lookup,max_checks=1,priority_hints={"a":3},
                        lookup_source_version=11)
        self.assertEqual(n,0)
        self.assertEqual(calls,[])


if __name__=="__main__":
    unittest.main()
