import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab.v4_audit import CUTOVER, audit, generate, numeric, read_jsonl

BASE = datetime.fromisoformat(CUTOVER) + timedelta(minutes=3)
EVENT_ID = "3571094759:900"
KEY = "2026-10-27,1,2"


def total_event(event_id=EVENT_ID, observed=None):
    return {"event_id": event_id, "observed_at": (observed or BASE).isoformat(),
            "market": "total", "match_key": KEY,
            "kickoff_utc": "2026-10-29T18:00:00+00:00",
            "total_before": 2.25, "total_after": 2.5,
            "over_before": 1.83, "over_after": 1.83,
            "under_before": 2.02, "under_after": 1.81}


def total_v4(event_id=EVENT_ID, observed=None):
    old = total_event(event_id, observed)
    return {"event_id": event_id, "schema_version": 4,
            "observed_at": old["observed_at"], "match_key": KEY,
            "kickoff_utc": old["kickoff_utc"], "trigger_market": "total",
            "markets": {"total": {
                "before": {"line": 2.25, "over_price": 1.83, "under_price": 2.02},
                "after": {"line": 2.5, "over_price": 1.83, "under_price": 1.81}}}}


def mixed_event():
    obj = total_event()
    obj.update({"market": "1x2", "one_x_two": {
        "1": {"before": 3.25, "after": 3.4},
        "X": {"before": 3.25, "after": 3.26},
        "2": {"before": 2.46, "after": 2.28}},
        "asian_handicap": {"before": {"line": 0.25, "home_odds": 1.86, "away_odds": 2.08},
                            "after": {"line": 0.25, "home_odds": 1.93, "away_odds": 1.96}}})
    return obj


def mixed_v4():
    obj = total_v4()
    obj["trigger_market"] = "1x2"
    obj["markets"]["one_x_two"] = mixed_event()["one_x_two"]
    obj["markets"]["asian_handicap"] = {
        "before": {"line": 0.25, "home_price": 1.86, "away_price": 2.08},
        "after": {"line": 0.25, "home_price": 1.93, "away_price": 1.96}}
    return obj


def report(alerts=None, markets=None, formats=None, now=None, **kwargs):
    return audit({"alerts": alerts if alerts is not None else [total_event()]},
                 formats if formats is not None else [],
                 markets if markets is not None else [total_v4()],
                 now=now or BASE + timedelta(hours=1), **kwargs)


class V4AuditTests(unittest.TestCase):
    def test_real_time_boundary_excludes_history(self):
        historical = total_event("old:1", BASE - timedelta(minutes=10))
        d = report(alerts=[historical, total_event()], markets=[total_v4()])
        self.assertEqual(d["phase_coverage"]["historical"]["eligible"], 1)
        self.assertEqual(d["phase_coverage"]["first_24h"]["eligible"], 1)
        self.assertEqual(d["phase_coverage"]["first_24h"]["pct"], 100)
        self.assertEqual(d["markets"]["total"]["totals"]["matched"], 6)
        self.assertEqual(d["markets_by_phase"]["historical"]["total"]["totals"]["missing_v4"], 6)

    def test_total_all_six_fields_equal_and_changed_line(self):
        d = report()
        self.assertEqual(d["markets"]["total"]["totals"]["matched"], 6)
        self.assertIsNone(d["markets"]["asian_handicap"]["agreement_pct"])
        self.assertEqual(d["markets"]["total"]["complete_pct"], 100)
        self.assertEqual(d["issues"], [])

    def test_mixed_all_18_correlated_fields(self):
        d = report(alerts=[mixed_event()], markets=[mixed_v4()])
        self.assertEqual(sum(m["totals"].get("matched", 0) for m in d["markets"].values()), 18)
        self.assertEqual(d["markets"]["one_x_two"]["totals"]["matched"], 6)
        self.assertEqual(d["markets"]["asian_handicap"]["totals"]["matched"], 6)
        self.assertEqual(d["phase_coverage"]["first_24h"]["eligible"], 1)

    def test_mismatches_are_field_specific(self):
        v = total_v4()
        v["markets"]["total"]["after"]["under_price"] = 1.85
        d = report(markets=[v])
        self.assertEqual(d["markets"]["total"]["totals"]["mismatch"], 1)
        self.assertEqual(d["markets"]["total"]["fields"]["under_price_after"]["mismatch"], 1)
        self.assertTrue(any(x["type"] == "field_mismatch" and x["legacy"] == 1.81 and
                            x["v4"] == 1.85 for x in d["issues"]))

    def test_absent_market_and_missing_price_not_hidden(self):
        v = total_v4()
        del v["markets"]["total"]["after"]["over_price"]
        d = report(markets=[v])
        self.assertEqual(d["markets"]["total"]["totals"]["missing_v4"], 1)
        self.assertEqual(d["markets"]["total"]["complete_pct"], round(500 / 6, 2))
        v["markets"] = {}
        d = report(markets=[v])
        self.assertEqual(d["markets"]["total"]["totals"]["missing_v4"], 6)
        self.assertIn("rejected_or_missing_table", d["issue_counts"])

    def test_invalid_odds_and_quarter_line(self):
        v = total_v4()
        v["markets"]["total"]["after"]["over_price"] = 1.0
        v["markets"]["total"]["before"]["line"] = 2.3
        d = report(markets=[v])
        self.assertEqual(d["markets"]["total"]["totals"]["invalid_v4"], 2)
        self.assertIsNone(numeric(float("nan"), "price"))
        self.assertIsNone(numeric(True, "line"))

    def test_missing_v4_counts_against_coverage(self):
        d = report(markets=[])
        self.assertEqual(d["phase_coverage"]["first_24h"]["pct"], 0)
        self.assertEqual(d["markets"]["total"]["totals"]["missing_v4"], 6)
        self.assertIn(EVENT_ID, d["active_missing_v4_ids"])

    def test_unknown_message_not_silently_dropped(self):
        fmt = {"event_id": "3571094759:901", "observed_at": BASE.isoformat(),
               "legacy_parsed": False, "line_classes": ["VS", "CLOCK", "WAS:3", "NOW:3"]}
        d = report(formats=[fmt])
        self.assertEqual(d["phase_coverage"]["first_24h"]["eligible"], 2)
        self.assertIn("unrecognized_legacy_format", d["issue_counts"])
        self.assertIn("missing_v4", d["issue_counts"])

    def test_missing_match_key_and_wrong_identity(self):
        v = total_v4()
        v["match_key"] = None
        d = report(markets=[v])
        self.assertIn("missing_v4_match_key", d["issue_counts"])
        self.assertIn("match_key_mismatch", d["issue_counts"])

    def test_duplicate_event_ids_flagged_even_identical(self):
        d = report(alerts=[total_event(), total_event()],
                   markets=[total_v4(), total_v4()])
        self.assertEqual(d["issue_counts"]["duplicate_event_id"], 2)
        self.assertEqual(d["phase_coverage"]["first_24h"]["eligible"], 1)

    def test_legacy_null_has_explicit_noncomparable_bucket(self):
        old = mixed_event()
        old["asian_handicap"]["before"]["home_odds"] = None
        d = report(alerts=[old], markets=[mixed_v4()])
        stat = d["markets"]["asian_handicap"]["fields"]["home_price_before"]
        self.assertEqual(stat["legacy_missing_or_invalid"], 1)
        self.assertEqual(stat["compared"], 0)
        self.assertIn("legacy_field_unavailable", d["issue_counts"])

    def test_rejected_mixed_ah_table_not_masked_by_total(self):
        v = mixed_v4()
        del v["markets"]["asian_handicap"]
        d = report(alerts=[mixed_event()], markets=[v])
        self.assertEqual(d["markets"]["total"]["totals"]["matched"], 6)
        self.assertEqual(d["markets"]["asian_handicap"]["totals"]["missing_v4"], 6)
        self.assertIn("rejected_or_missing_table", d["issue_counts"])

    def test_first24_gates_not_certified_with_tiny_sample(self):
        d = report(now=BASE + timedelta(days=2),
                   log_evidence={"status": "verified_24h_clean"})
        self.assertFalse(d["acceptance_gates"]["minimum_evidence"])
        self.assertEqual(d["status"], "PENDING")

    def test_corrupted_jsonl_and_duplicates_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"data/lab").mkdir(parents=True)
            (root/"data/state.json").write_text(json.dumps({"alerts":[total_event()]}))
            p = root/"data/lab/markets-2026-10.jsonl"
            p.write_bytes(b"\\xff\n" + (json.dumps(total_v4()) + "\n").encode())
            d = generate(root, now=BASE + timedelta(hours=1))
            self.assertIn("invalid_jsonl", d["issue_counts"])
            self.assertEqual(d["phase_coverage"]["first_24h"]["captured"], 1)

    def test_missing_state_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                generate(Path(d))


if __name__ == "__main__":
    unittest.main()
