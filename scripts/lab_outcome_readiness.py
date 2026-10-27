"""Generate outcome coverage diagnostics from tracked data (LAB-only)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from h1lab.outcome_readiness import generate

ROOT = Path(__file__).resolve().parents[1]


def main() -> dict:
    timeline = json.loads((ROOT / "docs/lab/match-trajectories.json").read_text(encoding="utf-8"))
    csv_content = (ROOT / "data/results.csv").read_text(encoding="utf-8")
    audit = json.loads((ROOT / "data/result_audit.json").read_text(encoding="utf-8"))
    expected_sha = os.getenv("LAB_SOURCE_SHA")
    if expected_sha and timeline.get("source_commit") != expected_sha:
        raise ValueError("Refusing stale timeline: source SHA differs from LAB checkout")
    report = generate(timeline, csv_content, audit)
    path = ROOT / "docs/lab/outcome-readiness.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    print("LAB_OUTCOME_READINESS", report["status"],
          "repeated_games", report["scope"]["published_repeated_matches"],
          "FT_linked", report["repeated_match_outcomes"]["with_h1_final_record"])
    return report


if __name__ == "__main__":
    main()
