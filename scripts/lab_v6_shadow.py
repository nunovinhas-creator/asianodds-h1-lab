"""V6 shadow audit after an H1 collector checkpoint: never sends messages."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_shadow import run, STATUS, snapshot_quality_rows
from h1lab.v6_hypotheses import ensure_registered
from h1lab.v6_readiness import measure
from h1lab.v6_shadow import read_journal
from h1lab.timeline import read_sources, collect_timelines

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--now", default=None, help="UTC replay timestamp, tests only")
    args = parser.parse_args(argv)
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise SystemExit("timezone required")
    registration, registered = ensure_registered(args.root, now)
    report, added = run(args.root, now)
    if report["status"] != STATUS:
        raise SystemExit("unexpected V6 status")
    # Source-eligible coverage is explicit; never claim Telegram delivery
    # time from observed_at alone. The 7/14-day windows start with real known_at.
    alerts, v4, errors = read_sources(args.root)
    timelines, _, _ = collect_timelines(alerts, v4, source_errors=errors)
    readiness = measure(timelines, read_journal(args.root), now)
    readiness_path = args.root / "docs/lab/v6-readiness.json"
    readiness_text = json.dumps(readiness, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if not readiness_path.exists() or readiness_path.read_text(encoding="utf-8") != readiness_text:
        readiness_path.parent.mkdir(parents=True, exist_ok=True)
        readiness_path.write_text(readiness_text, encoding="utf-8")
    # Every historical Telegram Total receives a per-event quality assessment,
    # explicitly NOT a retroactive or frozen forecast.
    quality_path = args.root / "docs/lab/v6-price-quality.json"
    qa_text = json.dumps(snapshot_quality_rows(args.root), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")) + "\n"
    if not quality_path.exists() or quality_path.read_text(encoding="utf-8") != qa_text:
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        quality_path.write_text(qa_text, encoding="utf-8")
    target = args.root / "docs/lab/v6-shadow.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Report is derived and safely replaceable. Journal is append-only.
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
    if old:
        old.pop("generated_at", None)
        cmp = dict(report)
        cmp.pop("generated_at", None)
        if old == cmp:
            print("V6_SHADOW_UNCHANGED", "forecasts_added", added, "hypothesis_registered", registered)
            return report
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print("V6_SHADOW", "forecasts_added", added,
          "oos_ft", report["comparisons"]["pattern_posthoc_original"]["n"],
          "state", report["hypothesis"]["state"])
    return report


if __name__ == "__main__":
    main()
