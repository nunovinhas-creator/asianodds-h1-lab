"""P0 scientific gate tests: null simulations cannot certify observed edge."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import v6_null_simulation as sim
from h1lab.v6_p0_gates import ft_chronology, _daily

UTC=timezone.utc


class P0SimulationTests(unittest.TestCase):
    def test_prespecified_design_and_no_data_outcomes(self):
        s=sim.settings()
        self.assertEqual(s["null_trials"],10000)
        self.assertEqual(s["checkpoints"][-1],1000)
        self.assertEqual(s["alpha_single_registered_hypothesis"],.005)
        self.assertIn("NOT fitted",s["design_assumption"])  # synthetic-only design

    def test_replay_seed_and_every_look_optional_hit(self):
        a=sim._paths(30,0,123)
        self.assertEqual(a,sim._paths(30,0,123))
        self.assertEqual(a["paths"],30)
        self.assertEqual(a["anytime_by_checkpoint"][-1]["crossings"],
                         a["ever_hit_at_any_look"])
        self.assertTrue(all(x["crossings"]<=y["crossings"] for x,y in zip(
            a["anytime_by_checkpoint"],a["anytime_by_checkpoint"][1:])))
        self.assertLessEqual(a["full_v6_rule_at_final_1000"],a["ever_hit_at_any_look"])

    def test_power_paths_are_distinct_from_null_and_never_oos_claims(self):
        a=sim._paths(100,0.10,123456)
        b=sim._paths(100,0.10,123456)
        self.assertEqual(a,b)
        self.assertEqual(a["anytime_by_checkpoint"][-1]["n"],1000)
        self.assertEqual(sim.wilson_upper(0,10000)>0,True)
        with self.assertRaises(ValueError):
            sim.wilson_upper(10,5)

    def test_ft_evidence_temporal_proof_and_quarantine(self):
        ko=datetime(2026,10,28,12,tzinfo=UTC)
        known=(ko-timedelta(hours=1)).isoformat()
        frozen=[{"match_key":"one","event_id":"x:1","sha256":"abc",
                 "known_at":known,"kickoff_utc":ko.isoformat()}]
        entry={"event":{"match_key":"one","event_id":"FT:1",
                        "state":"CONFIRMED","frozen_source_sha256":"abc",
                        "ft_checked_at":(ko+timedelta(hours=2)).isoformat()},
               "written_at":(ko+timedelta(hours=3)).isoformat()}
        result=ft_chronology(frozen,[entry],ko-timedelta(hours=2),ko+timedelta(hours=4))
        self.assertEqual(result["latest_temporally_consistent_ft_matches"],1)
        self.assertEqual(result["exceptions_total"],0)
        entry["event"]["ft_checked_at"]=(ko+timedelta(minutes=20)).isoformat()
        result=ft_chronology(frozen,[entry],ko-timedelta(hours=2),ko+timedelta(hours=4))
        self.assertEqual(result["latest_temporally_consistent_ft_matches"],0)
        self.assertEqual(result["counts"]["confirmed_event_chronology_invalid"],1)
        self.assertIn("NO_POST_90MIN_FT_CHECK",result["exceptions"][0]["failure_codes"])

    def test_never_accept_pre_registered_or_after_ko_freeze(self):
        ko=datetime(2026,10,28,12,tzinfo=UTC)
        frozen=[{"match_key":"x","event_id":"x","sha256":"sha",
                 "known_at":(ko+timedelta(minutes=5)).isoformat(),
                 "kickoff_utc":ko.isoformat()}]
        entry={"event":{"match_key":"x","event_id":"FT","state":"CONFIRMED",
                        "frozen_source_sha256":"sha",
                        "ft_checked_at":(ko+timedelta(hours=2)).isoformat()},
               "written_at":(ko+timedelta(hours=3)).isoformat()}
        result=ft_chronology(frozen,[entry],ko-timedelta(days=1),ko+timedelta(hours=4))
        self.assertEqual(result["registered_eligible_finished_matches"],0)
        self.assertEqual(result["latest_temporally_consistent_ft_matches"],0)
        self.assertIn("NOT_REGISTERED_PREKICKOFF",result["exceptions"][0]["failure_codes"])

    def test_cli_stores_second_precision_and_replays_exactly(self):
        from scripts.lab_v6_p0 import main
        def fake_evaluate(root, now):
            return {
                "evaluation_clock":now.isoformat(timespec="seconds"),
                "evaluation_clock_microsecond":now.microsecond,
                "gates":{"7_days":{"status":"WARMUP"},"14_days":{"status":"WARMUP"}},
                "ft_knowledge_timeline":{"latest_temporally_consistent_ft_matches":0},
                "scientific_state":"INCONCLUSIVO",
            }
        fake_null={"null":{"paths":10_000,"ever_hit_at_any_look":38}}
        with tempfile.TemporaryDirectory() as temp, patch(
                "scripts.lab_v6_p0.evaluate", side_effect=fake_evaluate), patch(
                "scripts.lab_v6_p0.run_nulls", return_value=fake_null), patch(
                "scripts.lab_v6_p0.validate_null"):
            first=main(["--root",temp])
            self.assertEqual(first["gates"]["evaluation_clock_microsecond"],0)
            replay=main(["--root",temp,"--verify-only"])
            self.assertEqual(first,replay)

    def test_seven_day_source_coverage_never_equals_git_delivery_proof(self):
        t={"match_key":"x","identity":{"kickoff_utc":["2026-11-01T13:00:00Z"],
             "kickoff_consistent":True,"team_names_consistent":True,
             "per_message_conflicts":[]},
             "events":[{"observed_at":"2026-10-30T00:00:00Z"}]}
        f=[{"match_key":"x","known_at":"2026-10-28T15:00:00Z",
            "kickoff_utc":"2026-11-01T13:00:00Z"}]
        days=_daily([t],f,datetime(2026,11,2,tzinfo=UTC),
                    datetime(2026,10,28,15,tzinfo=UTC),7)
        self.assertEqual(days["2026-11-01"]["captured"],1)
