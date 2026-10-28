"""Publish the V6.2 scientific radar as a bounded, replayable JSON projection."""
import argparse
import json
from pathlib import Path

from h1lab.v6_scientific_radar import build, MAX_ACTIVE, STATUS

ROOT=Path(__file__).resolve().parents[1]


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--verify-only",action="store_true")
    args=p.parse_args(argv)
    report=build(args.root)
    if report["status"]!=STATUS or report["active_hypotheses"]>MAX_ACTIVE:
        raise SystemExit("V6_RADAR_INVALID_REGISTRY")
    out=args.root/"docs/lab/v6-scientific-radar.json"
    if args.verify_only:
        if not out.is_file() or json.loads(out.read_text(encoding="utf-8"))!=report:
            raise SystemExit("V6_RADAR_REPLAY_MISMATCH")
        print("V6_RADAR_REPLAY_OK", report["active_hypotheses"],report["totals"]["unique_matches"])
        return report
    out.parent.mkdir(parents=True,exist_ok=True)
    rendered=json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if not out.is_file() or out.read_text(encoding="utf-8")!=rendered:
        out.write_text(rendered,encoding="utf-8")
    print("V6_SCIENCE_RADAR",report["active_hypotheses"],"hypotheses",
          report["totals"]["frozen_snapshots"],"forecasts",
          report["totals"]["unique_matches"],"matches")
    return report


if __name__=="__main__":
    main()
