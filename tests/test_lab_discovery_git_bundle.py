import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from h1lab import lab_discovery_store as store
from h1lab.lab_discovery_git_bundle import (
    PREFIX, MIRROR, seal, verify_against_seal,
)


class SegmentedGitBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="segmented-git-proof-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "offline@example.invalid")
        self.git("config", "user.name", "Offline test")
        self.store_dir = self.root / PREFIX
        self.raw1 = self.bytes_for(1)
        self.current = self.publish(self.raw1, expected=None)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL)

    @staticmethod
    def bytes_for(n):
        return (json.dumps({"schema_version": 1,
                            "patterns": {"one": {"latest": {"known": n},
                                                 "points": [{"at": n}]}},
                            "prospective_settled": {}, "latest_events": []},
                           sort_keys=True) + "\n").encode()

    def publish(self, raw, *, expected):
        mirror = self.root / MIRROR
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_bytes(raw)
        published = store.publish(raw, self.store_dir,
                                  expected_generation=expected)
        # Stage only immutable reachable objects, never WRITE.lock/temp files.
        names = [MIRROR, PREFIX + "CURRENT.json"]
        if (self.store_dir / "PREVIOUS.json").exists():
            names.append(PREFIX + "PREVIOUS.json")
        for generation in [published["generation"], expected]:
            if not generation:
                continue
            names.extend(
                p.relative_to(self.root).as_posix()
                for p in (self.store_dir / generation).iterdir()
                if p.is_file())
        self.git("add", "--", *sorted(set(names)))
        return published["generation"]

    def test_index_seal_then_head_commit_exact_parity(self):
        stage = seal(self.root)
        self.assertIn(MIRROR, stage["sha256"])
        self.assertIn(PREFIX + "CURRENT.json", stage["sha256"])
        self.assertIn(PREFIX + self.current + "/manifest.json", stage["sha256"])
        self.assertIn(PREFIX + self.current + "/legacy.json.gz", stage["sha256"])
        self.assertIsNone(stage["previous_generation"])
        self.git("commit", "-qm", "first complete snapshot")
        self.assertEqual(verify_against_seal(self.root, stage), stage)

    def test_second_generation_previous_reachable_and_cas(self):
        self.git("commit", "-qm", "first complete snapshot")
        old = self.current
        nxt = self.publish(self.bytes_for(2), expected=old)
        stage = seal(self.root)
        self.assertEqual(stage["current_generation"], nxt)
        self.assertEqual(stage["previous_generation"], old)
        self.assertIn(PREFIX + old + "/legacy.json.gz", stage["sha256"])
        self.git("commit", "-qm", "second complete snapshot")
        self.assertEqual(verify_against_seal(self.root, stage), stage)

    def test_missing_staged_shard_blocks_pointer_publication(self):
        path = next((self.store_dir / self.current).glob("state-*.json"))
        self.git("reset", "-q", "--", str(path.relative_to(self.root)))
        with self.assertRaisesRegex(ValueError, "Missing staged"):
            seal(self.root)

    def test_changed_mirror_or_segment_blocks_publication(self):
        original = seal(self.root)
        mirror = self.root / MIRROR
        mirror.write_bytes(self.bytes_for(3))
        self.git("add", MIRROR)
        with self.assertRaisesRegex(ValueError, "differs from legacy"):
            seal(self.root)
        mirror.write_bytes(self.raw1)
        self.git("add", MIRROR)
        part = next((self.store_dir / self.current).glob("state-*.json"))
        part.write_bytes(b"[]\n")
        self.git("add", str(part.relative_to(self.root)))
        with self.assertRaises(ValueError):
            seal(self.root)
        self.assertTrue(original["sha256"])

    def test_unreachable_or_lock_files_must_not_be_staged(self):
        extra = self.store_dir / "WRITE.lock"
        self.git("add", str(extra.relative_to(self.root)))
        with self.assertRaisesRegex(ValueError, "Unreachable or temporary"):
            seal(self.root)

    def test_symlinked_current_member_is_rejected(self):
        file = self.store_dir / "CURRENT.json"
        file.unlink()
        file.symlink_to("/etc/passwd")
        self.git("add", str(file.relative_to(self.root)))
        with self.assertRaisesRegex(ValueError, "Symlink"):
            seal(self.root)

    def test_head_rebase_or_post_seal_mutation_is_rejected(self):
        stage = seal(self.root)
        self.git("commit", "-qm", "first complete snapshot")
        self.assertEqual(verify_against_seal(self.root, stage), stage)
        self.publish(self.bytes_for(2), expected=self.current)
        self.git("commit", "-qm", "concurrent other generation")
        with self.assertRaisesRegex(ValueError, "changed after commit or rebase"):
            verify_against_seal(self.root, stage)

    def test_missing_stage_or_bad_ref_fails_closed(self):
        with self.assertRaises(ValueError):
            seal(self.root, ref="origin/main")
        self.git("reset", "-q", "--", MIRROR)
        with self.assertRaisesRegex(ValueError, "Missing durable legacy mirror"):
            seal(self.root)


if __name__ == "__main__":
    unittest.main()
