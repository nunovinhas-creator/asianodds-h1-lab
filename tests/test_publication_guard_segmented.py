"""FT publication guard: staged segment proofs with fail-closed Git history.

Local Git repositories only. No productive FT provider calls or migrations.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab import lab_discovery_store as store
from h1lab.lab_discovery_git_bundle import PREFIX, MIRROR
from scripts import publication_guard as guard


def command(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


class SegmentPublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ft-segment-git-gate-")
        self.addCleanup(self.temp.cleanup)
        self.home = os.getcwd()
        self.addCleanup(os.chdir, self.home)
        os.chdir(self.temp.name)
        command("init", "-q")
        command("config", "user.email", "offline@example.invalid")
        command("config", "user.name", "Offline")
        self.root = Path(self.temp.name)
        self.legacy = self.root / MIRROR
        self.legacy.parent.mkdir(parents=True, exist_ok=True)
        self.legacy.write_bytes(self.raw(1))
        self.manifest = self.root / "proof.json"
        self.patcher = patch.dict(guard.REQUIRED, {"ft": (MIRROR,)})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    @staticmethod
    def raw(value):
        return (json.dumps({"schema_version": 1, "patterns": {
            "match": {"points": [{"known": value}],
                      "latest": {"hits": value}}},
            "prospective_settled": {}, "latest_events": []},
            sort_keys=True) + "\n").encode("utf-8")

    def stage_segment(self, *, with_pointer=True):
        state_root = self.root / PREFIX
        original = self.legacy.read_bytes()
        published = store.publish(original, state_root, expected_generation=None)
        files = [MIRROR]
        if with_pointer:
            files.append(PREFIX + "CURRENT.json")
        files.extend(p.relative_to(self.root).as_posix()
                     for p in (state_root / published["generation"]).iterdir()
                     if p.is_file())
        command("add", "--", *files)
        return published["generation"]

    def test_legacy_only_workflow_does_not_activate_segmentation(self):
        command("add", "--", MIRROR)
        guard.seal("ft", self.manifest)
        self.assertIsNone(json.loads(self.manifest.read_text())["segmented"])
        command("commit", "-qm", "legacy")
        guard.verify(self.manifest)
        self.assertFalse((self.root / PREFIX / "CURRENT.json").exists())

    def test_complete_index_and_commit_include_all_reachable_members(self):
        generation = self.stage_segment()
        guard.seal("ft", self.manifest)
        proof = json.loads(self.manifest.read_text())
        self.assertEqual(proof["segmented"]["current_generation"], generation)
        self.assertIn(PREFIX + generation + "/manifest.json", proof["sha256"])
        self.assertIn(PREFIX + generation + "/legacy.json.gz", proof["sha256"])
        self.assertIn(MIRROR, proof["sha256"])
        command("commit", "-qm", "complete")
        guard.verify(self.manifest)

    def test_missing_staged_current_or_shard_blocks_precommit(self):
        self.stage_segment(with_pointer=False)
        with self.assertRaisesRegex(ValueError, "CURRENT pointer"):
            guard.seal("ft", self.manifest)
        command("add", "--", PREFIX + "CURRENT.json")
        generation = store.decode(
            (self.root / PREFIX / "CURRENT.json").read_bytes())["generation"]
        member = PREFIX + generation + "/state-0000.json"
        command("reset", "-q", "--", member)
        with self.assertRaises(ValueError):
            guard.seal("ft", self.manifest)

    def test_corrupt_mirror_blocks_staged_publish(self):
        self.stage_segment()
        self.legacy.write_bytes(self.raw(2))
        command("add", "--", MIRROR)
        with self.assertRaisesRegex(ValueError, "differs from legacy"):
            guard.seal("ft", self.manifest)

    def test_untracked_or_malformed_staged_segment_never_silently_accepted(self):
        command("add", "--", MIRROR)
        bad = self.root / PREFIX / "orphan.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text('{"orphan":true}\n')
        command("add", "--", PREFIX + "orphan.json")
        with self.assertRaisesRegex(ValueError, "CURRENT pointer"):
            guard.seal("ft", self.manifest)

    def test_after_legacy_seal_unexpected_remote_segment_is_blocked(self):
        command("add", "--", MIRROR)
        guard.seal("ft", self.manifest)
        command("commit", "-qm", "legacy")
        guard.verify(self.manifest)
        self.stage_segment()
        command("commit", "-qm", "concurrent segmented generation")
        with self.assertRaisesRegex(ValueError, "Unsealed segmented generation"):
            guard.verify(self.manifest)

    def test_postseal_generation_tampering_or_rebase_fails_closed(self):
        generation = self.stage_segment()
        guard.seal("ft", self.manifest)
        command("commit", "-qm", "complete")
        guard.verify(self.manifest)
        self.legacy.write_bytes(self.raw(7))
        command("add", "--", MIRROR)
        command("commit", "-qm", "concurrent replacement")
        with self.assertRaises(ValueError):
            guard.verify(self.manifest)
        self.assertTrue((self.root / PREFIX / generation / "manifest.json").exists())

    def test_previous_generation_also_must_be_validated(self):
        first = self.stage_segment()
        guard.seal("ft", self.manifest)
        command("commit", "-qm", "baseline")
        self.legacy.write_bytes(self.raw(2))
        state_root = self.root / PREFIX
        second = store.publish(self.legacy.read_bytes(), state_root,
                               expected_generation=first)
        self.assertTrue(second["changed"])
        files = [MIRROR, PREFIX + "CURRENT.json", PREFIX + "PREVIOUS.json"]
        files.extend(p.relative_to(self.root).as_posix()
                     for p in (state_root / second["generation"]).iterdir() if p.is_file())
        command("add", "--", *files)
        guard.seal("ft", self.manifest)
        command("commit", "-qm", "second complete generation")
        guard.verify(self.manifest)
        # Overwrite reachable PREVIOUS shard and commit, preserving CURRENT.
        previous_file = PREFIX + first + "/state-0000.json"
        (self.root / previous_file).write_text('[]\n')
        command("add", "--", previous_file)
        with self.assertRaises(ValueError):
            guard.seal("ft", self.manifest)


if __name__ == "__main__":
    unittest.main()
