"""Publish a deterministic, strictly read-only V6 falsification report."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_falsification import run, TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args(argv)
    root = args.root
    output = root / "docs/lab/v6-falsification.json"
    # Only the generated_at/evaluation_clock is volatile; verification compares
    # current frozen source references, never inference from a future snapshot.
    now = datetime.now(timezone.utc)
    result = run(root, now)
    assert tuple(x["code"] for x in result["checks"]) == TEST_IDS
    assert result["overall"] == "INCONCLUSIVO"
    if args.verify_only:
        if not output.exists():
            raise SystemExit("V6_FALSIFICATION_MISSING")
        prev = json.loads(output.read_text(encoding="utf-8"))
        # A later run can see new source data; compare only the same dataset.
        # For deterministic reconstruction, carry forward recorded evaluation_clock.
        prev_now = datetime.fromisoformat(prev["evaluation_clock"].replace("Z", "+00:00"))
        replay = run(root, prev_now)
        if replay != prev:
            raise SystemExit("V6_FALSIFICATION_REPLAY_MISMATCH")
        print("V6_FALSIFICATION_REPLAY_OK")
        return prev
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if not output.exists() or output.read_text(encoding="utf-8") != serialized:
        output.write_text(serialized, encoding="utf-8")
    print("V6_FALSIFICATION", result["sample"],
          result["check_result_counts"], "no automatic promotion")
    return result


if __name__ == "__main__":
    main()
