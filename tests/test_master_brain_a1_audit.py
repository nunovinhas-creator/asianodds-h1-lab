"""Adversarial read-only A1 audit tests; no LLM or provider calls."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.master_brain_a1_audit import audit, ft_rows, main, missing_reason, rates

KO = "2026-11-01T12:00:00+00:00"
BEFORE = "2026-11-01T11:00:00+00:00"
AFTER = "2026-11-01T14:00:00+00:00"


def timeline():
    return {"identity": {"kickoff_utc": [KO], "kickoff_consistent": True,
                         "team_names_consistent": True, "per_message_conflicts": []},
            "events": [{"observed_at": BEFORE}]}


def receipt(when=BEFORE, kind="FIRST_SEEN_BY_COLLECTOR"):
    return {"known_at": when, "kind": kind}


class MissingDataTests(unittest.TestCase):
    def test_no_receipt_is_unknown_not_synthetic_arrival(self):
        self.assertEqual(missing_reason(timeline(), [], []), "NO_FIRST_COLLECTOR_RECORD")
        self.assertEqual(missing_reason(timeline(), [], [receipt(kind="HISTORICAL_BASELINE_IMPORT")]),
                         "NO_FIRST_COLLECTOR_RECORD")

    def test_kickoff_is_not_pre_kickoff(self):
        for when in (KO, AFTER):
            self.assertEqual(missing_reason(timeline(), [], [receipt(when)]),
                             "FIRST_COLLECTOR_RECORD_AT_OR_AFTER_KICKOFF")

    def test_early_receipt_without_freeze_is_not_coverage(self):
        self.assertEqual(missing_reason(timeline(), [], [receipt()]),
                         "PREKICKOFF_COLLECTOR_RECORD_WITHOUT_FREEZE")

    def test_identity_and_alignment_fail_closed(self):
        t = timeline()
        t["identity"]["per_message_conflicts"] = ["event"]
        self.assertEqual(missing_reason(t, [], [receipt()]), "IDENTITY_OR_KICKOFF_CONFLICT")
        self.assertEqual(missing_reason(timeline(), [{"kickoff_utc": AFTER}], [receipt()]),
                         "FORECAST_KICKOFF_ALIGNMENT_CONFLICT")

    def test_missing_source_timestamp_is_not_invented(self):
        t = timeline()
        t["events"] = [{"observed_at": None}]
        self.assertEqual(missing_reason(t, [], [receipt()]), "SOURCE_WITHOUT_PREKICKOFF_EVIDENCE")

    def test_market_denominators_are_match_level_and_explicit(self):
        rows = [{"markets": ["total", "asian_handicap"], "frozen_pre_kickoff": True,
                 "quarantined_or_conflicting": True},
                {"markets": ["total"], "frozen_pre_kickoff": False,
                 "quarantined_or_conflicting": False}]
        r = rates(rows, "markets")
        self.assertEqual(r["total"]["source_eligible"], 2)
        self.assertEqual(r["total"]["ratio"], .5)
        self.assertEqual(r["asian_handicap"]["quarantined_or_conflicting"], 1)


class FTTests(unittest.TestCase):
    def setUp(self):
        self.f = {"sha256": "old", "match_key": "one", "known_at": BEFORE, "kickoff_utc": KO}
        self.e = {"id": "e", "written_at": AFTER, "event": {
            "event_id": "e", "match_key": "one", "frozen_source_sha256": "old",
            "frozen_known_at": BEFORE, "kickoff_utc": KO, "ft_checked_at": AFTER,
            "state": "CONFIRMED", "source_conflict": False}}
        self.registered = datetime(2026, 10, 28, tzinfo=timezone.utc)
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)

    def rows(self, evidence=None, forecasts=None):
        return ft_rows(forecasts or [self.f], evidence or [self.e], self.registered, self.now)

    def test_consistent_times_never_become_independent_proof(self):
        r = self.rows()[0]
        self.assertEqual(r["chronology_status"], "CONSISTENT_NOT_INDEPENDENTLY_PROVEN")
        self.assertIsNone(r["independently_proven_provider_checked_at"])
        self.assertFalse(r["training_or_result_eligible"])

    def test_uses_exact_reference_not_later_freeze(self):
        newer = {**self.f, "sha256": "new", "known_at": "2026-11-01T11:30:00+00:00"}
        self.assertEqual(self.rows(forecasts=[self.f, newer])[0]["failure_codes"], [])

    def test_wrong_match_or_missing_hash_fails(self):
        for mutation in ({"match_key": "other"}, {"frozen_source_sha256": "missing"}):
            e = copy.deepcopy(self.e)
            e["event"].update(mutation)
            self.assertIn("EXACT_FORECAST_REFERENCE_MISSING_OR_WRONG_MATCH",
                          self.rows([e])[0]["failure_codes"])

    def test_early_ft_write_does_not_certify_provider_check(self):
        e = copy.deepcopy(self.e)
        e["written_at"] = KO
        self.assertIn("FT_INGEST_BEFORE_CHECK_OR_FREEZE", self.rows([e])[0]["failure_codes"])
        e["event"]["ft_checked_at"] = KO
        self.assertIn("NO_POST_90MIN_FT_CHECK", self.rows([e])[0]["failure_codes"])

    def test_quarantine_and_conflict_never_score(self):
        e = copy.deepcopy(self.e)
        e["event"].update(state="QUARANTINED", source_conflict=True)
        rows = self.rows([self.e, {**e, "id": "quarantine"}])
        self.assertFalse(rows[0]["is_latest"])
        self.assertTrue(rows[1]["is_latest"])
        self.assertIn("FT_NOT_CONFIRMED", rows[1]["failure_codes"])
        self.assertIn("FT_SOURCE_CONFLICT", rows[1]["failure_codes"])
        self.assertFalse(any(r["training_or_result_eligible"] for r in rows))

    def test_future_or_missing_time_is_blocked(self):
        for when in (None, "2026-12-01T00:00:00+00:00"):
            e = copy.deepcopy(self.e)
            e["written_at"] = when
            self.assertIn("FT_INGEST_IN_FUTURE", self.rows([e])[0]["failure_codes"])


class ReadOnlyTests(unittest.TestCase):
    def test_cli_refuses_source_output_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "reports/master-brain-a1"):
                main(["--root", tmp, "--source-sha", "a"*40,
                      "--output", str(Path(tmp)/"data/state.json")])

    def test_incomplete_root_fails_without_registration_or_file_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                audit(tmp, "a"*40)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_real_replay_reconciles_without_mutating_inputs(self):
        root = Path(__file__).resolve().parents[1]
        published = root / "docs/lab/v6-readiness.json"
        if (not published.exists() or json.loads(published.read_text()).get("generated_at")
                != "2026-11-06T10:41:41+00:00"):
            self.skipTest("Pinned A1 snapshot advanced; replay separately with its source SHA")
        r = audit(root, "9d52a5bbf03d9301a6a3479b0e9c95e01945388c")
        self.assertTrue(r["source_bytes_unchanged"])
        self.assertTrue(r["published_readiness_replayed"])
        self.assertEqual(len(r["missing_matches"]), r["coverage_7d"]["missing_count"])
        self.assertEqual(len(r["ft_events"]), r["observed_lineage"]["ft_memory_events"])
        self.assertFalse(any(x["training_or_result_eligible"] for x in r["matches"] + r["ft_events"]))
        self.assertEqual(r["cost"], {"llm_calls": 0, "neurons": 0, "provider_calls": 0})


if __name__ == "__main__":
    unittest.main()
