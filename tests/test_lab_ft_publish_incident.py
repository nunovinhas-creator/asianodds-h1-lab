"""Incident 41358783489: a code+docs merge during an FT poll. Offline Git bare repos.

The refusal is correct and stays a refusal. These tests pin: (1) the exact incident is reproduced and
refused, (2) the message names every refused path (not only the alphabetically first), (3) nothing was
published and the remote is untouched, (4) hostile or unexpected concurrent changes stay refused, and
(5) legitimate concurrent H1/V4 updates still pass.
"""
import json
import unittest

from scripts import lab_ft_publish_safe as p
from tests.test_lab_ft_publish_safe import GitFTPublicationTests as Base, git, state, write


class IncidentTests(Base):
    def merge_like_commit(self, changes):
        self.collector_commit(changes)

    def test_incident_code_plus_new_doc_is_refused_with_every_cause_and_the_remote_is_untouched(self):
        self.merge_like_commit({
            "docs/audit/h1-retry-policy-v2-rollback.md": "# plan\n",
            "h1lab/results.py": "# new policy\n",
            "scripts/h1_reopen_expired.py": "# tool\n",
            "tests/test_h1_retry_horizon.py": "# tests\n",
        })
        remote_before = git(self.other, "rev-parse", "HEAD")
        with self.assertRaises(p.UnsafeFTPublication) as ctx:
            self.publish()
        message = str(ctx.exception)
        # the alphabetically-first path is the doc, but the PRIMARY cause (program change) is reported too
        self.assertIn("h1lab/results.py", message)
        self.assertIn("scripts/h1_reopen_expired.py", message)
        self.assertIn("tests/test_h1_retry_horizon.py", message)
        self.assertIn("docs/audit/h1-retry-policy-v2-rollback.md", message)
        self.assertIn("FT dependency or program changed", message)
        self.assertIn("Unknown concurrent path", message)
        git(self.root, "fetch", "-q", "origin", "main")
        self.assertEqual(git(self.root, "rev-parse", "origin/main"), remote_before)   # nothing published

    def test_message_reports_total_shown_and_explicit_truncation(self):
        changes = {"docs/audit/new-%02d.md" % i: "x\n" for i in range(12)}
        changes["h1lab/results.py"] = "# code\n"
        self.collector_commit(changes)
        with self.assertRaises(p.UnsafeFTPublication) as ctx:
            self.publish()
        message = str(ctx.exception)
        self.assertIn("13 refused paths in total", message)
        self.assertIn("FT dependency or program changed x1", message)
        self.assertIn("7 more shown", message)
        self.assertIn("TRUNCATED: 5 refused paths not listed", message)
        self.assertIn("FT dependency or program changed: h1lab/results.py", message)  # relevant reason kept

    def test_message_without_truncation_has_no_truncation_marker(self):
        self.collector_commit({"docs/audit/a.md": "x\n", "docs/audit/b.md": "x\n"})
        with self.assertRaises(p.UnsafeFTPublication) as ctx:
            self.publish()
        self.assertIn("2 refused paths in total (Unknown concurrent path x2); 1 more shown", str(ctx.exception))
        self.assertNotIn("TRUNCATED", str(ctx.exception))

    def test_docs_only_new_file_is_still_refused_no_generic_docs_allowlist(self):
        for path in ("docs/audit/anything.md", "docs/audit/nested/new.md", "docs/lab/new-report.json", "docs/NOTES.md"):
            with self.subTest(path=path):
                self.collector_commit({path: "x\n"})
                with self.assertRaisesRegex(p.UnsafeFTPublication, "Unknown concurrent path: " + path):
                    self.publish()

    def test_hostile_changes_are_refused(self):
        hostile = {
            "sealed ft ledger": {"data/lab/ft-ledger.json": '{"matches":{}}\n'},
            "workflow": {".github/workflows/lab-ft-results.yml": "name: x\n"},
            "ft report": {"docs/lab/ft-results.json": "{}\n"},
            "path traversal-looking name": {"docs/audit/../../h1lab/x.py": "x\n"},
            "state identity rewrite": {"data/state.json": state(home="REWRITTEN")},
        }
        for label, changes in hostile.items():
            with self.subTest(label=label):
                try:
                    self.collector_commit(changes)
                except Exception:        # git itself may refuse the odd path; that is also a refusal
                    continue
                with self.assertRaises(p.UnsafeFTPublication):
                    self.publish()

    def test_legitimate_concurrent_h1_update_still_passes(self):
        self.collector_commit({"docs/data.json": '{"version":2}\n', "data/state.json": state(extra=True)})
        self.publish()      # must not raise: the protection was not widened or narrowed

    def test_single_violation_message_is_unchanged_for_compatibility(self):
        self.collector_commit({"tests/new_test.py": "x\n"})
        with self.assertRaises(p.UnsafeFTPublication) as ctx:
            self.publish()
        self.assertEqual(str(ctx.exception), "FT dependency or program changed: tests/new_test.py")


# Reuse only the Git fixture; do not re-run every inherited test of the base class here.
for _name in [n for n in dir(Base) if n.startswith("test_") and n not in IncidentTests.__dict__]:
    setattr(IncidentTests, _name, None)
del Base
