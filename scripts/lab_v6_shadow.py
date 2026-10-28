"""V6 shadow audit after an H1 collector checkpoint: never sends messages."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_shadow import run, STATUS

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
    report, added = run(args.root, now)
    if report["status"] != STATUS:
        raise SystemExit("unexpected V6 status")
    target = args.root / "docs/lab/v6-shadow.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Report is derived and safely replaceable. Journal is append-only.
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
    if old:
        old.pop("generated_at", None)
        cmp = dict(report)
        cmp.pop("generated_at", None)
        if old == cmp:
            print("V6_SHADOW_UNCHANGED", "forecasts_added", added)
            return report
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print("V6_SHADOW", "forecasts_added", added,
          "oos_ft", report["comparisons"]["pattern_posthoc_original"]["n"],
          "state", report["hypothesis"]["state"])
    return report


if __name__ == "__main__":
    main()
