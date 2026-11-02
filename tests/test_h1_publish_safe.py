"""Bare-Git concurrency tests for the H1 results publisher (incident run 41403070558)."""
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import h1_publish_safe as h

HEADER = "match_key,status,home_goals,away_goals,source\n"
ROW_A = '"2026-11-01,1,2",final,1,0,https://bsd/1/\n'
ROW_B = '"2026-11-01,3,4",final,2,2,https://bsd/2/\n'
HTTP_408 = b"error: RPC failed; HTTP 408 curl 22\nfatal: the remote end hung up unexpectedly\n"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args],
                                   stderr=subprocess.PIPE).decode().strip()


def write(root, name, content):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def ledger(*finals):
    matches = {"2026-11-01,1,2": {"status": "FINAL", "result": {"home_goals": 1, "away_goals": 0}}}
    for i, key in enumerate(finals):
        matches[key] = {"status": "FINAL", "result": {"home_goals": i, "away_goals": 0}}
    return json.dumps({"schema_version": 1, "matches": matches}, sort_keys=True) + "\n"


def state(extra=False, home="A"):
    alerts = [{"match_key": "2026-11-01,1,2", "home": home, "away": "B",
               "kickoff_utc": "2026-11-01T13:00:00+00:00", "competition": "X"}]
    if extra:
        alerts.append({"match_key": "2026-11-02,9,9", "home": "C", "away": "D",
                       "kickoff_utc": "2026-11-02T13:00:00+00:00", "competition": "X"})
    return json.dumps({"alerts": alerts, "signals": []}, sort_keys=True) + "\n"


def audit(**over):
    doc = {"2026-11-01,1,2": {"status": "settled", "checked_at": "2026-11-01T20:00:00+00:00"},
           "2026-11-01,3,4": {"status": "pending", "checked_at": "2026-11-01T20:00:00+00:00",
                              "attempts": 1},
           "2026-10-30,5,6": {"status": "expired_unverified", "checked_at": "2026-10-31T10:00:00+00:00",
                              "expired_at": "2026-10-31T13:00:00+00:00"}}
    for key, value in over.items():
        doc[key.replace("_", ",")] = value
    return json.dumps(doc, sort_keys=True) + "\n"


class H1PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        self.remote = home / "bare.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(self.remote)], check=True)
        self.root = home / "h1"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.root)],
                       check=True, stderr=subprocess.DEVNULL)
        for r in (self.root,):
            git(r, "config", "user.name", "h1")
            git(r, "config", "user.email", "h1@example.invalid")
        git(self.root, "checkout", "-q", "-b", "main")
        write(self.root, h.RESULTS, HEADER + ROW_A)
        write(self.root, h.AUDIT, audit())
        write(self.root, h.RECEIPT, '{"status":"CYCLE_COMPLETED","n":1}\n')
        write(self.root, h.RENDERED, '{"roi":1}\n')
        write(self.root, h.STATE, state())
        write(self.root, "data/lab/ft-ledger.json", ledger())
        write(self.root, "data/lab/markets-2026-11.jsonl", '{"id":1}\n')
        write(self.root, "h1lab/results.py", "# code\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "baseline")
        git(self.root, "push", "-q", "-u", "origin", "main")
        self.base = git(self.root, "rev-parse", "HEAD")
        self.other = home / "lab"
        subprocess.run(["git", "clone", "-q", "-b", "main", str(self.remote), str(self.other)], check=True)
        git(self.other, "config", "user.name", "lab")
        git(self.other, "config", "user.email", "lab@example.invalid")
        # The H1 cycle: one new certified final, audit progresses, receipt, render.
        write(self.root, h.RESULTS, HEADER + ROW_A + ROW_B)
        write(self.root, h.AUDIT, audit(**{"2026-11-01_3_4": {
            "status": "settled", "checked_at": "2026-11-02T06:56:59+00:00", "attempts": 2}}))
        write(self.root, h.RECEIPT, '{"status":"CYCLE_COMPLETED","n":2}\n')
        write(self.root, h.RENDERED, '{"roi":2}\n')
        git(self.root, "commit", "-qam", h.MESSAGE)
        self.source = git(self.root, "rev-parse", "HEAD")
        self.renders = []

    def lab_commit(self, changes, message="LAB V4 refresh"):
        git(self.other, "pull", "-q", "--ff-only", "origin", "main")
        for path, content in changes.items():
            write(self.other, path, content)
        git(self.other, "add", ".")
        git(self.other, "commit", "-qm", message)
        git(self.other, "push", "-q", "origin", "main")
        return git(self.other, "rev-parse", "HEAD")

    def render(self, root):
        self.renders.append(1)
        st = json.loads((Path(root) / h.STATE).read_text())
        rows = (Path(root) / h.RESULTS).read_text().count("\n") - 1
        write(root, h.RENDERED, json.dumps({"alerts": len(st["alerts"]), "results": rows}) + "\n")

    def publish(self, push_hook=None, **kw):
        old_run = h.run
        pushes = []

        def hooked(root, *args, **kwargs):
            if args and args[0] == "push":
                pushes.append(1)
                if push_hook:
                    return push_hook(len(pushes), lambda: old_run(root, *args, **kwargs), args)
            return old_run(root, *args, **kwargs)
        with patch.object(h, "run", side_effect=hooked), \
             patch("urllib.request.urlopen", side_effect=AssertionError("provider call")):
            result = h.publish(self.root, base=self.base, render=self.render,
                               sleep=lambda s: None, **kw)
        return result, pushes

    def main_file(self, path):
        return git(self.remote, "show", "main:" + path)

    # -- the production incident -------------------------------------------------
    def test_lab_commit_between_rebase_and_push_is_preserved(self):
        def hook(n, real, args):
            if n == 1:
                self.lab_commit({"docs/lab/v4-audit.json": '{"v4":2}\n',
                                 "data/lab/markets-2026-11.jsonl": '{"id":1}\n{"id":2}\n'})
            return real()
        published, pushes = self.publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(git(self.remote, "rev-parse", "main"), published)
        self.assertEqual(self.main_file("docs/lab/v4-audit.json"), '{"v4":2}')
        self.assertEqual(self.main_file(h.RESULTS), (HEADER + ROW_A + ROW_B).strip())
        self.assertEqual(self.main_file(h.RENDERED), '{"roi":2}')
        self.assertEqual(self.renders, [])

    def test_exact_github_cannot_lock_ref_is_retried(self):
        def hook(n, real, args):
            if n == 1:
                actual = self.lab_commit({"docs/lab/v4-audit.json": '{"v4":3}\n'})
                err = ("! [remote rejected] main -> main (cannot lock ref 'refs/heads/main': "
                       f"is at {actual} but expected {self.base})\n")
                return subprocess.CompletedProcess(args, 1, b"", err.encode())
            return real()
        published, pushes = self.publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(self.main_file("docs/lab/v4-audit.json"), '{"v4":3}')

    def test_concurrent_ft_publication_preserved(self):
        self.lab_commit({"data/lab/ft-ledger.json": ledger("2026-11-02,7,8")}, "FT snapshot")
        published, _ = self.publish()
        self.assertEqual(self.main_file("data/lab/ft-ledger.json"), ledger("2026-11-02,7,8").strip())
        self.assertEqual(self.main_file(h.AUDIT), audit(**{"2026-11-01_3_4": {
            "status": "settled", "checked_at": "2026-11-02T06:56:59+00:00", "attempts": 2}}).strip())

    def test_collector_state_change_rerenders_dashboard_offline(self):
        self.lab_commit({h.STATE: state(extra=True), h.RENDERED: '{"collector":1}\n'}, "collect")
        self.publish()
        self.assertEqual(self.renders, [1])
        self.assertEqual(json.loads(self.main_file(h.RENDERED)), {"alerts": 2, "results": 2})
        self.assertEqual(json.loads(self.main_file(h.STATE))["alerts"][1]["home"], "C")

    # -- refusals -----------------------------------------------------------------
    def test_code_change_aborts_and_leaves_remote(self):
        head = self.lab_commit({"h1lab/results.py": "# new policy\n"}, "code")
        with self.assertRaisesRegex(h.UnsafeH1Publication, "Incompatible program change"):
            self.publish()
        self.assertEqual(git(self.remote, "rev-parse", "main"), head)

    def test_identity_rewrite_aborts(self):
        self.lab_commit({h.STATE: state(home="Z")}, "rewrite")
        with self.assertRaisesRegex(h.UnsafeH1Publication, "identity"):
            self.publish()

    def test_other_h1_writer_with_contradictory_result_aborts(self):
        self.lab_commit({h.RESULTS: HEADER + ROW_A + ROW_B.replace("2,2", "3,1")}, "other H1")
        with self.assertRaisesRegex(h.UnsafeH1Publication, "Concurrent H1 result writer"):
            self.publish()
        self.assertIn("3,1", self.main_file(h.RESULTS))

    def test_unknown_path_aborts(self):
        self.lab_commit({"README.md": "x\n"}, "docs")
        with self.assertRaisesRegex(h.UnsafeH1Publication, "Unknown concurrent path"):
            self.publish()

    def _amend(self, changes):
        for path, content in changes.items():
            write(self.root, path, content)
        git(self.root, "commit", "-q", "-a", "--amend", "--no-edit")

    def test_certified_row_change_refused_before_push(self):
        self._amend({h.RESULTS: HEADER + ROW_A.replace("1,0", "0,1") + ROW_B})
        with self.assertRaisesRegex(h.UnsafeH1Publication, "Certified H1 result changed"):
            self.publish()
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.base)

    def test_duplicate_contradictory_key_refused(self):
        self._amend({h.RESULTS: HEADER + ROW_A + ROW_B + ROW_B.replace("2,2", "0,0")})
        with self.assertRaisesRegex(h.UnsafeH1Publication, "Contradictory"):
            self.publish()

    def test_expired_reopen_refused(self):
        self._amend({h.AUDIT: audit(**{"2026-10-30_5_6": {
            "status": "pending", "checked_at": "2026-11-02T00:00:00+00:00"}})})
        with self.assertRaisesRegex(h.UnsafeH1Publication, "reopened"):
            self.publish()

    def test_audit_counter_or_timestamp_regression_refused(self):
        self._amend({h.AUDIT: audit(**{"2026-11-01_3_4": {
            "status": "pending", "checked_at": "2026-11-02T00:00:00+00:00", "attempts": 0}})})
        with self.assertRaisesRegex(h.UnsafeH1Publication, "counter decreased"):
            self.publish()
        self._amend({h.AUDIT: audit(**{"2026-11-01_3_4": {
            "status": "pending", "checked_at": "2026-10-01T00:00:00+00:00", "attempts": 1}})})
        with self.assertRaisesRegex(h.UnsafeH1Publication, "timestamp went back"):
            self.publish()

    def test_auth_refusal_not_retried(self):
        def hook(n, real, args):
            return subprocess.CompletedProcess(
                args, 128, b"", b"remote: Permission to x/y.git denied to bot.\nerror: 403\n")
        with self.assertRaisesRegex(h.UnsafeH1Publication, "AUTH"):
            self.publish(hook)

    # -- transport / idempotence -------------------------------------------------
    def test_408_after_acceptance_confirmed_single_push(self):
        def hook(n, real, args):
            real()
            return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
        published, pushes = self.publish(hook)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(git(self.remote, "rev-parse", "main"), published)

    def test_crash_after_push_rerun_is_noop(self):
        class Crash(BaseException):
            pass

        def hook(n, real, args):
            real()
            raise Crash()
        with self.assertRaises(Crash):
            self.publish(hook)
        head = git(self.remote, "rev-parse", "main")
        self.lab_commit({"docs/lab/v4-audit.json": '{"after":1}\n'})
        git(self.root, "reset", "-q", "--hard", self.source)
        receipt = Path(self.tmp.name) / "receipt.json"
        result, pushes = self.publish(receipt=receipt)
        self.assertEqual(pushes, [])
        self.assertEqual(json.loads(receipt.read_text())["status"], "ALREADY_PUBLISHED_EQUIVALENT")
        self.assertEqual(git(self.remote, "rev-list", "--count", "main"), "3")
        self.assertTrue(head)
        self.assertNotEqual(result, self.base)

    # -- deterministic contention -------------------------------------------------
    def _writer_rounds(self, rounds):
        """A real LAB/FT writer thread that pushes exactly once per H1 push attempt, in lock-step."""
        go, done = threading.Event(), threading.Event()
        pushed, errors = [], []

        def writer():
            for i in range(1, rounds + 1):
                if not go.wait(30):
                    errors.append("writer never released")
                    return
                go.clear()
                try:
                    if i % 2:
                        self.lab_commit({"docs/lab/v4-audit.json": json.dumps({"i": i}) + "\n"},
                                        "LAB V4 writer %d" % i)
                    else:
                        self.lab_commit({"data/lab/ft-ledger.json": ledger("2026-11-02,%d,0" % i)},
                                        "FT writer %d" % i)
                    pushed.append(i)
                except Exception as exc:  # pragma: no cover - reported by assertions
                    errors.append(repr(exc))
                finally:
                    done.set()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()

        def hook(n, real, args):
            if n <= rounds:
                done.clear()
                go.set()
                self.assertTrue(done.wait(30), "writer did not finish its round")
            return real()
        return hook, thread, pushed, errors

    def test_transient_contention_publishes_without_requery_and_keeps_every_commit(self):
        for repetition in range(5):
            with self.subTest(repetition=repetition):
                if repetition:
                    self.setUp()
                rounds = 4
                hook, thread, pushed, errors = self._writer_rounds(rounds)
                receipt = Path(self.tmp.name) / "receipt.json"
                published, pushes = self.publish(hook, receipt=receipt, max_attempts=6)
                thread.join(30)
                self.assertEqual(errors, [])
                self.assertEqual(pushed, list(range(1, rounds + 1)))
                self.assertEqual(len(pushes), rounds + 1)
                log = git(self.remote, "log", "--format=%s", "main")
                for i in pushed:
                    self.assertIn(("LAB V4 writer %d" if i % 2 else "FT writer %d") % i, log)
                self.assertEqual(log.count(h.MESSAGE), 1)
                self.assertEqual(git(self.remote, "rev-parse", "main"), published)
                self.assertEqual(self.main_file(h.RESULTS), (HEADER + ROW_A + ROW_B).strip())
                self.assertEqual(self.main_file("data/lab/ft-ledger.json"),
                                 ledger("2026-11-02,4,0").strip())
                doc = json.loads(receipt.read_text())
                self.assertEqual((doc["status"], doc["attempt"], doc["provider_requeries"]),
                                 ("PUBLISHED", rounds + 1, 0))

    def test_persistent_contention_exhausts_safely_with_receipt_and_bundle(self):
        attempts = 4
        hook, thread, pushed, errors = self._writer_rounds(attempts)
        receipt = Path(self.tmp.name) / "receipt.json"
        bundle = Path(self.tmp.name) / "h1-unpublished.bundle"
        with self.assertRaisesRegex(h.UnsafeH1Publication, "Remote advanced during all bounded"):
            self.publish(hook, receipt=receipt, bundle=bundle, max_attempts=attempts)
        thread.join(30)
        self.assertEqual(errors, [])
        log = git(self.remote, "log", "--format=%s", "main")
        self.assertEqual(log.count(h.MESSAGE), 0)            # nothing partial published
        self.assertEqual(log.count("writer"), attempts)       # every independent commit kept
        self.assertEqual(self.main_file(h.RESULTS), (HEADER + ROW_A).strip())
        doc = json.loads(receipt.read_text())
        self.assertEqual(doc["status"], "RETRY_EXHAUSTED")
        self.assertEqual((doc["attempts"], doc["push_failures"]), (attempts, ["CAS_REJECTED"] * attempts))
        self.assertEqual(doc["source_commit"], self.source)
        self.assertIsNone(doc["published_commit"])
        # local diagnostics: the branch is back on the unpublished H1 commit, also exported
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.source)
        self.assertIn("is okay", subprocess.run(
            ["git", "-C", str(self.root), "bundle", "verify", str(bundle)],
            capture_output=True, text=True).stderr)

    # -- hardening ------------------------------------------------------------------
    def test_concurrent_change_of_an_ft_final_used_by_h1_is_refused(self):
        bad = json.loads(ledger())
        bad["matches"]["2026-11-01,1,2"]["result"] = {"home_goals": 0, "away_goals": 0}
        self.lab_commit({"data/lab/ft-ledger.json": json.dumps(bad) + "\n"}, "FT rewrite")
        with self.assertRaisesRegex(h.UnsafeH1Publication, "FT FINAL used by H1 changed"):
            self.publish()

    def test_telegram_paths_use_the_strict_ft_validators(self):
        self.lab_commit({"data/telegram-delivery-block.json": '{"token": "123:ABC"}\n'}, "bad block")
        with self.assertRaises(h.UnsafeH1Publication):
            self.publish()

    def test_audit_timestamps_compared_as_utc_instants(self):
        # '07:00+01:00' is 06:00Z: lexically later, instant earlier -> regression refused.
        self._amend({h.AUDIT: audit(**{"2026-11-01_3_4": {
            "status": "pending", "checked_at": "2026-11-01T20:30:00+01:00", "attempts": 1}})})
        with self.assertRaisesRegex(h.UnsafeH1Publication, "timestamp went back"):
            self.publish()
        # 'Z' spelling of a later instant is accepted.
        self._amend({h.AUDIT: audit(**{"2026-11-01_3_4": {
            "status": "settled", "checked_at": "2026-11-02T06:56:59Z", "attempts": 2}})})
        self.publish()

    def test_failed_refusal_also_writes_a_complete_receipt(self):
        self.lab_commit({"h1lab/results.py": "# new policy\n"}, "code")
        receipt = Path(self.tmp.name) / "r.json"
        with self.assertRaises(h.UnsafeH1Publication):
            self.publish(receipt=receipt)
        doc = json.loads(receipt.read_text())
        self.assertEqual((doc["status"], doc["source_commit"]), ("REFUSED", self.source))
        self.assertIn("Incompatible program change", doc["reason"])

if __name__ == "__main__":
    unittest.main()
