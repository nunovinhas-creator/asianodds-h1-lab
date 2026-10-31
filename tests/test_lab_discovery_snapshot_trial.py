import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from h1lab.lab_discovery_snapshot_trial import publish_trial,read_snapshot,rollback_trial,recover_legacy_file
from scripts.lab_discovery_migration_trial import safe_trial_path,ROOT


class SegmentedSnapshotTrialTests(unittest.TestCase):
    def test_partial_shard_write_failure_preserves_current_and_source(self):
        import h1lab.lab_discovery_snapshot_trial as trial
        with tempfile.TemporaryDirectory() as d:
            source=self.raw(1);publish_trial(source,d)
            pointer=(Path(d)/'CURRENT.json').read_bytes()
            real_write=trial._write_new
            def fail(path,raw):
                if path.name.startswith('patterns-'):
                    real_write(path,raw[:2]);raise OSError('simulated disk full')
                real_write(path,raw)
            with patch.object(trial,'_write_new',side_effect=fail):
                with self.assertRaises(OSError):publish_trial(self.raw(2),d)
            self.assertEqual((Path(d)/'CURRENT.json').read_bytes(),pointer)
            self.assertEqual(read_snapshot(d)[1],source)

    def test_pointer_replace_failure_is_recoverable_without_partial_visibility(self):
        import h1lab.lab_discovery_snapshot_trial as trial
        with tempfile.TemporaryDirectory() as d:
            publish_trial(self.raw(1),d);real_replace=trial.os.replace
            def fail(source,destination):
                if Path(destination).name=='CURRENT.json':raise OSError('simulated pointer write failure')
                return real_replace(source,destination)
            with patch.object(trial.os,'replace',side_effect=fail):
                with self.assertRaises(OSError):publish_trial(self.raw(2),d)
            self.assertEqual(read_snapshot(d)[1],self.raw(1))
            publish_trial(self.raw(2),d);self.assertEqual(read_snapshot(d)[1],self.raw(2))

    def test_corrupt_compressed_legacy_is_not_hidden_by_valid_shards(self):
        with tempfile.TemporaryDirectory() as d:
            publish_trial(self.raw(1),d);r=publish_trial(self.raw(2),d)
            (Path(d)/r['generation']/'legacy.json.gz').write_bytes(b'invalid gzip')
            with self.assertRaises((ValueError,OSError,EOFError)):read_snapshot(d)
            rollback_trial(d);self.assertEqual(read_snapshot(d)[1],self.raw(1))

    def test_corrupt_previous_cannot_replace_healthy_current(self):
        with tempfile.TemporaryDirectory() as d:
            first=publish_trial(self.raw(1),d);publish_trial(self.raw(2),d)
            (Path(d)/first['generation']/'patterns-0000.json').write_bytes(b'{}')
            pointer=(Path(d)/'CURRENT.json').read_bytes()
            with self.assertRaises(ValueError):rollback_trial(d)
            self.assertEqual((Path(d)/'CURRENT.json').read_bytes(),pointer)
            self.assertEqual(read_snapshot(d)[1],self.raw(2))

    def state(self,n=1):return {'schema_version':1,'patterns':{str(i):{'history':[i]} for i in range(n)}}
    def raw(self,n=1):return (json.dumps(self.state(n),indent=2)+'\n').encode()

    def test_exact_legacy_bytes_and_semantics_survive_real_state_roundtrip(self):
        raw=(ROOT/'data/lab/discovery-state.json').read_bytes()
        with tempfile.TemporaryDirectory() as d:
            r=publish_trial(raw,d);state,legacy=read_snapshot(d)
            self.assertEqual(legacy,raw);self.assertEqual(state,json.loads(raw))
            self.assertGreater(r['shards'],1)

    def test_append_snapshot_and_verified_rollback_preserve_both_generations(self):
        with tempfile.TemporaryDirectory() as d:
            a=publish_trial(self.raw(1),d);b=publish_trial(self.raw(2),d)
            self.assertEqual(read_snapshot(d)[1],self.raw(2))
            rollback_trial(d);self.assertEqual(read_snapshot(d)[1],self.raw(1))
            self.assertTrue((Path(d)/a['generation']).is_dir())
            self.assertTrue((Path(d)/b['generation']).is_dir())

    def test_crash_before_pointer_is_invisible_and_resume_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            publish_trial(self.raw(1),d)
            old=(Path(d)/'CURRENT.json').read_bytes()
            def crash(stage):raise OSError('simulated interruption')
            with self.assertRaises(OSError):publish_trial(self.raw(2),d,crash_hook=crash)
            self.assertEqual((Path(d)/'CURRENT.json').read_bytes(),old)
            self.assertEqual(read_snapshot(d)[1],self.raw(1))
            self.assertTrue(publish_trial(self.raw(2),d)['changed'])
            self.assertFalse(publish_trial(self.raw(2),d)['changed'])

    def test_corrupt_or_missing_member_fails_without_silent_old_generation_fallback(self):
        for missing in (False,True):
            with tempfile.TemporaryDirectory() as d:
                publish_trial(self.raw(1),d);r=publish_trial(self.raw(2),d)
                shard=Path(d)/r['generation']/'patterns-0000.json'
                if missing:shard.unlink()
                else:shard.write_bytes(b'{}')
                pointer=(Path(d)/'CURRENT.json').read_bytes()
                with self.assertRaises(ValueError):read_snapshot(d)
                self.assertEqual((Path(d)/'CURRENT.json').read_bytes(),pointer)

    def test_manifest_tamper_and_duplicate_json_keys_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            r=publish_trial(self.raw(),d)
            (Path(d)/r['generation']/'manifest.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):read_snapshot(d)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):publish_trial(b'{"patterns":{},"patterns":{}}',d)

    def test_explicit_rollback_recovers_verified_previous_after_current_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            publish_trial(self.raw(1),d);r=publish_trial(self.raw(2),d)
            (Path(d)/r['generation']/'patterns-0000.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):read_snapshot(d)
            rollback_trial(d);self.assertEqual(read_snapshot(d)[1],self.raw(1))

    def test_recovered_legacy_file_is_atomic_exclusive_and_byte_exact(self):
        with tempfile.TemporaryDirectory() as d:
            publish_trial(self.raw(),d);target=Path(d)/'recovered.json'
            recover_legacy_file(d,target);self.assertEqual(target.read_bytes(),self.raw())
            with self.assertRaises(FileExistsError):recover_legacy_file(d,target)
            self.assertEqual(target.read_bytes(),self.raw())

    def test_symlink_generation_and_productive_cli_targets_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            r=publish_trial(self.raw(),d);member=Path(d)/r['generation']/'patterns-0000.json'
            member.unlink();member.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):read_snapshot(d)
        for p in (ROOT,ROOT/'data/trial',ROOT/'docs/trial',Path('/')):
            with self.assertRaises(ValueError):safe_trial_path(p)
