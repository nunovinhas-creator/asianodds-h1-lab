"""Concurrency tests of the V6 offline statistics publisher (local bare Git, no network).

Reproduces the two production failures of ``v6-offline-statistics.yml``:

* run 41420785839 (2026-11-02 09:27): LAB V4 published e75323e4 (v6-falsification,
  v6-p0-gates, v6-readiness, v4-audit, ...) between the V6 checkout of e90ec069 and
  its ``git push origin HEAD:main`` -> ``[rejected] HEAD -> main (fetch first)``;
* run 41540018891 (2026-11-02 22:46): the collector (2809ad5e docs/data.json), LAB V4
  (db891b1d) and FT (2c1b7851 ft-ledger, FT/discovery events, segmented state) all
  published after the V6 checkout of e59023de -> same rejection.

Both race windows changed V6 INPUTS, so transporting the old report would have been
wrong too: the publisher must recompute on the exact remote inputs.
"""
import hashlib
import json
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import git_selective_publish as sel
from scripts import lab_v6_offline_publish_safe as v6
from tests.git_writers import BASELINE, HTTP_408, BareGitFixture, git, jline, write

RUN = "41540018891"
NOW = datetime(2026, 11, 2, 22, 46, 30, tzinfo=timezone.utc)
SEG = "1867587f5cfd68868600015c35f1009373edd17346d5617c6d937c8a348ce6d6"

V6_FILES = {
    **BASELINE,
    "docs/lab/v6-falsification.json": {"v": 1},
    "docs/lab/v6-p0-gates.json": {"v": 1},
    "docs/lab/v6-readiness.json": {"v": 1},
    "docs/lab/v6-weekly-drift.json": {"v": 1},
    "docs/lab/pattern-research.json": {"v": 1},
    "docs/lab/golden-report.json": {"v": 1},
    "docs/lab/llm-investigator-runs/41537499107.json": {"recorded_at_utc": "2026-11-02T20:00:00+00:00",
                                                        "proposals": []},
    "data/lab/discovery-events-2026-11.jsonl": jline(event="d1"),
    "docs/lab/llm-statistics.json": {"status": "old"},
}


def fake_build(root, now):
    """Deterministic stand-in for ``build``: hashes the inputs from the working tree exactly
    the way ``build`` does (independent of the publisher's blob-based implementation)."""
    root = Path(root)
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((root / "data/lab").glob("*.json*")) if not p.is_symlink()}
    hashes["data/state.json"] = hashlib.sha256((root / "data/state.json").read_bytes()).hexdigest()
    names = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                   if p.is_file() and ".git" not in p.parts
                   and v6.is_input(str(p.relative_to(root))))
    digest = hashlib.sha256()
    for n in names:
        digest.update(n.encode() + b"\0" + (root / n).read_bytes())
    return {"schema_version": 1, "status": v6.EXPECTED_STATUS, "generated_at": now.isoformat(),
            "source_sha256": hashes, "inputs_digest": digest.hexdigest(), "hypotheses":
            [{"candidate_id": "x", "scientifically_proven": False}], "llm_calls": 0, "validated": 0}


def remote_inputs_digest(fx, ref="refs/heads/main"):
    tmp = fx.clone("inspect")
    git(tmp, "fetch", "-q", "origin", "main")
    git(tmp, "reset", "-q", "--hard", ref if ref != "refs/heads/main" else "origin/main")
    return fake_build(tmp, NOW)["inputs_digest"]


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        self.t += timedelta(minutes=1)
        return self.t


class V6PublishTests(unittest.TestCase):
    def setUp(self):
        self.fx = BareGitFixture(files=V6_FILES)
        self.addCleanup(self.fx.cleanup)
        self.root = self.fx.clone("v6")
        self.receipt = self.fx.home / "receipt.json"
        self.bundle = self.fx.home / "unpublished.bundle"

    # ------------------------------------------------------------ helpers
    def produce(self, run_id=RUN):
        """The evaluate+commit steps of the workflow, on the pinned checkout."""
        report = fake_build(self.root, NOW)
        data = v6.serialize(report)
        for path in (v6.REPORT, v6.run_path(run_id)):
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        git(self.root, "add", v6.REPORT, v6.run_path(run_id))
        git(self.root, "commit", "-qm", "data(llm): offline statistical audit %s [skip ci]" % run_id,
            "-m", "V6-Input-Commit: " + self.fx.base)
        return data

    def publish(self, run_id=RUN, push=sel.default_push, **kw):
        policy = v6.V6OfflineStatsPolicy(run_id, builder=fake_build, clock=Clock())
        return v6.publish(self.root, base=self.fx.base, run_id=run_id, receipt=self.receipt,
                          bundle=self.bundle, policy=policy, push=push, sleep=lambda s: None, **kw)

    def receipt_doc(self):
        return json.loads(self.receipt.read_text())

    def snapshot(self, ref="refs/heads/main"):
        names = git(self.fx.remote, "ls-tree", "-r", "--name-only", ref).split()
        return {n: self.fx.show(n, ref) for n in names}

    def legacy_push(self):
        """The exact command the old workflow used."""
        return subprocess.run(["git", "-C", str(self.root), "push", "origin", "HEAD:main"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def v4_race(self):
        return self.fx.plain_commit("v4", {
            "docs/lab/v6-falsification.json": {"v": 2}, "docs/lab/v6-p0-gates.json": {"v": 2},
            "docs/lab/v6-readiness.json": {"v": 2}, "docs/lab/v4-audit.json": {"n": 2},
            "docs/lab/golden-report.json": {"v": 2}},
            "data(lab): refresh V4 comparison and log checks [skip ci]")

    def ft_race(self):
        ledger = json.loads(json.dumps(V6_FILES["data/lab/ft-ledger.json"]))
        ledger["matches"]["2026-11-02,7,8"] = {"status": "FINAL",
                                               "result": {"home_goals": 2, "away_goals": 2}}
        return self.fx.plain_commit("ft", {
            "data/lab/ft-ledger.json": ledger,
            "data/lab/v6-ft-events-2026-11.jsonl": V6_FILES["data/lab/v6-ft-events-2026-11.jsonl"]
            + jline(ft="e2"),
            "data/lab/discovery-events-2026-11.jsonl": V6_FILES["data/lab/discovery-events-2026-11.jsonl"]
            + jline(event="d2"),
            "data/lab/discovery-segmented/%s/state-0000.json" % SEG: {"s": 1},
            "docs/lab/ft-results.json": {"final": 2}},
            "data(lab): publish verified FT snapshot over unrelated H1/V4 updates [skip ci]")

    def assert_published_on_remote_inputs(self, before_publish):
        doc = self.receipt_doc()
        self.assertEqual(doc["status"], "PUBLISHED")
        main = self.fx.main()
        self.assertEqual(doc["published_commit"], main)
        self.assertEqual(git(self.fx.remote, "rev-parse", "main^"), before_publish)
        latest = self.fx.show(v6.REPORT)
        self.assertEqual(latest, self.fx.show(v6.run_path(RUN)))
        self.assertEqual(hashlib.sha256(latest.encode()).hexdigest(), doc["published_report_sha256"])
        report = json.loads(latest)
        self.assertEqual(report["inputs_digest"], remote_inputs_digest(self.fx, before_publish))
        self.assertEqual(doc["input_commit"], before_publish)
        self.assertIn("V6-Input-Commit: " + before_publish,
                      git(self.fx.remote, "log", "-1", "--format=%B", "main"))
        # Only the two V6 outputs differ from the concurrent head.
        self.assertEqual(git(self.fx.remote, "diff", "--name-only", before_publish, "main").split(),
                         sorted([v6.REPORT, v6.run_path(RUN)]))
        self.assertEqual(doc["llm_calls"], 0)
        self.assertEqual(doc["provider_requeries"], 0)
        self.assertFalse(doc["force_push"])
        return report

    # ------------------------------------------------------------ real incidents
    def test_reproduces_run_41420785839_and_recovers_by_offline_recompute(self):
        old = self.produce()
        head = self.v4_race()
        legacy = self.legacy_push()
        self.assertNotEqual(legacy.returncode, 0)
        self.assertIn(b"[rejected]", legacy.stderr)
        self.assertIn(b"fetch first", legacy.stderr)
        self.assertEqual(self.fx.main(), head)
        before = self.snapshot()
        status, doc = self.publish()
        self.assertEqual(status, "PUBLISHED")
        report = self.assert_published_on_remote_inputs(head)
        self.assertTrue(doc["recomputed"])
        self.assertNotEqual(report["inputs_digest"], json.loads(old)["inputs_digest"])
        after = self.snapshot()
        for path, content in before.items():
            if path not in (v6.REPORT,):
                self.assertEqual(after[path], content, path)

    def test_reproduces_run_41540018891_collector_v4_ft_race(self):
        self.produce()
        self.fx.plain_commit("collector", {"docs/data.json": {"rendered": 2}},
                             "data: collect and notify H1 [skip ci]")
        self.v4_race()
        head = self.ft_race()
        legacy = self.legacy_push()
        self.assertIn(b"fetch first", legacy.stderr)
        before = self.snapshot()
        self.publish()
        report = self.assert_published_on_remote_inputs(head)
        self.assertEqual(report["source_sha256"]["data/lab/ft-ledger.json"],
                         hashlib.sha256(before["data/lab/ft-ledger.json"].encode()).hexdigest())
        after = self.snapshot()
        self.assertEqual({p: c for p, c in after.items() if p != v6.REPORT and p != v6.run_path(RUN)},
                         {p: c for p, c in before.items() if p != v6.REPORT})
        ledger = json.loads(after["data/lab/ft-ledger.json"])
        self.assertEqual(ledger["matches"]["2026-11-01,1,2"]["status"], "FINAL")

    # ------------------------------------------------------------ recoverable races
    def test_non_input_race_transports_the_exact_producer_bytes(self):
        data = self.produce()
        head = self.fx.plain_commit("collector", {"docs/data.json": {"rendered": 3},
                                                  "docs/lab/v4-audit.json": {"n": 9}}, "data")
        status, doc = self.publish()
        self.assertEqual(status, "PUBLISHED")
        self.assertFalse(doc["recomputed"])
        self.assertEqual(self.fx.show(v6.run_path(RUN)).encode(), data)
        self.assertEqual(doc["input_commit"], self.fx.base)
        self.assertEqual(git(self.fx.remote, "rev-parse", "main^"), head)

    def test_cas_race_during_push_is_retried_with_full_revalidation(self):
        self.produce()
        calls = []

        def racing_push(root, candidate, branch="main"):
            calls.append(candidate)
            if len(calls) == 1:
                self.ft_race()       # FT lands between the remote read and the push
            return sel.default_push(root, candidate, branch)

        status, doc = self.publish(push=racing_push)
        self.assertEqual(status, "PUBLISHED")
        self.assertEqual(doc["path"], "AFTER_CAS")
        self.assertEqual(doc["cas_retries"], 1)
        self.assertEqual(len(calls), 2)
        self.assert_published_on_remote_inputs(git(self.fx.remote, "rev-parse", "main^"))

    def test_http_408_after_acceptance_is_confirmed_not_republished(self):
        self.produce()

        def lost_response(root, candidate, branch="main"):
            sel.default_push(root, candidate, branch)
            return subprocess.CompletedProcess([], 128, b"", HTTP_408)

        status, doc = self.publish(push=lost_response)
        self.assertEqual(doc["status"], "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR")
        self.assertEqual(git(self.fx.remote, "rev-list", "--count", "main"), "2")

    def test_rerun_of_a_published_run_never_overwrites(self):
        self.produce()
        self.publish()
        first = self.fx.show(v6.run_path(RUN))
        main = self.fx.main()
        git(self.root, "reset", "-q", "--hard", self.fx.base)
        self.produce()                  # rerun: new report bytes, same run id
        status, doc = self.publish()
        self.assertEqual(status, "ALREADY_PUBLISHED_FOR_RUN")
        self.assertEqual(self.fx.main(), main)
        self.assertEqual(self.fx.show(v6.run_path(RUN)), first)
        self.assertEqual(doc["published_report_sha256"], hashlib.sha256(first.encode()).hexdigest())

    def test_other_run_history_added_concurrently_is_kept(self):
        self.produce()
        other = v6.run_path("41500000000")
        self.fx.plain_commit("v6-other", {other: fake_build(self.root, NOW),
                                          v6.REPORT: fake_build(self.root, NOW)}, "data(llm)")
        self.publish()
        self.assertIsNotNone(self.fx.show(other))
        self.assertIsNotNone(self.fx.show(v6.run_path(RUN)))
        self.assertTrue(self.receipt_doc()["recomputed"])   # never regress the newer latest

    # ------------------------------------------------------------ safe refusals / supersession
    def assert_nothing_pushed(self, head):
        self.assertEqual(self.fx.main(), head)
        self.assertIsNone(self.fx.show(v6.run_path(RUN)))
        self.assertTrue(self.bundle.exists())

    def test_program_change_supersedes_safely(self):
        self.produce()
        head = self.fx.plain_commit("human", {"h1lab/core.py": "# new program\n"}, "fix")
        with self.assertRaises(sel.Superseded):
            self.publish()
        self.assert_nothing_pushed(head)
        self.assertEqual(self.receipt_doc()["status"], "SUPERSEDED_BY_NEWER_INPUTS")

    def test_ft_final_rewritten_refuses(self):
        self.produce()
        ledger = json.loads(json.dumps(V6_FILES["data/lab/ft-ledger.json"]))
        ledger["matches"]["2026-11-01,1,2"]["result"] = {"home_goals": 0, "away_goals": 0}
        head = self.fx.plain_commit("bad-ft", {"data/lab/ft-ledger.json": ledger}, "x")
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish()
        self.assertEqual(ctx.exception.kind, "INTEGRITY")
        self.assert_nothing_pushed(head)
        self.assertEqual(self.receipt_doc()["status"], "REFUSED")

    def test_append_only_input_rewritten_refuses(self):
        self.produce()
        head = self.fx.plain_commit("bad", {"data/lab/v6-ft-events-2026-11.jsonl": jline(ft="X")}, "x")
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish()
        self.assertEqual(ctx.exception.kind, "INTEGRITY")
        self.assert_nothing_pushed(head)

    def test_existing_run_history_rewritten_refuses(self):
        other = v6.run_path("41400000000")
        self.fx.plain_commit("seed2", {other: {"status": "old"}}, "seed")
        self.fx.base = self.fx.main()
        git(self.root, "fetch", "-q", "origin", "main")
        git(self.root, "reset", "-q", "--hard", "origin/main")
        self.produce()
        head = self.fx.plain_commit("bad", {other: {"status": "rewritten"}}, "x")
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish()
        self.assertEqual(ctx.exception.kind, "INTEGRITY")
        self.assert_nothing_pushed(head)

    def test_concurrent_writer_of_the_same_run_refuses(self):
        self.produce()
        head = self.fx.plain_commit("dup", {v6.run_path(RUN): {"status": "other"}}, "x")
        # Caught up-front: an immutable run file already on main is never overwritten.
        status, _ = self.publish()
        self.assertEqual(status, "ALREADY_PUBLISHED_FOR_RUN")
        self.assertEqual(self.fx.main(), head)
        self.assertEqual(json.loads(self.fx.show(v6.run_path(RUN))), {"status": "other"})

    def test_unknown_path_refuses(self):
        self.produce()
        head = self.fx.plain_commit("odd", {"data/unregistered.bin": "x"}, "x")
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish()
        self.assertEqual(ctx.exception.kind, "UNKNOWN_PATH")
        self.assert_nothing_pushed(head)

    def test_recompute_failure_is_a_documented_refusal(self):
        self.produce()
        head = self.v4_race()

        def broken(root, now):
            raise ValueError("SOURCE_COVERAGE_ERRORS")

        policy = v6.V6OfflineStatsPolicy(RUN, builder=broken, clock=Clock())
        with self.assertRaises(sel.PublicationRefused) as ctx:
            v6.publish(self.root, base=self.fx.base, run_id=RUN, receipt=self.receipt,
                       bundle=self.bundle, policy=policy, sleep=lambda s: None)
        self.assertEqual(ctx.exception.kind, "RECOMPUTE_FAILED")
        self.assert_nothing_pushed(head)
        self.assertIn("RECOMPUTE_FAILED", self.receipt_doc()["reason_kind"])

    def test_report_not_matching_its_base_is_refused_before_any_push(self):
        report = fake_build(self.root, NOW)
        report["source_sha256"]["data/state.json"] = "0" * 64
        data = v6.serialize(report)
        for path in (v6.REPORT, v6.run_path(RUN)):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_bytes(data)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "x")
        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish()
        self.assertEqual(ctx.exception.kind, "INVALID_INPUT")
        self.assertEqual(self.fx.main(), self.fx.base)

    def test_research_invariants_enforced(self):
        report = fake_build(self.root, NOW)
        report["llm_calls"] = 1
        with self.assertRaises(sel.PublicationRefused):
            v6.check_report(v6.serialize(report), "x")

    def test_retry_bound_exhaustion_is_reported(self):
        self.produce()
        n = {"i": 0}

        def always_racing(root, candidate, branch="main"):
            n["i"] += 1
            self.fx.plain_commit("collector", {"docs/data.json": {"r": n["i"]}}, "data")
            return sel.default_push(root, candidate, branch)

        with self.assertRaises(sel.PublicationRefused) as ctx:
            self.publish(push=always_racing, max_attempts=3)
        self.assertEqual(ctx.exception.kind, "RETRY_EXHAUSTED")
        self.assertEqual(n["i"], 3)
        self.assertIsNone(self.fx.show(v6.run_path(RUN)))

    # ------------------------------------------------------------ isolation
    def test_recomputation_blocks_network_and_subprocesses(self):
        import socket

        def leaky(root, now):
            socket.getaddrinfo("example.invalid", 443)

        def spawning(root, now):
            subprocess.run(["true"])

        for fn in (leaky, spawning):
            with self.assertRaises(RuntimeError) as ctx:
                import h1lab.v6_offline_statistics as mod
                original = mod.build
                mod.build = fn
                try:
                    v6.offline_build(self.root, NOW)
                finally:
                    mod.build = original
            self.assertIn("V6_OFFLINE_ISOLATION", str(ctx.exception))
        # The hook is inactive outside the recomputation (git transport still works).
        self.assertEqual(subprocess.run(["true"]).returncode, 0)


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_uses_the_safe_publisher_without_bare_push(self):
        text = (Path(__file__).resolve().parents[1]
                / ".github/workflows/v6-offline-statistics.yml").read_text()
        self.assertIn("python -m scripts.lab_v6_offline_publish_safe", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("--force", text)
        self.assertNotIn("rebase", text.replace("never rebase", "").replace("no rebase", ""))
        self.assertIn("ref: ${{ github.sha }}", text)

    def test_input_patterns_cover_the_planner_sources(self):
        from h1lab.v6_llm_investigator import SOURCES
        self.assertEqual(set(SOURCES), set(v6.PLANNER_SOURCES))
        for path in ("data/state.json", "data/lab/ft-ledger.json", "data/lab/markets-2026-11.jsonl",
                     "docs/lab/llm-investigator-runs/1.json", "docs/lab/v6-readiness.json"):
            self.assertTrue(v6.is_input(path), path)
        for path in ("docs/data.json", "docs/lab/v4-audit.json", "data/results.csv",
                     "data/lab/discovery-segmented/%s/state-0000.json" % SEG, v6.REPORT):
            self.assertFalse(v6.is_input(path), path)


class RealRepositoryInputContractTests(unittest.TestCase):
    """The production build on the real tracked snapshot reads ONLY paths ``is_input`` declares,
    and ``source_hashes`` (blob based) equals the build's own ``source_sha256``."""

    def test_traced_reads_are_declared_inputs_and_hashes_match(self):
        import os
        import sys
        root = Path(__file__).resolve().parents[1]
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "data",
                                "docs/lab"], stdout=subprocess.PIPE).stdout
        if dirty.strip():
            self.skipTest("working tree data differs from HEAD")
        seen, state = set(), {"on": False}
        prefix = str(root) + os.sep

        def hook(event, args):
            if state["on"] and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
                p = os.path.abspath(os.fsdecode(args[0]))
                if p.startswith(prefix) and not p.endswith((".py", ".pyc")) and \
                        os.sep + ".git" + os.sep not in p and "__pycache__" not in p:
                    seen.add(os.path.relpath(p, root).replace(os.sep, "/"))

        sys.addaudithook(hook)
        from h1lab.v6_offline_statistics import build
        state["on"] = True
        try:
            report = build(root, now=datetime.now(timezone.utc).replace(microsecond=0))
        finally:
            state["on"] = False
        undeclared = sorted(p for p in seen if not v6.is_input(p))
        self.assertEqual(undeclared, [])
        self.assertTrue(any(p.startswith("data/lab/ft-ledger") for p in seen))
        self.assertEqual(report["source_sha256"], v6.source_hashes(root, "HEAD"))


if __name__ == "__main__":
    unittest.main()
