"""Scientific memory must be replayable, immutable and FT-revision aware."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_shadow import append_journal
from h1lab.v6_science_memory import read_stream, rebuild, synchronize


NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def fixture(root, *, final=True, goals=(2, 1)):
    root = Path(root)
    source = {
        "match_key": "test-match-1", "event_id": "channel:1",
        "known_at": "2026-10-28T14:00:00+00:00",
        "observed_at": "2026-10-28T13:59:00+00:00",
        "kickoff_utc": "2026-10-28T16:00:00+00:00",
        "match_label": "A vs B", "pattern_original_posthoc": True,
        "pattern_strict_posthoc": True, "total_origin": "V4_EXPLICIT",
        "price_quality": {"status": "USABLE", "flags": []},
        "market_probability_over_2_5": 0.55,
    }
    append_journal(root, datetime(2026, 10, 28, 14, tzinfo=timezone.utc), [source])
    change_ft(root, final=final, goals=goals)


def change_ft(root, *, final, goals=(2, 1)):
    path = Path(root) / "data/lab/ft-ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    matches = {}
    if final:
        matches["test-match-1"] = {
            "status": "FINAL", "checked_at": "2026-10-28T19:00:00+00:00",
            "result": {"home_goals": goals[0], "away_goals": goals[1],
                       "evidence": "verified_test_source", "source": "https://example.test/ft"}}
    path.write_text(json.dumps({"schema_version": 1, "matches": matches}), encoding="utf-8")


class ScientificMemory(unittest.TestCase):
    def test_five_streams_rebuild_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            first, appended = synchronize(tmp, NOW)
            self.assertEqual(set(first["stream_records"]),
                             {"observations", "patterns", "hypotheses", "evidence", "decisions"})
            self.assertEqual(first["stream_records"], {
                "observations": 1, "patterns": 1, "hypotheses": 1,
                "evidence": 1, "decisions": 1})
            self.assertEqual(first["ft_scored_pattern_original"], 1)
            self.assertEqual(first, rebuild(tmp))
            second, new = synchronize(tmp, NOW)
            self.assertEqual(first, second)
            self.assertTrue(all(v == 0 for v in new.values()))

    def test_ft_revision_is_new_event_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            synchronize(tmp, NOW)
            old = read_stream(tmp, "evidence")[0]
            change_ft(tmp, final=True, goals=(0, 0))
            latest, counts = synchronize(tmp, NOW)
            self.assertEqual(counts["evidence"], 1)
            events = read_stream(tmp, "evidence")
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0], old)
            self.assertEqual(events[1]["event"]["previous_evidence_event_id"], old["id"])
            self.assertEqual(latest["ft_scored_pattern_original"], 1)
            self.assertEqual(latest, rebuild(tmp))

    def test_missing_ft_quarantined_and_reappearing_ft_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            synchronize(tmp, NOW)
            change_ft(tmp, final=False)
            view, _ = synchronize(tmp, NOW)
            self.assertEqual(view["ft_evidence_state_counts"], {"QUARANTINED": 1})
            self.assertEqual(view["ft_scored_with_model_reference"], 0)
            # Same exact score comes back: unique event id must still be new.
            change_ft(tmp, final=True)
            view, _ = synchronize(tmp, NOW)
            self.assertEqual(view["ft_evidence_state_counts"], {"CONFIRMED": 1})
            self.assertEqual(len(read_stream(tmp, "evidence")), 3)
            self.assertEqual(rebuild(tmp), view)

    def test_tampering_breaks_chain_and_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            synchronize(tmp, NOW)
            file = next((Path(tmp) / "data/lab").glob("v6-memory-patterns-*.jsonl"))
            file.write_text(file.read_text().replace("true", "false", 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                rebuild(tmp)

    def test_missing_pattern_detected_even_if_observation_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            synchronize(tmp, NOW)
            file = next((Path(tmp) / "data/lab").glob("v6-memory-patterns-*.jsonl"))
            file.unlink()
            with self.assertRaises(ValueError):
                rebuild(tmp)

    def test_memory_created_later_does_not_backdate_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp, final=False)
            synchronize(tmp, NOW)
            event = read_stream(tmp, "observations")[0]
            self.assertEqual(event["written_at"], NOW.isoformat(timespec="seconds"))
            self.assertEqual(event["event"]["known_at"], "2026-10-28T14:00:00+00:00")
            self.assertNotEqual(event["written_at"], event["event"]["known_at"])


if __name__ == "__main__":
    unittest.main()
