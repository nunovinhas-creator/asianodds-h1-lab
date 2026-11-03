"""Auditor V5 (#107): Telegram ledgers as declared at each audited revision.

Reproduces the 24 h audit false positive of 2026-11-03: V4 imported ``TELEGRAM_LEDGERS`` from
the working tree, so after PR #209 retired the three/two ledgers in favour of E5 it counted
0 ``sent`` at the baseline (expected 13) and its commit-by-commit check ignored the retired
ledgers. Synthetic local Git history only: no network, no GitHub API.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import p0_stability_audit_v5 as audit

REAL_BASELINE = "b8bc46cab95549a3f43a5b05dd3c5693af723398"
REPO_ROOT = Path(__file__).resolve().parents[1]

OWNERSHIP_LEGACY = '''"""ownership"""
THREE_LEDGER = "data/three-total-moves-notifications.json"
TWO_LEDGER = "data/two-up-total-notifications.json"
TELEGRAM_LEDGERS = (THREE_LEDGER, TWO_LEDGER)
'''
OWNERSHIP_E5 = '''"""ownership"""
THREE_LEDGER = "data/three-total-moves-notifications.json"
TWO_LEDGER = "data/two-up-total-notifications.json"
E5_LEDGER = "data/e5-over25-notifications.json"
TELEGRAM_LEDGERS = (E5_LEDGER,)
'''
THREE, TWO, E5 = ("data/three-total-moves-notifications.json",
                  "data/two-up-total-notifications.json", "data/e5-over25-notifications.json")


def entries(n, prefix, status="sent"):
    return {"entries": {f"{prefix}{i}": {"status": status, "telegram_message_id": i}
                        for i in range(n)}}


class DeclaredLedgersTests(unittest.TestCase):
    def test_names_and_literals_are_resolved_without_executing_code(self):
        self.assertEqual(audit.declared_ledgers(OWNERSHIP_LEGACY), [THREE, TWO])
        self.assertEqual(audit.declared_ledgers(OWNERSHIP_E5), [E5])
        self.assertEqual(audit.declared_ledgers('TELEGRAM_LEDGERS = ["a.json", "b.json"]\n'),
                         ["a.json", "b.json"])
        # Never executed: a side effect in the module would be ignored.
        self.assertEqual(audit.declared_ledgers(
            'import os\nos.system("exit 1")\nA = "x.json"\nTELEGRAM_LEDGERS = (A,)\n'), ["x.json"])

    def test_unresolvable_declaration_is_an_evidence_gap_not_a_guess(self):
        for source in ("X = 1\n", "TELEGRAM_LEDGERS = compute()\n",
                       "TELEGRAM_LEDGERS = (UNKNOWN,)\n", "TELEGRAM_LEDGERS = (1,)\n"):
            with self.subTest(source=source):
                with self.assertRaises(audit.EvidenceGap):
                    audit.declared_ledgers(source)


class SyntheticHistoryTests(unittest.TestCase):
    """baseline (three=6, two=7) -> legacy sends -> #209-like retirement -> E5 sends."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        audit._LEDGER_CACHE.clear()
        audit._BLOB_CACHE.clear()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        os.makedirs("data/lab", exist_ok=True)
        os.makedirs("scripts", exist_ok=True)
        Path(audit.FT_LEDGER).write_text(json.dumps({"matches": {"k": {"status": "FINAL"}}}))
        Path(audit.RESULTS_CSV).write_text("match_key,h1\nk1,1-0\n")
        self.write(audit.OWNERSHIP_MODULE, OWNERSHIP_LEGACY)
        self.write(THREE, entries(6, "t"))
        self.write(TWO, entries(7, "w"))
        self.base = self.commit("baseline")

    def tearDown(self):
        os.chdir(self.cwd)
        audit._LEDGER_CACHE.clear()
        audit._BLOB_CACHE.clear()
        self.tmp.cleanup()

    def git(self, *a):
        return subprocess.run(["git", *a], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, path, content):
        Path(path).write_text(content if isinstance(content, str) else json.dumps(content))

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def retire_to_e5(self, e5_sent=2):
        self.write(audit.OWNERSHIP_MODULE, OWNERSHIP_E5)
        self.write(E5, entries(e5_sent, "e"))
        return self.commit("#209: E5 becomes the only emitter")

    def test_baseline_counts_use_the_ledgers_declared_at_the_baseline(self):
        head = self.retire_to_e5()
        self.assertEqual(audit.telegram_ledgers(head), [E5])
        self.assertEqual(audit.telegram_ledgers(self.base), [THREE, TWO])
        self.assertEqual(audit.snapshot_counts(self.base)["telegram_sent"], 13)

    def test_v4_failure_mode_is_reproduced_and_fixed(self):
        self.retire_to_e5()
        head = self.git("rev-parse", "HEAD")
        v4_like = audit.snapshot(self.base, ledgers=audit.telegram_ledgers(head))  # V4: current list
        self.assertEqual(sum(1 for led in v4_like["tg"].values() if led for e in led.values()
                             if e.get("status") == "sent"), 0)                   # the false 0
        self.assertEqual(audit.snapshot_counts(self.base)["telegram_sent"], 13)   # V5

    def test_window_ledgers_keep_retired_ledgers(self):
        head = self.retire_to_e5()
        self.assertEqual(audit.window_ledgers(self.base, head), [THREE, TWO, E5])

    def test_legacy_ledger_mutation_before_retirement_is_detected(self):
        bad = entries(6, "t")
        bad["entries"]["t0"]["telegram_message_id"] = 999        # terminal 'sent' rewritten
        self.write(THREE, bad)
        self.commit("rewrites a sent legacy receipt")
        head = self.retire_to_e5()
        problems, _, stats = audit.history_integrity(self.base, head, is_append_only=lambda p: False)
        self.assertTrue(any("Recibo Telegram terminal alterado" in p and THREE in p
                            for p in problems), problems)
        self.assertGreaterEqual(stats["state_transitions_checked"], 2)

    def test_legacy_append_and_retirement_are_clean(self):
        grown = entries(6, "t")
        grown["entries"]["t9"] = {"status": "sent", "telegram_message_id": 99}
        self.write(THREE, grown)
        self.commit("legacy send before retirement")
        head = self.retire_to_e5()
        problems, _, _ = audit.history_integrity(self.base, head, is_append_only=lambda p: False)
        self.assertEqual(problems, [])

    def test_e5_receipt_removal_after_retirement_is_detected(self):
        self.retire_to_e5(e5_sent=2)
        self.write(E5, entries(1, "e"))
        head = self.commit("drops an E5 receipt")
        problems, _, _ = audit.history_integrity(self.base, head, is_append_only=lambda p: False)
        self.assertTrue(any("Recibo Telegram removido" in p and E5 in p for p in problems), problems)

    def test_missing_ownership_module_is_an_evidence_gap(self):
        self.git("rm", "-q", audit.OWNERSHIP_MODULE)
        rev = self.commit("module removed")
        with self.assertRaises(audit.EvidenceGap):
            audit.telegram_ledgers(rev)


def in_real_clone(*shas):
    cwd = os.getcwd()
    try:
        os.chdir(REPO_ROOT)
        return all(audit.has_commit(s) for s in shas)
    finally:
        os.chdir(cwd)


class RealRepositoryTests(unittest.TestCase):
    @unittest.skipUnless(in_real_clone(REAL_BASELINE), "real baseline not in this clone (shallow)")
    def test_real_baseline_is_valid_with_13_sent(self):
        cwd = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            self.assertEqual(audit.telegram_ledgers(REAL_BASELINE), [THREE, TWO])
            self.assertEqual(audit.snapshot_counts(REAL_BASELINE), audit.BASELINE_COUNTS)
            self.assertEqual(audit.verify_baseline(REAL_BASELINE, audit.parse_ts(audit.WINDOW_START)), [])
        finally:
            os.chdir(cwd)
