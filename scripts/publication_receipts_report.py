"""Aggregate *_PUBLISH_RECEIPT lines from saved job logs into 24 h / 48 h / 7 d windows.

Offline and read-only: it parses log files that were downloaded separately (for
example with the GitHub UI or ``gh run view --log``); it never calls GitHub, a
provider or Telegram. It only measures; it draws no stability conclusion.

Categories (one per receipt):
  FIRST_ATTEMPT            published by the first push
  AFTER_CAS                published after >=1 CAS/non-fast-forward rejection
  AFTER_TRANSPORT          published after >=1 transport failure (HTTP 408/5xx)
  RECOVERED                an uncertain push confirmed on the remote, or an
                           equivalent publication already present (idempotent rerun)
  UNRECOVERED_FAILURE      RETRY_EXHAUSTED, OUTCOME_UNRESOLVED, PUSH_REFUSED
  SAFE_ABORT_INCOMPATIBLE  REFUSED (integrity / dependency / concurrent owner)
  SUPERSEDED               LAB V4 SUPERSEDED_BY_NEWER_INPUTS: deliberate safe skip, nothing
                           published (not a publication, not a failure, not corruption)
  NOTHING_TO_PUBLISH

Usage: python -m scripts.publication_receipts_report --since 2026-11-02T07:36:54Z logs/*.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LINE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)?\s*"
                  r"(?P<producer>[A-Z0-9_]+)_PUBLISH_RECEIPT (?P<doc>\{.*\})\s*$")
WINDOWS = (("24h", timedelta(hours=24)), ("48h", timedelta(hours=48)), ("7d", timedelta(days=7)))


def category(doc):
    status = doc.get("status")
    if status == "NOTHING_TO_PUBLISH":
        return "NOTHING_TO_PUBLISH"
    if status in ("PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR", "ALREADY_PUBLISHED_EQUIVALENT"):
        return "RECOVERED"
    if status == "SUPERSEDED_BY_NEWER_INPUTS" or doc.get("reason_kind") == "SUPERSEDED_BY_NEWER_INPUTS":
        return "SUPERSEDED"
    if status == "REFUSED":
        return "SAFE_ABORT_INCOMPATIBLE"
    if status in ("RETRY_EXHAUSTED", "OUTCOME_UNRESOLVED", "PUSH_REFUSED"):
        return "UNRECOVERED_FAILURE"
    if status == "PUBLISHED":
        path = doc.get("path")
        if path in ("FIRST_ATTEMPT", "AFTER_CAS", "AFTER_TRANSPORT"):
            return path
        if doc.get("transport_failures"):
            return "AFTER_TRANSPORT"
        return "FIRST_ATTEMPT" if int(doc.get("attempt", 1)) == 1 else "AFTER_CAS"
    return "UNCLASSIFIED"


def parse(lines):
    for raw in lines:
        m = LINE.match(raw.rstrip("\n"))
        if not m:
            continue
        try:
            doc = json.loads(m["doc"])
        except ValueError:
            continue
        ts = None
        if m["ts"]:   # GitHub prints 7 fractional digits; second precision is enough
            ts = datetime.strptime(m["ts"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        yield {"producer": m["producer"], "at": ts, "category": category(doc),
               "provider_requeries": doc.get("provider_requeries"),
               "published_commit": doc.get("published_commit"), "run_id": doc.get("run_id")}


def report(rows, since):
    out = {"since": since.isoformat(), "windows": {}, "provider_requeries_nonzero": 0}
    seen = set()
    unique = []
    for row in rows:   # the same receipt can appear twice (stdout + file echo)
        key = (row["producer"], row["run_id"], row["published_commit"], row["category"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
        if row["provider_requeries"] not in (None, 0):
            out["provider_requeries_nonzero"] += 1
    for name, span in WINDOWS:
        window = {}
        for row in unique:
            if row["at"] is None or not since <= row["at"] < since + span:
                continue
            counts = window.setdefault(row["producer"], {})
            counts[row["category"]] = counts.get(row["category"], 0) + 1
        out["windows"][name] = {"complete": datetime.now(timezone.utc) >= since + span,
                                "by_producer": window}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="UTC start, e.g. the merge time")
    parser.add_argument("logs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    since = datetime.fromisoformat(args.since.replace("Z", "+00:00")).astimezone(timezone.utc)
    rows = []
    for path in args.logs:
        rows.extend(parse(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    json.dump(report(rows, since), sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
