"""Create and verify append-only V6 FT audit after the existing LAB reconciliation.

No providers or result fetches are invoked. FT ledger remains authoritative.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_ft_events import synchronize, read_events, validate_against_ledger

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args(argv)
    ledger_path = args.root / "data/lab/ft-ledger.json"
    report_path = args.root / "docs/lab/v6-ft-evidence.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    view, new = synchronize(args.root, ledger, datetime.now(timezone.utc),
                            verify_only=args.verify_only)
    if args.verify_only:
        if not report_path.exists() or json.loads(report_path.read_text(encoding="utf-8")) != view:
            raise SystemExit("V6_FT_EVIDENCE_VIEW_MISMATCH")
        print("V6_FT_EVIDENCE_REPLAY_PASS", view["matches"], view["events_total"])
        return view
    report_path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not report_path.exists() or report_path.read_text(encoding="utf-8") != txt:
        report_path.write_text(txt, encoding="utf-8")
    validate_against_ledger(read_events(args.root), ledger)
    print("V6_FT_EVIDENCE", "new_events", new, "matches", view["matches"],
          "finals", view["confirmed_scores"], "quarantined", view["quarantined_count"])
    return view


if __name__ == "__main__":
    main()
