import copy,json,unittest
from pathlib import Path
from h1lab.lab_discovery_partition_trial import partition,restore,encode

class PartitionTrialTests(unittest.TestCase):
    def test_real_roundtrip_preserves_every_field_without_mutating_source(self):
        p=Path(__file__).resolve().parents[1]/'data/lab/discovery-state.json'
        original=p.read_bytes();state=json.loads(original)
        manifest,shards=partition(state)
        self.assertEqual(restore(manifest,shards),state)
        self.assertEqual(p.read_bytes(),original)
        self.assertLessEqual(max(map(len,shards.values())),256000)
        self.assertLessEqual(len(encode(manifest)),256000)

    def test_missing_or_corrupt_shard_fails_closed(self):
        state={'schema_version':1,'patterns':{'a':{'latest':7}}}
        manifest,shards=partition(state)
        with self.assertRaises(ValueError):restore(manifest,{})
        broken=copy.deepcopy(shards);broken[next(iter(broken))]+=b' '
        with self.assertRaises(ValueError):restore(manifest,broken)

    def test_oversized_pattern_is_not_silently_discarded(self):
        with self.assertRaises(ValueError):partition({'patterns':{'a':'x'*1000}},limit=100)
