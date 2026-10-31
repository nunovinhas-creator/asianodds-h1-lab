"""No-network P0 regression for the only safe post-FT source commit retry."""
import unittest
from unittest.mock import patch
from scripts.lab_ft_safe_publish import checked_paths, validate, SAFE_REMOTE_REPORTS

class StrictRemoteFTGateTests(unittest.TestCase):
    def test_known_v4_reports_are_safe_but_require_real_changes(self):
        self.assertEqual(set(checked_paths(list(SAFE_REMOTE_REPORTS))),
                         SAFE_REMOTE_REPORTS)
        with self.assertRaises(ValueError):
            checked_paths([])
        with self.assertRaises(ValueError):
            checked_paths(["docs/lab/v4-audit.json"]*2)

    def test_never_hide_h1_ft_discovery_or_source_changes(self):
        for path in (
            "data/state.json", "data/lab/ft-ledger.json",
            "data/lab/discovery-state.json",
            "data/lab/markets-2026-10.jsonl",
            "docs/lab/ft-results.json",
            "docs/lab/discoveries.json",
            "h1lab/lab_results.py", ".github/workflows/lab-ft-results.yml",
            "docs/lab/new-unknown-report.json",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                checked_paths(["docs/lab/v4-audit.json",path])

    def test_sha_ancestry_and_nul_paths(self):
        base="1"*40
        head="2"*40
        with patch("scripts.lab_ft_safe_publish.git",
                   side_effect=[b"",b"docs/lab/v4-audit.json\\0docs/lab/golden-report.json\\0"]) as git:
            self.assertEqual(validate(base,head)["status"],
                             "SAFE_REPORT_ONLY_REMOTE_ADVANCE")
            self.assertEqual(git.call_count,2)
        with patch("scripts.lab_ft_safe_publish.git",
                   side_effect=[b"",b"data/state.json\\0"]):
            with self.assertRaises(ValueError):
                validate(base,head)
        with self.assertRaises(ValueError):
            validate("not-a-sha",head)
        with patch("scripts.lab_ft_safe_publish.git") as git:
            self.assertEqual(validate(base,base)["status"],"UNCHANGED")
            git.assert_not_called()

if __name__=="__main__":
    unittest.main()
