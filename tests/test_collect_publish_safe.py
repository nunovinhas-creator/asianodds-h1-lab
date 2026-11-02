"""Bare-Git reproduction of the collector publication risks and of the safe publisher.

Part 1 (``LegacyCollectorFlowRisks``) replays the exact pre-fix shell sequence of
collect.yml (``git add`` ... ``git commit`` ... ``git pull --rebase origin main`` ...
``git push origin main``) AFTER the notifiers have recorded a sent Telegram
receipt, and demonstrates what is lost.

Part 2 (``SafeCollectorPublication``) runs ``scripts.collect_publish_safe`` against
the same events. No test contacts Telegram or a provider: both are patched to fail.
"""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import collect_publish_safe as c
from scripts import git_selective_publish as sel
from tests.git_writers import (AUTH_403, HTTP_408, SENT_NEW, SENT_OLD, BareGitFixture, PushHook,
                               accept_then_fail, fail, git, jline, ledger, race, state, view, write)

THREE = "data/three-total-moves-notifications.json"
TWO = "data/two-up-total-notifications.json"
BLOCK = "data/telegram-delivery-block.json"
MARKETS = "data/lab/markets-2026-11.jsonl"
FORMATS = "data/lab/formats-2026-11.jsonl"
REVISIONS = "data/lab/v4-revisions-2026-11.jsonl"


def no_network():
    return [patch("h1lab.bot.send_message", side_effect=AssertionError("Telegram called")),
            patch("urllib.request.urlopen", side_effect=AssertionError("provider called"))]


def collector_cycle(fx, name="collector", *, new_alert="c:2", last_id=150, receipt=SENT_NEW,
                    commit=True):
    """One collector job after Telegram: new observation, V4 rows, a SENT receipt, rendered view."""
    root = fx.clone(name)
    base = git(root, "rev-parse", "HEAD")
    write(root, "data/state.json", state(last_id=last_id, alerts=("c:1", new_alert)))
    write(root, "docs/data.json", view(2, 1))
    entries = {"2026-11-01_1_2": SENT_OLD}
    if receipt:
        entries["2026-11-03_" + new_alert.split(":")[1]] = receipt
    write(root, THREE, ledger(**entries))
    for path in (MARKETS, FORMATS):
        old = (root / path).read_text()
        write(root, path, old + jline(event_id=new_alert, observed_at="2026-11-02T07:00:00+00:00"))
    write(root, REVISIONS, (root / REVISIONS).read_text() + jline(event_id=new_alert, sha256="b" * 64))
    if commit:
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
    return root, base


def render(root):
    st = json.loads((Path(root) / "data/state.json").read_text())
    rows = (Path(root) / "data/results.csv").read_text().count("\n") - 1
    write(root, "docs/data.json", view(len(st["alerts"]), rows))


class Base(unittest.TestCase):
    def setUp(self):
        self.fx = BareGitFixture()
        self.addCleanup(self.fx.cleanup)
        for p in no_network():
            p.start()
            self.addCleanup(p.stop)

    def publish(self, root, base, hook=None, **kw):
        receipt = self.fx.home / "receipt.json"
        bundle = self.fx.home / "unpublished.bundle"
        self.hook = hook or PushHook()
        try:
            return sel.publish(root, base=base, policy=c.CollectorPolicy(render=render),
                               receipt=receipt, bundle=bundle, push=self.hook,
                               sleep=lambda s: None, **kw)
        finally:
            self.receipt = json.loads(receipt.read_text()) if receipt.exists() else None


# =============================================================================== part 1
class LegacyCollectorFlowRisks(Base):
    """The pre-fix collect.yml sequence (bash -e): every failure here happens AFTER Telegram."""

    def legacy_store(self, root, between_rebase_and_push=None):
        seq = [["add", "data/state.json", "docs/data.json"], ["add", THREE], ["add", TWO],
               ["add", "data/lab"], ["commit", "-qm", c.MESSAGE],
               ["pull", "-q", "--rebase", "origin", "main"]]
        for args in seq:
            proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
            if proc.returncode:
                return "FAILED_AT_" + args[0].upper(), proc
        if between_rebase_and_push:
            between_rebase_and_push()
        proc = subprocess.run(["git", "-C", str(root), "push", "origin", "main"], capture_output=True)
        return ("PUSHED" if proc.returncode == 0 else "FAILED_AT_PUSH"), proc

    def assert_receipt_lost(self):
        three = self.fx.json(THREE)
        self.assertNotIn("2026-11-03,2", three["entries"],
                         "the sent receipt never reached main: the next cycle sees no entry and "
                         "its gate() returns 'send' -> the same alert can be sent again")
        alerts = [a["event_id"] for a in self.fx.json("data/state.json")["alerts"]]
        self.assertNotIn("c:2", alerts, "the collected observation is lost too")
        self.assertNotEqual(self.fx.json("data/state.json")["last_id"], 150,
                            "and so is the Telegram checkpoint of this cycle")

    def test_lab_v4_push_between_rebase_and_push_loses_sent_receipt(self):
        root, _ = collector_cycle(self.fx, commit=False)
        outcome, proc = self.legacy_store(root, lambda: self.fx.plain_commit(
            "lab", {"docs/lab/v4-audit.json": {"n": 2}}, "data(lab): refresh V4"))
        self.assertEqual(outcome, "FAILED_AT_PUSH")
        self.assertRegex(proc.stderr.decode(), "rejected|fetch first|non-fast-forward")
        self.assert_receipt_lost()

    def test_concurrent_state_change_conflicts_after_telegram(self):
        root, _ = collector_cycle(self.fx, commit=False)
        self.fx.plain_commit("collector2", {"data/state.json": state(last_id=140, alerts=("c:1", "c:9"))},
                             "data: collect and notify H1 [skip ci]")
        outcome, proc = self.legacy_store(root)
        self.assertEqual(outcome, "FAILED_AT_PULL")
        self.assertIn("CONFLICT", proc.stdout.decode() + proc.stderr.decode())
        self.assert_receipt_lost()

    def test_concurrent_ledger_change_conflicts_after_telegram(self):
        root, _ = collector_cycle(self.fx, commit=False)
        self.fx.plain_commit("collector2", {THREE: ledger(**{"2026-11-01_1_2": SENT_OLD,
                                                            "2026-11-03_2": {**SENT_NEW, "telegram_message_id": 778}})},
                             "data: collect and notify H1 [skip ci]")
        outcome, _ = self.legacy_store(root)
        self.assertEqual(outcome, "FAILED_AT_PULL")
        self.assertEqual(self.fx.json(THREE)["entries"]["2026-11-03,2"]["telegram_message_id"], 778,
                         "two collectors sent the same alert; nobody reports the duplicate")

    def test_rebase_silently_text_merges_a_view_nobody_rendered(self):
        root, _ = collector_cycle(self.fx, commit=False)
        # H1 re-renders another field of the same dashboard file concurrently.
        self.fx.plain_commit("h1", {"docs/data.json": view(1, 2),
                                    "data/results.csv": "match_key,status,home_goals,away_goals,source\n"
                                    "\"2026-11-01,1,2\",final,1,0,x\n\"2026-11-02,3,4\",final,0,0,y\n"},
                             "data: reconcile verified H1 finals [skip ci]")
        outcome, _ = self.legacy_store(root)
        self.assertEqual(outcome, "PUSHED")
        self.assertEqual(self.fx.json("docs/data.json"), view(2, 2),
                         "a line-level merge of two JSON renders, never rendered or validated by anyone")

    def test_http_408_after_acceptance_fails_the_job_although_published(self):
        root, _ = collector_cycle(self.fx, commit=False)
        outcome, _ = self.legacy_store(root)
        self.assertEqual(outcome, "PUSHED")
        # With a lost response the same push exits 128: bash -e marks the job failed, the
        # watchdogs after it are skipped, and nothing records that main already has the data.
        self.assertIn("2026-11-03,2", self.fx.json(THREE)["entries"])

    def test_blanket_data_lab_staging_publishes_files_the_collector_does_not_own(self):
        root, _ = collector_cycle(self.fx, commit=False)
        write(root, "data/lab/v4-runchecks.jsonl", "partial-not-json")   # left by a crashed helper
        write(root, "data/lab/ft-ledger.json", {"schema_version": 1, "matches": {}})
        outcome, _ = self.legacy_store(root)
        self.assertEqual(outcome, "PUSHED")
        self.assertEqual(self.fx.show("data/lab/v4-runchecks.jsonl"), "partial-not-json")
        self.assertEqual(self.fx.json("data/lab/ft-ledger.json")["matches"], {},
                         "a certified FT FINAL was erased by the collector")


# =============================================================================== part 2
class SafeCollectorPublication(Base):
    def assert_collector_bytes(self, ref=None):
        self.assertEqual(self.fx.json("data/state.json", ref)["last_id"], 150)
        self.assertEqual(self.fx.json(THREE, ref)["entries"]["2026-11-03,2"]["telegram_message_id"], 777)
        self.assertIn('"c:2"', self.fx.show(MARKETS, ref))
        self.assertIn('"c:2"', self.fx.show(REVISIONS, ref))

    def test_quiet_main_publishes_on_first_attempt(self):
        root, base = collector_cycle(self.fx)
        published = self.publish(root, base)
        self.assertEqual(self.fx.main(), published)
        self.assertEqual(self.receipt["status"], "PUBLISHED")
        self.assertEqual(self.receipt["path"], "FIRST_ATTEMPT")
        self.assertEqual(self.receipt["telegram_requests"], 0)
        self.assertEqual(self.receipt["provider_requeries"], 0)
        self.assertEqual(self.receipt["telegram_receipts_changed"][0]["telegram_message_id"], 777)
        self.assert_collector_bytes()

    def test_lab_v4_publication_during_collection_is_kept_byte_for_byte(self):
        root, base = collector_cycle(self.fx)
        lab = self.fx.plain_commit("lab", {
            "docs/lab/v4-audit.json": {"n": 2},
            "data/lab/v6-forecasts-2026-11.jsonl": jline(forecast="f1") + jline(forecast="f2"),
            "data/lab/v4-runchecks.jsonl": jline(run=1) + jline(run=2)}, "data(lab): refresh V4")
        published = self.publish(root, base)
        self.assertEqual(git(self.fx.remote, "rev-parse", published + "^"), lab)
        self.assertEqual(self.fx.json("docs/lab/v4-audit.json"), {"n": 2})
        self.assertEqual(self.fx.show("data/lab/v4-runchecks.jsonl").count("\n"), 2)
        self.assert_collector_bytes()

    def test_ft_publication_during_collection_is_kept(self):
        root, base = collector_cycle(self.fx)
        ft = {"schema_version": 1, "matches": {
            "2026-11-01,1,2": {"status": "FINAL", "result": {"home_goals": 1, "away_goals": 0}},
            "2026-11-02,3,4": {"status": "FINAL", "result": {"home_goals": 0, "away_goals": 0}}}}
        self.fx.plain_commit("ft", {"data/lab/ft-ledger.json": ft, "docs/lab/ft-results.json": {"final": 2},
                                    "data/lab/v6-ft-events-2026-11.jsonl": jline(ft="e1") + jline(ft="e2")},
                             "data(lab): publish verified FT snapshot")
        self.publish(root, base)
        self.assertEqual(self.fx.json("data/lab/ft-ledger.json"), ft)
        self.assert_collector_bytes()

    def test_h1_publication_during_collection_rerenders_dashboard_offline(self):
        root, base = collector_cycle(self.fx)
        results = ("match_key,status,home_goals,away_goals,source\n\"2026-11-01,1,2\",final,1,0,x\n"
                   "\"2026-11-02,3,4\",final,0,0,y\n")
        self.fx.plain_commit("h1", {"data/results.csv": results, "docs/data.json": view(1, 2),
                                    "data/result_audit.json": {"2026-11-01,1,2": {"status": "settled"},
                                                               "2026-11-02,3,4": {"status": "settled"}}},
                             "data: reconcile verified H1 finals [skip ci]")
        self.publish(root, base)
        self.assertTrue(self.receipt["rerendered"])
        self.assertEqual(self.fx.show("data/results.csv"), results)
        self.assertEqual(self.fx.json("docs/data.json"), view(2, 2))
        self.assert_collector_bytes()

    def test_second_collector_cycle_is_refused_with_telegram_diagnostics(self):
        root, base = collector_cycle(self.fx)
        before = self.fx.plain_commit("collector2", {
            "data/state.json": state(last_id=140, alerts=("c:1", "c:9"))}, c.MESSAGE)
        with self.assertRaises(sel.PublicationRefused):
            self.publish(root, base)
        self.assertEqual(self.fx.main(), before, "remote untouched")
        r = self.receipt
        self.assertEqual((r["status"], r["reason_kind"], r["failure_class"]),
                         ("REFUSED", "CONCURRENT_OWNER_WRITE", "PERSISTENT_INCOMPATIBILITY"))
        self.assertEqual(r["telegram_receipts_unpublished"][0]["telegram_message_id"], 777)
        self.assertTrue(r["resend_risk"].startswith("AT_LEAST_ONCE"))
        self.assertTrue(Path(r["bundle"]).exists(), "unpublished observations and receipts kept")
        self.assertEqual(git(root, "rev-parse", "HEAD^"), base)
        bundle_heads = git(root, "bundle", "list-heads", r["bundle"])
        self.assertIn(git(root, "rev-parse", "HEAD"), bundle_heads)

    def test_concurrent_ledger_or_block_change_is_refused(self):
        for path, content in ((THREE, ledger(**{"2026-11-01_1_2": SENT_OLD, "x_y": SENT_NEW})),
                              (TWO, ledger(rule="TWO_UP", **{"x_y": SENT_NEW})),
                              (BLOCK, {"schema_version": 1, "until": "2099-01-01T00:00:00+00:00"})):
            with self.subTest(path=path):
                fx = BareGitFixture()
                self.addCleanup(fx.cleanup)
                self.fx = fx
                root, base = collector_cycle(fx)
                fx.plain_commit("collector2", {path: content}, c.MESSAGE)
                with self.assertRaises(sel.PublicationRefused):
                    self.publish(root, base)
                self.assertEqual(self.receipt["reason_kind"], "CONCURRENT_OWNER_WRITE")

    def test_cannot_lock_ref_race_retries_and_preserves_the_other_writer(self):
        root, base = collector_cycle(self.fx)
        hook = PushHook({1: race(self.fx, "lab", {"docs/lab/v4-audit.json": {"n": 3}}, "LAB V4")})
        published = self.publish(root, base, hook)
        self.assertEqual(len(hook.calls), 2)
        self.assertEqual(self.receipt["path"], "AFTER_CAS")
        self.assertEqual(self.receipt["cas_retries"], 1)
        self.assertEqual(self.fx.main(), published)
        self.assertEqual(self.fx.json("docs/lab/v4-audit.json"), {"n": 3})
        self.assert_collector_bytes()

    def test_http_408_before_acceptance_is_retried_once(self):
        root, base = collector_cycle(self.fx)
        hook = PushHook({1: fail(HTTP_408)})
        published = self.publish(root, base, hook)
        self.assertEqual((len(hook.calls), self.receipt["path"]), (2, "AFTER_TRANSPORT"))
        self.assertEqual(self.fx.main(), published)

    def test_http_408_after_acceptance_is_confirmed_without_second_push(self):
        root, base = collector_cycle(self.fx)
        hook = PushHook({1: accept_then_fail(HTTP_408)})
        published = self.publish(root, base, hook)
        self.assertEqual(len(hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR")
        self.assertEqual(self.fx.main(), published)
        self.assertEqual(git(self.fx.remote, "log", "--format=%s", "main").count(c.MESSAGE), 1)

    def test_408_after_acceptance_then_other_writer_is_still_confirmed(self):
        root, base = collector_cycle(self.fx)

        def action(real, candidate):
            assert real().returncode == 0
            self.fx.plain_commit("lab", {"docs/lab/v4-audit.json": {"n": 9}}, "LAB V4")
            return subprocess.CompletedProcess(["git"], 128, b"", HTTP_408)
        hook = PushHook({1: action})
        published = self.publish(root, base, hook)
        self.assertEqual(len(hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR")
        self.assertEqual(git(self.fx.remote, "rev-parse", "main^"), published)

    def test_crash_after_push_before_receipt_rerun_is_idempotent(self):
        root, base = collector_cycle(self.fx)
        source = git(root, "rev-parse", "HEAD")
        git(root, "push", "-q", "origin", "HEAD:refs/heads/main")   # accepted, then the job died
        self.fx.plain_commit("lab", {"docs/lab/v4-audit.json": {"n": 4}}, "LAB V4")
        git(root, "reset", "-q", "--hard", source)
        hook = PushHook()
        self.publish(root, base, hook)
        self.assertEqual(hook.calls, [])
        self.assertEqual(self.receipt["status"], "ALREADY_PUBLISHED_EQUIVALENT")

    def test_persistent_contention_is_bounded_and_reported_as_transient(self):
        root, base = collector_cycle(self.fx)
        hook = PushHook({n: race(self.fx, "lab", {"docs/lab/v4-audit.json": {"n": 10 + n}}, "LAB")
                         for n in range(1, 10)})
        with self.assertRaises(sel.RetryExhausted):
            self.publish(root, base, hook, max_attempts=4)
        self.assertEqual(len(hook.calls), 4)
        self.assertEqual((self.receipt["status"], self.receipt["failure_class"]),
                         ("RETRY_EXHAUSTED", "TRANSIENT_CONTENTION"))
        self.assertEqual(self.receipt["push_failures"], ["CAS_REJECTED"] * 4)

    def test_auth_refusal_is_not_retried(self):
        root, base = collector_cycle(self.fx)
        hook = PushHook({1: fail(AUTH_403)})
        with self.assertRaises(sel.PushRefused):
            self.publish(root, base, hook)
        self.assertEqual(len(hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUSH_REFUSED")

    def test_unreadable_remote_after_408_is_unresolved_and_never_repushed(self):
        root, base = collector_cycle(self.fx)

        def action(real, candidate):
            self.fx.remote.rename(self.fx.home / "offline.git")
            return subprocess.CompletedProcess(["git"], 128, b"", HTTP_408)
        with self.assertRaises(sel.OutcomeUnresolved):
            self.publish(root, base, PushHook({1: action}))
        self.assertEqual(self.receipt["status"], "OUTCOME_UNRESOLVED")
        self.assertEqual(len(self.hook.calls), 1)

    def test_program_legacy_and_unknown_concurrent_paths_are_refused(self):
        for path, kind in (("h1lab/core.py", "INCOMPATIBLE_PROGRAM"),
                           ("data/pattern-notifications.json", "INTEGRITY"),
                           ("data/mystery.json", "UNKNOWN_PATH")):
            with self.subTest(path=path):
                fx = BareGitFixture()
                self.addCleanup(fx.cleanup)
                self.fx = fx
                root, base = collector_cycle(fx)
                fx.plain_commit("human", {path: {"changed": True}}, "change")
                with self.assertRaises(sel.PublicationRefused):
                    self.publish(root, base)
                self.assertEqual(self.receipt["reason_kind"], kind)

    def test_documentation_and_tests_commits_do_not_block_the_collector(self):
        root, base = collector_cycle(self.fx)
        self.fx.plain_commit("human", {"docs/audit/note.md": "x\n", "tests/test_x.py": "# t\n"}, "docs")
        self.publish(root, base)
        self.assert_collector_bytes()

    def own_change_refused(self, mutate):
        root, base = collector_cycle(self.fx, commit=False)
        mutate(root)
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
        with self.assertRaises(sel.PublicationRefused):
            self.publish(root, base)
        self.assertEqual(self.fx.main(), self.fx.base)

    def test_own_guards_refuse_contradictory_collector_outputs(self):
        cases = {
            "terminal receipt rewritten": lambda r: write(r, THREE, ledger(**{
                "2026-11-01_1_2": {**SENT_OLD, "telegram_message_id": 11}})),
            "receipt removed": lambda r: write(r, THREE, ledger()),
            "checkpoint went back": lambda r: write(r, "data/state.json", state(last_id=99, alerts=("c:1", "c:2"))),
            "observation removed": lambda r: write(r, "data/state.json", state(last_id=150, alerts=("c:2",))),
            "fixture identity rewritten": lambda r: write(r, "data/state.json",
                                                          state(last_id=150, alerts=("c:1", "c:2"), home="Z")),
            "revision journal rewritten": lambda r: write(r, REVISIONS, jline(event_id="c:2", sha256="b" * 64)),
            "latest view lost an event": lambda r: write(r, MARKETS, jline(event_id="c:2", observed_at="x")),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                fx = BareGitFixture()
                self.addCleanup(fx.cleanup)
                self.fx = fx
                self.own_change_refused(mutate)

    def test_active_block_is_never_shortened_or_dropped(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0)
        iso = lambda d: d.isoformat()
        active = {"schema_version": 1, "until": iso(now + timedelta(hours=2)), "http_status": 429,
                  "set_at": iso(now - timedelta(minutes=1)), "diagnosis": "FLOOD_WAIT_RETRY_AFTER"}
        files = dict(__import__("tests.git_writers", fromlist=["BASELINE"]).BASELINE)
        files[BLOCK] = active
        for name, mutate in (
                ("shortened", lambda r: write(r, BLOCK, {**active, "until": iso(now + timedelta(hours=1))})),
                ("dropped while active", lambda r: (r / BLOCK).unlink())):
            with self.subTest(name):
                self.fx = BareGitFixture(files)
                self.addCleanup(self.fx.cleanup)
                self.own_change_refused(mutate)
                self.assertEqual(self.receipt["reason_kind"], "INTEGRITY")

    def test_block_is_never_shortened_and_expired_block_removal_is_published(self):
        files = dict(__import__("tests.git_writers", fromlist=["BASELINE"]).BASELINE)
        files[BLOCK] = {"schema_version": 1, "until": "2026-11-02T06:00:00+00:00", "http_status": 429,
                        "set_at": "2026-11-02T05:55:00+00:00", "diagnosis": "FLOOD_WAIT_RETRY_AFTER"}
        self.fx = BareGitFixture(files)
        self.addCleanup(self.fx.cleanup)
        root, base = collector_cycle(self.fx, commit=False)
        (root / BLOCK).unlink()                      # expired pause cleared after a confirmed send
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
        self.publish(root, base)
        self.assertIsNone(self.fx.show(BLOCK))

    def test_latest_view_repartition_keeps_every_event(self):
        root, base = collector_cycle(self.fx, commit=False)
        rows = (root / MARKETS).read_text().splitlines(keepends=True)
        write(root, MARKETS, rows[0])
        write(root, "data/lab/markets-2026-11-part0001.jsonl", "".join(rows[1:]))
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
        self.publish(root, base)
        self.assertIn('"c:2"', self.fx.show("data/lab/markets-2026-11-part0001.jsonl"))

    def test_stage_selects_only_collector_owned_paths(self):
        root, _ = collector_cycle(self.fx, commit=False)
        write(root, "data/lab/v4-runchecks.jsonl", "partial")
        write(root, "data/lab/ft-ledger.json", {"schema_version": 1, "matches": {}})
        write(root, "data/pattern-notifications.json", {"schema_version": 1, "entries": {"x": {}}})
        write(root, "data/lab/markets-2026-11.jsonl.tmp", "x")
        staged, unexpected = c.stage(root)
        self.assertEqual(sorted(staged), sorted(["data/state.json", "docs/data.json", THREE,
                                                 MARKETS, FORMATS, REVISIONS]))
        self.assertEqual(sorted(unexpected), ["data/lab/ft-ledger.json", "data/lab/v4-runchecks.jsonl",
                                              "data/pattern-notifications.json"])
        cached = git(root, "diff", "--cached", "--name-only").split()
        self.assertNotIn("data/lab/ft-ledger.json", cached)

    def test_cli_failure_prints_operational_annotations(self):
        root, base = collector_cycle(self.fx)
        self.fx.plain_commit("collector2", {"data/state.json": state(last_id=140)}, c.MESSAGE)
        receipt = self.fx.home / "r.json"
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with patch.object(sel, "default_push", side_effect=AssertionError("must not push")), \
                redirect_stdout(out), self.assertRaises(sel.PublicationRefused):
            c.main(["publish", "--root", str(root), "--base", base, "--receipt", str(receipt)])
        text = out.getvalue()
        self.assertIn("::error title=COLLECT_PUBLICATION_FAILED::", text)
        self.assertIn("::error title=TELEGRAM_RECEIPTS_NOT_ON_MAIN::", text)
        self.assertIn("msg=777", text)
        self.assertIn("::error title=TELEGRAM_RESEND_RISK::AT_LEAST_ONCE", text)


class ResidualTelegramWindow(Base):
    """Honest residual risk: a crash between the Telegram send and publication (durable mode OFF)."""

    def test_crash_after_send_before_publication_leaves_no_receipt_on_main(self):
        collector_cycle(self.fx, commit=False)        # Telegram accepted msg 777; the runner died here
        entries = self.fx.json(THREE)["entries"]
        self.assertNotIn("2026-11-03,2", entries)
        from h1lab import telegram_delivery as td
        from datetime import datetime, timezone
        gate = td.gate({"entries": entries}, "2026-11-03,2",
                       datetime(2026, 11, 3, 19, tzinfo=timezone.utc),
                       datetime(2026, 11, 2, 7, 6, tzinfo=timezone.utc), {})
        self.assertEqual(gate, "send", "AT-LEAST-ONCE: the next cycle may resend; only "
                                       "TG_DURABLE_INTENT=1 (not enabled) narrows this window")


if __name__ == "__main__":
    unittest.main()
