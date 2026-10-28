"""Regression tests for V6 market-relative inference and hypothesis provenance."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import pattern_engine
from h1lab.v6_hypotheses import ensure_registered, definition_digest, DEFINITION
from h1lab.v6_shadow import quality
from h1lab.v6_residual import residual_summary, latest_total


def now():
    return datetime(2026, 10, 28, 15, tzinfo=timezone.utc)


def timeline():
    return {"identity": {"kickoff_utc": ["2026-10-28T17:00:00+00:00"]},
            "events": [
                {"event_id": "source:1", "observed_at": "2026-10-28T13:00:00+00:00",
                 "snapshots": {"total": {
                     "before": {"line": 2.5, "over_price": 1.90, "under_price": 1.90},
                     "after": {"line": 2.5, "over_price": 1.89, "under_price": 1.92}}}},
                {"event_id": "source:2", "observed_at": "2026-10-28T17:00:01+00:00",
                 "snapshots": {"total": {
                     "before": {"line": 4.5, "over_price": 1.90, "under_price": 1.90},
                     "after": {"line": 4.5, "over_price": 1.90, "under_price": 1.90}}}},
            ]}


class QualityVersion(unittest.TestCase):
    def test_overround_greater_than_twelve_pct_quarantined(self):
        q = quality({"before": {"line": 2.5, "over_price": 1.90, "under_price": 1.90},
                     "after": {"line": 2.5, "over_price": 1.77, "under_price": 1.77}})
        self.assertEqual(q["status"], "UNUSABLE")
        self.assertIn("high_after_margin", q["flags"])

    def test_after_kickoff_quote_never_baseline(self):
        row = latest_total(timeline())
        self.assertEqual(row["event_id"], "source:1")
        self.assertIsNotNone(row["p_over_2_5"])


class ResidualTests(unittest.TestCase):
    def test_residual_deducts_market_baseline(self):
        baselines = {"a": {"p_over_2_5": .8, "kickoff_utc": "2026-10-28T12:00:00+00:00"},
                     "b": {"p_over_2_5": .2, "kickoff_utc": "2026-10-28T15:00:00+00:00"}}
        outcomes = {"a": {"OVER_2_5": True}, "b": {"OVER_2_5": False}}
        m = residual_summary(["a", "b"], baselines, outcomes)
        self.assertEqual(m["n"], 2)
        self.assertAlmostEqual(m["residual"], 0)
        self.assertEqual(m["distinct_days"], 1)
        self.assertIsNone(m["residual_ci95_day_bootstrap"])

    def test_no_baseline_excludes_confirmed_ft_from_valid_sample(self):
        m = residual_summary(["a"], {}, {"a": {"OVER_2_5": True}})
        self.assertEqual(m["n"], 0)
        self.assertEqual(m["state"], "INSUFFICIENT_N")

    def test_day_block_interval_is_deterministic_when_three_days(self):
        dates = ["2026-10-01", "2026-10-02", "2026-10-03"]
        baselines = {str(i): {"p_over_2_5": .5, "kickoff_utc": dates[i] + "T12:00:00+00:00"}
                     for i in range(3)}
        outcomes = {str(i): {"OVER_2_5": i != 2} for i in range(3)}
        a = residual_summary(list(baselines), baselines, outcomes)
        b = residual_summary(list(baselines), baselines, outcomes)
        self.assertEqual(a["residual_ci95_day_bootstrap"], b["residual_ci95_day_bootstrap"])
        self.assertEqual(a["distinct_days"], 3)
        self.assertEqual(a["state"], "INSUFFICIENT_TEMPORAL_DIVERSITY")


class HypothesisRegistry(unittest.TestCase):
    def test_registration_is_actual_time_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, changed = ensure_registered(tmp, now())
            second, again = ensure_registered(tmp, now())
            self.assertTrue(changed)
            self.assertFalse(again)
            self.assertEqual(first, second)
            self.assertEqual(first["definition"], DEFINITION)
            self.assertEqual(first["definition_sha256"], definition_digest())
            self.assertEqual(first["registered_at"], now().isoformat(timespec="seconds"))
            self.assertNotEqual(first["registered_at"], first["selected_at_claimed"])

    def test_tampered_definition_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ensure_registered(tmp, now())
            path = Path(tmp) / "data/lab/v6-hypotheses.jsonl"
            path.write_text(path.read_text().replace("G_MULTI_ALERT", "G_SINGLE_ALERT"))
            with self.assertRaises(ValueError):
                ensure_registered(tmp, now())

    def test_feature_upgrade_keeps_old_frozen_definition_hash(self):
        definition = {"op": "HAS", "a": "M_TOTAL_LINE_UP"}
        row = {"id": pattern_engine.hypothesis_id(definition, feature_version=1),
               "definition": definition,
               "definition_sha256": pattern_engine.definition_sha(definition, feature_version=1),
               "feature_version": 1}
        with patch.object(pattern_engine, "FEATURE_VERSION", 2):
            result = pattern_engine.load_registry({"schema_version": 1, "entries": [row]})
        self.assertEqual(result["entries"][0]["id"], row["id"])


if __name__ == "__main__":
    unittest.main()
