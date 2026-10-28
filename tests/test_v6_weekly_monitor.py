"""Fixed-threshold weekly monitoring, FT chronology, and weekly replay tests."""
import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab.v6_weekly_monitor import (
    analyze, comparisons, date_week, week_summary, STATUS)
from scripts.lab_v6_weekly_monitor import run, read_snapshots

UTC=timezone.utc
REG={"registered_at":"2026-10-01T00:00:00+00:00","sha256":"a"*64}


def fixtures(week_begin, count, *, p, goals, bad=0):
    forecasts, events, formats=[],[],[]
    for i in range(count):
        kickoff=week_begin+timedelta(days=2,minutes=i)
        known=kickoff-timedelta(hours=2)
        quality="UNUSABLE" if i<bad else "USABLE"
        key=week_begin.strftime("%Y%m%d")+"-"+str(i)
        forecasts.append({
            "match_key":key,"event_id":"test:"+key,
            "sha256":hashlib.sha256(key.encode()).hexdigest(),
            "known_at":known.isoformat(),"kickoff_utc":kickoff.isoformat(),
            "price_quality":{"status":quality,
                             "flags":["negative_after_margin"] if quality=="UNUSABLE" else [],
                             "after":{"line":2.5}},
            "market_probability_over_2_5":p,
        })
        events.append({
            "sha256":hashlib.sha256(("FT:"+key).encode()).hexdigest(),
            "match_key":key,"recorded_at":(kickoff+timedelta(hours=5)).isoformat(),
            "source_last_checked_at":(kickoff+timedelta(hours=4)).isoformat(),
            "snapshot":{"status":"FINAL","score":{"home":goals[0],"away":goals[1]}}
        })
        formats.append({
            "event_id":"fmt:"+key,
            "observed_at":(kickoff-timedelta(hours=3)).isoformat(),
            "line_classes":["VS","HDR_TOTAL_UP","NOW:3"],"legacy_parsed":True
        })
    return forecasts,events,formats


class WeeklyMonitorTests(unittest.TestCase):
    def test_one_incomplete_week_has_no_false_drift(self):
        monday=datetime(2026,10,26,tzinfo=UTC)
        a,b,c=fixtures(monday,6,p=.51,goals=(3,1))
        r=analyze(a,b,c,REG,now=monday+timedelta(days=4))
        self.assertEqual(r["overall"],"INSUFFICIENT_HISTORY")
        self.assertEqual(r["last_comparable_completed_weeks"],[])
        self.assertTrue(all(v["status"]=="INSUFFICIENT_HISTORY"
                            for v in r["comparisons"].values()))
        self.assertEqual(r["weeks"][0]["period"],"CURRENT_INCOMPLETE")

    def test_two_full_weeks_market_format_and_calibration_drift(self):
        old=datetime(2026,10,5,tzinfo=UTC)
        nxt=datetime(2026,10,12,tzinfo=UTC)
        a,b,c=fixtures(old,120,p=.85,goals=(2,1))
        a2,b2,c2=fixtures(nxt,120,p=.15,goals=(2,1))
        for f in c2:
            f["line_classes"]=["TROPHY","HDR_1X2","WAS:7","OTHER","NOW:7"]
        now=datetime(2026,10,22,tzinfo=UTC)
        r=analyze(a+a2,b+b2,c+c2,REG,now=now)
        self.assertEqual(r["overall"],"SUSPECTED_DRIFT_REVIEW")
        self.assertEqual(r["comparisons"]["calibration"]["status"],"SUSPECTED_DRIFT_REVIEW")
        self.assertEqual(r["comparisons"]["market"]["status"],"SUSPECTED_DRIFT_REVIEW")
        self.assertEqual(r["comparisons"]["formats"]["status"],"SUSPECTED_DRIFT_REVIEW")
        self.assertEqual(r["comparisons"]["quality"]["status"],"NO_THRESHOLD_CROSSED")
        self.assertGreater(r["comparisons"]["calibration"]["value"],.5)
        self.assertEqual(r["weeks"][0]["calibration"]["n"],120)
        self.assertEqual(r["weeks"][1]["calibration"]["n"],120)

    def test_quality_drift_requires_fifty_per_completed_week(self):
        old=datetime(2026,10,5,tzinfo=UTC)
        nxt=datetime(2026,10,12,tzinfo=UTC)
        a,b,c=fixtures(old,55,p=.55,goals=(0,0))
        d,e,f=fixtures(nxt,55,p=.55,goals=(0,0),bad=25)
        r=analyze(a+d,b+e,c+f,REG,now=datetime(2026,10,22,tzinfo=UTC))
        self.assertEqual(r["comparisons"]["quality"]["status"],"SUSPECTED_DRIFT_REVIEW")
        self.assertEqual(r["weeks"][1]["quality"]["unusable"],25)
        self.assertEqual(r["weeks"][1]["calibration"]["n"],30)
        self.assertEqual(r["comparisons"]["calibration"]["status"],"INSUFFICIENT_N")

    def test_missing_ft_before_ko_and_pre_registration_never_in_calibration(self):
        old=datetime(2026,10,5,tzinfo=UTC)
        a,b,c=fixtures(old,4,p=.7,goals=(2,1))
        b.pop()  # one missing
        b[0]["source_last_checked_at"]=(old+timedelta(days=1)).isoformat()
        a[1]["known_at"]="2026-09-28T12:00:00+00:00"
        r=analyze(a,b,c,REG,now=datetime(2026,10,22,tzinfo=UTC))
        w=r["weeks"][0]["calibration"]
        self.assertEqual(w["n"],1)
        self.assertEqual(w["status"],"INSUFFICIENT_N")

    def test_no_duplicate_match_from_multiple_frozen_alerts(self):
        old=datetime(2026,10,5,tzinfo=UTC)
        a,b,c=fixtures(old,1,p=.8,goals=(2,1))
        later=dict(a[0],event_id="test:later",
                   known_at=(datetime.fromisoformat(a[0]["known_at"])+timedelta(minutes=15)).isoformat(),
                   market_probability_over_2_5=.9)
        r=analyze(a+[later],b,c,REG,now=datetime(2026,10,22,tzinfo=UTC))
        self.assertEqual(r["weeks"][0]["quality"]["n"],1)
        self.assertEqual(r["weeks"][0]["calibration"]["n"],1)
        self.assertEqual(r["weeks"][0]["calibration"]["mean_reference_p"],.9)

    def test_warmup_not_recast_as_stable(self):
        summary=week_summary("2026-W42",False,[],[],[])
        decision=comparisons(None,summary)
        self.assertTrue(all(v["status"]=="INSUFFICIENT_HISTORY" for v in decision.values()))
        self.assertIsNone(summary["calibration"]["brier_score"])

    def test_immutable_weekly_ledger_and_replay(self):
        monday=datetime(2026,10,26,tzinfo=UTC)
        fake={
            "schema_version":1,"status":STATUS,"monitor_week":date_week(monday),
            "as_of":monday.isoformat(),"overall":"INSUFFICIENT_HISTORY",
            "weeks":[],"comparisons":{},"input":{}}
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scripts.lab_v6_weekly_monitor.build",return_value=fake) as build:
            view,n=run(tmp,monday)
            self.assertEqual(n,1)
            self.assertEqual(view["snapshot_count"],1)
            again,n=run(tmp,monday+timedelta(days=3))
            self.assertEqual(n,0)
            self.assertEqual(again,view)
            self.assertEqual(build.call_count,1)
            verified,n=run(tmp,monday+timedelta(days=3),verify_only=True)
            self.assertEqual(verified,view)
            self.assertEqual(len(read_snapshots(tmp)),1)
            f=Path(tmp)/"data/lab/v6-weekly-snapshots.jsonl"
            f.write_text(f.read_text().replace("INSUFFICIENT_HISTORY","VALIDADO",1))
            with self.assertRaises(ValueError):
                read_snapshots(tmp)


if __name__=="__main__":
    unittest.main()
