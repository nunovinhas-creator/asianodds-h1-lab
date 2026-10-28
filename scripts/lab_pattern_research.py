"""LAB V5: build docs/lab/pattern-research.json (read-only over H1 + V4 + LAB FT).

Inputs (never modified): data/state.json, data/lab/markets-*.jsonl,
data/lab/ft-ledger.json, docs/lab/ft-results.json, data/results.csv.
Outputs: docs/lab/pattern-research.json, data/lab/pattern-registry.json
(append-only frozen hypotheses) and a feature cache outside git
(data/lab/.cache/, restored by actions/cache).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from h1lab.pattern_engine import run
from h1lab.timeline import collect_timelines, read_sources

ROOT = Path(__file__).resolve().parents[1]
MAX_REPORT_BYTES = 350_000


def _load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path, data, *, compare_without=(), compact=False):
    text = (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if compact
            else json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)) + "\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if old == text:
            return False
        if compare_without:
            try:
                a, b = json.loads(old), json.loads(text)
                for k in compare_without:
                    a.pop(k, None)
                    b.pop(k, None)
                if a == b:
                    return False
            except ValueError:
                pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--now", default=None, help="ISO UTC timestamp (tests/replays)")
    args = ap.parse_args(argv)
    root = args.root
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    alerts, rows, errors = read_sources(root)
    timelines, _, _ = collect_timelines(alerts, rows, source_errors=errors)
    ledger = _load(root / "data/lab/ft-ledger.json", {"schema_version": 1, "matches": {}})
    ft_report = _load(root / "docs/lab/ft-results.json", None)
    h1_csv = root / "data/results.csv"
    h1_rows = list(csv.DictReader(h1_csv.open(encoding="utf-8"))) if h1_csv.exists() else []
    reg_path = root / "data/lab/pattern-registry.json"
    registry = _load(reg_path, {"schema_version": 1, "entries": []})
    out_path = root / "docs/lab/pattern-research.json"
    previous = _load(out_path, None)
    cache_path = root / "data/lab/.cache/pattern-features.json"
    try:
        cache = _load(cache_path, None)
    except ValueError:
        cache = None  # a corrupt cache only costs a full recompute
    report, registry, cache = run(timelines, ledger, registry, now=now, previous=previous,
                                  cache=cache, h1_results=h1_rows, ft_report=ft_report,
                                  source_commit=os.environ.get("LAB_SOURCE_SHA", "unknown"))
    size = len(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    if size > MAX_REPORT_BYTES:
        raise SystemExit("LAB_PATTERN_REPORT_TOO_LARGE %d" % size)
    # Registry first: a report must never cite a frozen hypothesis that is not stored.
    reg_changed = _write(reg_path, registry)
    wrote = _write(out_path, report, compare_without=("generated_at", "source_commit", "incremental"),
                   compact=True)
    _write(cache_path, cache, compact=True)
    s, g = report["scope"], report["generation"]
    print("LAB_PATTERN_RESEARCH", "matches", s["research_eligible"], "ft", s["ft_confirmed"],
          "past_without_ft", s["past_without_ft"], "future", s["future"],
          "patterns", g["individual_patterns_with_support"], "hypotheses", g["hypotheses_evaluated"],
          "tests", g["tests_performed"], "states", report["state_counts"],
          "new_frozen", len(report["changes"]["new_frozen_candidates"]),
          "reused", report["incremental"]["reused"], "recomputed", report["incremental"]["recomputed"],
          "report_written", wrote, "registry_written", reg_changed, "bytes", size)
    return report


if __name__ == "__main__":
    main()
