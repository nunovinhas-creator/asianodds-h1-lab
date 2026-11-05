"""Every FT publication refusal leaves a verifiable receipt (P0 #107, 24 h audit).

Runs 41476501130 and 41502044305 (2026-11-02) aborted in ``UnsafeFTPublication`` with a
traceback and NO ``FT_PUBLISH_RECEIPT``: the P0 auditor could only classify them as
``NO_RECEIPT_WORKFLOW_FAILURE``. These tests reproduce both refusal shapes on a local bare
Git remote and require a receipt with the exact reason, its context, a JSON file and a
verified bundle of the unpublished FT commit -- while the publication is still refused and
the remote is never changed. No network, no provider, no Telegram.
"""
import contextlib
import hashlib
import io
import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts import lab_ft_publish_safe as p
from scripts import publication_receipts_report as receipts_report
from tests import test_lab_ft_publish_safe as base

git = base.git

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_LINE = re.compile(r"^FT_PUBLISH_RECEIPT (\{.*\})$", re.M)


class FTRefusalReceiptTests(base.GitFTPublicationTests):
    def run_main(self, *, verify=None, extra=(), files=True):
        out = io.StringIO()
        self.receipt_file = Path(self.tmp.name) / "receipt.json"
        self.bundle = Path(self.tmp.name) / "unpublished.bundle"
        argv = ["--root", str(self.root), "--base", self.base, "--manifest", str(self.manifest),
                "--baseline", str(self.baseline), "--max-attempts", "3", *extra]
        if files:
            argv += ["--receipt", str(self.receipt_file), "--bundle", str(self.bundle)]
        error = None
        with patch.object(p.publication_guard, "verify", side_effect=verify), \
                patch.object(p, "discovery_verify", return_value=None), \
                contextlib.redirect_stdout(out):
            try:
                p.main(argv)
            except Exception as exc:  # noqa: BLE001 - the test inspects it
                error = exc
        docs = [json.loads(m) for m in RECEIPT_LINE.findall(out.getvalue())]
        return error, docs, out.getvalue()

    def assert_refused(self, error, docs, status, kind, reason_regex):
        self.assertIsNotNone(error, "a refusal must still fail the step")
        self.assertEqual(len(docs), 1, "exactly one receipt per run")
        doc = docs[0]
        self.assertEqual((doc["status"], doc["reason_kind"]), (status, kind))
        self.assertRegex(doc["reason"], reason_regex)
        self.assertEqual(doc["publication"], "NOT_PUBLISHED")
        self.assertIsNone(doc["published_commit"])
        self.assertEqual((doc["provider_requeries"], doc["telegram_requests"]), (0, 0))
        self.assertEqual(doc["base"], self.base)
        self.assertEqual(doc["source_commit"], self.source)
        self.assertEqual(json.loads(self.receipt_file.read_text()), doc)
        return doc

    def assert_bundle_holds_the_unpublished_commit(self, doc):
        self.assertEqual(doc["bundle"], str(self.bundle))
        subprocess.run(["git", "-C", str(self.root), "bundle", "verify", str(self.bundle)],
                       check=True, capture_output=True)
        heads = git(self.root, "bundle", "list-heads", str(self.bundle))
        self.assertIn(self.source, heads)
        self.assertEqual(doc["bundle_sha256"], hashlib.sha256(self.bundle.read_bytes()).hexdigest())
        # The temporary ref used to build the bundle is removed again.
        self.assertEqual(git(self.root, "for-each-ref", "refs/ft-unpublished"), "")

    def assert_remote_untouched(self, remote_before):
        git(self.root, "fetch", "-q", "origin", "main")
        self.assertEqual(git(self.root, "rev-parse", "origin/main"), remote_before)

    def test_recovery_actions_distinguish_refused_inputs_and_unknown_push(self):
        for reason, action in (
            ("FT dependency or program changed: h1lab/lab_results.py", "RECONCILE_FROM_CURRENT_MAIN"),
            ("FT push outcome unknown and remote unreadable", "VERIFY_REMOTE_BEFORE_RETRY"),
            ("Unknown concurrent path: unknown.json", "REVIEW_REFUSAL"),
        ):
            with self.subTest(reason=reason), contextlib.redirect_stdout(io.StringIO()):
                receipt = p.refusal_receipt(p.UnsafeFTPublication(reason), {}, env={})
                self.assertEqual(receipt["recovery_action"], action)
                self.assertEqual(receipt["publication"], "NOT_PUBLISHED")

    def test_incident_41502044305_invalid_h1_receipt_leaves_a_receipt(self):
        wrong = {"schema_version": 1, "entries": {
            "old": {"match_key": "changed", "kickoff_utc": "2026-11-01T16:00:00Z"}}}
        self.collector_commit({"data/three-total-moves-notifications.json": json.dumps(wrong) + "\n"})
        remote_before = git(self.other, "rev-parse", "HEAD")
        error, docs, out = self.run_main()
        self.assertIsInstance(error, p.UnsafeFTPublication)
        doc = self.assert_refused(error, docs, "REFUSED", "H1_NOTIFICATION_RECEIPT_INVALID",
                                  "H1 notification receipt invalid")
        self.assertEqual(doc["remote"], remote_before)
        self.assertEqual(doc["attempt"], 1)
        self.assertIn("::error title=FT_PUBLISH_REFUSED::H1_NOTIFICATION_RECEIPT_INVALID", out)
        self.assert_bundle_holds_the_unpublished_commit(doc)
        self.assert_remote_untouched(remote_before)

    def test_incident_41476501130_unknown_concurrent_path_leaves_a_receipt(self):
        self.collector_commit({"data/lab/unexpected-new-journal-2026-11.jsonl": '{"x":1}\n'})
        remote_before = git(self.other, "rev-parse", "HEAD")
        error, docs, _ = self.run_main()
        doc = self.assert_refused(error, docs, "REFUSED", "UNKNOWN_CONCURRENT_PATH",
                                  "Unknown concurrent path")
        self.assert_bundle_holds_the_unpublished_commit(doc)
        self.assert_remote_untouched(remote_before)

    def test_receipt_line_is_printed_even_without_receipt_or_bundle_flags(self):
        # Same command line as before this change: the log line alone must now be enough.
        self.collector_commit({"data/lab/unexpected-new-journal-2026-11.jsonl": '{"x":1}\n'})
        error, docs, _ = self.run_main(files=False)
        self.assertIsInstance(error, p.UnsafeFTPublication)
        self.assertEqual([(d["status"], d["reason_kind"]) for d in docs],
                         [("REFUSED", "UNKNOWN_CONCURRENT_PATH")])
        self.assertNotIn("bundle", docs[0])

    def test_program_change_is_an_incompatible_program_refusal(self):
        self.collector_commit({"h1lab/lab_results.py": "# unexpected code\n"})
        remote_before = git(self.other, "rev-parse", "HEAD")
        error, docs, _ = self.run_main()
        self.assert_refused(error, docs, "REFUSED", "INCOMPATIBLE_PROGRAM", "program changed")
        self.assert_remote_untouched(remote_before)

    def test_unexpected_error_fails_closed_with_a_receipt(self):
        remote_before = git(self.other, "rev-parse", "HEAD")

        def broken(_):
            raise RuntimeError("seal unreadable")
        error, docs, _ = self.run_main(verify=broken)
        self.assertIsInstance(error, RuntimeError)
        self.assert_refused(error, docs, "REFUSED", "UNEXPECTED_ERROR:RuntimeError", "seal unreadable")
        self.assert_remote_untouched(remote_before)

    def test_successful_publication_keeps_its_single_published_receipt(self):
        self.collector_commit({"docs/data.json": '{"version":2}\n'})
        hashes = json.loads(self.manifest.read_text())["sha256"]

        def sealed(_):
            for path, expected in hashes.items():
                self.assertEqual(hashlib.sha256(p.git(self.root, "show", "HEAD:" + path)).hexdigest(),
                                 expected)
        error, docs, _ = self.run_main(verify=sealed)
        self.assertIsNone(error)
        self.assertEqual([d["status"] for d in docs], ["PUBLISHED"])
        self.assertEqual(json.loads(self.receipt_file.read_text()), docs[0])
        self.assertFalse(self.bundle.exists())
        git(self.root, "fetch", "-q", "origin", "main")
        self.assertEqual(git(self.root, "rev-parse", "origin/main"), docs[0]["published_commit"])


class ClassificationTests(unittest.TestCase):
    def test_every_terminal_message_has_a_parseable_status(self):
        cases = {
            "Push failed for reason other than a Git race: denied": ("PUSH_REFUSED", "PUSH_REFUSED"),
            "FT push transport failed 4 times; commit not on remote: x":
                ("RETRY_EXHAUSTED", "TRANSPORT_RETRIES_EXHAUSTED"),
            "Remote advanced during all bounded FT publication attempts":
                ("RETRY_EXHAUSTED", "CAS_RETRIES_EXHAUSTED"),
            "FT push outcome unknown and remote unreadable; not retried: x":
                ("OUTCOME_UNRESOLVED", "OUTCOME_UNRESOLVED"),
            "Unknown concurrent path: data/lab/v6-memory-evidence-2026-11.jsonl":
                ("REFUSED", "UNKNOWN_CONCURRENT_PATH"),
            "H1 notification receipt invalid: data/e5-over25-notifications.json":
                ("REFUSED", "H1_NOTIFICATION_RECEIPT_INVALID"),
            "H1 fixture identity changed: data/state.json": ("REFUSED", "H1_ARTIFACT_INVALID"),
            "FT checkout is not clean": ("REFUSED", "INTEGRITY_REFUSAL"),
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(p.classify_refusal(p.UnsafeFTPublication(message)), expected)

    def test_existing_receipt_parsers_count_refusals_as_incidents_not_gaps(self):
        lines = [
            '2026-11-02T18:36:37.0000000Z FT_PUBLISH_RECEIPT {"publication": "NOT_PUBLISHED", '
            '"reason_kind": "H1_NOTIFICATION_RECEIPT_INVALID", "status": "REFUSED"}',
            '2026-11-02T18:40:00.0000000Z FT_PUBLISH_RECEIPT {"reason_kind": "PUSH_REFUSED", '
            '"status": "PUSH_REFUSED"}',
        ]
        cats = [receipts_report.category(doc) for _, _, doc in
                [(m.group("ts"), m.group("producer"), json.loads(m.group("doc")))
                 for m in map(receipts_report.LINE.match, lines)]]
        self.assertEqual(cats, ["SAFE_ABORT_INCOMPATIBLE", "UNRECOVERED_FAILURE"])


class WorkflowWiringTests(unittest.TestCase):
    def test_ft_workflow_keeps_receipt_and_bundle_on_every_outcome(self):
        text = (ROOT / ".github/workflows/lab-ft-results.yml").read_text()
        self.assertIn('--receipt "$RUNNER_TEMP/ft-publish-receipt.json"', text)
        self.assertIn('--bundle "$RUNNER_TEMP/ft-unpublished.bundle"', text)
        steps = yaml.safe_load(text)["jobs"]["reconcile"]["steps"]
        names = [s.get("name") or s.get("uses") for s in steps]
        commit = names.index("Commit only LAB FT artifacts")
        tail = steps[commit + 1:]
        self.assertTrue(tail and all(s.get("if") == "always()" for s in tail))
        upload = [s for s in tail if str(s.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertEqual(len(upload), 1)
        self.assertIn("ft-publish-receipt.json", upload[0]["with"]["path"])
        self.assertIn("ft-unpublished.bundle", upload[0]["with"]["path"])
        # Publication itself is unchanged: still the only push path, still no rebase.
        self.assertNotIn("git rebase", text)
        self.assertNotIn("continue-on-error: true\n        env:\n          PUBLICATION_STEPS", text)


# Reuse the parent's Git fixture only; its own tests run in their own module.
for _name in dir(base.GitFTPublicationTests):
    if _name.startswith("test_") and _name not in vars(FTRefusalReceiptTests):
        setattr(FTRefusalReceiptTests, _name, None)
