"""Explicit reopening of H1 `expired_unverified` fixtures (rollback / manual review).

Dry-run by default. Requires --reason and explicit --key values; refuses certified,
unknown or non-expired fixtures. Touches data/result_audit.json only - never results.csv,
ROI, FIFO or triples. Lengthen H1_RETRY_HORIZON first or the next sync expires them again.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.core import dump_json
from h1lab.results import load_results, reopen_expired

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--key", action="append", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    state = json.loads((args.root / "data/state.json").read_text(encoding="utf-8"))
    audit_path = args.root / "data/result_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    resolved = set(load_results(args.root / "data/results.csv"))
    reopened = reopen_expired(state["signals"], resolved, audit, args.key,
                              datetime.now(timezone.utc), reason=args.reason)
    print("H1_REOPEN", "APPLIED" if args.apply else "DRY_RUN", len(reopened), reopened)
    if args.apply:
        dump_json(audit_path, audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
