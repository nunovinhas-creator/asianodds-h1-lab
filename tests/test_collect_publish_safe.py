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
                               accept_then_fail, fail, git, jline, ledger, observe, race, state,
                               v4_journal_paths, write)
from tests.git_writers import render as production_render

THREE = "data/e5-over25-notifications.json"          # the active (E5) collector receipt ledger
TWO = "data/two-up-total-notifications.json"         # retired: frozen legacy proof
BLOCK = "data/telegram-delivery-block.json"
MARKETS = "data/lab/markets-2026-11.jsonl"
FORMATS = "data/lab/formats-2026-11.jsonl"


def revisions_path(root):
    """The V4 journal month follows the processing clock (known_at), as in production."""
    names = sorted(p.name for p in (Path(root) / "data/lab").glob("v4-revisions-*.jsonl"))
    return "data/lab/" + names[-1]


def pad(alerts, results):
    """Hand-made dashboard used ONLY by the legacy line-merge demonstration."""
    return {"alerts": alerts, "generated_at": "fixed", "h1": {"roi": 0}, "lab": [], "results": results}


def no_network():
    return [patch("h1lab.bot.send_message", side_effect=AssertionError("Telegram called")),
            patch("urllib.request.urlopen", side_effect=AssertionError("provider called"))]


def collector_cycle(fx, name="collector", *, new_alert="c:2", last_id=150, receipt=SENT_NEW,
                    commit=True):
    """One collector job after Telegram: new observation, V4 rows, a SENT receipt, rendered view."""
    root = fx.clone(name)
    base = git(root, "rev-parse", "HEAD")
    write(root, "data/state.json", state(last_id=last_id, alerts=("c:1", new_alert)))
    entries = {"2026-11-01_1_2": SENT_OLD}
    if receipt:
        entries["2026-11-03_" + new_alert.split(":")[1]] = receipt
    write(root, THREE, ledger(**entries))
    observe(root, int(new_alert.split(":")[1]), observed="2026-11-02T07:00:00+00:00")
    render(root)
    if commit:
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
    return root, base


def render(root):
    production_render(root)


def coherent(fx, ref="main"):
    return c.dashboard_is_coherent(fx.remote, ref)


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
        self.fx.plain_commit("seed2", {"docs/data.json": pad(1, 1)}, "hand-made dashboard")
        root, _ = collector_cycle(self.fx, commit=False)
        write(root, "docs/data.json", pad(2, 1))
        # H1 re-renders another field of the same dashboard file concurrently.
        self.fx.plain_commit("h1", {"docs/data.json": pad(1, 2),
                                    "data/results.csv": "match_key,status,home_goals,away_goals,source\n"
                                    "\"2026-11-01,1,2\",final,1,0,x\n\"2026-11-02,3,4\",final,0,0,y\n"},
                             "data: reconcile verified H1 finals [skip ci]")
        outcome, _ = self.legacy_store(root)
        self.assertEqual(outcome, "PUSHED")
        self.assertEqual(self.fx.json("docs/data.json"), pad(2, 2),
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
        self.assertTrue(any('"c:2"' in self.fx.show(p, ref) for p in v4_journal_paths(self.fx)))
        self.assertTrue(coherent(self.fx, ref or "main"), "docs/data.json is the render of main")

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
        self.fx.plain_commit("h1", {"data/results.csv": results}, "data: reconcile verified H1 finals [skip ci]",
                             action=render)
        self.fx.plain_commit("h1b", {
                                    "data/result_audit.json": {"2026-11-01,1,2": {"status": "settled"},
                                                               "2026-11-02,3,4": {"status": "settled"}}},
                             "data: reconcile verified H1 finals [skip ci]")
        self.publish(root, base)
        self.assertTrue(self.receipt["rerendered"])
        self.assertEqual(self.fx.show("data/results.csv"), results)
        self.assertTrue(coherent(self.fx))
        self.assertEqual(self.fx.json("docs/data.json")["alert_count"], 2)
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
        for path, content, kind in (
                (THREE, ledger(**{"2026-11-01_1_2": SENT_OLD, "x_y": SENT_NEW}), "CONCURRENT_OWNER_WRITE"),
                # A retired (frozen) ledger can never change: refused as an integrity breach.
                (TWO, ledger(rule="TWO_UP", **{"x_y": SENT_NEW}), "INTEGRITY"),
                (BLOCK, {"schema_version": 1, "until": "2099-01-01T00:00:00+00:00"},
                 "CONCURRENT_OWNER_WRITE")):
            with self.subTest(path=path):
                fx = BareGitFixture()
                self.addCleanup(fx.cleanup)
                self.fx = fx
                root, base = collector_cycle(fx)
                fx.plain_commit("collector2", {path: content}, c.MESSAGE)
                with self.assertRaises(sel.PublicationRefused):
                    self.publish(root, base)
                self.assertEqual(self.receipt["reason_kind"], kind)

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
            "revision journal rewritten": lambda r: write(r, revisions_path(r),
                                                          (r / revisions_path(r)).read_text().splitlines(True)[-1]),
            "latest view lost an event": lambda r: write(r, MARKETS,
                                                         (r / MARKETS).read_text().splitlines(True)[-1]),
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
                                                 MARKETS, FORMATS, revisions_path(root)]))
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


SIGNAL = {"signal_id": "c:1", "match_key": "2026-11-03,1", "home": "A", "away": "B1", "competition": "X",
          "observed_at": "2026-11-02T06:00:00+00:00", "kickoff_utc": "2026-11-03T19:00:00+00:00",
          "line": 2.5, "under_odds": 1.9, "source_url": "https://example.invalid/1"}


class HistoricalObservationImmutability(Base):
    """Phase 1: an already published observation can only change through an audited V4 revision."""

    def setUp(self):
        super().setUp()
        files = dict(__import__("tests.git_writers", fromlist=["BASELINE"]).BASELINE)
        base_state = state()
        base_state["signals"] = [SIGNAL]
        files["data/state.json"] = base_state
        self.fx = BareGitFixture(files)
        self.addCleanup(self.fx.cleanup)

    def cycle(self, mutate=None):
        """A normal collector cycle (new alert c:2) plus an optional mutation of history."""
        root, base = collector_cycle(self.fx, commit=False)
        st = json.loads((root / "data/state.json").read_text())
        st["signals"] = [dict(SIGNAL)]
        write(root, "data/state.json", st)
        if mutate:
            mutate(root)
        render(root)
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
        return root, base

    def refused(self, mutate, text):
        root, base = self.cycle(mutate)
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish(root, base)
        self.assertEqual(self.fx.main(), self.fx.base, "history untouched on main")
        self.assertEqual(self.receipt["status"], "REFUSED")
        self.assertEqual(self.receipt["failure_class"], "PERSISTENT_INCOMPATIBILITY")
        self.assertRegex(str(ctx.exception), text)
        self.assertEqual(self.hook.calls, [], "refused before any push")

    @staticmethod
    def edit_market_row(root, **fields):
        rows = [json.loads(line) for line in (root / MARKETS).read_text().splitlines()]
        for row in rows:
            if row["event_id"] == "c:1":
                for path, value in fields.items():
                    target = row
                    keys = path.split(".")
                    for key in keys[:-1]:
                        target = target[key]
                    target[keys[-1]] = value
        write(root, MARKETS, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                     for r in rows))

    # 1. odds rewritten in place, same event_id
    def test_1_odds_changed_in_place_is_refused(self):
        self.refused(lambda r: self.edit_market_row(r, **{"markets.total.after.under_price": 1.70}),
                     "projection|without an audited revision")

    # 2. Total line rewritten in place, same event_id
    def test_2_total_line_changed_in_place_is_refused(self):
        self.refused(lambda r: self.edit_market_row(r, **{"markets.total.after.line": 3.5,
                                                          "trigger.after": 3.5}),
                     "projection|without an audited revision")

    # 3. original timestamp rewritten (alert, V4 view, and via a journalled 'revision')
    def test_3_original_timestamp_rewrite_is_refused(self):
        def alert(r):
            st = json.loads((r / "data/state.json").read_text())
            st["alerts"][0]["kickoff_utc"] = st["alerts"][0]["kickoff_utc"]
            st["alerts"][0]["observed_at"] = "2026-11-01T00:00:00+00:00"
            write(r, "data/state.json", st)
        self.refused(alert, "Published alerts rewritten in place: c:1")
        self.fx = BareGitFixture(self.fx_files())
        self.addCleanup(self.fx.cleanup)
        self.refused(lambda r: self.edit_market_row(r, observed_at="2026-11-01T00:00:00+00:00"),
                     "projection|Original Telegram time")
        self.fx = BareGitFixture(self.fx_files())
        self.addCleanup(self.fx.cleanup)
        # Even through the production store (which journals it), the original time is immutable.
        self.refused(lambda r: observe(r, 1, observed="2026-11-02T05:00:00+00:00"),
                     "Original Telegram time rewritten")

    def fx_files(self):
        files = dict(__import__("tests.git_writers", fromlist=["BASELINE"]).BASELINE)
        base_state = state()
        base_state["signals"] = [SIGNAL]
        files["data/state.json"] = base_state
        return files

    # 4. a published signal changed, same signal_id
    def test_4_signal_fields_changed_is_refused(self):
        def mutate(r):
            st = json.loads((r / "data/state.json").read_text())
            st["signals"][0]["under_odds"] = 2.4
            write(r, "data/state.json", st)
        self.refused(mutate, "Published signals rewritten in place: c:1 fields \\['under_odds'\\]")

    # 5. an old observation replaced wholesale while every identifier is kept
    def test_5_whole_observation_replaced_keeping_ids_is_refused(self):
        def mutate(r):
            st = json.loads((r / "data/state.json").read_text())
            old = st["alerts"][0]
            st["alerts"][0] = {"event_id": old["event_id"], "match_key": old["match_key"],
                               "home": old["home"], "away": old["away"],
                               "kickoff_utc": old["kickoff_utc"], "competition": "Replaced"}
            write(r, "data/state.json", st)
        self.refused(mutate, "Published alerts rewritten in place")

    # 6. legitimate updates: a Telegram edit and an unproven content change, both journalled
    def test_6_audited_v4_revisions_are_published_with_provenance(self):
        for kind, kw in (("EDIT_DATE_CHANGED", {"edit_at": "2026-11-02T06:30:00+00:00", "line_after": 3.5}),
                         ("CONTENT_CHANGED_EDIT_UNPROVEN", {"under": 1.80})):
            with self.subTest(kind):
                self.fx = BareGitFixture(self.fx_files())
                self.addCleanup(self.fx.cleanup)
                root, base = self.cycle(lambda r: observe(r, 1, **kw))
                self.publish(root, base)
                self.assertEqual(self.receipt["status"], "PUBLISHED")
                self.assertEqual(self.receipt["v4_revision_kinds"].get(kind), 1)
                self.assertIn("c:1", self.receipt["v4_revised_events"])
                from h1lab import v4_revisions as rev
                events = [json.loads(line) for p in v4_journal_paths(self.fx)
                          for line in self.fx.show(p).splitlines()]
                chain = [e for e in events if e["event_id"] == "c:1"]
                first, last = chain[0], chain[-1]
                self.assertEqual(last["kind"], kind)
                self.assertEqual(last["previous_event_revision_id"], first["revision_id"],
                                 "linked to the previous content")
                self.assertEqual(first["snapshot"]["markets"]["total"]["after"]["under_price"], 1.88,
                                 "the original content is preserved in the journal")
                self.assertEqual(last["telegram_original_at"], first["telegram_original_at"])
                self.assertTrue(last["known_at"] and last["snapshot"]["parser_source_sha256"])
                self.assertEqual(rev.fingerprint(json.loads(
                    [line for line in self.fx.show(MARKETS).splitlines() if '"c:1"' in line][0])),
                    last["snapshot_sha256"], "the latest view is exactly the latest revision")

    # 7. a revision that references an event absent from the views
    def test_7_revision_for_unknown_event_is_refused(self):
        from datetime import datetime, timezone
        from h1lab import v4_revisions as rev
        self.refused(lambda r: rev.append(r, {}, [__import__("tests.git_writers", fromlist=["v4_row"])
                                                 .v4_row(99)],
                                          now=datetime.now(timezone.utc)),
                     "not fully indexed|projection")

    # 8. a revision with a broken hash or a broken chain link
    def test_8_revision_with_bad_hash_or_chain_is_refused(self):
        def tamper(field, value):
            def mutate(r):
                observe(r, 1, under=1.80)              # a genuine revision first
                path = r / revisions_path(r)
                lines = path.read_text().splitlines(True)
                event = json.loads(lines[-1])
                event[field] = value
                lines[-1] = json.dumps(event, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n"
                path.write_text("".join(lines))
            return mutate
        for field, value in (("sha256", "0" * 64), ("previous_sha256", "1" * 64),
                             ("previous_event_revision_id", None)):
            with self.subTest(field):
                self.fx = BareGitFixture(self.fx_files())
                self.addCleanup(self.fx.cleanup)
                self.refused(tamper(field, value), "chain altered|invalid")

    def test_format_signature_changes_only_with_a_v4_revision(self):
        def mutate(r):
            from h1lab import shadow_formats
            from datetime import datetime
            shadow_formats.store(r, [shadow_formats.inspect(
                "Totally different 1 2 3", datetime.fromisoformat("2026-11-02T06:00:00+00:00"), 1, "c", True)])
        self.refused(mutate, "Format observation rewritten without a V4 revision: c:1")


class PublicationReview(Base):
    """Phase 2: publication-path properties not covered elsewhere."""

    def test_foreign_files_staged_earlier_are_removed_from_the_commit(self):
        root, base = collector_cycle(self.fx, commit=False)
        write(root, "data/lab/ft-ledger.json", {"schema_version": 1, "matches": {}})
        git(root, "add", "data/lab/ft-ledger.json")              # staged by an earlier step
        patch_file = self.fx.home / "parked.patch"
        c.stage(root, park=patch_file)
        git(root, "commit", "-qm", c.MESSAGE)
        self.assertIn("ft-ledger.json", patch_file.read_text(), "kept for review, not lost")
        self.assertEqual(git(root, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertNotIn("data/lab/ft-ledger.json",
                         git(root, "diff", "--name-only", base, "HEAD").split())
        self.publish(root, base)
        self.assertEqual(self.fx.json("data/lab/ft-ledger.json")["matches"]["2026-11-01,1,2"]["status"],
                         "FINAL")

    def test_engine_refuses_a_commit_containing_foreign_paths(self):
        root, base = collector_cycle(self.fx, commit=False)
        c.stage(root)
        write(root, "docs/lab/v4-audit.json", {"forged": True})
        git(root, "add", "docs/lab/v4-audit.json")
        git(root, "commit", "-qm", c.MESSAGE)
        with self.assertRaises(sel.PublicationRefused):
            self.publish(root, base)
        self.assertEqual(self.receipt["reason_kind"], "NOT_OWNER")

    def test_active_auth_blocks_are_preserved(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0)
        for status in (401, 403):
            with self.subTest(status):
                block = {"schema_version": 1, "until": (now + timedelta(hours=20)).isoformat(),
                         "http_status": status, "set_at": (now - timedelta(hours=4)).isoformat(),
                         "diagnosis": "AUTH_REJECTED_CHECK_TG_BOT_TOKEN_AND_TG_CHAT_ID"}
                files = dict(__import__("tests.git_writers", fromlist=["BASELINE"]).BASELINE)
                files[BLOCK] = block
                self.fx = BareGitFixture(files)
                self.addCleanup(self.fx.cleanup)
                root, base = collector_cycle(self.fx, commit=False)
                (root / BLOCK).unlink()       # TG_IGNORE_AUTH_BLOCK never deletes; a bug would
                c.stage(root)
                git(root, "commit", "-qm", c.MESSAGE)
                with self.assertRaises(sel.PublicationRefused):
                    self.publish(root, base)
                self.assertEqual(self.fx.json(BLOCK)["http_status"], status)

    def test_incoherent_dashboard_is_refused(self):
        root, base = collector_cycle(self.fx, commit=False)
        view = json.loads((root / "docs/data.json").read_text())
        view["alert_count"] = 99
        write(root, "docs/data.json", view)
        c.stage(root)
        git(root, "commit", "-qm", c.MESSAGE)
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish(root, base)
        self.assertIn("docs/data.json is not the render", str(ctx.exception))

    def test_equivalent_path_does_not_hide_a_divergent_derived_view(self):
        root, base = collector_cycle(self.fx)
        source = git(root, "rev-parse", "HEAD")
        git(root, "push", "-q", "origin", "HEAD:refs/heads/main")      # accepted, job died
        stale = self.fx.show("docs/data.json", base)
        self.fx.plain_commit("buggy", {"docs/data.json": stale}, "stale dashboard")
        self.assertFalse(coherent(self.fx))
        git(root, "reset", "-q", "--hard", source)
        hook = PushHook()
        self.publish(root, base, hook)
        self.assertEqual(self.receipt["status"], "PUBLISHED", "not silently 'equivalent'")
        self.assertEqual(len(hook.calls), 1)
        self.assertTrue(coherent(self.fx))
        log = git(self.fx.remote, "log", "--format=%s", "main")
        self.assertEqual(log.count(c.MESSAGE), 2, "the original commit + one dashboard repair")
        self.assertEqual(git(self.fx.remote, "diff", "--name-only", "main^", "main"), "docs/data.json")
        self.assertEqual(self.fx.json("data/state.json")["last_id"], 150)

    def test_equivalent_path_with_coherent_view_pushes_nothing(self):
        root, base = collector_cycle(self.fx)
        source = git(root, "rev-parse", "HEAD")
        git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(root, "reset", "-q", "--hard", source)
        hook = PushHook()
        self.publish(root, base, hook)
        self.assertEqual((self.receipt["status"], hook.calls), ("ALREADY_PUBLISHED_EQUIVALENT", []))


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
