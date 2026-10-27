"""Publish a descriptive repeated-match analysis into LAB only."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from h1lab.trajectory_research import generate

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = generate(ROOT)
    expected = os.environ.get("LAB_SOURCE_SHA")
    if expected and result.get("source_commit") != expected:
        raise ValueError(
            "Stale timeline: report commit differs from LAB_SOURCE_SHA; "
            "do not publish research based on an old chronology")
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = ROOT / "docs" / "lab" / "trajectory-research.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)+"\n",
                   encoding="utf-8")
    tmp.replace(out)
    s = result["scope"]
    p = result["match_level_patterns"]
    print("LAB_EMPIRICAL",result["status"],
          "matches",s["repeated_matches_analysed"],
          "messages",s["events_analysed"],
          "opposing_direction_matches",p["opposing_intra_alert_directions"]["matches"],
          "related_pairs",result["transitions"]["related_pairs"],
          "coverage",s["coverage"])
    return result


if __name__ == "__main__":
    main()
