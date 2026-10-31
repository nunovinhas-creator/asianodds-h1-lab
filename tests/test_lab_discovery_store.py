import copy
import json
import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from h1lab import lab_discovery_store as store
from h1lab.lab_discovery_partition_trial import partition as old_partition


def race(directory, expected, n, result):
    try:
        store.publish(raw(n), directory, expected_generation=expected)
        result.put('won')
    except ValueError: result.put('stale')


def raw(n):
    return (json.dumps({'schema_version': 1, 'patterns': {'one': {'points': list(range(n))}},
                       'prospective_settled': {}, 'latest_events': [], 'n': n}, indent=2)+'\n').encode()


class DiscoveryStoreTests(unittest.TestCase):
    def test_byte_exact_real_state_reader_and_writer_compatibility(self):
        from h1lab.discovery_timeline import build
        from scripts.lab_discoveries import bounded_public, serialize, MAX_PUBLIC_BYTES, PUBLIC
        root=Path(__file__).resolve().parents[1]
        legacy=(root/'data/lab/discovery-state.json').read_bytes()
        with tempfile.TemporaryDirectory() as d:
            first=store.publish(legacy,d,expected_generation=None)
            state, recovered=store.read(d)
            self.assertEqual(recovered,legacy)
            self.assertEqual(state,json.loads(legacy))
            args=[json.loads((root/p).read_text()) for p in ('docs/lab/pattern-research.json',
                    'data/lab/pattern-watch-first-seen.json','data/lab/ft-ledger.json')]
            a=build(*args,json.loads(legacy));b=build(*args,state)
            self.assertEqual(a,b)
            public=bounded_public(a[1]);serialize(public,MAX_PUBLIC_BYTES,PUBLIC)
            next_raw=store.encode(a[0])
            second=store.publish(next_raw,d,expected_generation=first['generation'])
            self.assertEqual(store.read(d)[0],a[0])
            self.assertGreater(second['shards'],1)

    def test_reproduces_trial_metadata_ceiling_and_shards_all_history(self):
        state={'patterns':{},'prospective_settled':{str(i):{'result':i,'text':'x'*800} for i in range(500)},
               'latest_events':[{'x':i} for i in range(900)],'schema_version':1}
        with self.assertRaises(ValueError):old_partition(state)
        manifest,blobs=store.partition(state)
        self.assertEqual(store.restore(manifest,blobs),state)
        self.assertTrue(all(len(b)<=store.SHARD_LIMIT for b in blobs.values()))
        self.assertGreater(len(blobs),1)

    def test_two_process_writers_cannot_lose_an_update(self):
        with tempfile.TemporaryDirectory() as d:
            a=store.publish(raw(1),d,expected_generation=None)
            ctx=multiprocessing.get_context('fork');q=ctx.Queue()
            ps=[ctx.Process(target=race,args=(d,a['generation'],n,q)) for n in (2,3)]
            for p in ps:p.start()
            for p in ps:p.join(10);self.assertEqual(p.exitcode,0)
            self.assertEqual(sorted(q.get(timeout=2) for _ in ps),['stale','won'])
            self.assertIn(store.read(d)[1],(raw(2),raw(3)))
            q.close();q.join_thread()

    def test_readers_see_only_complete_generations_during_write(self):
        with tempfile.TemporaryDirectory() as d:
            a=store.publish(raw(1),d,expected_generation=None);observed=[];errors=[]
            stop=threading.Event();ready=threading.Event()
            def reader():
                ready.set()
                while not stop.is_set():
                    try:observed.append(store.read(d)[1])
                    except Exception as e:errors.append(e)
            thread=threading.Thread(target=reader);thread.start();ready.wait(2)
            try:store.publish(raw(2),d,expected_generation=a['generation'])
            finally:stop.set();thread.join(3)
            self.assertFalse(errors);self.assertTrue(observed)
            self.assertTrue(all(x in (raw(1),raw(2)) for x in observed))

    def test_stale_writer_crash_and_idempotent_resume(self):
        with tempfile.TemporaryDirectory() as d:
            a=store.publish(raw(1),d,expected_generation=None)
            with self.assertRaises(ValueError):store.publish(raw(2),d,expected_generation=None)
            def crash(stage):raise OSError('interruption')
            with self.assertRaises(OSError):store.publish(raw(2),d,expected_generation=a['generation'],crash_hook=crash)
            self.assertEqual(store.read(d)[1],raw(1))
            b=store.publish(raw(2),d,expected_generation=a['generation'])
            self.assertFalse(store.publish(raw(2),d,expected_generation=b['generation'])['changed'])

    def test_partial_write_and_pointer_failure_do_not_publish_partial_state(self):
        for stage in ('shard','pointer'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as d:
                a=store.publish(raw(1),d,expected_generation=None)
                real_new,real_replace=store._new,store.os.replace
                def new(path,b):
                    if path.name.startswith('state-'):
                        real_new(path,b[:2]);raise OSError('disk full')
                    return real_new(path,b)
                def replace(src,dst):
                    if Path(dst).name=='CURRENT.json':raise OSError('pointer failed')
                    return real_replace(src,dst)
                target='_new' if stage=='shard' else 'os.replace'
                with patch.object(store,'_new',side_effect=new) if stage=='shard' else patch.object(store.os,'replace',side_effect=replace):
                    with self.assertRaises(OSError):store.publish(raw(2),d,expected_generation=a['generation'])
                self.assertEqual(store.read(d)[1],raw(1))

    def test_corruption_is_visible_and_explicit_rollback_has_own_cas(self):
        for member in ('state-0000.json','manifest.json','legacy.json.gz'):
            with self.subTest(member=member),tempfile.TemporaryDirectory() as d:
                a=store.publish(raw(1),d,expected_generation=None)
                b=store.publish(raw(2),d,expected_generation=a['generation'])
                (Path(d)/b['generation']/member).write_bytes(b'corrupt')
                with self.assertRaises((ValueError,OSError,EOFError)):store.read(d)
                pointer=(Path(d)/'CURRENT.json').read_bytes()
                with self.assertRaises(ValueError):store.rollback(d,expected_pointer_sha256='0'*64)
                store.rollback(d,expected_pointer_sha256=store.digest(pointer))
                self.assertEqual(store.read(d)[1],raw(1))
                self.assertTrue((Path(d)/('before-rollback-'+store.digest(pointer)+'.json')).exists())

    def test_corrupt_previous_is_never_used_as_silent_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            a=store.publish(raw(1),d,expected_generation=None)
            b=store.publish(raw(2),d,expected_generation=a['generation'])
            (Path(d)/a['generation']/'state-0000.json').unlink()
            pointer=(Path(d)/'CURRENT.json').read_bytes()
            with self.assertRaises(ValueError):store.rollback(d,expected_pointer_sha256=store.digest(pointer))
            self.assertEqual(store.read(d)[1],raw(2))

    def test_duplicate_or_nonfinite_json_unsafe_paths_and_oversized_entries_reject(self):
        for data in (b'{"patterns":{},"patterns":{}}',b'{"n":NaN}',store.encode({'large':'x'*store.SHARD_LIMIT})):
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):store.publish(data,d,expected_generation=None)
        state={'patterns':{'one':1}}
        m,b=store.partition(state);m=copy.deepcopy(m);m['parts'][0]['name']='../escape.json'
        with tempfile.TemporaryDirectory() as d:
            a=store.publish(raw(1),d,expected_generation=None)
            member=Path(d)/a['generation']/'state-0000.json';member.unlink();member.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):store.read(d)

    def test_explicit_legacy_recovery_is_exclusive_and_byte_exact(self):
        with tempfile.TemporaryDirectory() as d:
            store.publish(raw(1),d,expected_generation=None);target=Path(d)/'recovered.json'
            store.recover_legacy(d,target);self.assertEqual(target.read_bytes(),raw(1))
            with self.assertRaises(FileExistsError):store.recover_legacy(d,target)
