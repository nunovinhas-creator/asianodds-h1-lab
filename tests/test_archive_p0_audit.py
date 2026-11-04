"""Offline checks of the P0 audit archive (reports/p0-audits) and of its archiver."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import archive_p0_audit as arch

REPO = Path(__file__).resolve().parents[1]


class ArchivedAuditsAreIntact(unittest.TestCase):
    def test_committed_archive_verifies(self):
        self.assertEqual(arch.verify(REPO), [])

    def test_verdicts_are_separate_and_match_the_original_text(self):
        doc = json.loads((REPO / arch.ARCHIVE / "48h/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["automatic_verdict"], "CRÍTICO — violação de integridade verificada")
        self.assertEqual(doc["manual_review_verdict"], "DEGRADED")
        self.assertEqual(doc["window_utc"], {"start": "2026-11-02T09:58:45Z",
                                             "end_exclusive": "2026-11-04T09:58:45Z"})
        self.assertEqual(doc["auditor"]["sha256"],
                         "97abba9edbe46f70093c7574994eb7c55b6f17c893cf4ef86aad8b6b7efe215b")
        self.assertIsNone(doc["machine_report"]["json"], "never reconstructed")
        day = json.loads((REPO / arch.ARCHIVE / "24h/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(day["window_utc"]["end_exclusive"], "2026-11-03T09:58:45Z")
        self.assertEqual(day["manual_review_verdict"], "DEGRADED")


class ArchiverRules(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(REPO / arch.ARCHIVE, self.tmp / arch.ARCHIVE)
        body = (REPO / arch.ARCHIVE / "48h/comment.md").read_text(encoding="utf-8")
        self.comment = {"id": 6628273701, "body": body, "user": {"login": "x"},
                        "html_url": "https://example.invalid", "created_at": "t",
                        "updated_at": "t"}

    def test_tampered_comment_is_detected(self):
        path = self.tmp / arch.ARCHIVE / "48h/comment.md"
        path.write_text(path.read_text(encoding="utf-8").replace("DEGRADED", "STABLE", 1),
                        encoding="utf-8")
        self.assertTrue(any("comment.md checksum" in p for p in arch.verify(self.tmp)))

    def test_tampered_manifest_is_detected(self):
        path = self.tmp / arch.ARCHIVE / "48h/manifest.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["manual_review_verdict"] = "STABLE"
        path.write_text(json.dumps(doc), encoding="utf-8")
        problems = arch.verify(self.tmp)
        self.assertTrue(any("manifest checksum" in p for p in problems))
        self.assertTrue(any("manual_review_verdict" in p for p in problems))

    def test_existing_archive_is_never_overwritten_with_other_content(self):
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            arch.archive(self.tmp, dict(self.comment, body=self.comment["body"] + "\nedit"))
        self.assertEqual(arch.verify(self.tmp), [])

    def test_edited_issue_comment_is_detected_online(self):
        live = dict(self.comment, body=self.comment["body"] + " ")
        problems = arch.verify(self.tmp, fetch=lambda cid: live)
        self.assertTrue(any("changed since archiving" in p for p in problems))

    def test_non_audit_comment_is_refused(self):
        with self.assertRaises(ValueError):
            arch.archive(self.tmp, dict(self.comment, body="hello"))


if __name__ == "__main__":
    unittest.main()
