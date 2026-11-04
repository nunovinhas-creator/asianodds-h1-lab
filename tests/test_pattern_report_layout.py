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
    """scripts.lab_pattern_research over a copy of the real inputs (offline, temp dir).

    ``changes`` (state transitions, new FT, new frozen) is by definition relative to the
    previously published report, so it legitimately differs between the first replay and the
    second one whenever new FT results move a frozen hypothesis across a threshold (FT runs
    41886312794 and 41892036736: P5-68bdd763e2 reached OOS_MIN_EVAL, CANDIDATO -> EM_VALIDACAO).
    Idempotence is therefore asserted at the fixed point: the second and third runs are
    byte-identical, and every other field is identical from the first run on.
    """

    VOLATILE = ("generated_at", "source_commit", "incremental")

    @classmethod
    def stable(cls, doc, *, without_changes=False):
        drop = cls.VOLATILE + (("changes",) if without_changes else ())
        return layout.dumps({k: v for k, v in doc.items() if k not in drop})

    def copy_inputs(self):
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
        return tmp

    def on_disk(self, tmp):
        return ((tmp / layout.SUMMARY_PATH).read_bytes(),
                (tmp / layout.PERIODS_PATH).read_text(encoding="utf-8"))

    def assert_replays_converge(self, tmp, now=None):
        """Run the writer three times; return the three in-memory reports."""
        from scripts import lab_pattern_research as writer
        now = now or self.now()
        registry_before = (tmp / "data/lab/pattern-registry.json").read_bytes()
        first = writer.main(["--root", str(tmp), "--now", now])
        summary = json.loads((tmp / layout.SUMMARY_PATH).read_text(encoding="utf-8"))
        detail = (tmp / layout.PERIODS_PATH).read_text(encoding="utf-8")
        self.assertLess((tmp / layout.SUMMARY_PATH).stat().st_size, layout.MAX_SUMMARY_BYTES)
        # The writer deliberately keeps the published summary when only run metadata differs
        # (scripts/lab_pattern_research.py, compare_without): compare without those fields.
        self.assertEqual(self.stable(layout.join(summary, detail)), self.stable(first))
        self.assertFalse(list(tmp.rglob("*.tmp")), "atomic writes leave no temp file")
        second = writer.main(["--root", str(tmp), "--now", now])
        # Same inputs: every hypothesis, state, statistic and per-day series is unchanged; only
        # the "changes since the previous report" section may differ, and it must now be empty.
        self.assertEqual(self.stable(second, without_changes=True),
                         self.stable(first, without_changes=True))
        self.assertEqual(second["changes"]["state_transitions"], [])
        self.assertEqual(second["changes"]["new_frozen_candidates"], [])
        settled = self.on_disk(tmp)
        third = writer.main(["--root", str(tmp), "--now", now])
        self.assertEqual(self.on_disk(tmp), settled, "idempotent once settled")
        registry_after = (tmp / "data/lab/pattern-registry.json").read_bytes()
        self.assertTrue(registry_after.startswith(registry_before[:-2]) or
                        registry_after == registry_before, "registry stays append-only")
        return first, second, third

    def test_writer_publishes_a_verified_pair_inside_the_contract(self):
        self.assert_replays_converge(self.copy_inputs())

    def test_threshold_crossing_is_reported_once_and_then_settles(self):
        """A frozen hypothesis crossing OOS_MIN_EVAL, on a synthetic deterministic root.

        No production data: the writer runs on a temporary root built from the engine's own
        synthetic fixtures, so the regression cannot depend on which hypotheses exist on main
        or on how many real FT results happen to be reconciled. Transitions are reported
        relative to the PUBLISHED report (the writer's ``previous``): the 10th OOS FT moves
        CANDIDATO -> EM_VALIDACAO exactly once and then settles; withdrawing it moves back
        exactly once and settles again. The registry stays append-only throughout.
        """
        from h1lab import pattern_engine as pe
        from h1lab.pattern_features import match_features
        from scripts import lab_pattern_research as writer
        try:                                   # discover -s tests (CI) or -m tests.<module>
            from test_pattern_engine import T0, iso, synthetic, timelines
        except ImportError:
            from tests.test_pattern_engine import T0, iso, synthetic, timelines

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "data/lab").mkdir(parents=True)
        state_path, ledger_path = tmp / "data/state.json", tmp / "data/lab/ft-ledger.json"
        write = lambda path, doc: path.write_text(json.dumps(doc), encoding="utf-8")
        (tmp / "data/lab/pattern-registry.json").write_text(
            json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")

        # 1. Discovery sample -> the engine freezes candidates (frozen_at = freeze_now).
        alerts, ledger = synthetic(60, T0)
        freeze_now = T0 + timedelta(days=12)
        write(state_path, {"alerts": alerts})
        write(ledger_path, {"schema_version": 1, "matches": ledger})
        writer.main(["--root", str(tmp), "--now", iso(freeze_now)])
        registry = json.loads((tmp / "data/lab/pattern-registry.json").read_text())
        self.assertTrue(registry["entries"], "synthetic discovery sample must freeze a candidate")

        # 2. Prospective sample, all kicked off and past RESULT_DELAY; FT still pending.
        more, more_ledger = synthetic(40, freeze_now + timedelta(hours=4), first_id=100)
        feats = {t["match_key"]: match_features(t) for t in timelines(alerts + more)}
        now = iso(max(pe._utc(f["kickoff_utc"]) for f in feats.values())
                  + pe.RESULT_DELAY + timedelta(hours=1))
        entry = registry["entries"][0]
        oos = sorted(k for k, f in feats.items() if "excluded" not in f
                     and pe.holds(entry["definition"], f)
                     and pe._utc(f["first_observed_at"]) > pe._utc(entry["frozen_at"]))
        self.assertGreater(len(oos), pe.OOS_MIN_EVAL, "fixture must be able to cross")
        matches = dict(ledger)
        matches.update({k: {"status": "PENDING"} for k in more_ledger})
        for k in oos[:pe.OOS_MIN_EVAL - 1]:                  # one FT short of the threshold
            matches[k] = more_ledger[k]
        write(state_path, {"alerts": alerts + more})
        write(ledger_path, {"schema_version": 1, "matches": matches})
        self.assert_replays_converge(tmp, now)
        published = json.loads((tmp / layout.SUMMARY_PATH).read_text(encoding="utf-8"))
        self.assertEqual(published["hypothesis_states"][entry["id"]], "CANDIDATO")

        def crossing(expected):
            first, second, _ = self.assert_replays_converge(tmp, now)
            moved = [(t["from"], t["to"]) for t in first["changes"]["state_transitions"]
                     if t["id"] == entry["id"]]
            self.assertEqual(moved, [expected])
            self.assertEqual(second["hypothesis_states"][entry["id"]], expected[1])

        tenth = oos[pe.OOS_MIN_EVAL - 1]
        matches[tenth] = more_ledger[tenth]                  # the 10th OOS FT arrives
        write(ledger_path, {"schema_version": 1, "matches": matches})
        crossing(("CANDIDATO", "EM_VALIDACAO"))
        matches[tenth] = {"status": "PENDING"}               # and is withdrawn again
        write(ledger_path, {"schema_version": 1, "matches": matches})
        crossing(("EM_VALIDACAO", "CANDIDATO"))

    @staticmethod
    def now():
        full = real_full_report()
        return full["generated_at"]


if __name__ == "__main__":
    unittest.main()
