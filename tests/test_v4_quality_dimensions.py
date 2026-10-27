"""Separate quality dimensions must never change the official V4 gates."""
import copy
import unittest
from datetime import timedelta

from h1lab.v4_audit import CUTOVER, audit, parser_period, instant
from tests.test_v4_audit import BASE, total_event, total_v4, mixed_event, mixed_v4


def run(alerts, markets, now=None):
    return audit({"alerts": alerts}, [], markets, now=now or BASE + timedelta(hours=1))


class QualityDimensionTests(unittest.TestCase):
    def test_gates_and_status_identical_with_or_without_dimensions(self):
        d = run([total_event()], [total_v4()])
        gates = dict(d["acceptance_gates"])
        self.assertIn("quality_dimensions", d)
        self.assertEqual(d["status"], "PENDING")
        self.assertEqual(d["acceptance_gates"], gates)
        self.assertFalse(d["quality_dimensions"]["human_validation"]["golden_set_verified"])
        self.assertEqual(d["quality_dimensions"]["statistical_certification"]["status"], "NOT_CERTIFIED")

    def test_value_agreement_separated_from_missing_provenance(self):
        legacy_row = total_v4()
        for k in ("identity_source", "parser_revision", "parser_commit", "field_source"):
            legacy_row.pop(k)
        d = run([total_event()], [legacy_row])
        q = d["quality_dimensions"]
        # Values agree 100% ...
        self.assertEqual(q["parser_agreement"]["by_family"]["total"]["messages_all_fields_agree"], 1)
        # ... while identity provenance is missing and the official gate stays false.
        self.assertEqual(q["identity_independence"]["unrecorded_or_inherited"], 1)
        self.assertFalse(d["acceptance_gates"]["field_agreement_100"])
        self.assertFalse(d["acceptance_gates"]["independent_identity"])

    def test_one_1x2_message_is_one_trial_not_eighteen(self):
        d = run([mixed_event()], [mixed_v4()])
        row = d["quality_dimensions"]["parser_agreement"]["by_family"]["1x2"]
        self.assertEqual((row["messages"], row["fields_compared"]), (1, 18))
        self.assertAlmostEqual(row["lower_95_by_message"], 0.05)

    def test_mismatch_is_not_counted_as_agreement(self):
        bad = total_v4()
        bad["markets"]["total"]["after"]["over_price"] = 1.99
        row = run([total_event()], [bad])["quality_dimensions"]["parser_agreement"]["by_family"]["total"]
        self.assertEqual(row["messages_all_fields_agree"], 0)
        self.assertEqual(row["fields_agree"], 5)

    def test_provenance_window_is_informational_and_never_rewrites(self):
        old = total_v4("3571094759:1", BASE)
        for k in ("identity_source", "parser_revision", "parser_commit"):
            old.pop(k)
        new = total_v4("3571094759:2", BASE + timedelta(minutes=30))
        markets = [old, new]
        before = copy.deepcopy(markets)
        d = run([total_event("3571094759:1", BASE),
                 total_event("3571094759:2", BASE + timedelta(minutes=30))], markets)
        w = d["quality_dimensions"]["provenance_window"]
        self.assertEqual(w["status"], "INFORMATIONAL_NOT_A_GATE")
        self.assertEqual(w["transitional_messages_without_provenance"], 1)
        self.assertEqual(w["messages"], 1)
        self.assertEqual(w["start_utc"], (BASE + timedelta(minutes=30)).isoformat(timespec="seconds"))
        self.assertEqual(markets, before)

    def test_displayed_pct_never_a_predictor(self):
        v = mixed_v4()
        v["trigger"] = {"market": "1x2", "selection": "2", "before": 2.46, "after": 2.28, "pct": -12.3}
        t = run([mixed_event()], [v])["quality_dimensions"]["trigger_displayed_pct"]
        self.assertFalse(t["use_as_predictor"])
        self.assertEqual(t["status"], "FORMULA_UNVALIDATED")
        self.assertEqual((t["messages_with_pct"], t["matches_simple_price_change_within_0_2pp"]), (1, 0))

    def test_parser_periods(self):
        self.assertEqual(parser_period({"observed_at": BASE.isoformat()}), "v4_initial_no_provenance")
        self.assertEqual(parser_period({"observed_at": "2026-10-27T17:31:15+00:00",
                                        "parser_revision": "v4-provenance-1"}), "v4_provenance_1")
        self.assertEqual(parser_period({"observed_at": "2026-10-27T20:00:00+00:00",
                                        "parser_revision": "v4-provenance-1"}),
                         "v4_provenance_1_anchored_rows")
        self.assertEqual(parser_period({"observed_at": "2026-10-27T20:00:00+00:00",
                                        "parser_source_sha256": "a" * 64}), "v4_source_aaaaaaaaaaaa")
        self.assertEqual(parser_period({"observed_at": "x"}), "unknown_time")


if __name__ == "__main__":
    unittest.main()
