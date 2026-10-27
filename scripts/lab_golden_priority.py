"""Publish an explicitly unverified priority queue for manual Golden reviews."""
import json
from datetime import datetime, timezone
from pathlib import Path
from h1lab.golden_priority import generate

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = generate(ROOT, limit=10)
    output["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = ROOT / "docs" / "lab" / "golden-priority.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    print("GOLDEN_PRIORITY", output["status"],
          "observations", output["source_event_count"],
          "already_reviewed", output["reviewed_event_count"],
          "selected", len(output["priorities"]),
          "unobserved", output["not_observed_in_source"])
    for item in output["priorities"][:5]:
        print("GOLDEN_PRIORITY_CASE", item["event_id"], ",".join(item["new_coverage"]))


if __name__ == "__main__":
    main()
