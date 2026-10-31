import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from h1lab import lab_discovery_dual_state as adapter
from h1lab import lab_discovery_store as store
from scripts import lab_discoveries

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_INPUTS = (
    "docs/lab/pattern-research.json",
    "data/lab/pattern-watch-first-seen.json",
    "data/lab/ft-ledger.json",
)


def write_fixture(root):
    for name in (str(adapter.STATE), *SNAPSHOT_INPUTS):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)


class DualDiscoveryStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dual-discovery-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_fixture(self.root)

    def test_production_default_does_not_activate_segmented_store(self):
        result = lab_discoveries.main(["--root", str(self.root)])
        self.assertIn("patterns", result)
        self.assertFalse((self.root / adapter.SEGMENT / "CURRENT.json").exists())

    def test_bootstrap_byte_exact_and_idempotency_rejected(self):
        previous, raw = adapter.legacy_source(self.root)
        first = adapter.bootstrap(self.root)
        self.assertEqual(first["generation"], store.digest(raw))
        self.assertEqual(adapter.load(self.root, format="legacy"), previous)
        self.assertEqual(adapter.load(self.root, format="dual"), previous)
        self.assertEqual(store.read(self.root / adapter.SEGMENT)[1], raw)
        with self.assertRaisesRegex(ValueError, "Already bootstrapped"):
            adapter.bootstrap(self.root)

    def test_dual_producer_replays_real_inputs_and_retains_mirror(self):
        # Two independent roots compare dual and pre-existing productive output.
        with tempfile.TemporaryDirectory(prefix="legacy-comparator-") as td:
            reference = Path(td)
            write_fixture(reference)
            original = lab_discoveries.main(["--root", str(reference)])
            adapter.bootstrap(self.root)
            dual = lab_discoveries.main(
                ["--root", str(self.root), "--state-backend", "dual"])
            self.assertEqual(dual, original)
            self.assertEqual((self.root / adapter.STATE).read_bytes(),
                             (reference / adapter.STATE).read_bytes())
            self.assertEqual(adapter.load(self.root, format="dual"),
                             adapter.load(reference, format="legacy"))
            self.assertEqual(
                store.read(self.root / adapter.SEGMENT)[1],
                (self.root / adapter.STATE).read_bytes())

    def test_stale_writer_rejected_without_touching_mirror(self):
        adapter.bootstrap(self.root)
        before = (self.root / adapter.STATE).read_bytes()
        state = adapter.load(self.root, format="dual")
        state["__test_only__"] = 1
        with self.assertRaisesRegex(ValueError, "Stale dual discovery writer"):
            adapter.write_dual(self.root, state, expected_generation="0" * 64)
        self.assertEqual((self.root / adapter.STATE).read_bytes(), before)

    def test_missing_corrupt_or_divergent_segment_never_falls_back(self):
        with self.assertRaises(ValueError):
            adapter.load(self.root, format="dual")
        adapter.bootstrap(self.root)
        old = (self.root / adapter.STATE).read_bytes()
        (self.root / adapter.STATE).write_bytes(old + b" ")
        with self.assertRaisesRegex(ValueError, "mirror/segment mismatch"):
            adapter.load(self.root, format="dual")
        (self.root / adapter.STATE).write_bytes(old)
        (self.root / adapter.SEGMENT / "CURRENT.json").write_bytes(b'{}')
        with self.assertRaises(ValueError):
            adapter.load(self.root, format="dual")

    def test_write_dual_changes_generation_and_preserves_previous(self):
        first = adapter.bootstrap(self.root)
        before = (self.root / adapter.STATE).read_bytes()
        next_state = copy.deepcopy(adapter.load(self.root, format="dual"))
        next_state["__test_only__"] = {"count": 1}
        response = adapter.write_dual(
            self.root, next_state, expected_generation=first["generation"])
        self.assertTrue(response["changed"])
        self.assertEqual(adapter.load(self.root, format="dual"), next_state)
        old = self.root / adapter.SEGMENT / "PREVIOUS.json"
        self.assertEqual(store.decode(old.read_bytes())["generation"],
                         first["generation"])
        self.assertNotEqual((self.root / adapter.STATE).read_bytes(), before)
        current = self.root / adapter.SEGMENT / "CURRENT.json"
        pointer = current.read_bytes()
        store.rollback(self.root / adapter.SEGMENT,
                       expected_pointer_sha256=store.digest(pointer))
        # Rolling back the pointer without the Git mirror MUST fail closed.
        with self.assertRaisesRegex(ValueError, "mirror/segment mismatch"):
            adapter.load(self.root, format="dual")

    def test_mirror_cap_enforced_before_segmented_write(self):
        original = adapter.bootstrap(self.root)
        state = adapter.load(self.root, format="dual")
        state["__test_only__"] = "x" * 2_000_000
        with self.assertRaisesRegex(ValueError, "legacy 2 MB cap"):
            adapter.write_dual(
                self.root, state, expected_generation=original["generation"])
        self.assertEqual(adapter.current_generation(self.root),
                         original["generation"])

    def test_unknown_mode_symlinked_mirror_and_invalid_bootstrap_fail(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            adapter.load(self.root, format="unknown")
        mirror = self.root / adapter.STATE
        mirror.unlink()
        mirror.symlink_to(ROOT / adapter.STATE)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            adapter.bootstrap(self.root)


if __name__ == "__main__":
    unittest.main()
