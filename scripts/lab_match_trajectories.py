"""Publish docs/lab/match-trajectories.json (read-only over H1 + V4 data).

Reads data/state.json and data/lab/markets-YYYY-MM.jsonl. Writes only the
explicit output path. Never modifies H1 state, picks, triples or results.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from h1lab.timeline import DEFAULT_MAX_TIMELINES, DEFAULT_NEAR_SECONDS, generate

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None,
                    help="default: <root>/docs/lab/match-trajectories.json; '-' for stdout")
    ap.add_argument("--near-seconds", type=int, default=DEFAULT_NEAR_SECONDS)
    ap.add_argument("--max-timelines", type=int, default=DEFAULT_MAX_TIMELINES)
    args = ap.parse_args(argv)
    report = generate(args.root, near_seconds=args.near_seconds,
                      max_timelines=args.max_timelines)
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["source_commit"] = os.environ.get("LAB_SOURCE_SHA", "unknown")
    text = json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if str(args.out) == "-":
        print(text, end="")
        return report
    out = args.out or args.root / "docs" / "lab" / "match-trajectories.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(out)
    s = report["summary"]
    print("LAB_TIMELINE", report["status"], "messages", s["messages"], "matches", s["matches"],
          "repeated", s["repeated_matches"], "related_pairs", s["related_message_pairs"],
          "episodes_upper_bound", s["movement_episodes_upper_bound"],
          "issues", report["issue_count"])
    return report


if __name__ == "__main__":
    main()
