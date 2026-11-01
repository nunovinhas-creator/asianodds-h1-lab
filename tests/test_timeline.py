"""Per-match chronology: unit tests + validation on the real tracked data."""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

from h1lab.timeline import build_report, generate, line_trajectory, V4, LEGACY

ROOT = Path(__file__).resolve().parents[1]
CH = "3571094759:"


def alert(n, at, market, before, after, *, match="m", prices=(1.8, 2.0, 1.9, 1.9),
          kickoff="2026-10-27T19:00:00+00:00", home="A", away="B", ah=None, x12=None):
    ob, ub, oa, ua = prices
    row = dict(event_id=CH + str(n), message_id=n, match_key=match, home=home, away=away,
               kickoff_utc=kickoff, observed_at=at, market=market,
               total_before=before, over_before=ob, under_before=ub,
               total_after=after, over_after=oa, under_after=ua, competition="", source_url="")
    if ah:
        row["asian_handicap"] = {"before": {"line": ah[0], "home_odds": 1.9, "away_odds": 1.9},
                                 "after": {"line": ah[1], "home_odds": 1.9, "away_odds": 1.9}}
    if x12:
        row["one_x_two"] = x12
    return row


def v4_from(a, **change):
    """V4 record built from a fixture alert (tests only; never in production)."""
    total = {"before": {"line": a["total_before"], "over_price": a["over_before"],
                        "under_price": a["under_before"]},
             "after": {"line": a["total_after"], "over_price": a["over_after"],
                       "under_price": a["under_after"]}}
    row = {"event_id": a["event_id"], "observed_at": a["observed_at"],
           "match_key": a["match_key"], "kickoff_utc": a["kickoff_utc"],
           "trigger_market": a["market"], "markets": {"total": total}}
    for path, value in change.items():
        side, field = path.split("__")
        row["markets"]["total"][side][field] = value
    return row


class UnitTests(unittest.TestCase):
    def test_every_message_preserved_and_grouped_by_match_key(self):
        rows = [alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75, match="a"),
                alert(2, "2026-10-27T12:00:01+00:00", "total", 2.5, 2.75, match="b"),
                alert(3, "2026-10-27T13:00:00+00:00", "total", 2.75, 3.0, match="a")]
        r = build_report(rows, [])
        self.assertEqual(r["summary"]["messages"], 3)
        self.assertEqual(r["summary"]["matches"], 2)
        self.assertEqual(r["summary"]["repeated_matches"], 1)
        self.assertEqual(r["timelines"][0]["event_ids"], [CH + "1", CH + "3"])
        # Different matches are never related, even with identical tables.
        self.assertEqual(r["summary"]["related_message_pairs"], 0)

    def test_order_uses_utc_instant_not_offset_text(self):
        # 13:30+02:00 == 11:30Z, which is BEFORE 12:00Z.
        rows = [alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75),
                alert(2, "2026-10-27T13:30:00+02:00", "total", 2.25, 2.5)]
        t = build_report(rows, [])["timelines"][0]
        self.assertEqual(t["event_ids"], [CH + "2", CH + "1"])
        self.assertEqual(t["events"][0]["observed_at"], "2026-10-27T11:30:00+00:00")
        self.assertEqual(t["trajectory"]["total"]["transitions"][0]["line"], "CONTINUOUS")

    def test_ties_broken_by_numeric_message_id(self):
        rows = [alert(10000, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75),
                alert(9999, "2026-10-27T12:00:00+00:00", "1x2", 2.5, 2.75)]
        t = build_report(rows, [])["timelines"][0]
        self.assertEqual(t["event_ids"], [CH + "9999", CH + "10000"])

    def test_identical_total_seconds_apart_is_annotated_never_deleted(self):
        rows = [alert(1, "2026-10-27T18:36:11+00:00", "1x2", 3.5, 3.75),
                alert(2, "2026-10-27T18:36:12+00:00", "total", 3.5, 3.75)]
        r = build_report(rows, [])
        t = r["timelines"][0]
        rel = t["related_messages"][0]
        self.assertEqual(rel["classification"], "SAME_MOVEMENT_DIFFERENT_MESSAGE")
        self.assertEqual(rel["evidence"], "IDENTICAL_TOTAL_SNAPSHOT")
        self.assertEqual(rel["action"], "ANNOTATE_ONLY_NEVER_DELETE")
        self.assertEqual(t["event_count"], 2)
        self.assertEqual(t["possibly_redundant_event_ids"], [CH + "2"])
        self.assertEqual(t["movement_episodes_upper_bound"], 1)
        # A re-report of one move is NOT a reversal or an unobserved change.
        tr = t["trajectory"]["total"]
        self.assertEqual(tr["transitions"][0]["line"], "SAME_MOVEMENT_REPEAT")
        self.assertEqual(tr["reversals"], [])

    def test_same_trigger_repeat_classified_separately(self):
        rows = [alert(1, "2026-10-27T12:00:00+00:00", "total", 3.0, 3.25),
                alert(2, "2026-10-27T12:00:30+00:00", "total", 3.0, 3.25)]
        rel = build_report(rows, [])["timelines"][0]["related_messages"][0]
        self.assertEqual(rel["classification"], "REPEATED_SNAPSHOT_SAME_TRIGGER")

    def test_threshold_is_configurable_and_far_identical_not_redundant(self):
        rows = [alert(1, "2026-10-27T12:00:00+00:00", "total", 3.0, 3.25),
                alert(2, "2026-10-27T12:05:00+00:00", "total", 3.0, 3.25)]
        self.assertEqual(build_report(rows, [])["summary"]["related_message_pairs"], 0)
        self.assertEqual(build_report(rows, [], near_seconds=300)["summary"]["related_message_pairs"], 1)
        t = build_report(rows, [])["timelines"][0]
        self.assertEqual(t["trajectory"]["total"]["transitions"][0]["line"],
                         "AMBIGUOUS_REPEAT_OR_REVERSAL")
        with self.assertRaises(ValueError):
            build_report(rows, [], near_seconds=-1)

    def test_same_line_move_with_different_prices_is_weaker_evidence(self):
        rows = [alert(1, "2026-10-27T17:41:39+00:00", "total", 2.25, 2.5, prices=(1.76, 2.0, 1.94, 1.82)),
                alert(2, "2026-10-27T17:41:40+00:00", "1x2", 2.25, 2.5, prices=(1.76, 2.0, 1.96, 1.82))]
        t = build_report(rows, [])["timelines"][0]
        rel = t["related_messages"][0]
        self.assertEqual(rel["evidence"], "SAME_TOTAL_LINE_MOVE_DIFFERENT_PRICES")
        self.assertFalse(rel["possibly_redundant_snapshot"])
        self.assertEqual(rel["total_fields_differing"], ["after.over_price"])
        self.assertEqual(t["possibly_redundant_event_ids"], [])
        self.assertEqual(t["movement_episodes_upper_bound"], 1)

    def test_continuity_gap_and_reversal_without_interpolation(self):
        rows = [alert(1, "2026-10-27T12:00:00+00:00", "total", 3.0, 3.25),
                alert(2, "2026-10-27T13:00:00+00:00", "total", 3.25, 3.5),
                alert(3, "2026-10-27T14:00:00+00:00", "total", 3.25, 3.0)]
        tr = build_report(rows, [])["timelines"][0]["trajectory"]["total"]
        self.assertEqual([x["line"] for x in tr["transitions"]], ["CONTINUOUS", "UNOBSERVED_CHANGE"])
        self.assertEqual(tr["transitions"][1]["unobserved_direction"], "DOWN")
        self.assertEqual(len(tr["reversals"]), 1)
        self.assertEqual(tr["reversals"][0]["evidence"], "gap")
        # Only observed endpoints; no intermediate price or line invented.
        self.assertEqual(len(tr["points"]), 3)
        self.assertEqual((tr["first_observed_line"], tr["last_observed_line"]), (3.0, 3.0))

    def test_v4_explicit_and_h1_legacy_kept_separate(self):
        a = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75)
        b = alert(2, "2026-10-27T13:00:00+00:00", "total", 2.75, 3.0)
        r = build_report([a, b], [v4_from(b)])
        ev = {e["event_id"]: e for e in r["timelines"][0]["events"]}
        self.assertEqual(ev[CH + "1"]["snapshots"]["total"]["origin"], LEGACY)
        self.assertEqual(ev[CH + "2"]["snapshots"]["total"]["origin"], V4)
        self.assertEqual(ev[CH + "2"]["v4_vs_h1_record"]["total"]["status"], "AGREE")
        self.assertEqual(r["summary"]["snapshots_by_origin"], {LEGACY: 1, V4: 1})
        self.assertEqual(r["summary"]["messages_h1_only"], 1)

    def test_v4_disagreement_is_visible_and_v4_value_not_overwritten(self):
        a = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75)
        r = build_report([a], [v4_from(a, after__over_price=1.99)])
        e = r["timelines"] or None
        self.assertIsNone(e)  # single-message match: counted, not listed
        self.assertEqual(r["summary"]["v4_vs_h1_record_agreement"], {"total:DIFFER": 1})

    def test_v4_only_message_is_not_lost(self):
        a = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75)
        b = alert(2, "2026-10-27T12:30:00+00:00", "total", 2.75, 3.0)
        r = build_report([a], [v4_from(b)])
        self.assertEqual(r["summary"]["messages"], 2)
        self.assertEqual(r["summary"]["messages_v4_only"], 1)

    def test_identity_conflicts_reported(self):
        a = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75)
        b = alert(2, "2026-10-27T13:00:00+00:00", "total", 2.75, 3.0,
                  kickoff="2026-10-27T20:00:00+00:00")
        v = v4_from(b)
        v["match_key"] = "other"
        r = build_report([a, b], [v])
        t = r["timelines"][0]
        self.assertFalse(t["identity"]["kickoff_consistent"])
        self.assertEqual(t["identity"]["per_message_conflicts"], [CH + "2"])
        self.assertEqual(r["summary"]["matches_with_identity_inconsistency"], 1)

    def test_invalid_and_duplicate_rows_are_counted_not_used(self):
        good = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75)
        bad_time = alert(2, "invalid", "total", 2.5, 2.75)
        dup = copy.deepcopy(good)
        dup["total_after"] = 3.0
        r = build_report([good, bad_time, dup, {"match_key": "x"}, "junk"], [])
        self.assertEqual(r["summary"]["messages"], 1)
        self.assertEqual(r["summary"]["messages_excluded"], 1)
        self.assertEqual(r["issue_counts"]["missing_event_id"], 2)
        self.assertEqual(r["issue_counts"]["duplicate_event_id"], 1)

    def test_invalid_numbers_never_become_snapshots(self):
        a = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.4, 2.75)
        b = alert(2, "2026-10-27T13:00:00+00:00", "total", 2.5, 2.75, prices=(True, 2.0, 1.9, 1.9))
        r = build_report([a, b], [])
        self.assertEqual(r["timelines"][0]["events"][0]["snapshots"], {})
        self.assertEqual(r["timelines"][0]["events"][1]["snapshots"], {})

    def test_ah_and_1x2_trajectories(self):
        x1 = {"1": {"before": 1.27, "after": 1.23}, "X": {"before": 6.61, "after": 6.92},
              "2": {"before": 8.77, "after": 9.48}}
        x2 = {"1": {"before": 1.25, "after": 1.2}, "X": {"before": 6.92, "after": 7.1},
              "2": {"before": 9.48, "after": 10.0}}
        rows = [alert(1, "2026-10-27T12:00:00+00:00", "1x2", 3.75, 3.75, ah=(-1.75, -2.0), x12=x1),
                alert(2, "2026-10-27T13:00:00+00:00", "1x2", 3.75, 3.75, ah=(-2.0, -2.0), x12=x2)]
        t = build_report(rows, [])["timelines"][0]["trajectory"]
        self.assertEqual(t["asian_handicap"]["points"][0]["move"], "DOWN")
        self.assertEqual(t["asian_handicap"]["transitions"][0]["line"], "CONTINUOUS")
        self.assertEqual(t["one_x_two"]["transitions"][0]["changed_selections"], ["1"])

    def test_output_bounded_and_deterministic(self):
        rows = []
        for m in range(5):
            rows += [alert(10 * m + 1, f"2026-10-27T1{m}:00:00+00:00", "total", 2.5, 2.75, match=str(m)),
                     alert(10 * m + 2, f"2026-10-27T1{m}:30:00+00:00", "total", 2.75, 3.0, match=str(m))]
        r1 = build_report(rows, [], max_timelines=2)
        r2 = build_report(list(reversed(rows)), [], max_timelines=2)
        self.assertEqual(r1, r2)
        self.assertEqual(r1["sampling"], {**r1["sampling"], "timelines_published": 2, "timelines_omitted": 3})
        self.assertEqual(r1["summary"]["repeated_matches"], 5)

    def test_report_contains_no_raw_text_or_urls(self):
        a = alert(1, "2026-10-27T12:00:00+00:00", "total", 2.5, 2.75)
        a["source_url"] = "https://www.asianodds.com/x?match=secret"
        b = alert(2, "2026-10-27T13:00:00+00:00", "total", 2.75, 3.0)
        text = json.dumps(build_report([a, b], []))
        self.assertNotIn("asianodds.com", text)
        self.assertNotIn("source_url", text)

    def test_module_does_not_import_h1_production(self):
        tree = ast.parse((ROOT / "h1lab" / "timeline.py").read_text(encoding="utf-8"))
        names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        for forbidden in ("core", "cli", "notify", "results", "bot", "bsd", "session"):
            self.assertFalse(any(x and x.split(".")[-1] == forbidden for x in names), forbidden)

    def test_line_trajectory_none_without_market(self):
        self.assertIsNone(line_trajectory([{"event_id": "1", "snapshots": {}}], "total"))


@unittest.skipUnless((ROOT / "data" / "state.json").exists(), "repository data not present")
class RealDataTests(unittest.TestCase):
    """Validated against data/state.json + data/lab/markets-*.jsonl in the repo."""

    @classmethod
    def setUpClass(cls):
        # Pinned real examples are looked up in the whole repeated-match
        # population: the published sample keeps only the N most recent
        # timelines, so ranks drift as normal publications add newer matches.
        cls.report = generate(ROOT, max_timelines=10 ** 6)
        cls.alerts = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))["alerts"]
        cls.by_key = {t["match_key"]: t for t in cls.report["timelines"]}
        cls.ids = {a["event_id"] for a in cls.alerts}

    def need(self, *numbers):
        missing = [n for n in numbers if CH + n not in self.ids]
        if missing:
            self.skipTest("real events not present: " + ",".join(missing))

    def timeline_of(self, number):
        return next(t for t in self.report["timelines"] if CH + number in t["event_ids"])

    def test_pinned_lookups_do_not_depend_on_the_published_sample_cap(self):
        # Regression (#107): with the default cap, examples at ranks 276-386
        # raised StopIteration (blocking the LAB bundle) once ~15 newer matches arrived.
        self.assertEqual(self.report["sampling"]["timelines_omitted"], 0)
        self.assertGreater(len(self.report["timelines"]), 0)

    def test_no_alert_lost(self):
        s = self.report["summary"]
        self.assertEqual(s["messages"] + s["messages_excluded"] - s["messages_v4_only"], len(self.alerts))
        self.assertEqual(self.report["status"], "DESCRIPTIVE_SHADOW_AUDIT_NOT_CERTIFIED")

    def test_blackpool_three_alerts(self):
        self.need("50588", "50675", "50681")
        t = self.timeline_of("50675")
        self.assertEqual(t["event_ids"][:3], [CH + "50588", CH + "50675", CH + "50681"])
        ev = {e["event_id"]: e for e in t["events"]}
        self.assertEqual(ev[CH + "50588"]["snapshots"]["total"]["origin"], LEGACY)
        self.assertEqual(ev[CH + "50675"]["snapshots"]["total"]["origin"], V4)
        self.assertEqual(ev[CH + "50681"]["snapshots"]["total"]["origin"], V4)
        tr = t["trajectory"]["total"]
        self.assertEqual([(p["before"], p["after"]) for p in tr["points"][:3]],
                         [(3.5, 3.75), (3.75, 3.75), (3.75, 4.0)])
        self.assertEqual([x["line"] for x in tr["transitions"][:2]], ["CONTINUOUS", "CONTINUOUS"])
        ah = t["trajectory"]["asian_handicap"]["points"][0]
        self.assertEqual((ah["event_id"], ah["before"], ah["after"]), (CH + "50675", -1.75, -2.0))
        self.assertEqual(t["related_messages"], [])

    def test_dortmund_same_total_one_second_apart(self):
        self.need("50582", "50685", "50686")
        t = self.timeline_of("50685")
        self.assertEqual(t["event_ids"][:3], [CH + "50582", CH + "50685", CH + "50686"])
        rel = [r for r in t["related_messages"] if r["events"] == [CH + "50685", CH + "50686"]]
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["separation_seconds"], 1.0)
        self.assertEqual(rel[0]["evidence"], "IDENTICAL_TOTAL_SNAPSHOT")
        self.assertEqual(rel[0]["classification"], "SAME_MOVEMENT_DIFFERENT_MESSAGE")
        self.assertIn([CH + "50685", CH + "50686"], t["movement_episodes"])
        self.assertEqual(t["event_count"], len(t["events"]))  # nothing removed
        ev = {e["event_id"]: e for e in t["events"]}
        self.assertEqual(ev[CH + "50582"]["snapshots"]["total"]["origin"], LEGACY)

    def test_braga_mixed_origin_pair(self):
        self.need("50654", "50655")
        rel = next(r for r in self.timeline_of("50654")["related_messages"]
                   if r["events"] == [CH + "50654", CH + "50655"])
        self.assertTrue(rel["mixed_origin"])
        self.assertEqual(rel["evidence"], "IDENTICAL_TOTAL_SNAPSHOT")

    def test_real_bedford_pair(self):
        self.need("50710", "50711")
        rel = next(r for r in self.timeline_of("50710")["related_messages"]
                   if r["events"] == [CH + "50710", CH + "50711"])
        self.assertEqual(rel["separation_seconds"], 2.0)
        self.assertEqual(rel["trigger_markets"], ["total", "1x2"])
        self.assertFalse(rel["mixed_origin"])

    def test_v4_never_disagrees_silently_with_h1_record(self):
        # A real difference must stay visible with its fields; it is reported,
        # never corrected or hidden (the V4 audit is the authority for it).
        agreement = self.report["summary"]["v4_vs_h1_record_agreement"]
        differ = sum(v for k, v in agreement.items() if k.endswith(":DIFFER"))
        listed = [m for t in self.report["timelines"] for e in t["events"]
                  for m in (e.get("v4_vs_h1_record") or {}).values() if m["status"] == "DIFFER"]
        self.assertTrue(all(m["fields"] for m in listed))
        self.assertLessEqual(len(listed), differ)

    def test_cli_writes_only_requested_file(self):
        from scripts.lab_match_trajectories import main
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "x.json"
            main(["--root", str(ROOT), "--out", str(out)])
            self.assertEqual(json.loads(out.read_text())["schema_version"], 1)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["x.json"])


if __name__ == "__main__":
    unittest.main()
