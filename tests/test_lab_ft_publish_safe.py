"""No-network Git tests: concurrent H1/V4 commits must not starve valid FT."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab.lab_ft_final_guard import final_snapshot
from scripts import lab_ft_publish_safe as p

def git(root, *args):
    return subprocess.check_output(["git","-C",str(root),*args],
                                   stderr=subprocess.PIPE).decode().strip()

def write(root, name, content):
    path=root/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(content)
    return path

def ft(count):
    matches={"known":{"status":"FINAL","home":"A","away":"B",
                      "kickoff_utc":"2026-10-31T13:00:00+00:00",
                      "result":{"home_goals":1,"away_goals":0,"source":"fixture"}}}
    if count>1:
        matches["new"]={"status":"FINAL","home":"C","away":"D",
                        "kickoff_utc":"2026-10-31T14:00:00+00:00",
                        "result":{"home_goals":2,"away_goals":2,"source":"fixture"}}
    return json.dumps({"schema_version":1,"matches":matches},sort_keys=True)+"\n"

def state(home="A",extra=False):
    alerts=[{"match_key":"2026-10-31,a,b","home":home,"away":"B",
            "kickoff_utc":"2026-10-31T13:00:00+00:00",
            "event_id":"alert:1","competition":"Sample"}]
    if extra:
        alerts.append({"match_key":"2026-11-01,c,d","home":"C","away":"D",
                       "kickoff_utc":"2026-11-01T14:00:00+00:00",
                       "event_id":"alert:2","competition":"Sample"})
    return json.dumps({"alerts":alerts,"signals":[]},sort_keys=True)+"\n"

class GitFTPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home=Path(self.tmp.name)
        self.remote=home/"bare.git"
        subprocess.run(["git","init","--bare","-q",str(self.remote)],check=True)
        self.root=home/"ft"
        subprocess.run(["git","clone","-q",str(self.remote),str(self.root)],check=True)
        git(self.root,"config","user.name","test")
        git(self.root,"config","user.email","test@example.invalid")
        git(self.root,"checkout","-b","main")
        write(self.root,"data/state.json",state())
        write(self.root,"docs/data.json",'{"version":1}\n')
        write(self.root,"data/three-total-moves-notifications.json",
              json.dumps({"schema_version":1,"entries":{
                  "old":{"match_key":"2026-11-01,a,b",
                         "kickoff_utc":"2026-11-01T16:00:00Z",
                         "status":"sent"}}})+"\n")
        write(self.root,"data/lab/ft-ledger.json",ft(1))
        write(self.root,"docs/lab/ft-results.json",'{"final":1}\n')
        write(self.root,"data/lab/markets-2026-10.jsonl",'{"id":"market1"}\n')
        self.retired="data/lab/discovery-segmented/"+("a"*64)+"/state-0000.json"
        write(self.root,self.retired,'[]\n')
        git(self.root,"add",".")
        git(self.root,"commit","-qm","baseline")
        self.base=git(self.root,"rev-parse","HEAD")
        git(self.root,"push","-q","-u","origin","main")
        self.other=home/"collector"
        subprocess.run(["git","clone","-q","-b","main",str(self.remote),str(self.other)],check=True)
        git(self.other,"config","user.name","collector")
        git(self.other,"config","user.email","test@example.invalid")
        self.baseline=home/"baseline.json"
        raw=(self.root/"data/lab/ft-ledger.json").read_bytes()
        self.baseline.write_text(json.dumps(final_snapshot(raw)))
        write(self.root,"data/lab/ft-ledger.json",ft(2))
        write(self.root,"docs/lab/ft-results.json",'{"final":2}\n')
        git(self.root,"rm","-q",self.retired)
        git(self.root,"add",".")
        git(self.root,"commit","-qm","new FT from one provider")
        self.source=git(self.root,"rev-parse","HEAD")
        hashes={}
        for name in ("data/lab/ft-ledger.json","docs/lab/ft-results.json"):
            data=(self.root/name).read_bytes()
            hashes[name]=hashlib.sha256(data).hexdigest()
        self.manifest=home/"sealed.json"
        self.manifest.write_text(json.dumps({"pipeline":"ft","segmented":{"backend":"segmented"},"sha256":hashes}))

    def collector_commit(self, changes):
        for path,contents in changes.items():
            write(self.other,path,contents)
        git(self.other,"add",".")
        git(self.other,"commit","-qm","unrelated collector update")
        git(self.other,"push","-q","origin","main")

    def publish(self):
        original_hashes=json.loads(self.manifest.read_text())["sha256"]
        def sealed(_):
            for path,expected in original_hashes.items():
                content=p.git(self.root,"show","HEAD:"+path)
                self.assertEqual(hashlib.sha256(content).hexdigest(),expected)
        with patch.object(p.publication_guard,"verify",side_effect=sealed), \
             patch.object(p,"discovery_verify",return_value=None):
            return p.publish(self.root,base=self.base,manifest=self.manifest,
                             baseline=self.baseline,max_attempts=5)

    def test_h1_and_v4_updates_preserved_without_requery_or_ft_change(self):
        self.collector_commit({
            "docs/data.json":'{"version":2}\n',
            "data/state.json":state(extra=True),
            "data/lab/markets-2026-10.jsonl":'{"id":"market1"}\n{"id":"market2"}\n',
            "docs/lab/v4-audit.json":'{"updated":1}\n'})
        latest_before=git(self.other,"rev-parse","HEAD")
        result=self.publish()
        self.assertEqual(result,git(self.root,"rev-parse","HEAD"))
        self.assertEqual(git(self.root,"rev-parse","HEAD^"),latest_before)
        self.assertEqual(git(self.root,"show","HEAD:docs/data.json"),'{"version":2}')
        self.assertEqual(git(self.root,"show","HEAD:docs/lab/v4-audit.json"),'{"updated":1}')
        self.assertEqual(git(self.root,"show","HEAD:data/lab/ft-ledger.json"),ft(2).strip())
        self.assertNotIn(self.retired, git(self.root,"ls-tree","-r","--name-only","HEAD"))
        self.assertEqual(git(self.root,"rev-parse","HEAD"),git(self.root,"rev-parse","origin/main"))

    def test_concurrent_h1_telegram_receipts_are_preserved(self):
        newer={"schema_version":1,"entries":{
            "old":{"match_key":"2026-11-01,a,b",
                   "kickoff_utc":"2026-11-01T16:00:00Z","status":"withdrawn"},
            "new":{"match_key":"2026-11-01,c,d",
                   "kickoff_utc":"2026-11-01T18:00:00Z","status":"sent"},
        }}
        self.collector_commit({"data/three-total-moves-notifications.json":
                               json.dumps(newer)+"\n"})
        self.publish()
        saved=json.loads(git(self.root,"show","HEAD:data/three-total-moves-notifications.json"))
        self.assertEqual(saved,newer)
        self.assertEqual(json.loads(git(self.root,"show","HEAD:docs/lab/ft-results.json"))["final"],2)

    def test_concurrent_receipt_loss_or_identity_rewrite_blocks_ft_publish(self):
        wrong={"schema_version":1,"entries":{
            "old":{"match_key":"changed","kickoff_utc":"2026-11-01T16:00:00Z"}}}
        self.collector_commit({"data/three-total-moves-notifications.json":
                               json.dumps(wrong)+"\n"})
        with self.assertRaisesRegex(p.UnsafeFTPublication,"notification receipt invalid"):
            self.publish()

    def test_remote_ft_change_blocks_and_never_overwrites(self):
        self.collector_commit({"data/lab/ft-ledger.json":ft(1)+" "})
        remote_before=git(self.other,"rev-parse","HEAD")
        with self.assertRaisesRegex(p.UnsafeFTPublication,"Concurrent FT"):
            self.publish()
        git(self.root,"fetch","-q","origin","main")
        self.assertEqual(git(self.root,"rev-parse","origin/main"),remote_before)

    def test_deleting_other_output_is_not_whitelisted(self):
        git(self.root,"rm","-q","docs/data.json")
        git(self.root,"commit","-qm","unexpected deletion after FT commit")
        # A second commit violates the pinned-single-FT-commit invariant.
        with self.assertRaisesRegex(p.UnsafeFTPublication,"pinned checkout"):
            self.publish()

    def test_h1_existing_fixture_identity_mutation_blocks(self):
        self.collector_commit({"data/state.json":state(home="Changed")})
        with self.assertRaisesRegex(p.UnsafeFTPublication,"H1 fixture identity"):
            self.publish()

    def test_historical_v4_rewrite_blocks(self):
        self.collector_commit({"data/lab/markets-2026-10.jsonl":'{"id":"changed"}\n'})
        with self.assertRaisesRegex(p.UnsafeFTPublication,"journal rewritten"):
            self.publish()

    def test_unknown_or_code_change_blocks(self):
        self.collector_commit({"h1lab/lab_results.py":"# unexpected code\n"})
        with self.assertRaisesRegex(p.UnsafeFTPublication,"program changed"):
            self.publish()

    def test_two_nonfastforward_races_retry_without_provider_calls(self):
        self.collector_commit({"docs/data.json":'{"version":2}\n'})
        old_run=p.run
        sent=[False]
        def race(root,*args,**kwargs):
            if args and args[0]=="push" and not sent[0]:
                sent[0]=True
                git(self.other,"pull","-q","--ff-only","origin","main")
                write(self.other,"docs/data.json",'{"version":3}\n')
                git(self.other,"add",".")
                git(self.other,"commit","-qm","collector races FT push")
                git(self.other,"push","-q","origin","main")
            return old_run(root,*args,**kwargs)
        hashes=json.loads(self.manifest.read_text())["sha256"]
        def sealed(_):
            for path,expected in hashes.items():
                self.assertEqual(hashlib.sha256(p.git(self.root,"show","HEAD:"+path)).hexdigest(),
                                 expected)
        with patch.object(p,"run",side_effect=race), \
             patch.object(p.publication_guard,"verify",side_effect=sealed), \
             patch.object(p,"discovery_verify",return_value=None):
            result=p.publish(self.root,base=self.base,manifest=self.manifest,
                             baseline=self.baseline,max_attempts=4)
        self.assertTrue(sent[0])
        self.assertEqual(result,git(self.root,"rev-parse","HEAD"))
        self.assertEqual(git(self.root,"show","HEAD:docs/data.json"),'{"version":3}')

    def test_non_append_only_or_nonfinite_journal_refused(self):
        self.assertFalse(p.append_only_jsonl(b'{}\n',b'{"bad":1}'))
        self.assertFalse(p.append_only_jsonl(b'{}\n',b'{}\n{"unfinished":'))
        self.assertTrue(p.append_only_jsonl(b'{}\n',b'{}\n{"ok":1}\n'))

if __name__=="__main__":
    unittest.main()
