"""V6.2 Radar: source hashes, two-click evidence, no false V5 promotion."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_shadow import append_journal, read_journal
from h1lab.v6_science_memory import synchronize as science_sync, read_stream
from h1lab.v6_ft_events import synchronize as ft_sync
from h1lab.v4_revisions import append as v4_append
from h1lab.v6_scientific_radar import build, MAX_ACTIVE, STATUS
from scripts.lab_v6_scientific_radar import main

NOW=datetime(2026,10,29,22,tzinfo=timezone.utc)
KO="2026-10-29T18:00:00+00:00"
KNOWN="2026-10-29T16:00:00+00:00"
EID="12345:99"
KEY="test-2026-10-29-fixture"


def fixture(root, *, has_ft=True, with_v4=False):
    root=Path(root)
    record={
        "match_key":KEY,"match_label":"Clube A vs Clube B",
        "event_id":EID,"kickoff_utc":KO,
        "known_at":KNOWN,"observed_at":"2026-10-29T15:50:00+00:00",
        "price_quality":{"status":"USABLE","flags":[],
                         "after":{"line":2.5,"over_price":1.90,"under_price":1.90}},
        "market_probability_over_2_5":.51,
        "pattern_original_posthoc":True,"pattern_strict_posthoc":False,
        "hypothesis_id":"V6-POSTHOC-20261028-NO-DOWN",
        "forecast_kind":"MARKET_BASELINE_ONLY",
        "model_delta_vs_market":0.0,
    }
    append_journal(root,datetime(2026,10,29,16,tzinfo=timezone.utc),[record])
    if with_v4:
        row={
            "schema_version":4,"event_id":EID,
            "observed_at":"2026-10-29T15:50:00+00:00",
            "markets":{"total":{"after":{"line":2.5,"over_price":1.9,"under_price":1.9}}}}
        v4_append(root,{},[row],now=datetime(2026,10,29,15,59,tzinfo=timezone.utc))
        p=root/"data/lab/markets-2026-10.jsonl"
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(row)+"\n",encoding="utf-8")
    result = {"home_goals":2,"away_goals":1,
              "source":"https://example.org/ft","evidence":"bsd_and_goal"}
    entry={
        "status":"FINAL" if has_ft else "PENDING",
        "home":"Clube A","away":"Clube B","kickoff_utc":KO,
        "checked_at":"2026-10-29T21:00:00+00:00",
        "reason":"ft_recorded_with_source" if has_ft else "awaiting_ft",
    }
    if has_ft:
        entry["result"]=result
    ledger={"schema_version":1,"matches":{KEY:entry}}
    p=root/"data/lab/ft-ledger.json";p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(ledger),encoding="utf-8")
    science_sync(root,NOW)
    ft_sync(root,ledger,NOW)


class ScientificRadarTests(unittest.TestCase):
    def test_radar_joins_forecast_and_immutable_ft_not_fake_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            d=build(tmp)
            self.assertEqual(d["status"],STATUS)
            self.assertEqual(d["active_hypotheses"],1)
            self.assertEqual(d["totals"]["frozen_snapshots"],1)
            h=d["hypotheses"][0]
            self.assertEqual(h["state"],"INCONCLUSIVO")
            self.assertEqual(h["frozen_matches"],1)
            self.assertEqual(h["ft_verified"],1)
            g=h["games"][0]
            self.assertEqual(g["ft"]["score"]["home"],2)
            self.assertEqual(g["ft"]["score"]["away"],1)
            self.assertEqual(g["ft"]["evidence_level"],"MULTI_PROVIDER")
            self.assertEqual(g["ft"]["status"],"FINAL_WITH_AFTER_KICKOFF_VERIFICATION")
            self.assertEqual(g["forecast"]["sha256"],read_journal(tmp)[0]["sha256"])
            self.assertEqual(g["source_v4"]["status"],"V4_HISTORY_NOT_PROVEN_AT_FREEZE")
            self.assertEqual(g["ft"]["science_status"],"SCIENCE_FT_CONFIRMED")
            self.assertEqual(g["falsification_checks"] if "falsification_checks" in g else [],
                             [])
            self.assertLessEqual(d["active_hypotheses"],MAX_ACTIVE)

    def test_radar_shows_no_ft_not_as_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp,has_ft=False)
            d=build(tmp)
            h=d["hypotheses"][0]
            self.assertEqual(h["ft_verified"],0)
            self.assertIsNone(h["games"][0]["ft"]["score"])
            self.assertEqual(h["games"][0]["ft"]["status"],"PENDING")

    def test_v4_only_if_evidence_stored_before_frozen_known_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp,with_v4=True)
            g=build(tmp)["hypotheses"][0]["games"][0]
            self.assertEqual(g["source_v4"]["status"],"V4_VERSION_VERIFIED_BEFORE_FREEZE")
            self.assertEqual(g["source_v4"]["markets"]["total"]["after"]["line"],2.5)

    def test_stale_falsification_report_is_not_displayed_as_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            report={
                "data_lineage":{"forecast_journal_tail":"a"*64,
                                "memory_evidence_tail":None},
                "hypothesis_definition_sha256":read_stream(tmp,"hypotheses")[0]["event"]["definition_sha256"],
                "checks":[{"code":"F01","result":"PASS","n":10000,"required":"1"}]
            }
            p=Path(tmp)/"docs/lab/v6-falsification.json"
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(report),encoding="utf-8")
            h=build(tmp)["hypotheses"][0]
            self.assertEqual(h["falsification_status"],"STALE_RELATIVE_TO_IMMUTABLE_JOURNALS")
            self.assertEqual(h["falsification_checks"],[])

    def test_tampered_memory_raises_instead_of_writing_fake_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            f=next((Path(tmp)/"data/lab").glob("v6-memory-patterns-*.jsonl"))
            f.write_text(f.read_text().replace("true","false",1),encoding="utf-8")
            with self.assertRaises(ValueError):
                build(tmp)

    def test_report_replay_and_source_chain_tails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            d=main(["--root",tmp])
            self.assertEqual(d,main(["--root",tmp,"--verify-only"]))
            self.assertEqual(d["source_tails"]["forecasts"],read_journal(tmp)[-1]["sha256"])
            self.assertEqual(d["source_tails"]["observations"],read_stream(tmp,"observations")[-1]["sha256"])
            self.assertEqual(d["memory_validation"],"V6_SCIENCE_MEMORY_SHADOW_WARMUP_NOT_VALIDATED")


if __name__=="__main__":
    unittest.main()
