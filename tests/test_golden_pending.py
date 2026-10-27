"""Pending human references and family summary of the Golden report."""
import json
import tempfile
import unittest
from pathlib import Path

from h1lab.golden import append_pending, append_summary, build, evidence_level

ROOT = Path(__file__).resolve().parents[1]


def cands(*items):
    return {"candidates": [{"event_id": e, "family": f} for e, f in items]}


def entry(eid="3571094759:50675", family="1x2", fields=19, **extra):
    row = {"event_id": eid, "family": family, "expected_fields": fields, "label": "x",
           "status": "TRANSCRIPTION_NOT_IN_REPOSITORY", "reported_by": "handoff",
           "required_action": "resupply"}
    row.update(extra)
    return row


class PendingTests(unittest.TestCase):
    def test_pending_never_counts_as_validation(self):
        report = {"issues": []}
        append_pending(report, cands(("3571094759:50675", "1x2")),
                       {"pending_references": [entry()]}, [])
        p = report["pending_references"][0]
        self.assertFalse(p["counts_as_validation"])
        self.assertEqual(p["status"], "TRANSCRIPTION_NOT_IN_REPOSITORY")
        self.assertTrue(p["expected_fields_consistent"])
        self.assertEqual(report["pending_reference_count"], 1)

    def test_review_file_resolves_pending_status_only(self):
        report = {"issues": []}
        append_pending(report, cands(("3571094759:50675", "1x2")),
                       {"pending_references": [entry()]},
                       [("f.json", {"event_id": "3571094759:50675"})])
        self.assertEqual(report["pending_references"][0]["status"], "REVIEW_FILE_PRESENT_SEE_CASE")
        self.assertEqual(report["pending_reference_count"], 0)

    def test_invalid_or_fabricated_entries_refused(self):
        report = {"issues": []}
        bad = [entry(status="VALIDATED"), entry(source_sha256="0" * 64), entry(fields=0), "x"]
        append_pending(report, cands(), {"pending_references": bad,
                                         "unattributed_tables": [{"identity": "PROVEN"}]}, [])
        self.assertEqual(report["pending_references"], [])
        self.assertEqual(len(report["issues"]), 5)

    def test_field_count_mismatch_flagged(self):
        report = {"issues": []}
        append_pending(report, cands(), {"pending_references": [entry(fields=7)]}, [])
        self.assertFalse(report["pending_references"][0]["expected_fields_consistent"])
        self.assertFalse(report["pending_references"][0]["in_candidate_pool"])

    def test_summary_counts_messages_and_fields_separately(self):
        report = {"limitations": [], "cases": [
            {"event_id": "a", "family": "1x2", "reviews_received": 1, "status": "USER_SOURCE_VALIDATED",
             "single_review_compared_fields": 19, "single_review_matched_fields": 19,
             "firsthand_user_validation": "CONFIRMED_BY_SOURCE_VIEWER"},
            {"event_id": "b", "family": "total_up", "reviews_received": 1, "status": "AWAITING_REVIEWS",
             "single_review_compared_fields": 7, "single_review_matched_fields": 6,
             "single_review_differences": [{"field": "x"}]},
            {"event_id": "c", "family": "total_down", "reviews_received": 0, "status": "AWAITING_REVIEWS"}]}
        append_summary(report)
        t = report["human_review_totals"]
        self.assertEqual((t["messages_with_human_review"], t["fields_compared"], t["fields_matching_v4"]),
                         (2, 26, 25))
        self.assertEqual(t["messages_with_differences"], 1)
        self.assertEqual(report["evidence_levels"],
                         {"R1_PLUS_USER_SOURCE_CONFIRMATION": 1, "R1_ONLY": 1, "NONE": 1})

    def test_evidence_levels(self):
        self.assertEqual(evidence_level({"reviews_received": 2}), "TWO_REVIEWS")
        self.assertEqual(evidence_level({"reviews_received": 0}), "NONE")


@unittest.skipUnless((ROOT / "data" / "lab" / "golden").exists(), "repository data not present")
class RealGoldenTests(unittest.TestCase):
    def test_real_report_states(self):
        _, report = build(ROOT)
        self.assertEqual(report["status"], "NOT_CERTIFIED")
        self.assertFalse(report["golden_set_verified"])
        totals = report["human_review_totals"]
        self.assertGreaterEqual(totals["fields_compared"], 52)
        self.assertEqual(totals["two_reviews"], report["two_review_agreements"] +
                         report["v4_mismatch_cases"] +
                         sum(c["status"] in ("SOURCE_DISAGREEMENT", "TRANSCRIPTION_DISAGREEMENT")
                             for c in report["cases"]))
        pending = {p["event_id"]: p for p in report["pending_references"]}
        for n in ("50675", "50681", "50685", "50686"):
            p = pending.get("3571094759:" + n)
            self.assertIsNotNone(p, n)
            self.assertFalse(p["counts_as_validation"])
        for t in report["unattributed_tables"]:
            self.assertEqual(t["identity"], "NOT_PROVEN")
            self.assertFalse(t["usable_as_reference"])


if __name__ == "__main__":
    unittest.main()
