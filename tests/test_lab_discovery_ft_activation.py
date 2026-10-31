"""Offline dual-mode activation, FT FINAL, rollback and remote-race regressions."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab import lab_discovery_dual_state as dual
from h1lab import lab_discovery_store as store
from h1lab.lab_ft_final_guard import final_snapshot, verify_preserved
from scripts.lab_discovery_ft_activation import (
    preflight, publish_ft, rollback_local, publish_rollback,
)
from scripts.lab_discovery_cutover_release import (
    CutoverBlocked, stage_reachable, commit_sha, remote_sha,
)


def state():
    return {"schema_version": 1, "patterns": {"demo": {"points": [{"at": 1}]}},
            "prospective_settled": {}, "latest_events": []}


def ft(status="FINAL", *, score=(2, 1), team="Home"):
    rows = {"old": {"status": status, "home": team, "away": "Away",
                    "kickoff_utc": "2026-10-30T17:00:00+00:00"}}
    if status == "FINAL":
        rows["old"]["result"] = {
            "home_goals": score[0], "away_goals": score[1],
            "source": "https://example.invalid/ft",
            "evidence": "bsd"}
    return store.encode({"schema_version": 1, "matches": rows})


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args],
                                   stderr=subprocess.DEVNULL).decode().strip()


class DualReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dual-ft-release-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.root.mkdir()
        self.legacy = self.root / dual.STATE
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_bytes(store.encode(state()))
        self.ft = self.root / "data/lab/ft-ledger.json"
        self.ft.write_bytes(ft())

    def start(self):
        first = dual.bootstrap(self.root)
        return first["generation"]

    def test_fail_closed_when_first_current_absent(self):
        with self.assertRaises(ValueError):
            preflight(self.root, self.root / "baseline.json")
        self.assertFalse((self.root / "baseline.json").exists())

    def test_preflight_captures_real_certified_identity_and_generation(self):
        generation = self.start()
        result = preflight(self.root, self.root / "baseline.json")
        self.assertEqual(result["generation"], generation)
        self.assertEqual(result["prior_final"], 1)
        self.assertEqual(result["state_backend"], "dual")

    def test_initial_repository_snapshot_has_full_recovery_and_frozen_final_keys(self):
        """A real cutover branch must include CURRENT and all referenced shards."""
        root = Path(__file__).resolve().parents[1]
        current = root / "data/lab/discovery-segmented/CURRENT.json"
        frozen = root / "reports/FT_CUTOVER_FROZEN_FINALS.json"
        if not current.exists() and not frozen.exists():
            self.skipTest("legacy-only main: activation has not been committed")
        self.assertTrue(current.is_file(), "initial CURRENT missing")
        self.assertTrue(frozen.is_file(), "full per-match FT baseline missing")
        self.assertEqual(dual.load(root, format="dual"),
                         store.decode((root / dual.STATE).read_bytes()))
        from h1lab.lab_discovery_git_bundle import seal
        proof = seal(root, ref="HEAD")
        self.assertIn("data/lab/discovery-segmented/CURRENT.json", proof["sha256"])
        self.assertGreaterEqual(len(proof["sha256"]), 5)
        baseline = json.loads(frozen.read_text(encoding="utf-8"))
        self.assertTrue(verify_preserved(
            baseline, (root / "data/lab/ft-ledger.json").read_bytes()
        )["previous_final_unchanged"])

    def test_real_ft_ledger_final_baseline_replay_is_exact(self):
        root = Path(__file__).resolve().parents[1]
        raw = (root / "data/lab/ft-ledger.json").read_bytes()
        baseline = final_snapshot(raw)
        self.assertGreater(baseline["final_count"], 0)
        replay = verify_preserved(baseline, raw)
        self.assertTrue(replay["previous_final_unchanged"])
        self.assertEqual(replay["new_final_count"], 0)

    def test_all_previous_final_identity_and_scores_preserved(self):
        old = final_snapshot(ft())
        candidate = store.decode(ft())
        candidate["matches"]["new"] = {
            **copy.deepcopy(candidate["matches"]["old"]),
            "home": "Additional", "result": {"home_goals": 1, "away_goals": 1,
                            "source": "https://example.invalid/other"}}
        result = verify_preserved(old, store.encode(candidate))
        self.assertEqual(result["new_final_count"], 1)
        for bad in (
            ft(status="PENDING"), ft(score=(2, 0)),
            ft(team="Different Home"),
            store.encode({"schema_version": 1, "matches": {}})):
            with self.subTest(bad=bad[:30]), self.assertRaisesRegex(ValueError, "altered or lost"):
                verify_preserved(old, bad)

    def test_reject_malformed_ledger_or_invalid_final_score(self):
        for raw in (b'{"schema_version":1,"matches":{},"matches":{}}',
                    b'{"schema_version":1,"matches":{"old":{"status":"FINAL"}}}',
                    ft(score=(True, 1))):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                final_snapshot(raw)

    def test_explicit_paired_rollback_and_old_generation_reachable(self):
        first = self.start()
        before = self.legacy.read_bytes()
        next_state = copy.deepcopy(state())
        next_state["__changed_for_test__"] = "new"
        dual.write_dual(self.root, next_state, expected_generation=first)
        pointer = (self.root / dual.SEGMENT / "CURRENT.json").read_bytes()
        result = rollback_local(self.root, expected_current_sha256=store.digest(pointer))
        self.assertEqual(result["status"], "ROLLBACK_PREPARED_NOT_PUBLISHED")
        self.assertEqual(result["previous_generation"], first)
        self.assertEqual(self.legacy.read_bytes(), before)
        self.assertEqual(dual.load(self.root, format="dual"), state())
        self.assertEqual(store.decode((self.root / dual.SEGMENT / "PREVIOUS.json").read_bytes())["generation"],
                         store.decode(pointer)["generation"])

    def test_rollback_requires_strict_pointer_cas(self):
        first = self.start()
        new_state = copy.deepcopy(state())
        new_state["unique"] = 1
        dual.write_dual(self.root, new_state, expected_generation=first)
        with self.assertRaisesRegex(CutoverBlocked, "CAS mismatch"):
            rollback_local(self.root, expected_current_sha256="0" * 64)
        self.assertEqual(dual.load(self.root, format="dual"), new_state)

    def test_interrupted_rollback_is_detected_not_silently_accepted(self):
        first = self.start()
        next_state = {**state(), "additional": 2}
        dual.write_dual(self.root, next_state, expected_generation=first)
        ptr = (self.root / dual.SEGMENT / "CURRENT.json").read_bytes()
        def interrupt(phase):
            if phase == "mirror_written":
                raise RuntimeError("simulated crash")
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            rollback_local(self.root, expected_current_sha256=store.digest(ptr),
                           crash_hook=interrupt)
        with self.assertRaisesRegex(ValueError, "mirror/segment mismatch"):
            dual.load(self.root, format="dual")
        self.assertEqual(store.digest((self.root / dual.SEGMENT / "CURRENT.json").read_bytes()),
                         store.digest(ptr))

    def test_stale_dual_writer_cannot_override_next_generation(self):
        first = self.start()
        snapshot = dual.load(self.root, format="dual")
        dual.write_dual(self.root, {**snapshot, "one": 1},
                        expected_generation=first)
        with self.assertRaises(ValueError):
            dual.write_dual(self.root, {**snapshot, "two": 2},
                            expected_generation=first)
        self.assertEqual(dual.load(self.root, format="dual")["one"], 1)

    def prepare_git(self):
        self.start()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "Test")
        stage_reachable(self.root)
        git(self.root, "add", "data/lab/ft-ledger.json")
        git(self.root, "commit", "-qm", "complete initial dual state")
        bare = Path(self.temp.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        git(self.root, "remote", "add", "origin", str(bare))
        git(self.root, "push", "-q", "origin", "main")
        return bare, commit_sha(self.root)

    def update_git(self):
        current = dual.current_generation(self.root)
        dual.write_dual(self.root, {**dual.load(self.root, format="dual"), "next": 42},
                        expected_generation=current)
        stage_reachable(self.root)
        git(self.root, "commit", "-qm", "new complete dual FT bundle")

    def test_normal_nonforce_ft_publish_verifies_and_advances_remote(self):
        bare, baseline = self.prepare_git()
        self.update_git()
        with patch("scripts.lab_discovery_ft_activation.publication_guard.verify") as verified:
            result = publish_ft(self.root, baseline, "seal.json")
        verified.assert_called_once_with("seal.json")
        self.assertEqual(result["status"], "FT_PUBLISHED_DUAL")
        self.assertEqual(remote_sha(self.root), commit_sha(self.root))

    def test_rollback_publishes_exact_pair_with_remote_cas(self):
        _, baseline = self.prepare_git()
        self.update_git()
        with patch("scripts.lab_discovery_ft_activation.publication_guard.verify"):
            publish_ft(self.root, baseline, "seal.json")
        update_commit = commit_sha(self.root)
        ptr = (self.root / dual.SEGMENT / "CURRENT.json").read_bytes()
        rollback_local(self.root, expected_current_sha256=store.digest(ptr))
        stage_reachable(self.root)
        git(self.root, "commit", "-qm", "authorized mirror + pointers rollback")
        result = publish_rollback(self.root, update_commit)
        self.assertEqual(result["status"], "ROLLBACK_PAIR_PUBLISHED")
        self.assertEqual(result["commit"], remote_sha(self.root))
        self.assertEqual(dual.load(self.root, format="dual"), state())

    def test_rollback_remote_race_cannot_override_other_writer(self):
        bare, baseline = self.prepare_git()
        self.update_git()
        with patch("scripts.lab_discovery_ft_activation.publication_guard.verify"):
            publish_ft(self.root, baseline, "seal.json")
        update_commit = commit_sha(self.root)
        ptr = (self.root / dual.SEGMENT / "CURRENT.json").read_bytes()
        rollback_local(self.root, expected_current_sha256=store.digest(ptr))
        stage_reachable(self.root)
        git(self.root, "commit", "-qm", "rollback prepared")
        other = Path(self.temp.name) / "other-rollback-writer"
        subprocess.run(["git", "clone", "-q", "--branch", "main",
                        str(bare), str(other)], check=True)
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.invalid")
        (other / "unrelated").write_text("concurrent change\\n")
        git(other, "add", "unrelated")
        git(other, "commit", "-qm", "concurrent remote update")
        git(other, "push", "-q", "origin", "main")
        remote_winner = remote_sha(self.root)
        with self.assertRaisesRegex(CutoverBlocked, "remote conflict"):
            publish_rollback(self.root, update_commit)
        self.assertEqual(remote_sha(self.root), remote_winner)

    def test_competing_remote_writer_blocks_rebase_and_push(self):
        bare, baseline = self.prepare_git()
        self.update_git()
        clone = Path(self.temp.name) / "other"
        subprocess.run(["git", "clone", "-q", "--branch", "main",
                        str(bare), str(clone)], check=True)
        git(clone, "config", "user.email", "other@example.invalid")
        git(clone, "config", "user.name", "Other")
        (clone / "unrelated").write_text("winner\n")
        git(clone, "add", "unrelated")
        git(clone, "commit", "-qm", "concurrent winner")
        git(clone, "push", "-q", "origin", "main")
        remote_winner = remote_sha(self.root)
        with patch("scripts.lab_discovery_ft_activation.publication_guard.verify"):
            with self.assertRaisesRegex(CutoverBlocked, "FT_REMOTE_CONFLICT"):
                publish_ft(self.root, baseline, "seal.json")
        self.assertEqual(remote_sha(self.root), remote_winner)
        self.assertNotEqual(commit_sha(self.root), remote_winner)


if __name__ == "__main__":
    unittest.main()
