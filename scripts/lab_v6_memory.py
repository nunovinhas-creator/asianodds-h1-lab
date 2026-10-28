"""Build and verify V6 scientific memory independently of the production H1."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_science_memory import synchronize, rebuild

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--verify-only", action="store_true", help="never append")
    args = p.parse_args(argv)
    root = args.root
    if args.verify_only:
        view = rebuild(root)
        existing = root / "docs/lab/v6-memory.json"
        if not existing.exists() or json.loads(existing.read_text(encoding="utf-8")) != view:
            raise SystemExit("V6_MEMORY_VIEW_MISMATCH")
        print("V6_MEMORY_REBUILD_PASS", view["stream_records"])
        return view
    report_path = root / "docs/lab/v6-shadow.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    view, appended = synchronize(root, datetime.now(timezone.utc), report=report)
    target = root / "docs/lab/v6-memory.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not target.exists() or target.read_text(encoding="utf-8") != serialized:
        target.write_text(serialized, encoding="utf-8")
    if rebuild(root) != view or json.loads(target.read_text(encoding="utf-8")) != view:
        raise SystemExit("V6_MEMORY_REBUILD_FAILED")
    print("V6_MEMORY_SHADOW", appended, "rebuild PASS")
    return view


if __name__ == "__main__":
    main()
