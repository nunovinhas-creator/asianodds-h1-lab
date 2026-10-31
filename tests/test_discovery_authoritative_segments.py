"""Proof of immutable authoritative discovery shards growing beyond 2 MB."""
import tempfile
import unittest
from pathlib import Path
from h1lab import lab_discovery_dual_state as dual
from h1lab import lab_discovery_store as store

class AuthoritativeSegmentTests(unittest.TestCase):
    def test_real_repository_legacy_bytes_are_recovered_without_2mb_gate(self):
        real=Path(__file__).resolve().parents[1]/dual.STATE
        before=real.read_bytes()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            initial=store.publish(before,root/dual.SEGMENT,expected_generation=None)
            self.assertEqual(store.read(root/dual.SEGMENT)[1],before)
            self.assertEqual(dual.load(root,format="segmented"),store.decode(before))
            self.assertEqual(store.digest(before),initial["generation"])
        self.assertEqual(real.read_bytes(),before)

    def test_no_legacy_mirror_and_large_state(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            directory = root / dual.SEGMENT
            first = {"schema_version":1,"patterns":{"a":{"points":[1]}}}
            old = store.publish(store.encode(first),directory,expected_generation=None)
            self.assertEqual(dual.load(root,format="segmented"),first)
            huge={"schema_version":1,"patterns":{
                str(i):{"points":["x"*1000]} for i in range(2300)}}
            self.assertGreater(len(store.encode(huge)),2_000_000)
            changed=dual.write_segmented(root,huge,expected_generation=old["generation"])
            self.assertTrue(changed["changed"])
            self.assertEqual(dual.load(root,format="segmented"),huge)
            self.assertFalse((root/dual.STATE).exists())
            with self.assertRaises(ValueError):
                dual.write_segmented(root,first,expected_generation=old["generation"])
            ptr=(directory/"CURRENT.json").read_bytes()
            store.rollback(directory,expected_pointer_sha256=store.digest(ptr))
            self.assertEqual(dual.load(root,format="segmented"),first)

    def test_corruption_has_no_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            obj={"schema_version":1,"patterns":{"one":1}}
            gen=store.publish(store.encode(obj),root/dual.SEGMENT,expected_generation=None)
            shard=root/dual.SEGMENT/gen["generation"]/"state-0000.json"
            shard.write_text("broken")
            with self.assertRaises((ValueError,UnicodeDecodeError)):
                dual.load(root,format="segmented")

if __name__=="__main__":
    unittest.main()
