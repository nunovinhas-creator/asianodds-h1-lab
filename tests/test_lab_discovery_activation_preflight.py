import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.lab_discovery_activation_preflight import (
    ROOT, STATE, MAX_STATE_BYTES, preflight, consumers,
)


class SegmentationActivationPreflightTests(unittest.TestCase):
    def test_real_state_byte_exact_semantics_publication_and_stress(self):
        source = ROOT / STATE
        before = source.read_bytes()
        baseline_hash = hashlib.sha256(before).hexdigest()
        result = preflight(ROOT, stress=True)
        self.assertEqual(result["status"], "PASS_OFFLINE_NOT_ACTIVATED")
        self.assertFalse(result["production_migration_enabled"])
        self.assertEqual(result["legacy_bytes"], len(before))
        self.assertEqual(result["legacy_sha256"], baseline_hash)
        self.assertEqual(result["legacy_margin_bytes"], MAX_STATE_BYTES-len(before))
        self.assertTrue(result["producer_output_parity"])
        self.assertTrue(result["byte_exact_reconstruction"])
        self.assertTrue(result["rollback_exact"])
        self.assertGreater(result["public_patterns"], 0)
        self.assertGreater(result["public_pages"], 0)
        self.assertGreater(result["stress_bytes"], MAX_STATE_BYTES+100000)
        self.assertEqual(source.read_bytes(), before)
        segmented = ROOT / "data/lab/discovery-segmented"
        if segmented.exists():
            from h1lab import lab_discovery_dual_state as dual
            from h1lab import lab_discovery_store as store
            self.assertTrue((segmented / "CURRENT.json").is_file())
            self.assertEqual(store.read(segmented)[0],
                             dual.load(ROOT, format="segmented"))
        else:
            self.assertFalse(segmented.exists())

    def test_inventory_lists_real_consumers_but_cannot_claim_completeness(self):
        entries = consumers(ROOT)
        self.assertIn("scripts/lab_discoveries.py", entries)
        self.assertIn(".github/workflows/lab-ft-results.yml", entries)
        self.assertEqual(entries, sorted(set(entries)))
        result = preflight(ROOT, stress=False)
        self.assertEqual(result["consumer_inventory"], entries)
        self.assertEqual(result["consumer_inventory_completeness"],
                         "STATIC_HEURISTIC_REQUIRES_REVIEW")

    def test_missing_or_symlinked_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                preflight(root)
            source = root / STATE
            source.parent.mkdir(parents=True)
            source.symlink_to(ROOT / STATE)
            with self.assertRaises(ValueError):
                preflight(root)


if __name__ == "__main__":
    unittest.main()
