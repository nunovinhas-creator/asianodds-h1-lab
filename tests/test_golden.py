import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab.golden import (select_candidates, validate_review, assemble_report,
                          build, source_family, compare_reference)

EID = "3571094759:50671"
OBSERVED = "2026-10-27T17:41:40+00:00"
KICKOFF = "2026-10-29T18:45:00+00:00"
HASH = hashlib.sha256(b"ORIGINAL TELEGRAM SOURCE (TEST ONLY)").hexdigest()


def market_total():
    return {"before": {"line": 2.25, "over_price": 1.83, "under_price": 2.05},
            "after": {"line": 2.5, "over_price": 1.82, "under_price": 2.07}}


def market_ah():
    return {"before": {"line": 0.25, "home_price": 1.86, "away_price": 2.08},
            "after": {"line": 0.25, "home_price": 1.93, "away_price": 1.96}}


def market_1x2():
    return {"1": {"before": 3.25, "after": 3.40},
            "X": {"before": 3.25, "after": 3.26},
            "2": {"before": 2.46, "after": 2.28}}


def fixture(family="1x2", eid=EID):
    item = {"event_id": eid, "observed_at": OBSERVED, "market":
            "1x2" if family == "1x2" else "total",
            "home": "Fixture Home", "away": "Fixture Away",
            "competition": "Test league", "total_before": 2.25,
            "total_after": 2.5 if family != "total_down" else 2.0}
    tables = {"total": market_total()}
    if family == "total_down":
        tables["total"]["after"]["line"] = 2.0
    if family == "1x2":
        tables.update({"one_x_two": market_1x2(),
                       "asian_handicap": market_ah()})
    v4 = {"event_id": eid, "observed_at": OBSERVED,
          "kickoff_utc": KICKOFF, "markets": tables,
          "parser_revision": "v4-provenance-1"}
    return item, v4


def test_selection(family="1x2", eid=EID):
    legacy, v4 = fixture(family, eid)
    return select_candidates({"alerts": [legacy]}, [], [v4])["candidates"][0]


def review(candidate, code):
    markets = {"total": market_total()}
    if candidate["family"] == "total_down":
        markets["total"]["after"]["line"] = 2.0
    if candidate["family"] == "1x2":
        markets.update({"one_x_two": market_1x2(), "asian_handicap": market_ah()})
    return {"schema_version": 1, "event_id": candidate["event_id"],
            "family": candidate["family"], "reviewer_code": code,
            "source_kind": "telegram_copied_text", "source_checked": True,
            "source_sha256": HASH, "checked_at": "2026-10-27T18:00:00+00:00",
            "kickoff_utc": KICKOFF, "markets": markets}


def make_report(candidate, reviews, observed=None):
    _, v4 = fixture(candidate["family"], candidate["event_id"])
    if observed is not None:
        v4 = observed
    return assemble_report({"candidates": [candidate]},
                           [(str(i) + ".json", x) for i, x in enumerate(reviews)],
                           [v4])


class GoldenSetTests(unittest.TestCase):
    def test_three_strata_and_no_prefilled_model_prices(self):
        fixtures = [fixture("total_up", "33:1"), fixture("total_down", "33:2"),
                    fixture("1x2", "33:3")]
        candidates = select_candidates(
            {"alerts": [a for a, _ in fixtures]}, [], [v for _, v in fixtures],
            per_family=1)
        self.assertEqual({x["family"] for x in candidates["candidates"]},
                         {"total_up", "total_down", "1x2"})
        self.assertTrue(candidates["no_reference_values_prefilled"])
        for case in candidates["candidates"]:
            self.assertNotIn("markets", case)
            self.assertNotIn("total_before", case)
            self.assertNotIn("over_before", case)
            self.assertNotIn("source_url", case)

    def test_no_reviews_means_not_certified(self):
        candidate = test_selection()
        report = make_report(candidate, [])
        self.assertEqual(report["cases"][0]["status"], "AWAITING_REVIEWS")
        self.assertFalse(report["golden_set_verified"])

    def test_two_blind_reviews_agree_with_v4_but_not_automatically_certified(self):
        candidate = test_selection()
        report = make_report(candidate, [review(candidate, "R1"), review(candidate, "R2")])
        self.assertEqual(report["cases"][0]["status"], "TWO_REVIEWS_AGREE_WITH_V4")
        self.assertEqual(report["cases"][0]["checked_fields"], 19)
        self.assertEqual(report["two_review_agreements"], 1)
        self.assertFalse(report["golden_set_verified"])

    def test_single_review_does_not_count(self):
        candidate = test_selection("total_up", "33:1")
        d = make_report(candidate, [review(candidate, "R1")])
        self.assertEqual(d["cases"][0]["reviews_received"], 1)
        self.assertEqual(d["cases"][0]["status"], "AWAITING_REVIEWS")

    def test_two_reviewer_value_disagreement_not_silenced(self):
        c = test_selection()
        second = review(c, "R2")
        second["markets"]["asian_handicap"]["after"]["away_price"] = 1.91
        d = make_report(c, [review(c, "R1"), second])
        self.assertEqual(d["cases"][0]["status"], "TRANSCRIPTION_DISAGREEMENT")
        self.assertIn("asian_handicap.after.away_price", d["cases"][0]["fields_disagreed"])

    def test_source_digest_disagreement_blocks(self):
        c = test_selection()
        other = review(c, "R2")
        other["source_sha256"] = "0" * 64
        d = make_report(c, [review(c, "R1"), other])
        self.assertEqual(d["cases"][0]["status"], "SOURCE_DISAGREEMENT")

    def test_v4_wrong_field_is_visible_with_value(self):
        c = test_selection()
        _, v4 = fixture()
        v4["markets"]["total"]["after"]["under_price"] = 2.99
        d = make_report(c, [review(c, "R1"), review(c, "R2")], v4)
        self.assertEqual(d["cases"][0]["status"], "V4_MISMATCH")
        self.assertEqual(d["cases"][0]["differences"][0]["field"], "total.after.under_price")

    def test_invalid_price_or_incomplete_table_never_passes(self):
        c = test_selection("total_up", "33:1")
        a = review(c, "R1")
        a["markets"]["total"]["after"]["over_price"] = 1.0
        with self.assertRaisesRegex(ValueError, "invalid_field"):
            validate_review(a, c)
        a["markets"]["total"]["after"].pop("over_price")
        with self.assertRaisesRegex(ValueError, "missing_field"):
            validate_review(a, c)

    def test_extra_raw_message_private_data_key_refused(self):
        c = test_selection()
        a = review(c, "R1")
        a["raw_telegram_message"] = "CONFIDENTIAL"
        with self.assertRaisesRegex(ValueError, "unsafe_review_keys"):
            validate_review(a, c)

    def test_bad_digest_and_false_source_attestation_refused(self):
        c = test_selection()
        a = review(c, "R1")
        a["source_sha256"] = "abc"
        with self.assertRaisesRegex(ValueError, "invalid_source_digest"):
            validate_review(a, c)
        a["source_sha256"] = HASH
        a["source_checked"] = False
        with self.assertRaisesRegex(ValueError, "source_not_checked"):
            validate_review(a, c)

    def test_duplicate_reviewer_cannot_impersonate_second(self):
        c = test_selection()
        a = review(c, "R1")
        d = make_report(c, [a, copy.deepcopy(a)])
        self.assertIn("duplicate_reviewer", {x["type"] for x in d["issues"]})
        self.assertEqual(d["cases"][0]["reviews_received"], 1)

    def test_unknown_case_not_added_by_reviews(self):
        c = test_selection()
        d = make_report(c, [review(dict(c, event_id="33:999"), "R1")])
        self.assertIn("review_not_in_candidate_pool", {x["type"] for x in d["issues"]})

    def test_malformed_json_never_fabricates_golden(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "data/lab/golden/reviews").mkdir(parents=True)
            (root / "data/state.json").write_text('{"alerts":[]}', encoding="utf-8")
            (root / "data/lab/golden/reviews/bad.json").write_text("not json")
            pool, report = build(root)
            self.assertEqual(pool["candidates"], [])
            self.assertFalse(report["golden_set_verified"])
            self.assertIn("review_read_error", {x["type"] for x in report["issues"]})

    def test_source_family_of_stable_1x2_includes_related_tables(self):
        c = test_selection()
        self.assertEqual(c["expected_markets"], ["one_x_two", "asian_handicap", "total"])


if __name__ == "__main__":
    unittest.main()
