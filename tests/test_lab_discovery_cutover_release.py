"""Offline release rehearsal against bare Git remotes; no production push."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from h1lab import lab_discovery_store as store
from h1lab.lab_discovery_git_bundle import PREFIX, seal as proof
from scripts.lab_discovery_cutover_release import (
    CutoverBlocked, commit_sha, prepare_bootstrap, publish_pinned_commit,
    remote_sha, stage_reachable,
)


class ControlledCutoverReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cutover-remote-cas-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "checkout"
        self.repo.mkdir()
        self.bare = self.base / "origin.git"
        self.cmd(self.base, "git", "init", "--bare", "-q", str(self.bare))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Offline")
        self.git("config", "user.email", "offline@example.invalid")
        path = self.repo / "data/lab/discovery-state.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(store.encode({"schema_version": 1,
                "patterns": {"test": {"points": [{"value": 1}]}},
                "prospective_settled": {}, "latest_events": []}))
        self.git("add", "--", "data/lab/discovery-state.json")
        self.git("commit", "-qm", "initial real legacy snapshot")
        self.git("remote", "add", "origin", str(self.bare))
        self.git("push", "-q", "-u", "origin", "main")
        self.base_sha = commit_sha(self.repo)

    def cmd(self, root, *args):
        return subprocess.check_output(list(args), cwd=root,
                                       stderr=subprocess.DEVNULL).decode().strip()

    def git(self, *args):
        return self.cmd(self.repo, "git", *args)

    def test_bootstrap_stage_commit_nonforce_push_and_readback(self):
        prepared = prepare_bootstrap(self.repo, expected_head=self.base_sha)
        self.assertEqual(prepared["status"], "STAGED_NOT_COMMITTED_NOT_PUBLISHED")
        self.assertGreater(prepared["members"], 3)
        self.assertEqual(prepared["expected_remote_head"], self.base_sha)
        self.assertEqual(prepared["proof"], proof(self.repo, ref="INDEX"))
        self.assertEqual(remote_sha(self.repo), self.base_sha)
        self.git("commit", "-qm", "authorized cutover")
        released = publish_pinned_commit(self.repo, expected_parent=self.base_sha)
        self.assertEqual(released["status"], "PUBLISHED_COMPLETE_BUNDLE")
        self.assertEqual(remote_sha(self.repo), released["commit"])
        self.assertEqual(proof(self.repo, ref="HEAD")["current_generation"],
                         prepared["generation"])
        self.assertEqual(self.git("show", "HEAD:data/lab/discovery-state.json").strip(),
                         (self.repo / "data/lab/discovery-state.json").read_text().strip())

    def test_no_preapproval_push_or_automatic_retry(self):
        prepare_bootstrap(self.repo, expected_head=self.base_sha)
        self.assertEqual(remote_sha(self.repo), self.base_sha)
        with self.assertRaises(CutoverBlocked):
            publish_pinned_commit(self.repo, expected_parent=self.base_sha)
        self.assertEqual(remote_sha(self.repo), self.base_sha)

    def test_remote_advanced_before_bootstrap_aborts_without_writing(self):
        self._concurrent_commit()
        with self.assertRaisesRegex(CutoverBlocked, "advanced"):
            prepare_bootstrap(self.repo, expected_head=self.base_sha)
        self.assertFalse((self.repo / PREFIX / "CURRENT.json").exists())

    def test_remote_conflict_after_prepare_aborts_no_force(self):
        prepare_bootstrap(self.repo, expected_head=self.base_sha)
        self.git("commit", "-qm", "staged cutover")
        concurrently = self._concurrent_commit()
        with self.assertRaisesRegex(CutoverBlocked, "Remote main advanced"):
            publish_pinned_commit(self.repo, expected_parent=self.base_sha)
        self.assertEqual(remote_sha(self.repo), concurrently)
        self.assertNotEqual(commit_sha(self.repo), concurrently)

    def _concurrent_commit(self):
        clone = self.base / "another-writer"
        self.cmd(self.base, "git", "clone", "-q", "--branch", "main",
                 str(self.bare), str(clone))
        self.cmd(clone, "git", "config", "user.name", "Concurrent")
        self.cmd(clone, "git", "config", "user.email", "concurrent@example.invalid")
        (clone / "other.txt").write_text("concurrent\n")
        self.cmd(clone, "git", "add", "other.txt")
        self.cmd(clone, "git", "commit", "-qm", "remote winner")
        self.cmd(clone, "git", "push", "-q", "origin", "main")
        return self.cmd(clone, "git", "rev-parse", "HEAD")

    def test_incomplete_index_blocks_stage_proof_and_publish(self):
        prepared = prepare_bootstrap(self.repo, expected_head=self.base_sha)
        generation = prepared["generation"]
        path = PREFIX + generation + "/state-0000.json"
        self.git("reset", "-q", "HEAD", "--", path)
        with self.assertRaises(ValueError):
            stage_reachable(self.repo) if (self.repo / path).exists() is False else proof(self.repo)
        self.git("commit", "-qm", "partial invalid generation")
        with self.assertRaises(ValueError):
            publish_pinned_commit(self.repo, expected_parent=self.base_sha)
        self.assertEqual(remote_sha(self.repo), self.base_sha)

    def test_unrelated_file_is_never_staged_into_release(self):
        (self.repo / "ft-ledger-fake.json").write_text('{"protected":true}\n')
        self.git("add", "--", "ft-ledger-fake.json")
        with self.assertRaisesRegex(CutoverBlocked, "Unrelated staged"):
            prepare_bootstrap(self.repo, expected_head=self.base_sha)
        self.assertEqual(remote_sha(self.repo), self.base_sha)

    def test_dirty_or_repeated_bootstrap_rejected(self):
        legacy = self.repo / "data/lab/discovery-state.json"
        legacy.write_bytes(legacy.read_bytes() + b" ")
        with self.assertRaisesRegex(CutoverBlocked, "Dirty legacy"):
            prepare_bootstrap(self.repo, expected_head=self.base_sha)
        self.git("checkout", "--", "data/lab/discovery-state.json")
        prepare_bootstrap(self.repo, expected_head=self.base_sha)
        with self.assertRaises(CutoverBlocked):
            prepare_bootstrap(self.repo, expected_head=self.base_sha)

    def test_release_rejects_unrelated_commit_and_invalid_parent(self):
        prepare_bootstrap(self.repo, expected_head=self.base_sha)
        (self.repo / "protected.txt").write_text("do not change H1\n")
        self.git("add", "protected.txt")
        self.git("commit", "-qm", "contains unrelated files")
        with self.assertRaisesRegex(CutoverBlocked, "unrelated"):
            publish_pinned_commit(self.repo, expected_parent=self.base_sha)
        with self.assertRaises(CutoverBlocked):
            publish_pinned_commit(self.repo, expected_parent="0" * 40)
        self.assertEqual(remote_sha(self.repo), self.base_sha)


if __name__ == "__main__":
    unittest.main()
