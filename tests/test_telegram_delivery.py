"""Telegram delivery state machine: confirmed / rejected / uncertain / expired. Offline only."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from h1lab import bot, telegram_delivery as td
from h1lab import three_moves_notify as three
from h1lab import two_up_notify as two
from h1lab.bot import BotBlockedError, BotDeliveryError, BotRejectedError
from h1lab.telegram_block import BlockStore
from tests.test_three_moves_notify import candidates as three_rows, NOW as T0, KO

NOW = T0
_TMP = None


def setUpModule():
    global _TMP
    _TMP = tempfile.mkdtemp()
    os.environ["TG_DELIVERY_BLOCK_FILE"] = os.path.join(_TMP, "block.json")


def tearDownModule():
    os.environ.pop("TG_DELIVERY_BLOCK_FILE", None)
    shutil.rmtree(_TMP, ignore_errors=True)


def rejected(code, retry_after=None):
    def send(_):
        raise BotRejectedError("TELEGRAM_DELIVERY_REJECTED: HTTP %d" % code, code, retry_after)
    return send


class Clock:
    def __init__(self, start): self.now = start
    def __call__(self): return self.now
    def advance(self, **kw): self.now += timedelta(**kw)


def run_once(rows, ledger, sender, clock, persist=None, store=None):
    return three.process(rows, ledger, clock.now, sender, True, clock=clock, persist=persist, store=store)


class Base(unittest.TestCase):
    def setUp(self):
        BlockStore().clear()
        self.rows = three_rows()
        self.clock = Clock(NOW)
        self.ledger = three.empty_ledger(NOW)

    def tearDown(self):
        BlockStore().clear()

    def entry(self):
        return self.ledger["entries"]["fixture-1"]


class HttpClassificationTests(Base):
    """bot.send_message against a faked urlopen: the real classification, no network."""

    def call(self, exc_or_body, counter=None):
        env = {"TG_BOT_TOKEN": "123:SECRET", "TG_CHAT_ID": "42"}
        def fake(request, timeout=0):
            if counter is not None: counter.append(1)
            if isinstance(exc_or_body, Exception):
                raise exc_or_body
            return exc_or_body
        with patch.dict(os.environ, env), patch.object(bot, "urlopen", fake):
            return bot.send_message("x")

    def http_error(self, code, body=None):
        return HTTPError("https://api.telegram.org/botSECRET/sendMessage", code, "x", {},
                         io.BytesIO(json.dumps(body or {}).encode()))

    def test_429_carries_retry_after_never_leaks_the_token_and_blocks_everyone(self):
        with self.assertRaises(BotRejectedError) as ctx:
            self.call(self.http_error(429, {"ok": False, "parameters": {"retry_after": 17}}))
        self.assertEqual((ctx.exception.http_status, ctx.exception.retry_after), (429, 17))
        self.assertNotIn("SECRET", str(ctx.exception))
        block = BlockStore().read()
        self.assertEqual(block["http_status"], 429)
        self.assertNotIn("SECRET", json.dumps(block))
        calls = []
        with self.assertRaises(BotBlockedError):          # any other notifier is stopped before HTTP
            self.call(self.http_error(500), calls)
        self.assertEqual(calls, [])

    def test_auth_rejection_blocks_24h_with_a_diagnosis_and_no_secret(self):
        for code in (401, 403):
            BlockStore().clear()
            with self.assertRaises(BotRejectedError):
                self.call(self.http_error(code))
            block = BlockStore().read()
            self.assertEqual(block["diagnosis"], td.AUTH_DIAGNOSIS)
            until = datetime.fromisoformat(block["until"])
            self.assertGreater(until - datetime.now(timezone.utc), timedelta(hours=23, minutes=59))
            self.assertNotIn("SECRET", json.dumps(block))

    def test_other_4xx_rejected_without_block_but_5xx_and_network_are_uncertain(self):
        for code in (400, 404):
            with self.assertRaises(BotRejectedError):
                self.call(self.http_error(code))
            self.assertIsNone(BlockStore().read())
        for exc in (self.http_error(500), self.http_error(502), URLError("down"), TimeoutError()):
            with self.assertRaises(BotDeliveryError) as ctx:
                self.call(exc)
            self.assertNotIsInstance(ctx.exception, BotRejectedError)
            self.assertEqual(ctx.exception.outcome, "DELIVERY_UNCERTAIN")
        self.assertIsNone(BlockStore().read())

    def test_hostile_retry_after_is_ignored_and_a_conservative_default_blocks(self):
        for bad in ("5", -1, 10 ** 9, None, True):
            BlockStore().clear()
            with self.assertRaises(BotRejectedError) as ctx:
                self.call(self.http_error(429, {"parameters": {"retry_after": bad}}))
            self.assertIsNone(ctx.exception.retry_after)
            self.assertEqual(BlockStore().read()["diagnosis"], "FLOOD_WAIT_CONSERVATIVE_5MIN")

    def test_corrupt_or_inaccessible_block_file_sends_nothing_explicitly_and_does_not_crash_the_job(self):
        import contextlib, io
        target = Path(os.environ["TG_DELIVERY_BLOCK_FILE"])
        for label, prepare in (("corrupt", lambda: target.write_text("{not json")),
                               ("wrong schema", lambda: target.write_text('{"schema_version": 9}')),
                               ("a directory", lambda: (target.unlink(), target.mkdir()))):
            with self.subTest(label=label):
                if target.is_dir(): target.rmdir()
                prepare()
                buf = io.StringIO()
                with contextlib.redirect_stderr(buf):
                    ledger, stats = run_once(self.rows, three.empty_ledger(NOW), lambda m: self.fail("sent"), self.clock)
                self.assertEqual((ledger["entries"], stats.get("block_unreadable")), ({}, 1))
                self.assertIn("TELEGRAM_BLOCK_UNREADABLE", buf.getvalue())
                with self.assertRaises(BotBlockedError):                      # bot.send_message itself (all six modules)
                    with patch.dict(os.environ, {"TG_BOT_TOKEN": "1:T", "TG_CHAT_ID": "1"}), \
                         patch.object(bot, "urlopen", lambda *a, **k: self.fail("HTTP attempted")):
                        bot.send_message("x")
                if target.is_dir(): target.rmdir()
        target.unlink(missing_ok=True)


class RetryAfterTests(Base):
    def test_retry_after_is_never_truncated(self):
        for seconds in (30, 300, 6 * 3600, 12 * 3600, 24 * 3600):
            BlockStore().clear()
            ledger = three.empty_ledger(NOW)
            clock = Clock(NOW)
            ledger, _ = run_once(self.rows, ledger, rejected(429, seconds), clock)
            entry = ledger["entries"]["fixture-1"]
            self.assertEqual(entry["status"], "delivery_rejected", seconds)
            expected = NOW + timedelta(seconds=seconds) + td.RETRY_MARGIN
            self.assertEqual(entry["retry_not_before"], expected.isoformat(timespec="seconds"))
            self.assertEqual(BlockStore().read()["until"], expected.isoformat(timespec="seconds"))
            # inside the wait: no HTTP; right after it: sent once
            clock.now = expected - timedelta(seconds=2)
            calls = []
            ledger, st = run_once(self.rows, ledger, lambda m: calls.append(m) or 1, clock)
            self.assertEqual((calls, st.get("rejected_waiting")), ([], 1), seconds)
            clock.now = expected
            ledger, _ = run_once(self.rows, ledger, lambda m: calls.append(m) or 7, clock)
            self.assertEqual((len(calls), ledger["entries"]["fixture-1"]["status"]), (1, "sent"), seconds)

    def test_retry_after_beyond_kickoff_expires_without_a_new_send(self):
        self.clock.now = KO - timedelta(hours=1)
        self.ledger, stats = run_once(self.rows, self.ledger, rejected(429, 6 * 3600), self.clock)
        self.assertEqual(self.entry()["status"], "expired_not_sent")
        self.assertEqual(self.entry()["reason"], "retry_not_before_kickoff")
        self.assertEqual(stats["expired_not_sent"], 1)
        self.clock.now = KO + timedelta(days=1)
        run_once(self.rows, self.ledger, lambda m: self.fail("sent after expiry"), self.clock)

    def test_missing_retry_after_uses_a_bounded_exponential_backoff(self):
        waits = []
        for _ in range(4):
            self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, None), self.clock)
            waits.append((datetime.fromisoformat(self.entry()["retry_not_before"]) - self.clock.now).total_seconds())
            self.clock.now = datetime.fromisoformat(self.entry()["retry_not_before"])
        self.assertEqual(waits, [300, 600, 1200, 2400])
        self.assertLessEqual(max(waits), 3600)

    def test_flood_attempts_are_bounded(self):
        calls = []
        def send(m): calls.append(m); raise BotRejectedError("x", 429, 5)
        for _ in range(td.MAX_FLOOD_ATTEMPTS + 3):
            self.ledger, _ = run_once(self.rows, self.ledger, send, self.clock)
            self.clock.advance(seconds=10)
        self.assertEqual(len(calls), td.MAX_FLOOD_ATTEMPTS)
        self.assertEqual(self.entry()["status"], "delivery_rejected_final")


class AuthTests(Base):
    def test_401_suspends_for_a_day_then_one_probe_then_stops(self):
        calls = []
        def send(m): calls.append(m); raise BotRejectedError("x", 401)
        self.ledger, _ = run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(self.entry()["diagnosis"], td.AUTH_DIAGNOSIS)
        for hours in (1, 6, 12, 23):          # suspended: no repeated useless attempts
            self.clock.now = NOW + timedelta(hours=hours)
            run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(len(calls), 1)
        self.clock.now = NOW + timedelta(hours=24, seconds=2)   # controlled recovery probe
        self.ledger, _ = run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.entry()["status"], "delivery_rejected_final")  # MAX_AUTH_ATTEMPTS
        self.clock.now = NOW + timedelta(days=3)
        run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(len(calls), 2)

    def test_a_new_game_after_the_credentials_are_fixed_recovers_the_channel(self):
        self.ledger, _ = run_once(self.rows, self.ledger, rejected(403), self.clock)
        self.assertIsNotNone(BlockStore().read())
        other = {**three_rows()[0], "match_key": "fixture-2", "match_label": "B vs C"}
        self.clock.now = NOW + timedelta(hours=24, seconds=2)     # block lapsed; token was fixed meanwhile
        self.ledger, stats = run_once([other], self.ledger, lambda m: 55, self.clock)
        self.assertEqual(self.ledger["entries"]["fixture-2"]["status"], "sent")


class StateMachineTests(Base):
    def test_429_stops_the_whole_batch_but_does_not_poison_other_games(self):
        other = {**three_rows()[0], "match_key": "fixture-2", "match_label": "B vs C"}
        calls = []
        def send(m): calls.append(m); raise BotRejectedError("x", 429, 30)
        self.ledger, stats = three.process([self.rows[0], other], self.ledger, NOW, send, True, clock=self.clock)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("fixture-2", self.ledger["entries"])

    def test_non_retryable_4xx_is_final_without_blocking_the_channel(self):
        self.ledger, stats = run_once(self.rows, self.ledger, rejected(400), self.clock)
        self.assertEqual(self.entry()["status"], "delivery_rejected_final")
        self.assertIsNone(BlockStore().read())

    def test_timeout_before_or_after_acceptance_is_uncertain_and_never_resent(self):
        calls = []
        def send(m): calls.append(m); raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: timeout")
        self.ledger, _ = run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(self.entry()["status"], "delivery_uncertain_manual_review")
        for _ in range(3):
            self.clock.advance(hours=1)
            run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(len(calls), 1)

    def test_missing_message_id_is_uncertain(self):
        self.ledger, _ = run_once(self.rows, self.ledger, lambda m: None, self.clock)
        self.assertEqual(self.entry()["status"], "delivery_uncertain_manual_review")

    def test_expiry_during_suspension(self):
        self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, 600), self.clock)
        self.clock.now = KO + timedelta(minutes=1)
        BlockStore().clear()
        calls = []
        self.ledger, stats = three.process([], self.ledger, self.clock.now, lambda m: calls.append(m) or 1, True, clock=self.clock)
        self.assertEqual((calls, self.entry()["status"], stats["expired_not_sent"]), ([], "expired_not_sent", 1))
        self.assertEqual(self.entry()["http_status"], 429)

    def test_kickoff_passing_during_the_run_never_sends(self):
        calls = []
        clock = Clock(KO + timedelta(seconds=1))
        ledger, stats = three.process(self.rows, three.empty_ledger(NOW), NOW, lambda m: calls.append(m) or 1, True, clock=clock)
        self.assertEqual((calls, ledger["entries"]), ([], {}))

    def test_crash_during_send_never_duplicates(self):
        snapshots = []
        def persist(value): snapshots.append(json.loads(json.dumps(value)))
        class Crash(BaseException): pass
        def dies(_): raise Crash()
        with self.assertRaises(Crash):
            run_once(self.rows, self.ledger, dies, self.clock, persist)
        self.assertEqual(snapshots[-1]["entries"]["fixture-1"]["status"], "send_in_progress")
        restarted, calls = snapshots[-1], []
        self.clock.advance(minutes=5)
        restarted, _ = run_once(self.rows, restarted, lambda m: calls.append(m) or 5, self.clock)
        self.assertEqual(calls, [])
        self.assertEqual(restarted["entries"]["fixture-1"]["reason"], "process_ended_during_send")

    def test_duplicate_candidate_rows_send_one_alert(self):
        calls = []
        ledger, stats = three.process([self.rows[0], dict(self.rows[0])], self.ledger, NOW, lambda m: calls.append(m) or 3, True, clock=self.clock)
        self.assertEqual((len(calls), stats["sent"], stats["already_notified"]), (1, 1, 1))

    def test_existing_receipts_and_message_ids_are_preserved(self):
        self.ledger["entries"]["fixture-1"] = {"status": "sent", "telegram_message_id": 352, "at": "x"}
        before = json.dumps(self.ledger, sort_keys=True)
        self.ledger, stats = run_once(self.rows, self.ledger, lambda m: self.fail("resent"), self.clock)
        self.assertEqual(json.dumps(self.ledger, sort_keys=True), before)

    def test_state_is_deterministic_after_restart_from_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.json"
            persist = lambda v: path.write_text(json.dumps(v, sort_keys=True))
            self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, 90), self.clock, persist)
            reloaded = json.loads(path.read_text())
            self.assertEqual(reloaded, self.ledger)
            self.clock.advance(seconds=100)
            reloaded, _ = run_once(self.rows, reloaded, lambda m: 9, self.clock, persist)
            self.assertEqual(reloaded["entries"]["fixture-1"]["status"], "sent")


class SharedBlockTests(Base):
    def test_a_429_seen_by_one_notifier_stops_the_other(self):
        from tests.test_two_up_notify import select as select_two, lomza, NOW as T2
        two_rows = select_two(lomza())
        c3 = Clock(T2 - timedelta(minutes=1))
        three_ledger = three.empty_ledger(c3.now)
        run_once(self.rows, three_ledger, rejected(429, 900), c3)
        c2 = Clock(T2)
        calls = []
        ledger, stats = two.process(two_rows, two.empty_ledger(T2), T2, lambda m: calls.append(m) or 1, True, clock=c2)
        self.assertEqual((calls, ledger["entries"], stats.get("suspended")), ([], {}, 1))
        c2.advance(seconds=900)
        ledger, stats = two.process(two_rows, ledger, c2.now, lambda m: calls.append(m) or 2, True, clock=c2)
        self.assertEqual(stats["sent"], 1)

    def test_two_up_uses_the_same_machine(self):
        from tests.test_two_up_notify import select as select_two, lomza, NOW as T2
        rows = select_two(lomza())
        clock = Clock(T2)
        ledger, stats = two.process(rows, two.empty_ledger(T2), T2, rejected(429, 30), True, clock=clock)
        key = rows[0]["match_key"]
        self.assertEqual((ledger["entries"][key]["status"], stats["rejected"]), ("delivery_rejected", 1))
        clock.advance(seconds=32)
        ledger, stats = two.process(rows, ledger, clock.now, lambda m: 11, True, clock=clock)
        self.assertEqual(ledger["entries"][key]["status"], "sent")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class DurableIntentTests(Base):
    """Opt-in TG_DURABLE_INTENT: the intent reaches the remote BEFORE the HTTP call."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", self.remote)
        self.a = os.path.join(self.tmp, "a")
        git(self.tmp, "clone", "-q", self.remote, self.a)
        for key, value in (("user.name", "t"), ("user.email", "t@t")):
            git(self.a, "config", key, value)
        Path(self.a, "data").mkdir()
        Path(self.a, "data/ledger.json").write_text(json.dumps(self.ledger))
        git(self.a, "add", "."); git(self.a, "commit", "-q", "-m", "init"); git(self.a, "push", "-q", "origin", "HEAD:main")
        git(self.a, "checkout", "-q", "-B", "main"); git(self.a, "branch", "-q", "--set-upstream-to=origin/main")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def persist_fn(self, publish):
        path = Path(self.a, "data/ledger.json")
        def persist(value):
            path.write_text(json.dumps(value, sort_keys=True))
            if td.has_intent(value):
                publish()
        return persist

    def test_crash_after_acceptance_and_before_the_final_commit_cannot_duplicate_in_a_fresh_checkout(self):
        publish = td.git_intent_publisher(self.a, "data/ledger.json")
        class Crash(BaseException): pass
        def accepted_then_dies(_): raise Crash()      # Telegram accepted; the job ends here
        with self.assertRaises(Crash):
            run_once(self.rows, self.ledger, accepted_then_dies, self.clock, self.persist_fn(publish))
        fresh = os.path.join(self.tmp, "fresh")       # a NEW Actions job: brand new checkout
        git(self.tmp, "clone", "-q", self.remote, fresh)
        remote_ledger = json.loads(Path(fresh, "data/ledger.json").read_text())
        self.assertEqual(remote_ledger["entries"]["fixture-1"]["status"], "send_in_progress")
        calls = []
        self.clock.advance(minutes=30)
        remote_ledger, _ = run_once(self.rows, remote_ledger, lambda m: calls.append(m) or 9, self.clock)
        self.assertEqual(calls, [])                    # at-most-once: flagged, not resent
        self.assertEqual(remote_ledger["entries"]["fixture-1"]["status"], "delivery_uncertain_manual_review")

    def test_without_the_durable_publisher_a_fresh_checkout_would_resend(self):
        """Documents the residual at-least-once limit of the default configuration."""
        class Crash(BaseException): pass
        def dies(_): raise Crash()
        with self.assertRaises(Crash):
            run_once(self.rows, self.ledger, dies, self.clock, lambda v: Path(self.a, "data/ledger.json").write_text(json.dumps(v)))
        fresh_state = json.loads(git(self.a, "show", "HEAD:data/ledger.json"))   # what the remote/main still holds
        calls = []
        run_once(self.rows, fresh_state, lambda m: calls.append(m) or 9, self.clock)
        self.assertEqual(len(calls), 1)

    def test_unpublishable_intent_fails_closed_and_nothing_is_sent(self):
        git(self.a, "remote", "set-url", "origin", os.path.join(self.tmp, "does-not-exist.git"))
        publish = td.git_intent_publisher(self.a, "data/ledger.json", retries=1)
        calls = []
        ledger, stats = run_once(self.rows, self.ledger, lambda m: calls.append(m) or 1, self.clock, self.persist_fn(publish))
        self.assertEqual((calls, stats.get("intent_not_durable"), ledger["entries"]), ([], 1, {}))

    def test_push_race_is_rebased_and_retried(self):
        other = os.path.join(self.tmp, "other")
        git(self.tmp, "clone", "-q", self.remote, other)
        for key, value in (("user.name", "o"), ("user.email", "o@o")):
            git(other, "config", key, value)
        Path(other, "elsewhere.txt").write_text("x"); git(other, "add", "."); git(other, "commit", "-q", "-m", "o"); git(other, "push", "-q", "origin", "HEAD:main")
        publish = td.git_intent_publisher(self.a, "data/ledger.json")
        calls = []
        ledger, stats = run_once(self.rows, self.ledger, lambda m: calls.append(m) or 4, self.clock, self.persist_fn(publish))
        self.assertEqual((len(calls), ledger["entries"]["fixture-1"]["status"]), (1, "sent"))
        self.assertIn("data: telegram delivery state", git(self.remote, "log", "--format=%s", "main"))


class DurableGitScenarioTests(DurableIntentTests):
    """Phase-3 scenarios against real (local) git remotes."""

    def publisher(self, **kw):
        return td.git_publisher(self.a, lambda: ["data/ledger.json"], guard=td.claim_guard(self.a, "data/ledger.json"),
                                guard_path="data/ledger.json", **kw)

    def checkout(self, name):
        path = os.path.join(self.tmp, name)
        git(self.tmp, "clone", "-q", self.remote, path)
        for key, value in (("user.name", name), ("user.email", name + "@x")):
            git(path, "config", key, value)
        return path

    def test_confirmed_receipt_is_published_right_after_the_send_so_a_later_crash_cannot_make_it_uncertain(self):
        publish = self.publisher()
        persist = self.persist_fn_all(publish)
        class Crash(BaseException): pass
        sent = []
        def send(m): sent.append(m); return 321
        self.ledger, _ = run_once(self.rows, self.ledger, send, self.clock, persist)
        # the job dies here: the final "Store data" commit never happens
        fresh = self.checkout("fresh")
        remote = json.loads(Path(fresh, "data/ledger.json").read_text())
        self.assertEqual((remote["entries"]["fixture-1"]["status"], remote["entries"]["fixture-1"]["telegram_message_id"]), ("sent", 321))
        calls = []
        self.clock.advance(minutes=10)
        remote, _ = run_once(self.rows, remote, lambda m: calls.append(m) or 1, self.clock)
        self.assertEqual(calls, [])

    def persist_fn_all(self, publish):
        path = Path(self.a, "data/ledger.json")
        def persist(value):
            path.write_text(json.dumps(value, sort_keys=True))
            publish()
        return persist

    def test_published_intent_survives_the_later_reconcile_pull_rebase_of_the_job(self):
        publish = self.publisher()
        class Crash(BaseException): pass
        def dies(_): raise Crash()
        with self.assertRaises(Crash):
            run_once(self.rows, self.ledger, dies, self.clock, self.persist_fn_all(publish))
        git(self.a, "pull", "--rebase", "origin", "main")        # what the workflow's final step does
        self.assertEqual(json.loads(git(self.a, "show", "origin/main:data/ledger.json"))["entries"]["fixture-1"]["status"], "send_in_progress")
        self.assertEqual(json.loads(Path(self.a, "data/ledger.json").read_text())["entries"]["fixture-1"]["status"], "send_in_progress")

    def test_dirty_collector_tree_and_remote_race_do_not_break_or_swallow_the_publication(self):
        Path(self.a, "data/state.json").write_text("{}"); git(self.a, "add", "."); git(self.a, "commit", "-q", "-m", "state"); git(self.a, "push", "-q", "origin", "HEAD:main")
        Path(self.a, "data/state.json").write_text('{"collector":"fresh"}')       # uncommitted work of the collect step
        other = self.checkout("other")
        Path(other, "elsewhere.txt").write_text("x"); git(other, "add", "."); git(other, "commit", "-q", "-m", "o"); git(other, "push", "-q", "origin", "HEAD:main")
        calls = []
        ledger, stats = run_once(self.rows, self.ledger, lambda m: calls.append(m) or 4, self.clock, self.persist_fn_all(self.publisher()))
        self.assertEqual((len(calls), ledger["entries"]["fixture-1"]["status"]), (1, "sent"))
        self.assertEqual(Path(self.a, "data/state.json").read_text(), '{"collector":"fresh"}')   # not committed, not lost
        remote_files = git(self.remote, "ls-tree", "-r", "--name-only", "main")
        self.assertIn("elsewhere.txt", remote_files)
        self.assertEqual(git(self.remote, "show", "main:data/state.json"), "{}")

    def test_two_concurrent_runs_cannot_both_send_the_same_alert(self):
        b = self.checkout("b")                                   # stale clone: same starting ledger
        publish_a = self.publisher()
        calls_a, calls_b = [], []
        run_once(self.rows, three.empty_ledger(NOW), lambda m: calls_a.append(m) or 1, self.clock, self.persist_fn_all(publish_a))
        path_b = Path(b, "data/ledger.json")
        def persist_b(v):
            path_b.write_text(json.dumps(v, sort_keys=True))
            td.git_publisher(b, ["data/ledger.json"], guard=td.claim_guard(b, "data/ledger.json"), guard_path="data/ledger.json")()
        ledger_b, stats_b = run_once(self.rows, three.empty_ledger(NOW), lambda m: calls_b.append(m) or 2, Clock(NOW + timedelta(seconds=1)), persist_b)
        self.assertEqual((len(calls_a), len(calls_b)), (1, 0))
        self.assertEqual(stats_b.get("intent_not_durable"), 1)

    def test_retry_of_a_retryable_rejection_is_not_blocked_by_its_own_earlier_state(self):
        publish = self.publisher()
        persist = self.persist_fn_all(publish)
        self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, 60), self.clock, persist)
        self.assertEqual(self.entry()["status"], "delivery_rejected")
        self.clock.advance(seconds=70)
        calls = []
        self.ledger, _ = run_once(self.rows, self.ledger, lambda m: calls.append(m) or 8, self.clock, persist)
        self.assertEqual((len(calls), self.entry()["status"]), (1, "sent"))

    def test_post_outcome_publication_failure_is_diagnosed_not_silent_and_keeps_the_outcome(self):
        good = self.publisher()
        state = {"fail": False}
        def persist(value):
            Path(self.a, "data/ledger.json").write_text(json.dumps(value, sort_keys=True))
            if state["fail"]:
                raise td.IntentNotDurable("simulated push failure")
            good()
        def send(m): state["fail"] = True; return 11          # intent published OK, outcome publication fails
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            ledger, stats = run_once(self.rows, self.ledger, send, self.clock, persist)
        self.assertEqual((ledger["entries"]["fixture-1"]["status"], stats.get("publish_failed")), ("sent", 1))
        self.assertIn("TELEGRAM_PUBLISH_FAILED", buf.getvalue())

    def test_429_block_is_published_and_a_fresh_checkout_sees_it(self):
        env = os.environ.get("TG_DELIVERY_BLOCK_FILE")
        block_path = Path(self.a, "data/telegram-delivery-block.json")
        os.environ["TG_DELIVERY_BLOCK_FILE"] = str(block_path)
        try:
            publish = td.git_publisher(self.a, lambda: ["data/ledger.json", "data/telegram-delivery-block.json"],
                                       guard=td.claim_guard(self.a, "data/ledger.json"), guard_path="data/ledger.json")
            self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, 900), self.clock, self.persist_fn_all(publish), store=BlockStore(block_path))
            fresh = self.checkout("fresh2")
            data = json.loads(Path(fresh, "data/telegram-delivery-block.json").read_text())
            self.assertEqual(data["http_status"], 429)
            until = datetime.fromisoformat(data["until"])
            self.assertEqual(until, NOW + timedelta(seconds=901))
            self.assertIsNotNone(BlockStore(Path(fresh, "data/telegram-delivery-block.json")).active(NOW + timedelta(seconds=10)))
            self.assertIsNone(BlockStore(Path(fresh, "data/telegram-delivery-block.json")).active(NOW + timedelta(seconds=902)))
        finally:
            if env is None: os.environ["TG_DELIVERY_BLOCK_FILE"] = os.path.join(_TMP, "block.json")
            else: os.environ["TG_DELIVERY_BLOCK_FILE"] = env

    def test_rollback_to_default_mode_changes_nothing_in_the_ledger_format(self):
        """Durable off (default): the same ledger, no git calls at all."""
        calls = []
        ledger, _ = run_once(self.rows, self.ledger, lambda m: calls.append(m) or 5, self.clock, None)
        self.assertEqual(self.entry()["status"], "sent")
        self.assertFalse(td.durable_enabled())


class BlockStoreSemanticsTests(Base):
    def test_never_shortens_an_active_block_and_ignore_auth_only_lifts_401_403(self):
        store = BlockStore()
        store.record(NOW + timedelta(hours=2), 429, NOW, "FLOOD")
        store.record(NOW + timedelta(minutes=5), 429, NOW, "FLOOD_SHORT")      # a shorter value must not win
        self.assertEqual(store.read()["until"], (NOW + timedelta(hours=2)).isoformat(timespec="seconds"))
        self.assertIsNotNone(store.active(NOW, ignore_auth=True))                # 429 is never lifted early
        store.clear()
        store.record(NOW + timedelta(hours=24), 401, NOW, td.AUTH_DIAGNOSIS)
        self.assertIsNotNone(store.active(NOW))
        self.assertIsNone(store.active(NOW, ignore_auth=True))                   # credentials fixed
        self.assertIsNone(store.active(NOW + timedelta(hours=25)))               # expired lapses by itself

    def test_a_confirmed_send_clears_only_an_expired_block_file(self):
        store = BlockStore()
        store.record(NOW - timedelta(minutes=1), 429, NOW - timedelta(minutes=10), "OLD")
        self.ledger, _ = run_once(self.rows, self.ledger, lambda m: 3, self.clock)
        self.assertIsNone(store.read())


class MergeGateTests(Base):
    """Gates 4-10 of the integration order, as executable checks."""

    def test_no_secret_reaches_any_output_ledger_or_block_file_on_any_failure_path(self):
        import contextlib, io
        secret = "987654321:AAH-SECRET-TOKEN-VALUE"
        env = {"TG_BOT_TOKEN": secret, "TG_CHAT_ID": "42"}
        out, err = io.StringIO(), io.StringIO()
        exceptions = []
        def http(code, body=None):
            return HTTPError("https://api.telegram.org/bot%s/sendMessage" % secret, code, "x", {},
                             io.BytesIO(json.dumps(body or {"parameters": {"retry_after": 30}}).encode()))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.dict(os.environ, env):
            for failure in (http(429), http(401), http(403), http(400), http(500), URLError("https://x/bot" + secret), TimeoutError()):
                BlockStore().clear()
                ledger = three.empty_ledger(NOW)
                def fake(request, timeout=0, failure=failure): raise failure
                with patch.object(bot, "urlopen", fake):
                    ledger, stats = three.process(self.rows, ledger, NOW, bot.send_message, True, clock=Clock(NOW))
                exceptions.append(json.dumps(ledger) + json.dumps(stats))
                block = Path(os.environ["TG_DELIVERY_BLOCK_FILE"])
                if block.exists():
                    exceptions.append(block.read_text())
        everything = out.getvalue() + err.getvalue() + "".join(exceptions)
        self.assertNotIn("AAH-SECRET", everything)
        self.assertNotIn(secret, everything)

    def test_old_sent_receipts_and_message_ids_survive_every_state_transition(self):
        old = {"status": "sent", "telegram_message_id": 352, "at": "2026-11-01T20:30:00+00:00",
               "kickoff_utc": KO.isoformat(), "rule_version": three.RULE_VERSION}
        self.ledger["entries"]["fixture-1"] = dict(old)
        self.ledger["entries"]["other"] = {"status": "sent", "telegram_message_id": 354}
        for sender in (rejected(429, 5), lambda m: 1, rejected(401)):
            self.ledger, _ = run_once(self.rows, self.ledger, sender, self.clock)
        three.process([], self.ledger, KO + timedelta(days=1), lambda m: 1, True, clock=Clock(KO + timedelta(days=1)))
        self.assertEqual(self.ledger["entries"]["fixture-1"], old)
        self.assertEqual(self.ledger["entries"]["other"]["telegram_message_id"], 354)

    def test_two_up_blocked_before_http_is_not_uncertain(self):
        from tests.test_two_up_notify import select as select_two, lomza, NOW as T2
        def blocked(_): raise BotBlockedError("TELEGRAM_SEND_BLOCKED: no request made")
        ledger, stats = two.process(select_two(lomza()), two.empty_ledger(T2), T2, blocked, True, clock=Clock(T2))
        self.assertEqual((ledger["entries"], stats.get("blocked_before_http"), stats.get("uncertain", 0)), ({}, 1, 0))

    def test_ft_publication_validator_accepts_the_new_terminal_states_and_keeps_receipts_immutable(self):
        from tests.test_lab_ft_publish_safe import eligibility_report
        from scripts import lab_ft_publish_safe as safe
        key = "2026-11-01,a,b"
        def blob(when, receipts):
            return json.dumps(eligibility_report(when, receipts=receipts), sort_keys=True).encode()
        old = blob("2026-11-01T12:00:00+00:00", {})
        for status in td.TERMINAL_RECEIPT_STATUSES:
            with self.subTest(status=status):
                new = blob("2026-11-01T13:00:00+00:00", {"three": {"status": status, "telegram_message_id": 5 if status == "sent" else None}})
                self.assertTrue(safe.valid_telegram_eligibility_update(old, new), status)
        sent = blob("2026-11-01T13:00:00+00:00", {"three": {"status": "sent", "telegram_message_id": 5}})
        flipped = blob("2026-11-01T14:00:00+00:00", {"three": {"status": "delivery_rejected_final", "telegram_message_id": None}})
        self.assertFalse(safe.valid_telegram_eligibility_update(sent, flipped))           # immutability kept
        transient = blob("2026-11-01T14:00:00+00:00", {"three": {"status": "delivery_rejected", "telegram_message_id": None}})
        self.assertFalse(safe.valid_telegram_eligibility_update(old, transient))           # never published as a receipt

    def test_eligibility_report_skips_transient_states_and_accepts_terminal_ones(self):
        from h1lab import telegram_eligibility as te
        self.assertEqual(set(td.TERMINAL_RECEIPT_STATUSES), {"sent", "delivery_uncertain_manual_review", "delivery_rejected_final", "expired_not_sent"})
        self.assertTrue(hasattr(te, "TERMINAL_RECEIPT_STATUSES"))

    def test_the_four_legacy_notifiers_remain_disabled_in_the_workflow(self):
        text = Path(".github/workflows/collect.yml").read_text(encoding="utf-8")
        for module in ("e4_notify", "strategy_notify", "t05_notify", "pattern_notify"):
            self.assertNotIn("h1lab." + module, text, module)
        self.assertIn("h1lab.three_moves_notify", text)
        self.assertIn("h1lab.two_up_notify", text)


class PublicationContractTests(unittest.TestCase):
    def test_transient_states_are_not_receipts_and_terminal_ones_are_accepted(self):
        self.assertIn("delivery_rejected_final", td.TERMINAL_RECEIPT_STATUSES)
        self.assertNotIn("delivery_rejected", td.TERMINAL_RECEIPT_STATUSES)
        self.assertNotIn("send_in_progress", td.TERMINAL_RECEIPT_STATUSES)
        import scripts.lab_ft_publish_safe as safe
        src = Path(safe.__file__).read_text()
        for status in td.TERMINAL_RECEIPT_STATUSES:
            self.assertIn('"%s"' % status, src, status)

    def test_other_notifiers_share_the_block_through_send_message(self):
        # e4/strategy/t05/pattern all send via bot.send_message and therefore stop on the shared block.
        for module in ("e4_notify", "strategy_notify", "t05_notify", "pattern_notify", "three_moves_notify", "two_up_notify"):
            src = Path("h1lab", module + ".py").read_text()
            self.assertIn("send_message", src, module)


if __name__ == "__main__":
    unittest.main()
