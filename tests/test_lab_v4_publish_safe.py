"""Bare-Git reproduction of the LAB V4 publication risks and of the safe publisher.

``LegacyLabV4LoopRisks`` replays the pre-fix loop of lab-v4-audit.yml
(``git fetch; git rebase origin/main; publication_guard verify; git push``) with the
REAL ``publication_guard`` seal. ``SafeLabV4Publication`` runs
``scripts.lab_v4_publish_safe`` against the same concurrent writers.
"""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import git_selective_publish as sel
from scripts import lab_v4_publish_safe as lab
from scripts import publication_guard
from tests import git_writers as gw
from tests.git_writers import (HTTP_408, BareGitFixture, PushHook, accept_then_fail, fail, git,
                               jline, ledger, race, write)

CLOSED_FT = "data/lab/v6-ft-events-2026-10.jsonl"
CLOSED_V4 = "data/lab/discovery-events-2026-10.jsonl"   # a second closed append-only month
INDEX = "data/lab/v6-archive-index.json"
RUNCHECKS = "data/lab/v4-runchecks.jsonl"
FORECASTS = "data/lab/v6-forecasts-2026-11.jsonl"
ELIG = "docs/lab/telegram-eligibility.json"
THREE = "data/three-total-moves-notifications.json"


def lab_files():
    files = dict(gw.BASELINE)
    for name in publication_guard.REQUIRED["audit"]:
        files[name] = {"generated": 0}
    files[CLOSED_FT] = jline(ft="old-1") + jline(ft="old-2")
    files[CLOSED_V4] = jline(discovery="d0")
    files[INDEX] = {"schema_version": 1, "sealed": []}
    files["data/lab/golden/reviews/a.json"] = {"label": "ok"}
    return files


def index_for(root, paths):
    sealed = []
    for path in sorted(paths):
        raw = (Path(root) / path).read_bytes()
        sealed.append({"path": path, "bytes": len(raw), "rows": len(raw.splitlines()),
                       "sha256_bytes": hashlib.sha256(raw).hexdigest()})
    return {"schema_version": 1, "status": "V6_LAB_MONTHLY_ARCHIVE_SEALED", "sealed": sealed}


def eligibility(receipts):
    return {"schema_version": 1, "source_commit": "unknown",
            "games": {"2026-11-01,1,2": {"match_key": "2026-11-01,1,2", "receipts": receipts}}}


def lab_cycle(fx, name="lab"):
    """One LAB V4 audit after its producers succeeded: stage, seal (real guard), commit."""
    root = fx.clone(name)
    git(root, "fetch", "-q", "origin", "main")
    git(root, "reset", "-q", "--hard", "origin/main")
    base = git(root, "rev-parse", "HEAD")
    write(root, "docs/lab/v4-audit.json", {"generated": 1, "source_commit": base})
    write(root, RUNCHECKS, (root / RUNCHECKS).read_text() + jline(run=2))
    write(root, FORECASTS, (root / FORECASTS).read_text() + jline(forecast="f2"))
    write(root, INDEX, index_for(root, [CLOSED_FT, CLOSED_V4]))
    write(root, ELIG, eligibility({"three": {"status": "sent", "telegram_message_id": 10}}))
    git(root, "add", "docs/lab", RUNCHECKS, FORECASTS)
    git(root, "add", "-f", INDEX)
    manifest = fx.home / (name + "-seal.json")
    with lab.inside(root):
        publication_guard.seal("audit", str(manifest))
    git(root, "commit", "-q", "-m", lab.MESSAGE, "-m", lab.TRAILER + base)   # as lab-v4-audit.yml
    return root, base, manifest


FT_FINAL_CHANGED = {"schema_version": 1, "matches": {
    "2026-11-01,1,2": {"status": "FINAL", "result": {"home_goals": 2, "away_goals": 0}}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.fx = BareGitFixture(lab_files())
        self.addCleanup(self.fx.cleanup)
        for p in (patch("h1lab.bot.send_message", side_effect=AssertionError("Telegram")),
                  patch("urllib.request.urlopen", side_effect=AssertionError("provider"))):
            p.start()
            self.addCleanup(p.stop)

    def publish(self, root, base, manifest, hook=None, **kw):
        receipt = self.fx.home / "lab-receipt.json"
        self.hook = hook or PushHook()
        try:
            return sel.publish(root, base=base, policy=lab.LabV4Policy(manifest), receipt=receipt,
                               bundle=self.fx.home / "lab.bundle", push=self.hook,
                               sleep=lambda s: None, **kw)
        finally:
            self.receipt = json.loads(receipt.read_text()) if receipt.exists() else None


# =============================================================================== legacy
class LegacyLabV4LoopRisks(Base):
    def legacy_loop(self, root, manifest, attempts=5):
        for _ in range(attempts):
            for args in (["fetch", "-q", "origin", "main"], ["rebase", "-q", "origin/main"]):
                proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
                if proc.returncode:
                    return "FAILED_AT_" + args[0].upper()
            try:
                with lab.inside(root):
                    publication_guard.verify(str(manifest))
            except ValueError:
                return "SEAL_REFUSED"
            if subprocess.run(["git", "-C", str(root), "push", "-q", "origin", "HEAD:main"],
                              capture_output=True).returncode == 0:
                return "LAB_AUDIT_PUBLISHED"
        return "LAB_AUDIT_PUBLISH_FAILED"

    def test_closed_month_append_publishes_an_index_that_contradicts_main(self):
        root, _, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("ft", {CLOSED_FT: jline(ft="old-1") + jline(ft="old-2") + jline(ft="late")},
                             "data(lab): publish verified FT snapshot")
        self.assertEqual(self.legacy_loop(root, manifest), "LAB_AUDIT_PUBLISHED")
        sealed = {e["path"]: e for e in self.fx.json(INDEX)["sealed"]}
        actual = hashlib.sha256(self.fx.show(CLOSED_FT).encode()).hexdigest()
        self.assertNotEqual(sealed[CLOSED_FT]["sha256_bytes"], actual,
                            "main now holds an archive index that every later build rejects "
                            "(SEALED_MONTH_MUTATED_OR_MISSING)")

    def test_rewritten_ft_final_is_not_noticed(self):
        root, _, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("ft", {"data/lab/ft-ledger.json": FT_FINAL_CHANGED}, "FT")
        self.assertEqual(self.legacy_loop(root, manifest), "LAB_AUDIT_PUBLISHED")

    def test_report_contradicting_rolled_back_receipt_is_published(self):
        root, _, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("collector", {THREE: ledger()}, "data: collect and notify H1 [skip ci]")
        self.assertEqual(self.legacy_loop(root, manifest), "LAB_AUDIT_PUBLISHED")
        self.assertEqual(self.fx.json(THREE)["entries"], {})
        self.assertEqual(self.fx.json(ELIG)["games"]["2026-11-01,1,2"]["receipts"]["three"]["status"], "sent")

    def test_same_artifact_by_another_lab_run_conflicts_or_is_caught_by_the_seal(self):
        root, _, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("lab2", {"docs/lab/v4-audit.json": {"generated": 9}}, lab.MESSAGE)
        self.assertEqual(self.legacy_loop(root, manifest), "FAILED_AT_REBASE")

    def test_concurrent_journal_append_conflicts(self):
        root, _, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("lab2", {RUNCHECKS: jline(run=1) + jline(run=99)}, lab.MESSAGE)
        self.assertEqual(self.legacy_loop(root, manifest), "FAILED_AT_REBASE")


# =============================================================================== safe
class SafeLabV4Publication(Base):
    def assert_lab_bytes(self):
        self.assertEqual(self.fx.json("docs/lab/v4-audit.json")["generated"], 1)
        self.assertEqual(self.fx.show(RUNCHECKS).count("\n"), 2)
        self.assertIn('"f2"', self.fx.show(FORECASTS))

    def test_quiet_main_publishes_first_attempt_with_seal_and_dependency_proof(self):
        root, base, manifest = lab_cycle(self.fx)
        published = self.publish(root, base, manifest)
        self.assertEqual(self.fx.main(), published)
        r = self.receipt
        self.assertEqual((r["status"], r["path"]), ("PUBLISHED", "FIRST_ATTEMPT"))
        self.assertEqual(r["archive_entries_checked"], 2)
        self.assertEqual(r["eligibility_receipts_checked"], 1)
        self.assert_lab_bytes()

    def test_non_material_concurrent_commits_are_preserved(self):
        root, base, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("llm", {"docs/lab/llm-investigator-index.json": {"runs": 1}}, "LLM")
        self.fx.plain_commit("human", {"docs/audit/note.md": "x\n"}, "docs")
        view = self.fx.json("docs/data.json")
        self.fx.plain_commit("h1view", {"docs/data.json": {**view, "generated_at": "2026-11-02T09:00:00+00:00"}},
                             "dashboard re-render")
        heads = git(self.fx.remote, "rev-list", "main").split()
        published = self.publish(root, base, manifest)
        self.assertTrue(set(heads) <= set(git(self.fx.remote, "rev-list", published).split()))
        self.assertEqual(self.receipt["status"], "PUBLISHED")
        self.assertIn(lab.TRAILER + base, git(self.fx.remote, "log", "-1", "--format=%B", published))
        self.assert_lab_bytes()

    def material_changes(self):
        ft = {"schema_version": 1, "matches": {
            "2026-11-01,1,2": {"status": "FINAL", "result": {"home_goals": 1, "away_goals": 0}},
            "2026-11-02,3,4": {"status": "FINAL", "result": {"home_goals": 0, "away_goals": 0}}}}

        def collect(root):
            write(root, "data/state.json", gw.state(150, ("c:1", "c:2")))
            gw.observe(root, 2, observed="2026-11-02T07:00:00+00:00")
            gw.render(root)
        return (("FT new FINAL", {"data/lab/ft-ledger.json": ft}, None),
                ("FT event", {"data/lab/v6-ft-events-2026-11.jsonl": jline(ft="e1") + jline(ft="e2")}, None),
                ("FT report", {"docs/lab/ft-results.json": {"final": 2}}, None),
                ("H1 result", {"data/results.csv": gw.BASELINE["data/results.csv"]
                               + "\"2026-11-02,3,4\",final,0,0,y\n"}, None),
                ("collector observation", {}, collect),
                ("Telegram receipt", {THREE: ledger(**{"2026-11-01_1_2": gw.SENT_OLD,
                                                      "2026-11-03_2": gw.SENT_NEW})}, None))

    def test_valid_material_input_changes_supersede_instead_of_publishing_stale_reports(self):
        for name, changes, action in self.material_changes():
            with self.subTest(name):
                self.fx = BareGitFixture(lab_files())
                self.addCleanup(self.fx.cleanup)
                root, base, manifest = lab_cycle(self.fx)
                head = self.fx.plain_commit("other", changes, name, action=action)
                with self.assertRaises(sel.Superseded):
                    self.publish(root, base, manifest)
                self.assertEqual(self.fx.main(), head, "no stale LAB report published")
                self.assertEqual(self.hook.calls, [])
                self.assertEqual((self.receipt["status"], self.receipt["failure_class"]),
                                 ("SUPERSEDED_BY_NEWER_INPUTS", "SUPERSEDED_SAFE_SKIP"))
                self.assertNotIn(lab.MESSAGE, git(self.fx.remote, "log", "--format=%s", "main"))

    def test_rerun_after_supersession_publishes_reports_of_exactly_the_new_inputs(self):
        _, changes, action = self.material_changes()[4]
        root, base, manifest = lab_cycle(self.fx)
        self.fx.plain_commit("collector", changes, "collect", action=action)
        with self.assertRaises(sel.Superseded):
            self.publish(root, base, manifest)
        rerun, new_base, new_manifest = lab_cycle(self.fx, "lab-rerun")   # next triggered run
        self.assertNotEqual(new_base, base)
        published = self.publish(rerun, new_base, new_manifest)
        body = git(self.fx.remote, "log", "-1", "--format=%B", published)
        self.assertEqual(self.fx.json("docs/lab/v4-audit.json")["source_commit"], new_base)
        input_commit = body.split(lab.TRAILER)[1].split()[0]
        moved = git(self.fx.remote, "diff", "--name-only", input_commit, published + "^").split()
        self.assertEqual([p for p in moved if p not in lab.NON_MATERIAL], [],
                         "the reports sit on exactly the inputs they were computed from")

    def test_cas_race_by_a_material_writer_supersedes_on_the_retry(self):
        root, base, manifest = lab_cycle(self.fx)
        hook = PushHook({1: race(self.fx, "ft", {"docs/lab/ft-results.json": {"final": 3}}, "FT")})
        with self.assertRaises(sel.Superseded):
            self.publish(root, base, manifest, hook)
        self.assertEqual(len(hook.calls), 1)
        self.assertEqual(self.fx.json("docs/lab/ft-results.json"), {"final": 3})
        self.assertEqual(self.fx.json("docs/lab/v4-audit.json"), {"generated": 0})

    def refused(self, changes, kind, writer="other"):
        root, base, manifest = lab_cycle(self.fx)
        before = self.fx.plain_commit(writer, changes, "concurrent")
        with self.assertRaises(sel.PublicationRefused):
            self.publish(root, base, manifest)
        self.assertEqual(self.fx.main(), before, "nothing partial published")
        self.assertEqual(self.receipt["reason_kind"], kind)
        self.assertEqual(self.receipt["failure_class"], "PERSISTENT_INCOMPATIBILITY")
        self.assertTrue(Path(self.receipt["bundle"]).exists())
        return self.receipt

    def test_closed_month_change_contradicting_new_index_is_refused(self):
        r = self.refused({CLOSED_FT: lab_files()[CLOSED_FT] + jline(ft="late")}, "DEPENDENCY_CHANGED")
        self.assertIn("Closed month sealed by the archive index changed", r["reason"])
        # Second line of defence on the exact tree: the produced index is re-hashed against
        # the blobs. Build the tree the old rebase loop would have published and check it.
        root = self.fx.clone("lab")                    # holds the unpublished LAB commit
        git(root, "fetch", "-q", "origin", "main")
        git(root, "checkout", "-q", "origin/main", "--", CLOSED_FT)
        git(root, "commit", "-qm", "LAB index over the concurrently changed closed month")
        with self.assertRaises(sel.PublicationRefused) as ctx:
            lab.verify_archive_index(root, "HEAD")
        self.assertIn("Archive index contradicts", str(ctx.exception))

    def test_rewritten_ft_final_is_refused(self):
        self.refused({"data/lab/ft-ledger.json": FT_FINAL_CHANGED}, "DEPENDENCY_CHANGED")

    def test_rolled_back_receipt_is_refused(self):
        self.refused({THREE: ledger()}, "DEPENDENCY_CHANGED")

    def test_fixture_identity_rewrite_is_refused(self):
        self.refused({"data/state.json": gw.state(home="Z")}, "DEPENDENCY_CHANGED")

    def test_rewritten_v4_revision_journal_is_refused(self):
        journal = gw.v4_journal_paths(self.fx)[0]
        self.refused({journal: jline(event_id="x", sha256="c" * 64)}, "DEPENDENCY_CHANGED")

    def test_certified_h1_result_change_is_refused(self):
        self.refused({"data/results.csv": "match_key,status,home_goals,away_goals,source\n"
                                          "\"2026-11-01,1,2\",final,0,0,x\n"}, "DEPENDENCY_CHANGED")

    def test_another_lab_publication_of_the_same_artifact_is_refused(self):
        self.refused({"docs/lab/v4-audit.json": {"generated": 9}}, "CONCURRENT_OWNER_WRITE")

    def test_concurrent_journal_entries_are_refused_not_merged(self):
        self.refused({RUNCHECKS: jline(run=1) + jline(run=99)}, "CONCURRENT_OWNER_WRITE")

    def test_new_archive_generation_by_another_writer_is_refused(self):
        self.refused({INDEX: {"schema_version": 1, "sealed": [{"path": "x"}]}}, "CONCURRENT_OWNER_WRITE")

    def test_golden_labels_program_and_unknown_paths_are_refused(self):
        for changes, kind in (({"data/lab/golden/reviews/a.json": {"label": "bad"}}, "DEPENDENCY_CHANGED"),
                              ({"scripts/lab_golden.py": "# new\n"}, "INCOMPATIBLE_PROGRAM"),
                              ({"data/lab/unknown.json": {}}, "UNKNOWN_PATH")):
            with self.subTest(kind=kind):
                self.fx = BareGitFixture(lab_files())
                self.addCleanup(self.fx.cleanup)
                self.refused(changes, kind)

    def test_seal_mismatch_on_own_commit_is_refused_before_any_push(self):
        root, base, manifest = lab_cycle(self.fx)
        write(root, "docs/lab/v4-audit.json", {"generated": "tampered"})
        git(root, "commit", "-qam", "amend after seal")
        git(root, "reset", "-q", "--soft", "HEAD~2")
        git(root, "commit", "-qm", lab.MESSAGE)
        with self.assertRaises(sel.PublicationRefused):
            self.publish(root, base, manifest)
        self.assertEqual(self.hook.calls, [])
        self.assertEqual(self.receipt["reason_kind"], "INTEGRITY")

    def test_cas_race_retries_and_keeps_the_independent_commit(self):
        root, base, manifest = lab_cycle(self.fx)
        hook = PushHook({1: race(self.fx, "llm", {"docs/lab/llm-investigator-index.json": {"runs": 3}}, "LLM")})
        published = self.publish(root, base, manifest, hook)
        self.assertEqual((self.receipt["path"], self.receipt["cas_retries"]), ("AFTER_CAS", 1))
        self.assertEqual(self.fx.json("docs/lab/llm-investigator-index.json"), {"runs": 3})
        self.assertEqual(self.fx.main(), published)

    def test_http_408_before_and_after_acceptance(self):
        root, base, manifest = lab_cycle(self.fx)
        self.publish(root, base, manifest, PushHook({1: fail(HTTP_408)}))
        self.assertEqual((len(self.hook.calls), self.receipt["path"]), (2, "AFTER_TRANSPORT"))
        self.fx = BareGitFixture(lab_files())
        self.addCleanup(self.fx.cleanup)
        root, base, manifest = lab_cycle(self.fx)
        self.publish(root, base, manifest, PushHook({1: accept_then_fail(HTTP_408)}))
        self.assertEqual(len(self.hook.calls), 1)
        self.assertEqual(self.receipt["status"], "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR")
        self.assertEqual(git(self.fx.remote, "log", "--format=%s", "main").count(lab.MESSAGE), 1,
                         "no duplicated append-only entries")

    def test_crash_after_publication_rerun_is_equivalent_without_push(self):
        root, base, manifest = lab_cycle(self.fx)
        git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.fx.plain_commit("llm", {"docs/lab/llm-investigator-index.json": {"runs": 2}}, "LLM")
        hook = PushHook()
        self.publish(root, base, manifest, hook)
        self.assertEqual(hook.calls, [])
        self.assertEqual(self.receipt["status"], "ALREADY_PUBLISHED_EQUIVALENT")
        self.assertEqual(self.fx.show(RUNCHECKS).count("\n"), 2, "journal entry not duplicated")


class ProvenanceContract(Base):
    def test_commit_naming_another_input_commit_is_refused(self):
        root, base, manifest = lab_cycle(self.fx)
        git(root, "commit", "-q", "--amend", "-m", lab.MESSAGE, "-m", lab.TRAILER + "0" * 40)
        with self.assertRaises(sel.PublicationRefused):
            self.publish(root, base, manifest)
        self.assertEqual(self.receipt["reason_kind"], "INVALID_INPUT")


class WorkflowContract(unittest.TestCase):
    def test_workflow_keeps_guard_and_seal_and_drops_the_rebase_loop(self):
        text = (Path(__file__).resolve().parents[1] / ".github/workflows/lab-v4-audit.yml").read_text()
        self.assertIn("python -m scripts.publication_guard outcomes --pipeline audit", text)
        self.assertIn("python -m scripts.publication_guard seal --pipeline audit", text)
        self.assertIn("python -m scripts.lab_v4_publish_safe --base \"$LAB_SOURCE_SHA\"", text)
        self.assertIn('-m "LAB-Input-Commit: $LAB_SOURCE_SHA"', text)
        self.assertNotIn("git rebase", text)
        self.assertNotIn("for attempt in", text)
        self.assertNotIn("--force", text)
        import yaml
        yaml.safe_load(text)


if __name__ == "__main__":
    unittest.main()
