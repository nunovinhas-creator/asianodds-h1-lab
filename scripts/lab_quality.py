"""Build a small public data-quality aggregate; no raw channel content."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from h1lab.market_v2 import summary

ROOT=Path(__file__).resolve().parents[1]
def main():
    state=json.loads((ROOT/"data/state.json").read_text(encoding="utf-8"))
    formats=[]
    malformed=0
    for file in sorted((ROOT/"data/lab").glob("formats-????-??.jsonl")) if (ROOT/"data/lab").exists() else []:
        for line in file.read_text(encoding="utf-8",errors="replace").splitlines():
            if not line.strip(): continue
            try:
                value=json.loads(line)
                if not isinstance(value,dict): raise ValueError("not an object")
                formats.append(value)
                if "\ufffd" in line: malformed+=1
            except (ValueError,TypeError): malformed+=1
    report=summary(state.get("alerts",[]),formats)
    observations=[a.get("observed_at") for a in state.get("alerts",[]) if isinstance(a,dict) and isinstance(a.get("observed_at"),str)]
    report["period_start"]=min(observations) if observations else None
    report["period_end"]=max(observations) if observations else None
    report["source_commit"]=os.environ.get("LAB_SOURCE_SHA") or os.environ.get("GITHUB_SHA") or "unknown"
    report["generated_at"]=datetime.now(timezone.utc).isoformat()
    report["invalid_jsonl_lines"]=malformed
    path=ROOT/"docs/lab/quality.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("LAB_QUALITY",report["alerts"],report["format_observations"])
if __name__=="__main__": main()
