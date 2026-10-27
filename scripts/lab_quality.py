"""Build a small public data-quality aggregate; no raw channel content."""
import json
from pathlib import Path
from h1lab.market_v2 import summary

ROOT=Path(__file__).resolve().parents[1]
def main():
    state=json.loads((ROOT/"data/state.json").read_text(encoding="utf-8"))
    formats=[]
    for file in sorted((ROOT/"data/lab").glob("formats-????-??.jsonl")) if (ROOT/"data/lab").exists() else []:
        for line in file.read_text(encoding="utf-8").splitlines():
            try: formats.append(json.loads(line))
            except (ValueError,TypeError): continue
    report=summary(state.get("alerts",[]),formats)
    path=ROOT/"docs/lab/quality.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("LAB_QUALITY",report["alerts"],report["format_observations"])
if __name__=="__main__": main()
