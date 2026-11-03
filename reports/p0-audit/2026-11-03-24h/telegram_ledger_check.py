import json,subprocess,sys,collections
B,C=sys.argv[1],sys.argv[2]
def load(rev,f):
    r=subprocess.run(["git","show",f"{rev}:{f}"],capture_output=True,text=True)
    if r.returncode: return None
    d=json.loads(r.stdout); e=d.get('entries',d) if isinstance(d,dict) else d
    return e
for f in ["data/three-total-moves-notifications.json","data/two-up-total-notifications.json","data/e5-over25-notifications.json"]:
    revs=subprocess.run(["git","rev-list","--reverse","--first-parent",f"{B}..{C}","--",f],capture_output=True,text=True).stdout.split()
    prev=load(B,f); viol=0
    for r in revs:
        cur=load(r,f)
        if prev and cur is not None:
            if not isinstance(cur,dict): print("non-dict",f); break
            for k,v in prev.items():
                if k not in cur: viol+=1; print("REMOVED",f,r[:8],k)
                elif v.get('status')=='sent' and cur[k]!=v: viol+=1; print("MUTATED",f,r[:8],k)
        if cur is not None: prev=cur
    fin=load(C,f) or {}
    mids=[(v.get('message_id') or v.get('telegram_message_id')) for v in fin.values()]
    dupmid=[m for m,c in collections.Counter(mids).items() if m and c>1]
    print(f.split('/')[-1],"commits",len(revs),"violations",viol,"final",len(fin),"dup message_ids",dupmid[:5], "keys sample", list(fin.values())[0].keys() if fin else None)
