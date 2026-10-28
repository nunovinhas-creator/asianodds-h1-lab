"""Record at most one immutable scientific-drift report per UTC ISO week.

Runs inside the EXISTING V4 audit job; no new Actions schedule or provider
calls. At first audit of a new week append a snapshot and refresh the public
read-only view. Repeat invocations skip without touching the historic week.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path

from h1lab.v6_shadow import canonical, utc
from h1lab.lab_archive import MAX_BYTES, monthly_paths, append_monthly
from h1lab.v6_weekly_monitor import build, digest, date_week, STATUS

ROOT=Path(__file__).resolve().parents[1]
ZERO="0"*64
PATH="data/lab/v6-weekly-snapshots.jsonl"
REPORT="docs/lab/v6-weekly-drift.json"
SCHEMA=1


def read_snapshots(root):
    """Replay the legacy file followed by any bounded month partitions."""
    root = Path(root)
    legacy = root / PATH
    paths = ([legacy] if legacy.is_file() else []) + monthly_paths(root, "v6-weekly-snapshots")
    out, prev, weeks = [], ZERO, set()
    for f in paths:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                raise ValueError("Empty V6 weekly snapshot")
            e=json.loads(line)
            week=e.get("monitor_week")
            if (e.get("schema_version")!=SCHEMA or week in weeks or
                    e.get("previous_sha256")!=prev or
                    e.get("sha256")!=digest({k:v for k,v in e.items() if k!="sha256"}) or
                    e.get("report_sha256")!=digest(e.get("report")) or
                    (e.get("report") or {}).get("monitor_week")!=week or
                    (e.get("report") or {}).get("status")!=STATUS):
                raise ValueError("V6 weekly journal chain or report invalid")
            weeks.add(week)
            prev=e["sha256"]
            out.append(e)
    return out


def projection(events):
    latest=events[-1]["report"] if events else None
    return {
        "schema_version":SCHEMA,
        "status":STATUS,
        "latest_monitor_week":latest["monitor_week"] if latest else None,
        "latest_snapshot_at":latest["as_of"] if latest else None,
        "snapshot_count":len(events),
        "last_sha256":events[-1]["sha256"] if events else ZERO,
        "latest":latest,
        "history":[{"week":e["monitor_week"],
                    "as_of":e["report"]["as_of"],
                    "overall":e["report"]["overall"],
                    "sha256":e["sha256"],
                    "quality_n":sum(x["quality"]["n"] for x in e["report"]["weeks"]),
                    "calibration_n":sum(x["calibration"]["n"] for x in e["report"]["weeks"])}
                   for e in events[-12:]],
        "method":"one snapshot per UTC ISO week; previous snapshots never revised",
    }


def run(root, now, *, verify_only=False):
    root=Path(root)
    if now.tzinfo is None:
        raise ValueError("Missing UTC time")
    week=date_week(now)
    events=read_snapshots(root)
    current=next((e for e in events if e["monitor_week"]==week),None)
    if verify_only:
        view=projection(events)
        p=root/REPORT
        if not p.exists() or json.loads(p.read_text(encoding="utf-8"))!=view:
            raise ValueError("V6 weekly published view does not match journal")
        return view,0
    if current is not None:
        # The monitoring data evolves all week. The snapshot stays frozen:
        # source hashes/provenance refer to the actual original execution.
        return projection(events),0
    if events and week < events[-1]["monitor_week"]:
        raise ValueError("Cannot backdate V6 weekly scientific monitor")
    report=build(root,now)
    if report["status"]!=STATUS or report["monitor_week"]!=week:
        raise ValueError("Inconsistent V6 drift report")
    payload={
        "schema_version":SCHEMA,"monitor_week":week,
        "report_sha256":digest(report),"report":report,
        "previous_sha256":events[-1]["sha256"] if events else ZERO,
    }
    payload["sha256"]=digest(payload)
    p=root/PATH
    p.parent.mkdir(parents=True,exist_ok=True)
    row = canonical(payload)+"\n"
    # Preserve the original legacy file untouched once its byte limit is near.
    # The first bounded monthly extension starts at the SAME previous SHA.
    if monthly_paths(root, "v6-weekly-snapshots") or (
            p.exists() and p.stat().st_size + len(row.encode("utf-8")) > MAX_BYTES):
        append_monthly(root, "v6-weekly-snapshots",
                       now.astimezone(timezone.utc).strftime("%Y-%m"), [row])
    elif len(row.encode("utf-8")) <= MAX_BYTES:
        with p.open("a",encoding="utf-8") as stream:
            stream.write(row)
    else:
        raise ValueError("Oversized weekly journal event")
    verified=read_snapshots(root)
    if verified[-1]["sha256"]!=payload["sha256"]:
        raise ValueError("V6 weekly journal write failed")
    view=projection(verified)
    output=root/REPORT
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(view,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    if json.loads(output.read_text(encoding="utf-8"))!=view:
        raise ValueError("Weekly projection failed")
    return view,1


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--verify-only",action="store_true")
    args=p.parse_args(argv)
    result,created=run(args.root,datetime.now(timezone.utc),verify_only=args.verify_only)
    print("V6_WEEKLY_MONITOR",result["latest_monitor_week"],
          "appended",created,"snapshots",result["snapshot_count"],
          "overall",result["latest"]["overall"] if result["latest"] else "NO_DATA")
    return result


if __name__=="__main__":
    main()
