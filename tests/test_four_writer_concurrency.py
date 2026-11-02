"""Deterministic four-writer concurrency simulation on one bare 'GitHub' main.

Writers use their REAL production publishers:
  collector -> scripts.collect_publish_safe (shared selective engine)
  LAB V4    -> scripts.lab_v4_publish_safe  (shared selective engine, real publication seal)
  FT        -> scripts.lab_ft_publish_safe  (#202)
  H1        -> scripts.h1_publish_safe      (#203)

Every writer prepares its cycle from the SAME base, then the writers publish in
every one of the 24 possible orders; each later publisher meets the commits of
the earlier ones. Faults are injected at fixed push numbers (CAS race by an
independent LLM commit, HTTP 408 before and after acceptance), never through
thread timing, so every run follows exactly the same path.
"""
import hashlib
import itertools
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab.lab_ft_final_guard import final_snapshot
from scripts import collect_publish_safe as col
from scripts import git_selective_publish as sel
from scripts import h1_publish_safe as h1
from scripts import lab_ft_publish_safe as ft
from scripts import lab_v4_publish_safe as lab
from scripts import publication_guard
from tests import git_writers as gw
from tests.git_writers import HTTP_408, BareGitFixture, git, jline, ledger, write

RESULTS_HEADER = "match_key,status,home_goals,away_goals,source\n"
RESULTS_BASE = gw.BASELINE["data/results.csv"]
RESULT_NEW = "\"2026-11-02,3,4\",final,0,0,bsd\n"
FT_BASE = gw.BASELINE["data/lab/ft-ledger.json"]
FT_NEW = {"schema_version": 1, "matches": {
    **FT_BASE["matches"],
    "2026-11-02,5,6": {"status": "FINAL", "result": {"home_goals": 3, "away_goals": 1}}}}


def files():
    out = dict(gw.BASELINE)
    for name in publication_guard.REQUIRED["audit"]:
        out[name] = {"generated": 0}
    out["docs/lab/telegram-eligibility.json"] = {"games": {}}
    out["data/lab/v6-archive-index.json"] = {"schema_version": 1, "sealed": []}
    return out


def render(root):
    st = json.loads((Path(root) / "data/state.json").read_text())
    rows = (Path(root) / "data/results.csv").read_text().count("\n") - 1
    write(root, "docs/data.json", gw.view(len(st["alerts"]), rows))


class Writers:
    """Prepare each writer's cycle from the same base; publish on demand."""

    def __init__(self, fx, home):
        self.fx, self.home = fx, home
        self.published = {}

    # -------------------------------------------------------------- collector
    def prepare_collector(self):
        root = self.fx.clone("collector")
        self.collector = (root, git(root, "rev-parse", "HEAD"))
        write(root, "data/state.json", gw.state(150, ("c:1", "c:2")))
        render(root)
        write(root, "data/three-total-moves-notifications.json",
              ledger(**{"2026-11-01_1_2": gw.SENT_OLD, "2026-11-03_2": gw.SENT_NEW}))
        for path in ("data/lab/markets-2026-11.jsonl", "data/lab/formats-2026-11.jsonl"):
            write(root, path, gw.BASELINE[path] + jline(event_id="c:2", observed_at="2026-11-02T07:00:00+00:00"))
        write(root, "data/lab/v4-revisions-2026-11.jsonl",
              gw.BASELINE["data/lab/v4-revisions-2026-11.jsonl"] + jline(event_id="c:2", sha256="b" * 64))
        col.stage(root)
        git(root, "commit", "-qm", col.MESSAGE)

    def publish_collector(self, push):
        root, base = self.collector
        return sel.publish(root, base=base, policy=col.CollectorPolicy(render=render), push=push,
                           receipt=self.home / "collector.json", sleep=lambda s: None)

    # -------------------------------------------------------------- LAB V4
    def prepare_lab(self):
        root = self.fx.clone("lab")
        base = git(root, "rev-parse", "HEAD")
        write(root, "docs/lab/v4-audit.json", {"generated": 1, "source_commit": base})
        write(root, "data/lab/v4-runchecks.jsonl", gw.BASELINE["data/lab/v4-runchecks.jsonl"] + jline(run=2))
        write(root, "data/lab/v6-forecasts-2026-11.jsonl",
              gw.BASELINE["data/lab/v6-forecasts-2026-11.jsonl"] + jline(forecast="f2"))
        git(root, "add", "docs/lab", "data/lab/v4-runchecks.jsonl", "data/lab/v6-forecasts-2026-11.jsonl")
        manifest = self.home / "lab-seal.json"
        with lab.inside(root):
            publication_guard.seal("audit", str(manifest))
        git(root, "commit", "-qm", lab.MESSAGE)
        self.lab = (root, base, manifest)

    def publish_lab(self, push):
        root, base, manifest = self.lab
        return sel.publish(root, base=base, policy=lab.LabV4Policy(manifest), push=push,
                           receipt=self.home / "lab.json", sleep=lambda s: None)

    # -------------------------------------------------------------- FT (#202)
    def prepare_ft(self):
        root = self.fx.clone("ft")
        base = git(root, "rev-parse", "HEAD")
        baseline = self.home / "ft-baseline.json"
        baseline.write_text(json.dumps(final_snapshot((root / "data/lab/ft-ledger.json").read_bytes())))
        write(root, "data/lab/ft-ledger.json", FT_NEW)
        write(root, "docs/lab/ft-results.json", {"final": 2})
        write(root, "data/lab/v6-ft-events-2026-11.jsonl",
              gw.BASELINE["data/lab/v6-ft-events-2026-11.jsonl"] + jline(ft="e2"))
        git(root, "add", "-A")
        git(root, "commit", "-qm", "data(lab): publish verified FT snapshot [skip ci]")
        hashes = {n: hashlib.sha256((root / n).read_bytes()).hexdigest()
                  for n in ("data/lab/ft-ledger.json", "docs/lab/ft-results.json",
                            "data/lab/v6-ft-events-2026-11.jsonl")}
        manifest = self.home / "ft-seal.json"
        manifest.write_text(json.dumps({"pipeline": "ft", "segmented": {"backend": "segmented"},
                                        "sha256": hashes}))
        self.ft = (root, base, manifest, baseline, hashes)

    def publish_ft(self, push):
        root, base, manifest, baseline, hashes = self.ft

        def sealed(_):
            for name, digest in hashes.items():
                assert hashlib.sha256(ft.git(root, "show", "HEAD:" + name)).hexdigest() == digest
        with patch.object(ft.publication_guard, "verify", side_effect=sealed), \
                patch.object(ft, "discovery_verify", return_value=None), \
                patch.object(ft, "run", side_effect=_hooked(ft.run, push, root)):
            return ft.publish(root, base=base, manifest=manifest, baseline=baseline,
                              max_attempts=6, sleep=lambda s: None)

    # -------------------------------------------------------------- H1 (#203)
    def prepare_h1(self):
        root = self.fx.clone("h1")
        base = git(root, "rev-parse", "HEAD")
        write(root, "data/results.csv", RESULTS_BASE + RESULT_NEW)
        write(root, "data/result_audit.json", {"2026-11-01,1,2": {"status": "settled"},
                                               "2026-11-02,3,4": {"status": "settled",
                                                                  "checked_at": "2026-11-02T07:00:00+00:00"}})
        write(root, "data/health/h1-results.json", {"status": "CYCLE_COMPLETED", "n": 2})
        render(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", h1.MESSAGE)
        self.h1 = (root, base)

    def publish_h1(self, push):
        root, base = self.h1
        with patch.object(h1, "run", side_effect=_hooked(h1.run, push, root)):
            return h1.publish(root, base=base, receipt=self.home / "h1.json",
                              render=render, sleep=lambda s: None)


def _hooked(real_run, push, root):
    """Route the legacy publishers' `git push` through the same deterministic PushHook."""
    def run(r, *args, **kwargs):
        if args and args[0] == "push":
            ref = args[-1]
            candidate = git(root, "rev-parse", ref.split(":")[0])
            return push(root, candidate)
        return real_run(r, *args, **kwargs)
    return run


def independent_llm(fx, n):
    def action(real, candidate):
        before = fx.main()
        fx.plain_commit("llm", {"docs/lab/llm-investigator-index.json": {"runs": n}}, "LLM run %d" % n)
        return subprocess.CompletedProcess(["git"], 1, b"", gw.cas(fx.main(), before))
    return action


class FourWriterConcurrency(unittest.TestCase):
    def setUp(self):
        for p in (patch("h1lab.bot.send_message", side_effect=AssertionError("Telegram called")),
                  patch("urllib.request.urlopen", side_effect=AssertionError("provider called"))):
            p.start()
            self.addCleanup(p.stop)

    def run_schedule(self, order, faults=True):
        fx = BareGitFixture(files())
        self.addCleanup(fx.cleanup)
        home = fx.home
        w = Writers(fx, home)
        for name in ("collector", "lab", "ft", "h1"):        # all prepared from the SAME base
            getattr(w, "prepare_" + name)()
        llm_runs = [0]
        results = {}
        for position, name in enumerate(order):
            script = {}
            if faults and position == 1:
                llm_runs[0] += 1
                script = {1: independent_llm(fx, llm_runs[0])}
            elif faults and position == 2:
                script = {1: gw.fail(HTTP_408)}
            elif faults and position == 3:
                def after(real, candidate):
                    assert real().returncode == 0
                    fx.plain_commit("llm", {"docs/lab/llm-investigator-index.json": {"runs": 99}}, "LLM late")
                    return subprocess.CompletedProcess(["git"], 128, b"", HTTP_408)
                script = {1: after}
            hook = gw.PushHook(script)
            results[name] = getattr(w, "publish_" + name)(hook)
            results[name + "_pushes"] = len(hook.calls)
        return fx, results

    def check_invariants(self, fx, results, order):
        history = git(fx.remote, "rev-list", "main").split()
        for name in ("collector", "lab", "ft", "h1"):
            self.assertIn(results[name], history, "%s publication lost (%s)" % (name, order))
        log = git(fx.remote, "log", "--format=%s", "main")
        for message in (col.MESSAGE, lab.MESSAGE, h1.MESSAGE, "data(lab): publish verified FT snapshot"):
            self.assertEqual(log.count(message), 1, "%s published %d times" % (message, log.count(message)))
        # Collector: observation, receipts (old terminal + new), V4 views/journal.
        st = fx.json("data/state.json")
        self.assertEqual((st["last_id"], [a["event_id"] for a in st["alerts"]]), (150, ["c:1", "c:2"]))
        receipts = fx.json("data/three-total-moves-notifications.json")["entries"]
        self.assertEqual(receipts["2026-11-01,1,2"], gw.SENT_OLD)
        self.assertEqual(receipts["2026-11-03,2"]["telegram_message_id"], 777)
        # Certified finals: H1 row added, base row intact; FT FINALs intact + new one.
        self.assertEqual(fx.show("data/results.csv"), RESULTS_BASE + RESULT_NEW)
        self.assertEqual(fx.json("data/lab/ft-ledger.json"), FT_NEW)
        self.assertEqual(fx.json("data/result_audit.json")["2026-11-01,1,2"]["status"], "settled")
        # Journals: base bytes are a prefix, every line JSON, no duplicates.
        for path, base_key in (("data/lab/v4-revisions-2026-11.jsonl", None),
                               ("data/lab/v4-runchecks.jsonl", None),
                               ("data/lab/v6-forecasts-2026-11.jsonl", None),
                               ("data/lab/v6-ft-events-2026-11.jsonl", None),
                               ("data/lab/markets-2026-11.jsonl", None)):
            text = fx.show(path)
            self.assertTrue(text.startswith(gw.BASELINE[path]), path)
            lines = text.splitlines()
            self.assertEqual(len(lines), len(set(lines)), "duplicate journal entry in " + path)
            self.assertEqual(len(lines), 2, path)
            [json.loads(line) for line in lines]
        # LAB artifacts and their seal survive every later publisher.
        self.assertEqual(fx.json("docs/lab/v4-audit.json")["generated"], 1)
        self.assertEqual(fx.json("docs/lab/ft-results.json"), {"final": 2})
        # The derived dashboard is consistent with the final inputs (re-rendered offline).
        self.assertEqual(fx.json("docs/data.json"), gw.view(2, 2), order)

    def test_all_24_publication_orders_with_cas_and_408_faults(self):
        for order in itertools.permutations(("collector", "lab", "ft", "h1")):
            with self.subTest(order=order):
                fx, results = self.run_schedule(order)
                self.check_invariants(fx, results, order)
                # transient faults are recovered within the bound; 408-after is never re-pushed
                self.assertEqual(results[order[3] + "_pushes"], 1)
                self.assertEqual(results[order[1] + "_pushes"], 2)
                self.assertEqual(results[order[2] + "_pushes"], 2)

    def test_persistent_contention_exhausts_safely_for_every_engine_writer(self):
        fx = BareGitFixture(files())
        self.addCleanup(fx.cleanup)
        w = Writers(fx, fx.home)
        w.prepare_collector()
        w.prepare_lab()
        for name, exc in (("collector", sel.RetryExhausted), ("lab", sel.RetryExhausted)):
            with self.subTest(name):
                before = fx.main()
                hook = gw.PushHook({n: independent_llm(fx, 100 + n) for n in range(1, 11)})
                with self.assertRaises(exc):
                    getattr(w, "publish_" + name)(hook)
                self.assertEqual(len(hook.calls), 6, "bounded, not increased")
                receipt = json.loads((fx.home / (name + ".json")).read_text())
                self.assertEqual(receipt["failure_class"], "TRANSIENT_CONTENTION")
                self.assertNotIn(results_message(name), git(fx.remote, "log", "--format=%s", "main"))
                self.assertNotEqual(fx.main(), before, "independent commits were all kept")
        # Once contention clears, the same unpublished commits publish without new work.
        w.publish_collector(gw.PushHook())
        w.publish_lab(gw.PushHook())
        self.assertIn(col.MESSAGE, git(fx.remote, "log", "--format=%s", "main"))
        self.assertIn(lab.MESSAGE, git(fx.remote, "log", "--format=%s", "main"))

    def test_persistent_incompatibility_refuses_explicitly(self):
        fx = BareGitFixture(files())
        self.addCleanup(fx.cleanup)
        w = Writers(fx, fx.home)
        w.prepare_collector()
        w.prepare_lab()
        # A second collector cycle (concurrency group bypassed) and a contradictory FT FINAL.
        fx.plain_commit("collector2", {"data/state.json": gw.state(140, ("c:1", "c:9"))}, col.MESSAGE)
        fx.plain_commit("ft2", {"data/lab/ft-ledger.json": {"schema_version": 1, "matches": {
            "2026-11-01,1,2": {"status": "FINAL", "result": {"home_goals": 0, "away_goals": 0}}}}}, "FT")
        head = fx.main()
        for name, kind in (("collector", "CONCURRENT_OWNER_WRITE"), ("lab", "DEPENDENCY_CHANGED")):
            with self.subTest(name):
                with self.assertRaises(sel.PublicationRefused):
                    getattr(w, "publish_" + name)(gw.PushHook())
                receipt = json.loads((fx.home / (name + ".json")).read_text())
                self.assertEqual((receipt["reason_kind"], receipt["failure_class"]),
                                 (kind, "PERSISTENT_INCOMPATIBILITY"))
        self.assertEqual(fx.main(), head, "nothing partial published")


class KnownCrossProducerRefusals(unittest.TestCase):
    """Documented (not changed here): the merged FT publisher refuses safely in two LAB/collector cases."""

    def setUp(self):
        self.fx = BareGitFixture(files())
        self.addCleanup(self.fx.cleanup)
        self.w = Writers(self.fx, self.fx.home)
        self.w.prepare_ft()

    def assert_ft_refused(self, changes, text):
        head = self.fx.plain_commit("other", changes, "concurrent")
        with self.assertRaises(ft.UnsafeFTPublication) as ctx:
            self.w.publish_ft(gw.PushHook())
        self.assertIn(text, str(ctx.exception))
        self.assertEqual(self.fx.main(), head)

    def test_new_v6_archive_generation_blocks_that_ft_cycle(self):
        self.assert_ft_refused({"data/lab/v6-archive-index.json": {"schema_version": 1, "sealed": [
            {"path": "x"}]}}, "V4 source archive index changed")

    def test_repartitioned_market_view_is_unknown_to_ft(self):
        self.assert_ft_refused({"data/lab/markets-2026-11-part0001.jsonl": jline(event_id="c:3")},
                               "Unknown concurrent path")


def results_message(name):
    return {"collector": col.MESSAGE, "lab": lab.MESSAGE}[name]


if __name__ == "__main__":
    unittest.main()
