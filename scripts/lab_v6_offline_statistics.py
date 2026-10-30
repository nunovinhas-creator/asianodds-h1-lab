"""Generate a replayable research-only report, zero network/AI calls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from h1lab.v6_offline_statistics import build


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--now')
    p.add_argument('--output',type=Path)
    a=p.parse_args(argv)
    now=datetime.fromisoformat(a.now.replace('Z','+00:00')) if a.now else datetime.now(timezone.utc)
    report=build(a.root,now=now)
    target=a.output or a.root/'docs/lab/llm-statistics.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix('.tmp')
    tmp.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=1,allow_nan=False)+'\n')
    tmp.replace(target)
    print(json.dumps({'hypotheses':len(report['hypotheses']),'coverage':report['coverage'], 'llm_calls':0}))
    return report

if __name__=='__main__':main()
