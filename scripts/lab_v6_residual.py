"""Publish all V5 hypothesis effects in the market-relative V6 reference frame."""
from __future__ import annotations

import json
from pathlib import Path
from h1lab.v6_residual import run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/lab/v6-residual-research.json"


def main(root=ROOT):
    root = Path(root)
    report = run(root)
    path = root / "docs/lab/v6-residual-research.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != body:
        path.write_text(body, encoding="utf-8")
    print("V6_RESIDUAL", "hypotheses", len(report["all_hypotheses"]),
          "ft_clean", report["scope"]["ft_with_usable_price"],
          "historical_exploratory_only", True)
    return report


if __name__ == "__main__":
    main()
