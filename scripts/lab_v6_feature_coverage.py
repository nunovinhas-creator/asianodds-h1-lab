"""Source-only report for V6F2 feature observations, not a prediction."""
import json
from collections import Counter
from pathlib import Path
from h1lab.v6_shadow import read_journal
from h1lab.v6_features_v2 import verify

ROOT=Path(__file__).resolve().parents[1]

def run(root=ROOT):
    rows=read_journal(root)
    latest={}
    cnt=Counter()
    for row in rows:
        v=row.get("feature_context_v2")
        if v is not None and not verify(v):
            raise ValueError("V6F2 feature checksum invalid")
        cnt["snapshots_v2" if v else "snapshots_legacy"]+=1
        latest[row["match_key"]]=row
    market=Counter()
    relation=Counter()
    competition=Counter()
    for row in latest.values():
        v=row.get("feature_context_v2")
        if v is None:
            continue
        for name,field in (("total","with_total"),("one_x_two","with_one_x_two"),
                           ("asian_handicap","with_asian_handicap")):
            if v["coverage"][field]:
                market[name]+=1
        if v["coverage"]["unobserved_inter_message_intervals"]:
            market["unobserved_gap"]+=1
        relation[v["total_1x2_relation"]]+=1
        competition[v["competition"]["category_heuristic"]]+=1
    return {"schema_version":1,"status":"V6F2_SHADOW_COVERAGE_NOT_VALIDATED",
            "total_records":len(rows),"unique_matches":len(latest),
            "snapshot_versions":dict(cnt),"market_presence":dict(market),
            "total_1x2_relation":dict(relation),"competition_heuristic":dict(competition),
            "limitations":["No historical backfill","Co-observed is not causal",
                           "Different message odds are not simultaneous",
                           "No prediction or betting validation"]}

def main():
    d=run()
    p=ROOT/"docs/lab/v6-feature-coverage.json"
    p.parent.mkdir(parents=True,exist_ok=True)
    s=json.dumps(d,sort_keys=True,ensure_ascii=False,indent=2)+"\n"
    if not p.exists() or p.read_text(encoding="utf-8")!=s:
        p.write_text(s,encoding="utf-8")
    print("V6F2_COVERAGE",d["snapshot_versions"])
    return d

if __name__=="__main__":
    main()
