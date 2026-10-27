import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from h1lab.v4_audit import CUTOVER
from scripts import lab_v4_audit as mod

END = datetime.fromisoformat(CUTOVER) + timedelta(hours=25)


class V4LogScanTests(unittest.TestCase):
    def test_log_failure_marker_detected_without_exposing_content(self):
        with patch.object(mod, "api", return_value={"jobs": [{"id": 123}], "total_count": 1}), \
             patch.object(mod, "download_job_logs",
                          return_value=b"hello\\nLAB_MARKET_V4_STORE_FAILED: ValueError\\n"):
            result = mod.scan_run(42, "safe-token")
        self.assertEqual(result, {"run_id": 42, "status": "fail", "error_count": 1})

    def test_log_download_failure_not_clean(self):
        with patch.object(mod, "api", side_effect=OSError("unable")):
            result = mod.scan_run(42, "safe-token")
        self.assertEqual(result["status"], "unverified")

    def test_signed_redirect_never_receives_github_authorization(self):
        url = "https://productionresultssa9.blob.core.windows.net/signed/log?sig=redacted"
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            mod.ENDPOINT + "/actions/jobs/123/logs", 302, "Found",
            {"Location": url}, None)
        with patch.object(mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(mod.urllib.request, "urlopen",
                          return_value=io.BytesIO(b"LAB_MARKET_V4_INSPECT_FAILED")) as download:
            raw = mod.download_job_logs(123, "secret-github-token")
        self.assertIn(b"LAB_MARKET_V4_INSPECT_FAILED", raw)
        original_request = opener.open.call_args.args[0]
        self.assertIn("Authorization", original_request.headers)
        redirected_request = download.call_args.args[0]
        self.assertNotIn("Authorization", redirected_request.headers)
        self.assertNotIn("secret-github-token", str(redirected_request.headers))
        self.assertTrue(redirected_request.full_url.startswith("https://"))

    def test_redirect_to_untrusted_host_rejected_without_request(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            mod.ENDPOINT + "/actions/jobs/123/logs", 302, "Found",
            {"Location": "https://evil.example.com/log"}, None)
        with patch.object(mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(mod.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(ValueError, "untrusted_host"):
                mod.download_job_logs(123, "secret")
            download.assert_not_called()

    def test_github_endpoint_denies_access_does_not_mark_clean(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            mod.ENDPOINT + "/actions/jobs/123/logs", 401, "Unauthorized", {}, None)
        with patch.object(mod.urllib.request, "build_opener", return_value=opener), \
             patch.object(mod, "api", return_value={"jobs": [{"id": 123}]}):
            result = mod.scan_run(42, "not-actually-valid")
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["reason"], "http_401")

    def test_24h_cannot_pass_without_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = mod.log_evidence(Path(tmp), "", None, END)
        self.assertEqual(info["status"], "unverified")

    def test_backfills_all_missing_completed_runs_and_persists_journal(self):
        runs = {1: {"status": "completed", "conclusion": "success"},
                2: {"status": "completed", "conclusion": "success"}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "all_window_runs", return_value=runs), \
                 patch.object(mod, "scan_run", side_effect=lambda rid, token: {
                     "run_id": rid, "status": "clean", "error_count": 0}) as mock:
                info = mod.log_evidence(Path(tmp), "token", 2, END)
            self.assertEqual(info["status"], "verified_24h_clean")
            self.assertEqual(mock.call_count, 2)
            path = Path(tmp)/"data/lab/v4-runchecks.jsonl"
            records = [json.loads(s) for s in path.read_text().splitlines()]
            self.assertEqual({v["run_id"] for v in records}, {1, 2})

    def test_unscanned_past_runs_never_certify(self):
        runs = {i: {"status": "completed", "conclusion": "success"}
                for i in range(1, 12)}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "all_window_runs", return_value=runs), \
                 patch.object(mod, "scan_run", side_effect=lambda rid, token: {
                     "run_id": rid, "status": "clean", "error_count": 0}):
                info = mod.log_evidence(Path(tmp), "token", None, END)
            self.assertNotEqual(info["status"], "verified_24h_clean")
            self.assertEqual(len(info["unscanned_run_ids"]), 3)

    def test_failure_in_any_run_blocks_acceptance(self):
        runs = {1: {"status": "completed", "conclusion": "failure"}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "all_window_runs", return_value=runs), \
                 patch.object(mod, "scan_run", return_value={
                     "run_id": 1, "status": "fail", "error_count": 1}):
                info = mod.log_evidence(Path(tmp), "token", 1, END)
            self.assertEqual(info["status"], "errors_detected")

    def test_bad_jsonl_journal_explicitly_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"data/lab/v4-runchecks.jsonl"
            p.parent.mkdir(parents=True)
            p.write_bytes(b"\\xff\\n")
            rows = mod.read_journal(Path(tmp))
            self.assertIn("invalid_1", rows)
            self.assertEqual(rows["invalid_1"]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
