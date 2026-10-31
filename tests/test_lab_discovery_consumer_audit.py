"""Full tracked-source consumer inventory gate for the FT dual cutover."""
import unittest
from pathlib import Path

from scripts.lab_discovery_consumer_audit import inventory, verify

ROOT = Path(__file__).resolve().parents[1]


class DiscoveryConsumerAuditTests(unittest.TestCase):
    def test_all_tracked_code_readers_explicitly_reviewed(self):
        result = verify(ROOT)
        self.assertEqual(result["unknown_files"], [])
        self.assertGreaterEqual(result["known_runtime_references"], 6)
        self.assertEqual(result["classification"],
                         "STATIC_TRACKED_CODE_NOT_DYNAMIC_PROOF")

    def test_real_consumer_inventory_covers_workflow_and_mirror(self):
        found = inventory(ROOT)
        self.assertIn("scripts/lab_discoveries.py", found)
        self.assertIn("h1lab/lab_discovery_dual_state.py", found)
        self.assertIn("scripts/publication_guard.py", found)
        self.assertIn(".github/workflows/lab-ft-results.yml", found)


if __name__ == "__main__":
    unittest.main()
