"""Git index/commit sealing without the old 2 MB mirror."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from h1lab import lab_discovery_store as store
from h1lab import lab_discovery_dual_state as dual
from h1lab.lab_discovery_git_bundle import seal, verify_against_seal
from scripts.lab_discovery_authoritative_release import stage

def git(root,*args):
    subprocess.run(["git","-C",str(root),*args],check=True,
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)

class AuthoritativeGitTests(unittest.TestCase):
    def test_two_generations_and_stale_mirror_are_safe(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            git(root,"init","-q")
            git(root,"config","user.name","Automated Test")
            git(root,"config","user.email","tests@example.invalid")
            old={"schema_version":1,"patterns":{"a":{"points":[1]}}}
            directory=root/dual.SEGMENT
            initial=store.publish(store.encode(old),directory,expected_generation=None)
            mirror=root/dual.STATE
            mirror.parent.mkdir(parents=True,exist_ok=True)
            mirror.write_bytes(store.encode(old))
            git(root,"add","data/lab/discovery-state.json")
            proof=stage(root)["proof"]
            self.assertEqual(proof["backend"],"segmented")
            self.assertNotIn("data/lab/discovery-state.json",proof["sha256"])
            git(root,"commit","-qm","initial generation + stale mirror")
            self.assertEqual(seal(root,ref="HEAD",require_mirror=False),proof)
            new={"schema_version":1,"patterns":{"a":{"points":[1,2]}}}
            dual.write_segmented(root,new,expected_generation=initial["generation"])
            proof2=stage(root)["proof"]
            self.assertNotEqual(proof2["current_generation"],proof["current_generation"])
            git(root,"commit","-qm","next generation without mirror")
            verify_against_seal(root,proof2,ref="HEAD")
            self.assertEqual(mirror.read_bytes(),store.encode(old))
            self.assertEqual(dual.load(root,format="segmented"),new)
            newer={"schema_version":1,"patterns":{"a":{"points":[1,2,3]}}}
            current=proof2["current_generation"]
            dual.write_segmented(root,newer,expected_generation=current)
            proof3=stage(root)["proof"]
            # The first generation is no longer reachable after a second
            # publication and cannot grow the authoritative HEAD forever.
            git(root,"commit","-qm","third generation prunes old shards")
            verify_against_seal(root,proof3,ref="HEAD")
            manifest_names=set(proof3["sha256"])
            self.assertFalse(any(initial["generation"] in name
                                 for name in manifest_names))
            self.assertEqual(dual.load(root,format="segmented"),newer)
            with self.assertRaises(ValueError):
                seal(root,ref="HEAD",require_mirror=True)

    def test_missing_shard_prevents_staging(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);git(root,"init","-q")
            gen=store.publish(store.encode({"schema_version":1,"patterns":{"x":1}}),
                              root/dual.SEGMENT,expected_generation=None)
            (root/dual.SEGMENT/gen["generation"]/"state-0000.json").unlink()
            with self.assertRaises(ValueError):
                stage(root)

if __name__=="__main__":
    unittest.main()
