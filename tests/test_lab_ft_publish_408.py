"""Bare-Git fault injection for the FT push outcome machine (incident run 41393026365).

Every scenario is offline: a local bare repository plays GitHub, failures are
injected around the real ``git push`` and no provider can be called.
"""
import hashlib
import json
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import git_publish_outcome as outcome
from scripts import lab_ft_publish_safe as p
from tests import test_lab_ft_publish_safe as _base

git, write, ft = _base.git, _base.write, _base.ft

HTTP_408 = (b"error: RPC failed; HTTP 408 curl 22 The requested URL returned error: 408\n"
            b"send-pack: unexpected disconnect while reading sideband packet\n"
            b"fatal: the remote end hung up unexpectedly\nEverything up-to-date\n")
CONN_RESET = b"fatal: unable to access 'https://github.com/x/y/': Connection reset by peer\n"
AUTH_403 = (b"remote: Permission to x/y.git denied to github-actions[bot].\n"
            b"fatal: unable to access 'https://github.com/x/y/': The requested URL returned error: 403\n")


class FTPushOutcomeTests(_base.GitFTPublicationTests):
    """Inherit the realistic bare-repo fixture; skip re-running the parent's tests."""

    def run_publish(self, run_hook, **kw):
        hashes = json.loads(self.manifest.read_text())["sha256"]
        provider_calls = []

        def sealed(_):
            for name, digest in hashes.items():
                self.assertEqual(hashlib.sha256(p.git(self.root, "show", "HEAD:" + name)).hexdigest(),
                                 digest)
        old_run = p.run
        pushes = []

        def hooked(root, *args, **kwargs):
            if args and args[0] == "push":
                pushes.append(git(self.root, "rev-parse", "HEAD"))
                return run_hook(len(pushes), lambda: old_run(root, *args, **kwargs), args)
            return old_run(root, *args, **kwargs)
        with patch.object(p, "run", side_effect=hooked), \
             patch.object(p.publication_guard, "verify", side_effect=sealed), \
             patch.object(p, "discovery_verify", return_value=None), \
             patch("urllib.request.urlopen", side_effect=AssertionError("provider call")):
            result = p.publish(self.root, base=self.base, manifest=self.manifest,
                               baseline=self.baseline, max_attempts=kw.get("max_attempts", 5),
                               sleep=lambda s: None)
        self.assertEqual(provider_calls, [])
        return result, pushes

    def remote_main(self):
        return git(self.remote, "rev-parse", "refs/heads/main")

    def remote_commits_with_message(self, text):
        return git(self.remote, "log", "--format=%s", "refs/heads/main").count(text)

    # 1. HTTP 408 before the remote accepted anything -> bounded, revalidated retry.
    def test_408_before_acceptance_retries_and_publishes_once(self):
        def hook(n, real, args):
            if n == 1:
                return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
            return real()
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(self.remote_main(), published)
        self.assertEqual(git(self.root, "show", published + ":data/lab/ft-ledger.json"), ft(2).strip())

    # 2. HTTP 408 AFTER the remote accepted the commit -> confirmed, no second push.
    def test_408_after_acceptance_is_confirmed_without_republishing(self):
        def hook(n, real, args):
            ok = real()
            self.assertEqual(ok.returncode, 0)
            return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(self.remote_main(), published)
        self.assertEqual(git(self.remote, "rev-list", "--count", "refs/heads/main"), "2")

    # 2b. accepted, and the collector already advanced on top before we probe.
    def test_408_after_acceptance_with_later_collector_commit_is_still_confirmed(self):
        def hook(n, real, args):
            real()
            git(self.other, "pull", "-q", "--ff-only", "origin", "main")
            write(self.other, "docs/data.json", '{"version":9}\n')
            git(self.other, "commit", "-qam", "collector after FT")
            git(self.other, "push", "-q", "origin", "main")
            return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/main^"), published)

    # 2c. Outcome unknown AND remote unreadable: never a blind second push.
    def test_408_with_unreadable_remote_aborts_without_second_push(self):
        def hook(n, real, args):
            return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
        with patch.object(outcome, "remote_head", return_value=None):
            with self.assertRaisesRegex(p.UnsafeFTPublication, "outcome unknown"):
                self.run_publish(hook)
        self.assertEqual(self.remote_main(), self.base)

    # 2d. Probe semantics on a real bare remote.
    def test_probe_remote_states(self):
        sleeps = []
        self.assertEqual(outcome.probe_remote(self.root, self.source, sleep=sleeps.append)[0],
                         outcome.NOT_ACCEPTED)
        self.assertEqual(outcome.probe_remote(self.root, self.base, sleep=sleeps.append)[0],
                         outcome.PUBLISHED)
        failed = subprocess.CompletedProcess([], 128, b"", b"fatal: unable to access")
        self.assertEqual(outcome.probe_remote(self.root, self.base, fetch=lambda: failed,
                                              sleep=sleeps.append)[0], outcome.UNRESOLVED)
        self.assertEqual(sleeps, [2, 4])

    # 3. Connection dropped before any response (pack never arrived).
    def test_connection_failure_before_response_retries(self):
        def hook(n, real, args):
            if n == 1:
                return subprocess.CompletedProcess(args, 128, b"", CONN_RESET)
            return real()
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(self.remote_main(), published)

    # 4. CAS rejection: retried only after full revalidation on the new remote.
    def test_cas_rejection_retries_over_independent_h1_data(self):
        def hook(n, real, args):
            if n == 1:
                git(self.other, "pull", "-q", "--ff-only", "origin", "main")
                write(self.other, "docs/data.json", '{"version":5}\n')
                write(self.other, "data/results.csv", "match_key,status\nx,final\n")
                git(self.other, "add", ".")
                git(self.other, "commit", "-qm", "H1 results publish")
                git(self.other, "push", "-q", "origin", "main")
            return real()
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(git(self.remote, "show", "main:docs/data.json"), '{"version":5}')
        self.assertEqual(git(self.remote, "show", "main:data/results.csv"), "match_key,status\nx,final")
        self.assertEqual(git(self.remote, "show", "main:data/lab/ft-ledger.json"), ft(2).strip())

    # 5. Main advanced with FT program changes -> incompatible, abort, remote untouched.
    def test_main_advanced_with_ft_code_is_refused(self):
        def hook(n, real, args):
            if n == 1:
                git(self.other, "pull", "-q", "--ff-only", "origin", "main")
                write(self.other, "h1lab/lab_ft_evidence.py", "# new FT rule\n")
                git(self.other, "add", ".")
                git(self.other, "commit", "-qm", "FT code change")
                git(self.other, "push", "-q", "origin", "main")
                return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
            return real()
        with self.assertRaisesRegex(p.UnsafeFTPublication, "program changed"):
            self.run_publish(hook)
        self.assertEqual(self.remote_commits_with_message("publish verified FT"), 0)
        self.assertNotEqual(git(self.remote, "show", "main:data/lab/ft-ledger.json"), ft(2).strip())

    # 6. Sealed bundle incompatible -> refused before any push.
    def test_incompatible_sealed_bundle_never_pushes(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["sha256"]["data/lab/ft-ledger.json"] = "0" * 64
        self.manifest.write_text(json.dumps(manifest))
        pushes = []
        old_run = p.run

        def hooked(root, *args, **kwargs):
            if args and args[0] == "push":
                pushes.append(1)
            return old_run(root, *args, **kwargs)

        def strict(manifest_path):
            data = json.loads(Path(manifest_path).read_text())
            for name, digest in data["sha256"].items():
                if hashlib.sha256(p.git(self.root, "show", "HEAD:" + name)).hexdigest() != digest:
                    raise ValueError("seal mismatch " + name)
        with patch.object(p, "run", side_effect=hooked), \
             patch.object(p.publication_guard, "verify", side_effect=strict), \
             patch.object(p, "discovery_verify", return_value=None):
            with self.assertRaises(Exception):
                p.publish(self.root, base=self.base, manifest=self.manifest,
                          baseline=self.baseline, sleep=lambda s: None)
        self.assertEqual(pushes, [])
        self.assertEqual(self.remote_main(), self.base)

    # 7. Authentication refusal is never retried.
    def test_auth_refusal_is_not_retried(self):
        def hook(n, real, args):
            return subprocess.CompletedProcess(args, 128, b"", AUTH_403)
        with self.assertRaisesRegex(p.UnsafeFTPublication, "other than a Git race"):
            self.run_publish(hook)
        self.assertEqual(self.remote_main(), self.base)

    # 8. Persistent transport failure is bounded and leaves the remote untouched.
    def test_persistent_transport_failure_is_bounded(self):
        calls = []

        def hook(n, real, args):
            calls.append(n)
            return subprocess.CompletedProcess(args, 128, b"", HTTP_408)
        with self.assertRaisesRegex(p.UnsafeFTPublication, "transport failed 4 times"):
            self.run_publish(hook, max_attempts=10)
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.remote_main(), self.base)

    # 9. Crash after the remote accepted and before confirmation: rerun is a no-op.
    def test_crash_after_publication_then_rerun_is_idempotent(self):
        class Crash(BaseException):
            pass

        def hook(n, real, args):
            real()
            raise Crash()
        with self.assertRaises(Crash):
            self.run_publish(hook)
        published = self.remote_main()
        # Process restarts from the original sealed source commit.
        git(self.root, "reset", "-q", "--hard", self.source)
        pushes = []

        def second(n, real, args):
            pushes.append(n)
            return real()
        result, _ = self.run_publish(second)
        self.assertEqual(pushes, [])
        self.assertEqual(result, published)
        self.assertEqual(self.remote_main(), published)

    # 10. Two concurrent publishers of the same sealed bundle: exactly one commit lands.
    def test_two_concurrent_identical_publishers_publish_once(self):
        twin = Path(self.tmp.name) / "twin"
        subprocess.run(["git", "clone", "-q", "-b", "main", str(self.remote), str(twin)], check=True)
        git(twin, "config", "user.name", "test")
        git(twin, "config", "user.email", "test@example.invalid")
        git(twin, "fetch", "-q", str(self.root), self.source)
        git(twin, "reset", "-q", "--hard", self.source)
        barrier = threading.Barrier(2)
        results, errors = [], []
        old_run = p.run

        def hooked(root, *args, **kwargs):
            if args and args[0] == "push":
                try:
                    barrier.wait(timeout=10)
                except threading.BrokenBarrierError:
                    pass
            return old_run(root, *args, **kwargs)

        def sealed(_):
            return None

        def worker(root):
            try:
                results.append(p.publish(root, base=self.base, manifest=self.manifest,
                                         baseline=self.baseline, sleep=lambda s: None))
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
        with patch.object(p, "run", side_effect=hooked), \
             patch.object(p.publication_guard, "verify", side_effect=sealed), \
             patch.object(p, "discovery_verify", return_value=None):
            threads = [threading.Thread(target=worker, args=(r,)) for r in (self.root, twin)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(self.remote_main(), results[0])
        self.assertEqual(git(self.remote, "rev-list", "--count", "refs/heads/main"), "2")

    # 11. A concurrent DIFFERENT FT publication is incompatible: never overwritten.
    def test_concurrent_different_ft_publication_is_refused(self):
        git(self.other, "pull", "-q", "--ff-only", "origin", "main")
        write(self.other, "data/lab/ft-ledger.json", ft(1).replace('"fixture"', '"other"'))
        git(self.other, "commit", "-qam", "other FT run")
        git(self.other, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Concurrent FT"):
            self.run_publish(lambda n, real, args: real())


# Do not re-run the inherited publication tests twice.
for _name in [n for n in dir(_base.GitFTPublicationTests) if n.startswith("test_")]:
    if _name not in FTPushOutcomeTests.__dict__:
        setattr(FTPushOutcomeTests, _name, None)


class ClassifierTests(unittest.TestCase):
    def test_production_408_is_uncertain_not_absent(self):
        self.assertEqual(outcome.classify_push_failure(HTTP_408.decode()), outcome.UNCERTAIN)

    def test_cas_and_auth(self):
        a, b = "a" * 40, "b" * 40
        self.assertEqual(outcome.classify_push_failure(
            f"! [remote rejected] main -> main (cannot lock ref 'refs/heads/main': is at {a} but expected {b})"),
            outcome.CAS_REJECTED)
        self.assertEqual(outcome.classify_push_failure(
            f"cannot lock ref 'refs/heads/other': is at {a} but expected {b}"), "UNKNOWN")
        self.assertEqual(outcome.classify_push_failure(AUTH_403.decode()), outcome.AUTH)
        self.assertEqual(outcome.classify_push_failure(
            "remote: error: GH006: Protected branch update failed"), outcome.AUTH)
        self.assertEqual(outcome.classify_push_failure(
            "fatal: unable to access: Could not resolve host: github.com"), outcome.TRANSIENT)
        self.assertEqual(outcome.classify_push_failure("pre-receive hook declined"), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
