"""Replay of the 2026-11-04 GitHub push incidents (P0 #107, runs 41808825267 and 41813625818).

Production stderr: ``remote: fatal error in commit_refs`` followed by
``! [remote rejected] <sha> -> main (failure)``. Before this fix the classifier returned
UNKNOWN, so the collector stopped after ONE attempt without reading the remote (PUSH_REFUSED),
and LAB V4 stopped on the 4th attempt the same way. These tests prove, offline against a bare
repository (no provider, no Telegram), that the error is now treated as an uncertain 5xx:

* the remote is read before anything else happens (a candidate GitHub did apply is accepted,
  never pushed twice);
* a candidate that did not land is retried with a bounded, revalidated attempt;
* a persistent failure stops after ``max_transport_failures`` with a bundle and a receipt;
* an UNCLASSIFIED refusal is still read back once (no retry) so a landed commit is never
  reported as lost;
* AUTH refusals are still never retried.
"""
import subprocess
import unittest

from scripts import git_publish_outcome as outcome
from scripts import git_selective_publish as sel
from tests import test_collect_publish_safe as collect_tests
from tests import test_h1_publish_safe as h1_tests
from tests import test_lab_ft_publish_408 as ft_tests
from tests.git_writers import AUTH_403, HTTP_408, PushHook, accept_then_fail, fail, git

# Exact stderr of collector run 41808825267 (2026-11-04T09:36:22Z).
COMMIT_REFS = (b"remote: fatal error in commit_refs        \n"
               b"To https://github.com/nunovinhas-creator/asianodds-h1-lab\n"
               b" ! [remote rejected] 9706ef918213cc5ab0d009affa04e75ac65d6a0c -> main (failure)\n"
               b"error: failed to push some refs to "
               b"'https://github.com/nunovinhas-creator/asianodds-h1-lab'\n")
# Exact stderr of the E5 receipt pushes in run 41809284355 (GitHub 500 on the ref line).
REMOTE_500 = (b"To https://github.com/nunovinhas-creator/asianodds-h1-lab\n"
              b" ! [remote rejected] df83ac4c8956c6bb07d3ab448726a1afc5980164 -> main "
              b"(Internal Server Error)\n"
              b"error: failed to push some refs to "
              b"'https://github.com/nunovinhas-creator/asianodds-h1-lab'\n")
HOOK_DECLINED = (b"remote: error: hook declined to update refs/heads/main\n"
                 b" ! [remote rejected] HEAD -> main (hook declined)\n")


class Classifier(unittest.TestCase):
    def test_commit_refs_is_uncertain_not_unknown(self):
        self.assertEqual(outcome.classify_push_failure(COMMIT_REFS.decode()), outcome.UNCERTAIN)

    def test_existing_classes_unchanged(self):
        self.assertEqual(outcome.classify_push_failure(REMOTE_500.decode()), outcome.UNCERTAIN)
        self.assertEqual(outcome.classify_push_failure(HTTP_408.decode()), outcome.UNCERTAIN)
        self.assertEqual(outcome.classify_push_failure(AUTH_403.decode()), outcome.AUTH)
        # An auth refusal stays AUTH even if the same stderr also mentions commit_refs.
        self.assertEqual(outcome.classify_push_failure(
            AUTH_403.decode() + COMMIT_REFS.decode()), outcome.AUTH)
        self.assertEqual(outcome.classify_push_failure(HOOK_DECLINED.decode()), "UNKNOWN")

    def test_backoff_is_bounded_and_monotonic(self):
        waits = [outcome.transport_backoff(n) for n in range(1, 9)]
        self.assertEqual(waits[:3], [4, 12, 36])
        self.assertEqual(waits, sorted(waits))
        self.assertLessEqual(max(waits), 60)
        # Default bound (3 transport failures) waits at most 52 s in total.
        self.assertEqual(sum(outcome.transport_backoff(n) for n in range(1, 4)), 52)


class CollectorAndLabIncident(collect_tests.Base):
    """The shared selective publisher (collector, LAB V4, E5 receipts, offline V6)."""

    def publish_recording_sleeps(self, root, base, hook, **kw):
        sleeps = []
        receipt = self.fx.home / "receipt.json"
        bundle = self.fx.home / "unpublished.bundle"
        self.hook = hook
        try:
            return sel.publish(root, base=base,
                               policy=collect_tests.c.CollectorPolicy(render=collect_tests.render),
                               receipt=receipt, bundle=bundle, push=hook,
                               sleep=sleeps.append, **kw), sleeps
        finally:
            import json
            self.receipt = json.loads(receipt.read_text()) if receipt.exists() else None
            self.bundle = bundle
            self.sleeps = sleeps

    def test_run_41808825267_commit_refs_before_acceptance_is_retried_once(self):
        root, base = collect_tests.collector_cycle(self.fx)
        hook = PushHook({1: fail(COMMIT_REFS)})
        published, sleeps = self.publish_recording_sleeps(root, base, hook)
        self.assertEqual(len(hook.calls), 2)
        self.assertEqual((self.receipt["status"], self.receipt["path"]),
                         ("PUBLISHED", "AFTER_TRANSPORT"))
        self.assertEqual(self.fx.main(), published)
        self.assertEqual(git(self.fx.remote, "log", "--format=%s", "main")
                         .count(collect_tests.c.MESSAGE), 1)
        self.assertIn(4, sleeps)

    def test_commit_refs_after_acceptance_is_confirmed_without_second_push(self):
        root, base = collect_tests.collector_cycle(self.fx)
        hook = PushHook({1: accept_then_fail(COMMIT_REFS)})
        published, _ = self.publish_recording_sleeps(root, base, hook)
        self.assertEqual(len(hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR")
        self.assertEqual(self.fx.main(), published)
        self.assertEqual(git(self.fx.remote, "log", "--format=%s", "main")
                         .count(collect_tests.c.MESSAGE), 1)

    def test_run_41813625818_sequence_is_bounded_and_keeps_a_bundle(self):
        # LAB V4 10:22Z: UNCERTAIN x3 then commit_refs. Every failure is transport now; the
        # publisher stops after the bound with OUTCOME_UNRESOLVED (TRANSPORT) and a bundle.
        root, base = collect_tests.collector_cycle(self.fx)
        script = {1: fail(REMOTE_500), 2: fail(REMOTE_500), 3: fail(REMOTE_500),
                  4: fail(COMMIT_REFS), 5: fail(COMMIT_REFS)}
        with self.assertRaises(sel.OutcomeUnresolved):
            self.publish_recording_sleeps(root, base, PushHook(script))
        self.assertEqual(len(self.hook.calls), 4)
        self.assertEqual((self.receipt["status"], self.receipt["failure_class"]),
                         ("OUTCOME_UNRESOLVED", "TRANSPORT"))
        self.assertEqual(self.receipt["push_failures"], ["UNCERTAIN"] * 4)
        self.assertEqual(self.fx.main(), base, "remote untouched")
        self.assertTrue(self.bundle.exists(), "unpublished observations exported")
        self.assertEqual(self.sleeps.count(4) + self.sleeps.count(12) + self.sleeps.count(36), 3)
        self.assertEqual(self.receipt["provider_requeries"], 0)
        self.assertEqual(self.receipt["telegram_requests"], 0)

    def test_unclassified_refusal_that_landed_is_confirmed_not_lost(self):
        root, base = collect_tests.collector_cycle(self.fx)
        hook = PushHook({1: accept_then_fail(HOOK_DECLINED)})
        published, _ = self.publish_recording_sleeps(root, base, hook)
        self.assertEqual(len(hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR")
        self.assertEqual(self.receipt["unclassified_push_error"], "UNKNOWN")
        self.assertEqual(self.fx.main(), published)

    def test_unclassified_refusal_not_on_remote_is_refused_without_retry(self):
        root, base = collect_tests.collector_cycle(self.fx)
        with self.assertRaises(sel.PushRefused):
            self.publish_recording_sleeps(root, base, PushHook({1: fail(HOOK_DECLINED)}))
        self.assertEqual(len(self.hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUSH_REFUSED")
        self.assertEqual(self.fx.main(), base)
        self.assertTrue(self.bundle.exists())

    def test_auth_is_still_never_retried(self):
        root, base = collect_tests.collector_cycle(self.fx)
        with self.assertRaises(sel.PushRefused):
            self.publish_recording_sleeps(root, base, PushHook({1: fail(AUTH_403)}))
        self.assertEqual(len(self.hook.calls), 1)


class FTIncident(ft_tests.FTPushOutcomeTests):
    def test_ft_commit_refs_is_retried_and_published_once(self):
        def hook(n, real, args):
            if n == 1:
                return subprocess.CompletedProcess(args, 1, b"", COMMIT_REFS)
            return real()
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(self.remote_main(), published)

    def test_ft_commit_refs_after_acceptance_single_push(self):
        def hook(n, real, args):
            real()
            return subprocess.CompletedProcess(args, 1, b"", COMMIT_REFS)
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(self.remote_main(), published)

    def test_ft_unclassified_refusal_that_landed_is_confirmed(self):
        def hook(n, real, args):
            real()
            return subprocess.CompletedProcess(args, 1, b"", HOOK_DECLINED)
        published, pushes = self.run_publish(hook)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(self.remote_main(), published)


class H1Incident(h1_tests.H1PublishTests):
    def test_h1_commit_refs_is_retried_and_published_once(self):
        def hook(n, real, args):
            if n == 1:
                return subprocess.CompletedProcess(args, 1, b"", COMMIT_REFS)
            return real()
        published, pushes = self.publish(hook)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(git(self.remote, "rev-parse", "main"), published)

    def test_h1_unclassified_refusal_that_landed_is_confirmed(self):
        def hook(n, real, args):
            real()
            return subprocess.CompletedProcess(args, 1, b"", HOOK_DECLINED)
        published, pushes = self.publish(hook)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(git(self.remote, "rev-parse", "main"), published)


# Do not re-run the inherited test suites from this module.
for _cls, _parents in ((CollectorAndLabIncident, (collect_tests.Base,)),
                       (FTIncident, (ft_tests.FTPushOutcomeTests, ft_tests._base.GitFTPublicationTests)),
                       (H1Incident, (h1_tests.H1PublishTests,))):
    for _parent in _parents:
        for _name in [n for n in dir(_parent) if n.startswith("test_")]:
            if _name not in _cls.__dict__:
                setattr(_cls, _name, None)
del _cls, _parents, _parent, _name   # never let the loop variables be collected as test classes

if __name__ == "__main__":
    unittest.main()
