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


if __name__ == "__main__":
    unittest.main()
