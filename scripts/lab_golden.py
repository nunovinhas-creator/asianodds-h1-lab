"""Reproducible, offline-capable Golden Set publication (never modifies H1)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from h1lab.golden import build

ROOT = Path(__file__).resolve().parents[1]


def main():
    candidates, report = build(ROOT)
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["source_commit"] = os.environ.get("LAB_SOURCE_SHA", "unknown")
    directory = ROOT / "docs" / "lab"
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in (("golden-candidates.json", candidates),
                        ("golden-report.json", report)):
        (directory / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    print("LAB_GOLDEN", report["status"], "candidates", report["candidate_count"],
          "paired_matches", report["two_review_agreements"],
          "v4_mismatches", report["v4_mismatch_cases"],
          "invalid_records", len(report["issues"]))


if __name__ == "__main__":
    main()
