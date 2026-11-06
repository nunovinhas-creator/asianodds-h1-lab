"""Adversarial read-only A1 audit tests; no LLM or provider calls."""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import scripts.master_brain_a1_audit as a1

from scripts.master_brain_a1_audit import audit, ft_rows, main, missing_reason, rates

KO = "2026-11-01T12:00:00+00:00"
BEFORE = "2026-11-01T11:00:00+00:00"
AFTER = "2026-11-01T14:00:00+00:00"


def timeline():
    return {"identity": {"kickoff_utc": [KO], "kickoff_consistent": True,
                         "team_names_consistent": True, "per_message_conflicts": []},
            "events": [{"observed_at": BEFORE}]}


def receipt(when=BEFORE, kind="FIRST_SEEN_BY_COLLECTOR"):
    return {"known_at": when, "kind": kind}


class MissingDataTests(unittest.TestCase):
    def test_no_receipt_is_unknown_not_synthetic_arrival(self):
        self.assertEqual(missing_reason(timeline(), [], []), "NO_FIRST_COLLECTOR_RECORD")
        self.assertEqual(missing_reason(timeline(), [], [receipt(kind="HISTORICAL_BASELINE_IMPORT")]),
                         "NO_FIRST_COLLECTOR_RECORD")

    def test_kickoff_is_not_pre_kickoff(self):
        for when in (KO, AFTER):
            self.assertEqual(missing_reason(timeline(), [], [receipt(when)]),
                             "FIRST_COLLECTOR_RECORD_AT_OR_AFTER_KICKOFF")

    def test_early_receipt_without_freeze_is_not_coverage(self):
        self.assertEqual(missing_reason(timeline(), [], [receipt()]),
                         "PREKICKOFF_COLLECTOR_RECORD_WITHOUT_FREEZE")

    def test_identity_and_alignment_fail_closed(self):
        t = timeline()
        t["identity"]["per_message_conflicts"] = ["event"]
        self.assertEqual(missing_reason(t, [], [receipt()]), "IDENTITY_OR_KICKOFF_CONFLICT")
        self.assertEqual(missing_reason(timeline(), [{"kickoff_utc": AFTER}], [receipt()]),
                         "FORECAST_KICKOFF_ALIGNMENT_CONFLICT")

    def test_missing_source_timestamp_is_not_invented(self):
        t = timeline()
        t["events"] = [{"observed_at": None}]
        self.assertEqual(missing_reason(t, [], [receipt()]), "SOURCE_WITHOUT_PREKICKOFF_EVIDENCE")

    def test_market_denominators_are_match_level_and_explicit(self):
        rows = [{"markets": ["total", "asian_handicap"], "frozen_pre_kickoff": True,
                 "quarantined_or_conflicting": True},
                {"markets": ["total"], "frozen_pre_kickoff": False,
                 "quarantined_or_conflicting": False}]
        r = rates(rows, "markets")
        self.assertEqual(r["total"]["source_eligible"], 2)
        self.assertEqual(r["total"]["ratio"], .5)
        self.assertEqual(r["asian_handicap"]["quarantined_or_conflicting"], 1)


class FTTests(unittest.TestCase):
    def setUp(self):
        self.f = {"sha256": "old", "match_key": "one", "known_at": BEFORE, "kickoff_utc": KO}
        self.e = {"id": "e", "written_at": AFTER, "event": {
            "event_id": "e", "match_key": "one", "frozen_source_sha256": "old",
            "frozen_known_at": BEFORE, "kickoff_utc": KO, "ft_checked_at": AFTER,
            "state": "CONFIRMED", "source_conflict": False}}
        self.registered = datetime(2026, 10, 28, tzinfo=timezone.utc)
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)

    def rows(self, evidence=None, forecasts=None):
        return ft_rows(forecasts or [self.f], evidence or [self.e], self.registered, self.now)

    def test_consistent_times_never_become_independent_proof(self):
        r = self.rows()[0]
        self.assertEqual(r["chronology_status"], "CONSISTENT_NOT_INDEPENDENTLY_PROVEN")
        self.assertIsNone(r["independently_proven_provider_checked_at"])
        self.assertFalse(r["training_or_result_eligible"])

    def test_uses_exact_reference_not_later_freeze(self):
        newer = {**self.f, "sha256": "new", "known_at": "2026-11-01T11:30:00+00:00"}
        self.assertEqual(self.rows(forecasts=[self.f, newer])[0]["failure_codes"], [])

    def test_wrong_match_or_missing_hash_fails(self):
        for mutation in ({"match_key": "other"}, {"frozen_source_sha256": "missing"}):
            e = copy.deepcopy(self.e)
            e["event"].update(mutation)
            self.assertIn("EXACT_FORECAST_REFERENCE_MISSING_OR_WRONG_MATCH",
                          self.rows([e])[0]["failure_codes"])

    def test_early_ft_write_does_not_certify_provider_check(self):
        e = copy.deepcopy(self.e)
        e["written_at"] = KO
        self.assertIn("FT_INGEST_BEFORE_CHECK_OR_FREEZE", self.rows([e])[0]["failure_codes"])
        e["event"]["ft_checked_at"] = KO
        self.assertIn("NO_POST_90MIN_FT_CHECK", self.rows([e])[0]["failure_codes"])

    def test_quarantine_and_conflict_never_score(self):
        e = copy.deepcopy(self.e)
        e["event"].update(state="QUARANTINED", source_conflict=True)
        rows = self.rows([self.e, {**e, "id": "quarantine"}])
        self.assertFalse(rows[0]["is_latest"])
        self.assertTrue(rows[1]["is_latest"])
        self.assertIn("FT_NOT_CONFIRMED", rows[1]["failure_codes"])
        self.assertIn("FT_SOURCE_CONFLICT", rows[1]["failure_codes"])
        self.assertFalse(any(r["training_or_result_eligible"] for r in rows))

    def test_future_or_missing_time_is_blocked(self):
        for when in (None, "2026-12-01T00:00:00+00:00"):
            e = copy.deepcopy(self.e)
            e["written_at"] = when
            self.assertIn("FT_INGEST_IN_FUTURE", self.rows([e])[0]["failure_codes"])


class SourceCommitTests(unittest.TestCase):
    """Real local Git repositories; rejection tests exercise CLI before any output."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "source"
        self.root.mkdir()
        self.output = Path(self.tmp.name) / "not-created" / "audit.json"
        self.git("init", "-q")
        now = datetime.fromisoformat(AFTER)
        registration = {"registered_at": BEFORE}
        registration["sha256"] = a1.sha256(a1.canonical(registration).encode())
        inputs = {
            "data/state.json": json.dumps({"alerts": []}),
            "data/lab/v6-hypotheses.jsonl": json.dumps(registration),
            "docs/lab/v6-readiness.json": json.dumps(a1.measure([], [], now)),
            "docs/lab/v6-p0-gates.json": json.dumps({"evaluation_clock": AFTER,
                "ft_knowledge_timeline": a1.ft_chronology([], [], now, now), "data_lineage": {}}),
            "reports/incidents/one/receipt.json": "{}",
            **{"data/lab/" + prefix + "-2026-11.jsonl": "" for prefix in a1.MONTHLY_INPUTS},
        }
        for name, content in inputs.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.source = self.commit()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=A1 test", "-c", "user.email=a1@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()
                and ".git" not in p.relative_to(self.root).parts}

    def rejected(self, sha=None, message=None):
        before = self.files()
        with self.assertRaisesRegex(ValueError, message or "."):
            main(["--root", str(self.root), "--source-sha", sha or self.source,
                  "--output", str(self.output)])
        self.assertFalse(self.output.parent.exists())
        self.assertEqual(before, self.files())

    def test_exact_local_objects_prove_inventory_and_bytes(self):
        before = self.files()
        proof = a1.verify_source_commit(self.root, self.source)
        self.assertEqual(set(proof["input_blobs"]), set(before))
        self.assertEqual(proof["input_sha256"], {p: a1.sha256(v) for p, v in before.items()})
        self.assertEqual(before, self.files())

    def test_nonexistent_and_malformed_commits_rejected_without_output(self):
        for sha in ("a" * 40, "abc", "A" * 40):
            with self.subTest(sha=sha):
                self.rejected(sha)

    def test_real_but_wrong_commit_rejected_without_output(self):
        path = self.root / "data/state.json"
        original = path.read_bytes()
        path.write_text('{"alerts": [], "tampered": true}')
        wrong = self.commit()
        path.write_bytes(original)
        self.rejected(wrong, "differs from declared commit")

    def test_every_input_mutation_and_deletion_rejected_without_output(self):
        for name, content in self.files().items():
            path = self.root / name
            for mutation in ("modified", "missing"):
                with self.subTest(name=name, mutation=mutation):
                    if mutation == "modified":
                        path.write_bytes(content + b" ")
                    else:
                        path.unlink()
                    try:
                        self.rejected()
                    finally:
                        path.write_bytes(content)

    def test_extra_month_part_or_receipt_rejected_without_output(self):
        for name in ("data/lab/markets-2026-12.jsonl",
                     "data/lab/v6-forecasts-2026-11-part0001.jsonl",
                     "reports/incidents/extra-receipt.json"):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text("{}")
                try:
                    self.rejected(message="inventory mismatch")
                finally:
                    path.unlink()

    def test_no_git_checkout_and_nested_root_rejected_without_output(self):
        gitdir = self.root / ".git"
        moved = self.root / ".git-hidden"
        gitdir.rename(moved)
        try:
            self.rejected()
        finally:
            moved.rename(gitdir)
        with self.assertRaisesRegex(ValueError, "checkout root"):
            a1.verify_source_commit(self.root / "data", self.source)

    def test_missing_commit_tree_and_blob_objects_rejected_without_output(self):
        for oid in (self.source, self.git("rev-parse", "HEAD^{tree}"),
                    self.git("rev-parse", "HEAD:data/state.json")):
            with self.subTest(oid=oid):
                path = self.root / ".git/objects" / oid[:2] / oid[2:]
                original = path.read_bytes()
                path.unlink()
                try:
                    self.rejected(message="objects unavailable")
                finally:
                    path.write_bytes(original)

    def test_partial_clone_missing_blob_cannot_lazy_fetch(self):
        remote = Path(self.tmp.name) / "available-remote.git"
        subprocess.run(["git", "clone", "--bare", str(self.root), str(remote)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.git("config", "extensions.partialClone", "origin")
        self.git("config", "remote.origin.promisor", "true")
        self.git("config", "remote.origin.url", str(remote))
        oid = self.git("rev-parse", "HEAD:data/state.json")
        path = self.root / ".git/objects" / oid[:2] / oid[2:]
        path.unlink()
        # The object exists in the configured remote. A lazy fetch would make
        # verification pass and write fetched objects, violating offline mode.
        self.rejected(message="objects unavailable")
        self.assertFalse(path.exists())
        self.assertEqual(list((self.root / ".git/objects/pack").iterdir()), [])

    def test_corrupt_blob_hash_rejected_without_output(self):
        import zlib
        oid = self.git("rev-parse", "HEAD:data/state.json")
        path = self.root / ".git/objects" / oid[:2] / oid[2:]
        path.unlink()
        path.write_bytes(zlib.compress(b"blob 2\0{}"))
        self.rejected(message="hash mismatch")

    def test_replacement_objects_cannot_fake_source(self):
        path = self.root / "data/state.json"
        path.write_text('{"alerts": [], "tampered": true}')
        replacement = self.commit()
        self.git("replace", self.source, replacement)
        self.rejected(message="differs from declared commit")

    def test_symlink_to_identical_bytes_rejected_without_output(self):
        path = self.root / "data/state.json"
        target = self.root / "elsewhere.json"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        self.rejected(message="Symlinked source input")

    def test_caller_git_overrides_do_not_redirect_verification(self):
        with patch.dict(os.environ, {"GIT_DIR": "/nonexistent", "GIT_WORK_TREE": "/nonexistent"}):
            a1.verify_source_commit(self.root, self.source)

    def test_published_ft_divergence_rejected_before_output(self):
        path = self.root / "docs/lab/v6-p0-gates.json"
        p0 = json.loads(path.read_text())
        p0["ft_knowledge_timeline"]["evidence_events_total"] = 1
        path.write_text(json.dumps(p0))
        # Commit the adversarial publication so provenance succeeds: the FT
        # reconciliation itself must block this independently valid Git snapshot.
        self.source = self.commit()
        self.rejected(message="Published FT chronology does not replay")

    def test_computed_ft_divergence_rejected_even_with_custom_clock(self):
        original = a1.ft_chronology
        def divergent(*args):
            result = original(*args)
            result["evidence_events_total"] += 1
            return result
        with patch.object(a1, "ft_chronology", side_effect=divergent) as replay:
            self.rejected(message="Published FT chronology does not replay")
            self.assertEqual(replay.call_args.args[-1], datetime.fromisoformat(AFTER))
            with self.assertRaisesRegex(ValueError, "Published FT chronology does not replay"):
                main(["--root", str(self.root), "--source-sha", self.source,
                      "--as-of", BEFORE, "--output", str(self.output)])
            self.assertEqual(replay.call_args.args[-1], datetime.fromisoformat(AFTER))
            self.assertFalse(self.output.parent.exists())


class ReadOnlyTests(unittest.TestCase):
    def test_cli_refuses_source_output_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "reports/master-brain-a1"):
                main(["--root", tmp, "--source-sha", "a"*40,
                      "--output", str(Path(tmp)/"data/state.json")])

    def test_incomplete_root_fails_without_registration_or_file_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                audit(tmp, "a"*40)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_real_replay_reconciles_without_mutating_inputs(self):
        root = Path(__file__).resolve().parents[1]
        source = "9d52a5bbf03d9301a6a3479b0e9c95e01945388c"
        try:
            a1.git_object(root, "commit", source)
        except ValueError:
            self.skipTest("Original source Git object unavailable in shallow checkout; replay separately in full clone")
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "original"
            subprocess.run(["git", "clone", "--shared", "--no-checkout", str(root), str(checkout)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", source],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with patch("socket.socket.connect", side_effect=AssertionError("Audit must stay offline")):
                r = main(["--root", str(checkout), "--source-sha", source,
                          "--output", str(Path(tmp) / "result.json")])
            original_ft_rows = a1.ft_rows
            def add_input_during_audit(*args):
                extra = checkout / "reports/incidents/extra-receipt.json"
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text("{}")
                return original_ft_rows(*args)
            late_output = Path(tmp) / "late" / "result.json"
            with patch.object(a1, "ft_rows", side_effect=add_input_during_audit):
                with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                    main(["--root", str(checkout), "--source-sha", source,
                          "--output", str(late_output)])
            self.assertFalse(late_output.parent.exists())
        self.assertTrue(r["source_commit_verified"])
        self.assertTrue(r["ft_published_reconciled"])
        self.assertEqual(r["coverage_7d"]["source_eligible"], 1030)
        self.assertEqual(r["coverage_7d"]["frozen_pre_kickoff"], 992)
        self.assertAlmostEqual(r["coverage_7d"]["exact_ratio"] * 100, 96.31067961165049)
        self.assertEqual(len(r["missing_matches"]), 38)
        self.assertEqual(len(r["ft_events"]), 420)
        self.assertEqual(r["ft_exact_reference_status_counts"],
                         {"CONSISTENT_NOT_INDEPENDENTLY_PROVEN": 360, "INVALID": 60})
        self.assertTrue(r["source_bytes_unchanged"])
        self.assertTrue(r["published_readiness_replayed"])
        self.assertEqual(len(r["missing_matches"]), r["coverage_7d"]["missing_count"])
        self.assertEqual(len(r["ft_events"]), r["observed_lineage"]["ft_memory_events"])
        self.assertFalse(any(x["training_or_result_eligible"] for x in r["matches"] + r["ft_events"]))
        self.assertEqual(r["cost"], {"llm_calls": 0, "neurons": 0, "provider_calls": 0})


if __name__ == "__main__":
    unittest.main()
