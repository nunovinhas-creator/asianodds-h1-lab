"""Offline classification of publication receipts into 24h/48h/7d windows."""
import unittest
from datetime import datetime, timezone

from scripts import publication_receipts_report as r

LOG = [
    '2026-11-02T08:02:56.2464464Z FT_PUBLISH_RECEIPT {"attempt": 1, "provider_requeries": 0, "status": "PUBLISHED"}',
    '2026-11-02T09:00:00.0000000Z H1_PUBLISH_RECEIPT {"attempt": 2, "provider_requeries": 0, "status": "PUBLISHED", "run_id": "1"}',
    '2026-11-03T09:00:00.0000000Z COLLECT_PUBLISH_RECEIPT {"status": "PUBLISHED", "path": "AFTER_TRANSPORT", "run_id": "2"}',
    '2026-11-03T10:00:00.0000000Z COLLECT_PUBLISH_RECEIPT {"status": "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR", "run_id": "3"}',
    '2026-11-05T10:00:00.0000000Z LAB_V4_PUBLISH_RECEIPT {"status": "REFUSED", "run_id": "4"}',
    '2026-11-05T11:00:00.0000000Z LAB_V4_PUBLISH_RECEIPT {"status": "RETRY_EXHAUSTED", "run_id": "5", "provider_requeries": 1}',
    'noise line',
]


class ReceiptReportTests(unittest.TestCase):
    def test_windows_and_categories(self):
        out = r.report(list(r.parse(LOG)), datetime(2026, 11, 2, 7, 36, tzinfo=timezone.utc))
        self.assertEqual(out["windows"]["24h"]["by_producer"],
                         {"FT": {"FIRST_ATTEMPT": 1}, "H1": {"AFTER_CAS": 1}})
        self.assertEqual(out["windows"]["48h"]["by_producer"]["COLLECT"],
                         {"AFTER_TRANSPORT": 1, "RECOVERED": 1})
        self.assertEqual(out["windows"]["7d"]["by_producer"]["LAB_V4"],
                         {"SAFE_ABORT_INCOMPATIBLE": 1, "UNRECOVERED_FAILURE": 1})
        self.assertEqual(out["provider_requeries_nonzero"], 1)

    # Real receipt from production run 41425408616 (first LAB V4 run after #206).
    SUPERSEDED_LINE = (
        '2026-11-02T10:02:08.6785573Z LAB_V4_PUBLISH_RECEIPT {"attempts": 1, '
        '"base": "d817947404f4b0228054027776716a32fb8d3876", "failure_class": '
        '"SUPERSEDED_SAFE_SKIP", "provider_requeries": 0, "published_commit": null, '
        '"push_failures": [], "reason": "LAB inputs advanced on main since d817947404f4: '
        'data/health/h1-results.json", "reason_kind": "SUPERSEDED_BY_NEWER_INPUTS", '
        '"remote_heads": ["f5672576ec40a4a73c6ad8c7093e1ca3dd4bac9c"], "run_id": "41425408616", '
        '"status": "SUPERSEDED_BY_NEWER_INPUTS", "telegram_requests": 0}')

    def test_supersession_is_its_own_category(self):
        rows = list(r.parse([self.SUPERSEDED_LINE]))
        self.assertEqual([row["category"] for row in rows], ["SUPERSEDED"])
        self.assertIsNone(rows[0]["published_commit"])

    def test_supersession_is_neither_publication_nor_failure_nor_unclassified(self):
        out = r.report(list(r.parse([self.SUPERSEDED_LINE] + LOG)),
                       datetime(2026, 11, 2, 7, 36, tzinfo=timezone.utc))
        lab = out["windows"]["24h"]["by_producer"]["LAB_V4"]
        self.assertEqual(lab, {"SUPERSEDED": 1})
        for cat in ("FIRST_ATTEMPT", "AFTER_CAS", "AFTER_TRANSPORT", "RECOVERED",
                    "UNRECOVERED_FAILURE", "SAFE_ABORT_INCOMPATIBLE", "UNCLASSIFIED"):
            self.assertNotIn(cat, lab)

    def test_reason_kind_alone_marks_supersession(self):
        self.assertEqual(r.category({"status": "REFUSED",
                                     "reason_kind": "SUPERSEDED_BY_NEWER_INPUTS"}), "SUPERSEDED")

    def test_real_refusals_and_unknown_statuses_unchanged(self):
        self.assertEqual(r.category({"status": "REFUSED", "reason_kind": "INTEGRITY"}),
                         "SAFE_ABORT_INCOMPATIBLE")
        self.assertEqual(r.category({"status": "SOMETHING_NEW"}), "UNCLASSIFIED")


if __name__ == "__main__":
    unittest.main()
