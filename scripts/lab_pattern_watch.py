"""Refresh V5 future-only movement watch without odds provider API requests."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.pattern_watch import build
from h1lab.timeline import read_sources, collect_timelines

ROOT = Path(__file__).resolve().parents[1]
OUT = "docs/lab/pattern-watch.json"
HISTORY = "data/lab/pattern-watch-first-seen.json"
MAX_BYTES = 180_000


def write_if_changed(path, data, *, timestamp_keys=()):
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("LAB_PATTERN_WATCH_TOO_LARGE " + path.name)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        new = json.loads(text)
        for key in timestamp_keys:
            old.pop(key, None)
            new.pop(key, None)
        if old == new:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--now", help="UTC ISO replay timestamp (tests only)")
    args = ap.parse_args(argv)
    root = args.root
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    alerts, v4, errors = read_sources(root)
    timelines, issues, excluded = collect_timelines(alerts, v4, source_errors=errors)
    prior_path = root / HISTORY
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else None
    report, history = build(timelines, now, prior)
    report["input_diagnostics"] = {"invalid_messages": len(excluded),
                                   "timeline_issues": len(issues)}
    history_changed = write_if_changed(prior_path, history)
    report_changed = write_if_changed(root / OUT, report, timestamp_keys=("generated_at",))
    print("V5_PROSPECTIVE_WATCH", "observed", report["summary"]["future_with_two_or_more_messages"],
          "original", report["summary"]["original_condition"],
          "strict", report["summary"]["strict_eligible"],
          "opposing", report["summary"]["contradictory_excluded_from_original"],
          "first_seen", len(history["entries"]),
          "watch_changed", report_changed, "history_changed", history_changed)
    return report


if __name__ == "__main__":
    main()
