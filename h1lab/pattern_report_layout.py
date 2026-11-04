"""Size contract of the public LAB pattern report (P0 #107, runs 41796944393 / 41811582951).

``docs/lab/pattern-research.json`` hit its 350 000-byte contract (350 074 and 350 270 bytes).
The only unbounded block is ``patterns[].outcomes.*.periods.by_kickoff_day``: one entry per
kickoff day x single pattern x tested outcome (~80 KB on 2026-11-04, ~8 KB more per day). Every
other block is capped by the engine (top-40 combinations, 30 x 5 neighbours, 40 negatives).

The writer therefore publishes two files:

* the SUMMARY (same path, same ``schema_version`` 1, every hypothesis, statistic, negative
  result, OOS verdict and the per-half stability that the engine itself uses). Each
  ``periods`` keeps ``halves`` and replaces ``by_kickoff_day`` with ``by_kickoff_day_ref`` and
  ``kickoff_days``;
* the DETAIL ``docs/lab/pattern-research-periods.json``: the per-day series keyed by those refs.
  It holds no timestamp, so it is content-addressed: the summary records its exact ``sha256``
  and ``bytes``.

``join(summary, detail)`` verifies the checksum and rebuilds the original engine report exactly
(``join(*split(r)) == r``), so nothing is lost and any reader can reconstitute it.
"""
from __future__ import annotations

import copy
import hashlib
import json

SUMMARY_PATH = "docs/lab/pattern-research.json"
PERIODS_PATH = "docs/lab/pattern-research-periods.json"
LAYOUT_VERSION = 2
PERIODS_SCHEMA = 1
PERIODS_KIND = "LAB_PATTERN_PERIODS_BY_KICKOFF_DAY"
SECTIONS = ("patterns", "combinations_top")
MAX_SUMMARY_BYTES = 350_000      # unchanged public contract
WARN_SUMMARY_BYTES = 300_000     # visible warning long before the contract is reached
MAX_PERIODS_BYTES = 2_000_000    # detail file contract (~8 KB/day of growth -> months of margin)


class LayoutError(ValueError):
    pass


def dumps(value) -> str:
    """Exactly the compact form the writer publishes (and the size contract measures)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def size(value) -> int:
    return len(dumps(value).encode("utf-8")) - 1


def _series(report):
    for section in SECTIONS:
        for item in report.get(section) or []:
            for outcome, stats in sorted((item.get("outcomes") or {}).items()):
                if isinstance(stats, dict) and isinstance(stats.get("periods"), dict):
                    yield "%s/%s/%s" % (section, item["id"], outcome), stats["periods"]


def split(report):
    """Return (summary, detail_text). Pure: ``report`` is not modified."""
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise LayoutError("Unsupported pattern report")
    if "details" in report or (report.get("versions") or {}).get("report_layout"):
        raise LayoutError("Report already split")
    summary = copy.deepcopy(report)
    series = {}
    for ref, periods in _series(summary):
        if "by_kickoff_day" not in periods:
            continue
        if ref in series:
            raise LayoutError("Duplicate period series: " + ref)
        days = periods.pop("by_kickoff_day")
        if not isinstance(days, dict):
            raise LayoutError("Invalid period series: " + ref)
        series[ref] = days
        periods["by_kickoff_day_ref"] = ref
        periods["kickoff_days"] = len(days)
    text = dumps({"schema_version": PERIODS_SCHEMA, "kind": PERIODS_KIND, "series": series})
    raw = text.encode("utf-8")
    summary["details"] = {"periods_by_kickoff_day": {
        "path": PERIODS_PATH, "schema_version": PERIODS_SCHEMA, "kind": PERIODS_KIND,
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "series": len(series)}}
    summary["versions"] = dict(summary.get("versions") or {}, report_layout=LAYOUT_VERSION)
    return summary, text


def verify(summary, detail_text):
    """Raise unless ``detail_text`` is exactly the detail file the summary references."""
    meta = ((summary or {}).get("details") or {}).get("periods_by_kickoff_day")
    if not isinstance(meta, dict) or meta.get("path") != PERIODS_PATH:
        raise LayoutError("LAB_PATTERN_PERIODS_REFERENCE_MISSING")
    raw = detail_text.encode("utf-8") if isinstance(detail_text, str) else bytes(detail_text)
    if len(raw) != meta.get("bytes") or hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
        raise LayoutError("LAB_PATTERN_PERIODS_CHECKSUM_MISMATCH")
    doc = json.loads(raw.decode("utf-8"))
    if (not isinstance(doc, dict) or doc.get("schema_version") != PERIODS_SCHEMA
            or doc.get("kind") != PERIODS_KIND or not isinstance(doc.get("series"), dict)):
        raise LayoutError("LAB_PATTERN_PERIODS_INVALID")
    if len(doc["series"]) != meta.get("series"):
        raise LayoutError("LAB_PATTERN_PERIODS_SERIES_COUNT")
    return doc


def join(summary, detail_text):
    """Rebuild the full engine report from the published pair (checksum verified)."""
    doc = verify(summary, detail_text)
    full = copy.deepcopy(summary)
    series = dict(doc["series"])
    for ref, periods in _series(full):
        if "by_kickoff_day_ref" not in periods:
            continue
        if periods["by_kickoff_day_ref"] != ref or ref not in series:
            raise LayoutError("LAB_PATTERN_PERIODS_UNRESOLVED_REF " + ref)
        days = series.pop(ref)
        if periods.get("kickoff_days") != len(days):
            raise LayoutError("LAB_PATTERN_PERIODS_DAY_COUNT " + ref)
        del periods["by_kickoff_day_ref"], periods["kickoff_days"]
        periods["by_kickoff_day"] = days
    if series:
        raise LayoutError("LAB_PATTERN_PERIODS_ORPHAN_SERIES %d" % len(series))
    del full["details"]
    versions = dict(full["versions"])
    versions.pop("report_layout", None)
    full["versions"] = versions
    return full
