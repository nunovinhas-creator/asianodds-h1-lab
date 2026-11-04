"""P0 #107: the pattern report stays inside its 350 000-byte contract without losing information.

Runs 41796944393 (350 074 bytes) and 41811582951 (350 270 bytes) were blocked by the size guard.
The per-kickoff-day series (``periods.by_kickoff_day``) is the only block that grows with time;
it now lives in a checksum-referenced detail file. These tests use the real report on main.
"""
import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab import discovery_timeline, e5_notify, strategy_notify
from h1lab import pattern_report_layout as layout

REPO = Path(__file__).resolve().parents[1]


def real_full_report():
    """The full engine report as published on main (either layout)."""
    summary = json.loads((REPO / layout.SUMMARY_PATH).read_text(encoding="utf-8"))
    if "details" in summary:
        return layout.join(summary, (REPO / layout.PERIODS_PATH).read_text(encoding="utf-8"))
    return summary


def grow(report, extra_days):
    """Synthetic future: every per-day series gains ``extra_days`` kickoff days."""
    out = copy.deepcopy(report)
    for section in layout.SECTIONS:
        for item in out.get(section) or []:
            for stats in (item.get("outcomes") or {}).values():
                days = (stats.get("periods") or {}).get("by_kickoff_day")
                if not isinstance(days, dict):
                    continue
                start = datetime(2027, 1, 1)
                for n in range(extra_days):
                    day = (start + timedelta(days=n)).strftime("%Y-%m-%d")
                    days[day] = {"known": 12, "rate": 0.5833, "reference_known": 31,
                                 "reference_rate": 0.4839}
    return out


class SplitContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full = real_full_report()
        cls.summary, cls.detail = layout.split(cls.full)

    def test_real_report_round_trip_is_exact(self):
        self.assertEqual(layout.join(self.summary, self.detail), self.full)

    def test_real_summary_is_inside_the_contract_with_margin(self):
        size = layout.size(self.summary)
        self.assertLess(size, layout.MAX_SUMMARY_BYTES)
        self.assertLess(size, layout.WARN_SUMMARY_BYTES, "at least 50 KB of margin today")
        self.assertLess(len(self.detail.encode()), layout.MAX_PERIODS_BYTES)

    def test_contract_itself_is_not_raised(self):
        self.assertEqual(layout.MAX_SUMMARY_BYTES, 350_000)

    def test_summary_keeps_every_hypothesis_statistic_and_verdict(self):
        self.assertEqual(self.summary["schema_version"], 1)
        for key in ("patterns", "combinations_top", "frozen", "negative_evidence",
                    "similar_matches", "hypothesis_states", "state_counts", "evolution",
                    "changes", "rules", "scope", "ft_coverage", "limitations"):
            if key in ("patterns", "combinations_top"):
                self.assertEqual([x["id"] for x in self.summary[key]],
                                 [x["id"] for x in self.full[key]])
            else:
                self.assertEqual(self.summary[key], self.full[key], key)
        for a, b in zip(self.summary["patterns"], self.full["patterns"]):
            for outcome, stats in b["outcomes"].items():
                kept = a["outcomes"][outcome]
                for field, value in stats.items():
                    if field != "periods":
                        self.assertEqual(kept[field], value, (a["id"], outcome, field))
                if "periods" in stats:
                    self.assertEqual(kept["periods"]["halves"], stats["periods"]["halves"])

    def test_detail_is_content_addressed_and_deterministic(self):
        again = copy.deepcopy(self.full)
        again["generated_at"] = "2030-01-01T00:00:00+00:00"
        again["source_commit"] = "f" * 40
        _, detail = layout.split(again)
        self.assertEqual(detail, self.detail)
        self.assertNotIn("generated_at", json.loads(self.detail))

    def test_split_is_pure_and_not_reentrant(self):
        before = json.dumps(self.full, sort_keys=True)
        layout.split(self.full)
        self.assertEqual(json.dumps(self.full, sort_keys=True), before)
        with self.assertRaises(layout.LayoutError):
            layout.split(self.summary)

    def test_tampered_or_mismatched_detail_is_refused(self):
        with self.assertRaisesRegex(layout.LayoutError, "CHECKSUM_MISMATCH"):
            layout.join(self.summary, self.detail.replace('"known":', '"known": ', 1))
        doc = json.loads(self.detail)
        ref = sorted(doc["series"])[0]
        doc["series"]["patterns/P5-0000000000/OVER_2_5"] = doc["series"][ref]
        forged = layout.dumps(doc)
        summary = copy.deepcopy(self.summary)
        meta = summary["details"]["periods_by_kickoff_day"]
        import hashlib
        meta.update(sha256=hashlib.sha256(forged.encode()).hexdigest(), bytes=len(forged.encode()),
                    series=len(doc["series"]))
        with self.assertRaisesRegex(layout.LayoutError, "ORPHAN"):
            layout.join(summary, forged)
        missing = copy.deepcopy(self.summary)
        del missing["details"]
        with self.assertRaisesRegex(layout.LayoutError, "REFERENCE_MISSING"):
            layout.join(missing, self.detail)

    def test_future_growth_moves_only_the_detail_file(self):
        for days in (30, 90, 180):
            grown = grow(self.full, days)
            self.assertGreater(layout.size(grown), layout.MAX_SUMMARY_BYTES,
                               "without the split the report would be refused")
            summary, detail = layout.split(grown)
            # The summary grows only by the digits of kickoff_days (bounded), never per day.
            self.assertLess(layout.size(summary) - layout.size(self.summary), 2_000)
            self.assertLess(layout.size(summary), layout.MAX_SUMMARY_BYTES)
            self.assertLess(len(detail.encode()), layout.MAX_PERIODS_BYTES, days)
            self.assertEqual(layout.join(summary, detail), grown)


class ConsumersAreUnaffected(unittest.TestCase):
    """Every production reader of the summary gets exactly what it got from the full report."""

    @classmethod
    def setUpClass(cls):
        cls.full = real_full_report()
        cls.summary, cls.detail = layout.split(cls.full)
        cls.now = datetime.fromisoformat(cls.full["generated_at"]).astimezone(timezone.utc)

    def test_discovery_timeline_reads_the_same_hypotheses(self):
        self.assertEqual(discovery_timeline._published(self.summary),
                         discovery_timeline._published(self.full))

    def test_e5_history_is_identical(self):
        self.assertEqual(e5_notify.history(self.summary, self.now),
                         e5_notify.history(self.full, self.now))

    def test_frozen_strategy_catalogue_still_validates(self):
        # Retired emitter, still a reader: same rows apart from the moved per-day series.
        def strip(mapping):
            out = json.loads(json.dumps(mapping, sort_keys=True))
            for row in out.values():
                for stats in (row.get("outcomes") or {}).values():
                    (stats.get("periods") or {}).pop("by_kickoff_day", None)
                    (stats.get("periods") or {}).pop("by_kickoff_day_ref", None)
                    (stats.get("periods") or {}).pop("kickoff_days", None)
            return out
        try:
            full = strategy_notify._validate_catalogue(self.full, self.now)
        except ValueError as exc:
            self.skipTest("real catalogue not valid for the frozen rule: %s" % exc)
        self.assertEqual(strip(strategy_notify._validate_catalogue(self.summary, self.now)),
                         strip(full))

    def test_dashboard_contract_fields_present(self):
        # docs/master-brain.js: schema_version === 1 and OVER_2_5/BTTS_YES objects per row.
        self.assertEqual(self.summary["schema_version"], 1)
        for row in self.summary["patterns"] + self.summary["combinations_top"]:
            self.assertIsInstance(row["label"], str)
            self.assertIsInstance(row["outcomes"]["OVER_2_5"], dict)
            self.assertIsInstance(row["outcomes"]["BTTS_YES"], dict)


class WriterEndToEnd(unittest.TestCase):
    """scripts.lab_pattern_research over a copy of the real inputs (offline, temp dir)."""

    def test_writer_publishes_a_verified_pair_inside_the_contract(self):
        from scripts import lab_pattern_research as writer
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for rel in ("data/state.json", "data/results.csv", "data/lab/ft-ledger.json",
                    "data/lab/pattern-registry.json", "docs/lab/ft-results.json",
                    layout.SUMMARY_PATH):
            if (REPO / rel).exists():
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / rel, tmp / rel)
        for path in (REPO / "data/lab").glob("markets-*.jsonl"):
            shutil.copy2(path, tmp / "data/lab" / path.name)
        registry_before = (tmp / "data/lab/pattern-registry.json").read_bytes()
        report = writer.main(["--root", str(tmp), "--now", self.now()])
        summary = json.loads((tmp / layout.SUMMARY_PATH).read_text(encoding="utf-8"))
        detail = (tmp / layout.PERIODS_PATH).read_text(encoding="utf-8")
        self.assertLess((tmp / layout.SUMMARY_PATH).stat().st_size, layout.MAX_SUMMARY_BYTES)
        # The writer deliberately keeps the published summary when only these run-metadata
        # fields differ (scripts/lab_pattern_research.py, compare_without). Since main carries
        # an already split summary (f703ae07), replaying the committed inputs hits exactly that
        # no-rewrite path, so the on-disk pair is compared without them; every hypothesis,
        # statistic and per-day series must still be identical.
        volatile = ("generated_at", "source_commit", "incremental")

        def stable(doc):
            return layout.dumps({k: v for k, v in doc.items() if k not in volatile})

        self.assertEqual(stable(layout.join(summary, detail)), stable(report))
        self.assertFalse(list(tmp.rglob("*.tmp")), "atomic writes leave no temp file")
        # A second run with identical inputs rewrites nothing (idempotent).
        before = ((tmp / layout.SUMMARY_PATH).read_bytes(), detail)
        writer.main(["--root", str(tmp), "--now", self.now()])
        self.assertEqual(((tmp / layout.SUMMARY_PATH).read_bytes(),
                          (tmp / layout.PERIODS_PATH).read_text(encoding="utf-8")), before)
        registry_after = (tmp / "data/lab/pattern-registry.json").read_bytes()
        self.assertTrue(registry_after.startswith(registry_before[:-2]) or
                        registry_after == registry_before, "registry stays append-only")

    @staticmethod
    def now():
        full = real_full_report()
        return full["generated_at"]


if __name__ == "__main__":
    unittest.main()
