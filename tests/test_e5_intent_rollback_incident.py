"""Replay of collector/E5 run 41809284355 (2026-11-04T09:42Z, P0 #107).

Production sequence: the E5 notifier persisted the intent ``2026-11-04,1488,797|WITHDRAWN``
(send_in_progress) and asked the E5 receipt publisher to put it on main BEFORE the Telegram
request. GitHub answered four pushes with ``[remote rejected] ... (Internal Server Error)``;
the intent was not durable, so nothing was sent (correct: ``sent 0, withdrawals_sent 0``).
The notifier rolled the intent back in memory and flushed the final ledger. That flush was
composed on top of the UNPUBLISHED local intent commit (df83ac4c), so the rollback looked like
"Telegram receipt removed" and was refused as PERSISTENT_INCOMPATIBILITY.

The tests drive the real ``telegram_delivery.deliver`` + the real ``e5_receipt_publisher``
against a bare 'GitHub' (no Telegram, no provider) and prove:

* a failed intent publication leaves HEAD on the published base and main untouched;
* the final flush after the rollback is a no-op (nothing removed, nothing refused);
* the next cycle publishes the intent, sends once, and records ``sent`` exactly once;
* if GitHub DID apply the intent despite the error, nothing is sent and the next cycle
  marks it UNCERTAIN (at-most-once), never a resend.
"""
import functools
import json
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from h1lab import telegram_delivery as delivery
from h1lab.e5_notify import _write as e5_write
from scripts import collect_publish_safe as c
from scripts import git_selective_publish as sel
from tests.git_writers import BareGitFixture, PushHook, accept_then_fail, fail, git

LEDGER = "data/e5-over25-notifications.json"
KEY = "2026-11-04,1488,797|WITHDRAWN"
REMOTE_500 = (b"To https://github.com/nunovinhas-creator/asianodds-h1-lab\n"
              b" ! [remote rejected] df83ac4c8956c6bb07d3ab448726a1afc5980164 -> main "
              b"(Internal Server Error)\n"
              b"error: failed to push some refs to "
              b"'https://github.com/nunovinhas-creator/asianodds-h1-lab'\n")
NOW = datetime(2026, 11, 4, 9, 42, 9, tzinfo=timezone.utc)
BASE = {"match_key": "2026-11-04,1488,797", "kickoff_utc": "2026-11-04T10:00:00+00:00",
        "transition": "WITHDRAWN"}


class Store:
    def active(self, moment):
        return None

    def read(self):
        return None


class Sender:
    def __init__(self):
        self.messages = []

    def __call__(self, text):
        self.messages.append(text)
        return 483


class E5IntentRollback(unittest.TestCase):
    def setUp(self):
        self.fx = BareGitFixture()
        self.addCleanup(self.fx.cleanup)
        self.root = self.fx.clone("collector")
        self.no_network = patch("urllib.request.urlopen",
                                side_effect=AssertionError("provider called"))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def publisher(self, hook):
        publish = functools.partial(sel.publish, push=hook, sleep=lambda s: None)
        return c.e5_receipt_publisher(self.root, publish=publish)

    def cycle(self, publisher, sender):
        """The e5_notify.run persistence contract around one deliver() call."""
        path = self.root / LEDGER
        ledger = json.loads(path.read_text())
        stats = {}

        def persist(value):
            e5_write(path, value)
            if delivery.has_intent(value):
                publisher(final=False)
        outcome = delivery.deliver(ledger, KEY, sender, "withdrawal", BASE, {}, lambda: NOW,
                                   persist, stats, Store())
        e5_write(path, ledger)
        final_error = None
        try:
            publisher(final=True)
        except delivery.IntentNotDurable as exc:
            final_error = str(exc)
        return outcome, stats, final_error

    def test_run_41809284355_failed_intent_then_final_flush_is_not_a_refusal(self):
        before = self.fx.main()
        sender = Sender()
        hook = PushHook({n: fail(REMOTE_500) for n in range(1, 20)})
        outcome, stats, final_error = self.cycle(self.publisher(hook), sender)
        self.assertEqual(outcome, "stop")
        self.assertEqual(stats.get("intent_not_durable"), 1)
        self.assertEqual(sender.messages, [], "nothing sent without a durable intent")
        self.assertEqual(len(hook.calls), 4, "bounded: 1 + 3 transport retries")
        self.assertIsNone(final_error, "rollback of an undurable intent is not 'receipt removed'")
        self.assertEqual(self.fx.main(), before, "main untouched")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before, "HEAD back on the base")
        self.assertNotIn(KEY, self.fx.json(LEDGER)["entries"])
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=no"), "")

        # Next cycle (09:51Z in production): GitHub healthy -> intent, one send, outcome.
        sender2 = Sender()
        outcome, stats, final_error = self.cycle(self.publisher(PushHook()), sender2)
        self.assertEqual((outcome, final_error), ("sent", None))
        self.assertEqual(len(sender2.messages), 1)
        entry = self.fx.json(LEDGER)["entries"][KEY]
        self.assertEqual((entry["status"], entry["telegram_message_id"]), ("sent", 483))
        log = git(self.fx.remote, "log", "--format=%s", "main")
        self.assertEqual(log.count(c.E5_MESSAGE), 2, "one intent commit + one outcome commit")

    def test_intent_applied_by_github_despite_error_is_never_resent(self):
        sender = Sender()
        hook = PushHook({1: accept_then_fail(REMOTE_500)})
        outcome, stats, final_error = self.cycle(self.publisher(hook), sender)
        # The probe confirms the intent on main -> durable -> the send happens exactly once.
        self.assertEqual(outcome, "sent")
        self.assertEqual(len(sender.messages), 1)
        self.assertIsNone(final_error)
        self.assertEqual(self.fx.json(LEDGER)["entries"][KEY]["status"], "sent")

    def test_unreadable_remote_after_intent_push_sends_nothing_and_next_cycle_is_uncertain(self):
        sender = Sender()

        def accepted_then_offline(real, candidate):
            assert real().returncode == 0
            self.fx.remote.rename(self.fx.home / "offline.git")
            return subprocess.CompletedProcess(["git"], 128, b"", REMOTE_500)
        outcome, stats, final_error = self.cycle(
            self.publisher(PushHook({1: accepted_then_offline})), sender)
        self.assertEqual(outcome, "stop")
        self.assertEqual(sender.messages, [])
        (self.fx.home / "offline.git").rename(self.fx.remote)
        # GitHub had applied the intent: main holds send_in_progress although nothing was sent.
        self.assertEqual(self.fx.json(LEDGER)["entries"][KEY]["status"], delivery.IN_PROGRESS)
        # Next cycle starts from main: the stale intent becomes UNCERTAIN, never a resend.
        git(self.root, "fetch", "-q", "origin", "main")
        git(self.root, "reset", "-q", "--hard", "origin/main")
        ledger = json.loads((self.root / LEDGER).read_text())
        stats = {}
        self.assertEqual(delivery.gate(ledger, KEY, NOW, NOW, stats), "skip")
        self.assertEqual(ledger["entries"][KEY]["status"], delivery.UNCERTAIN)


if __name__ == "__main__":
    unittest.main()
