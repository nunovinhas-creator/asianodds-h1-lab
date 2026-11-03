"""V4 regression suite re-run against tools/p0_stability_audit_v5.py (#107): every V4 behaviour is kept.
transient integrity changes.  No network: GitHub calls are mocked; git tests use a
throwaway repository (or the real baseline commits when the clone has them)."""
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tools import p0_stability_audit_v5 as audit

START = datetime(2026, 11, 2, 9, 58, 45, tzinfo=timezone.utc)
REAL_BASELINE = "b8bc46cab95549a3f43a5b05dd3c5693af723398"
LATER_COMMIT = "2fbc3e93f6482707c82d23a7a12873021582262c"
REPO_ROOT = Path(__file__).resolve().parents[1]


def T(minutes=0, hours=0):
    return START + timedelta(minutes=minutes, hours=hours)


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(created, updated=None, status="completed", conclusion="success", rid=1):
    return {"id": rid, "created_at": ts(created), "updated_at": ts(updated or created),
            "status": status, "conclusion": conclusion, "event": "schedule", "head_sha": "x"}


def receipt_line(prefix, when, **doc):
    return f"{ts(when)} {prefix}_PUBLISH_RECEIPT {json.dumps(doc)}"


def in_real_clone(*shas):
    cwd = os.getcwd()
    try:
        os.chdir(REPO_ROOT)
        return all(audit.has_commit(s) for s in shas)
    finally:
        os.chdir(cwd)


class BaselineTests(unittest.TestCase):
    def test_constants_point_to_window_start_commit(self):
        self.assertEqual(audit.BASELINE_COMMIT, REAL_BASELINE)
        self.assertEqual(audit.WINDOW_START, "2026-11-02T09:58:45Z")
        self.assertEqual(audit.BASELINE_COUNTS, {
            "ft": {"FINAL": 446, "EXPIRED_UNVERIFIED": 423, "PENDING": 308,
                   "IDENTITY_CONFLICT": 1},
            "h1_certified": 116, "telegram_sent": 13})
        self.assertIn(LATER_COMMIT, audit.REJECTED_BASELINES)
        self.assertNotIn(audit.BASELINE_COMMIT, audit.REJECTED_BASELINES)

    def test_correct_baseline_accepted_with_injected_facts(self):
        counts = {"ft": dict(audit.BASELINE_COUNTS["ft"]), "h1_certified": 116,
                  "telegram_sent": 13}
        self.assertEqual(audit.verify_baseline(REAL_BASELINE, START, counts=counts,
                                               ctime=START, last_before=REAL_BASELINE), [])

    def test_later_commit_rejected_with_injected_facts(self):
        counts = {"ft": {"FINAL": 447, "EXPIRED_UNVERIFIED": 427, "PENDING": 305,
                         "IDENTITY_CONFLICT": 1}, "h1_certified": 116, "telegram_sent": 13}
        probs = audit.verify_baseline(LATER_COMMIT, START, counts=counts,
                                      ctime=datetime(2026, 11, 2, 10, 7, 14, tzinfo=timezone.utc),
                                      last_before=REAL_BASELINE)
        text = " | ".join(probs)
        self.assertIn("posterior", text)
        self.assertIn("FT FINAL: 447", text)
        self.assertIn("rejeitada", text)
        self.assertIn(REAL_BASELINE[:12], text)

    @unittest.skipUnless(in_real_clone(REAL_BASELINE, LATER_COMMIT),
                         "real baseline commits not in this clone (shallow)")
    def test_real_commits(self):
        cwd = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            self.assertEqual(audit.snapshot_counts(REAL_BASELINE), audit.BASELINE_COUNTS)
            self.assertEqual(audit.commit_time(REAL_BASELINE), START)
            self.assertEqual(audit.verify_baseline(REAL_BASELINE, START), [])
            later = audit.snapshot_counts(LATER_COMMIT)
            self.assertEqual(later["ft"]["FINAL"], 447)
            probs = audit.verify_baseline(LATER_COMMIT, START)
            self.assertTrue(any("posterior" in p for p in probs), probs)
            self.assertTrue(any("FT FINAL: 447" in p for p in probs), probs)
            # the real window history between them carries no transient violation
            p, _, s = audit.history_integrity(REAL_BASELINE, LATER_COMMIT)
            self.assertEqual(p, [])
            self.assertGreater(s["commits_walked"], 0)
        finally:
            os.chdir(cwd)


class EvidenceTests(unittest.TestCase):
    end = T(hours=24)

    def a(self, r, log="", err=None, prefix="COLLECT", steps=None):
        return audit.analyse_run(r, prefix, log, START, self.end, log_error=err, now=self.end,
                                 steps=steps)

    def test_completed_with_receipt(self):
        row = self.a(run(T(5), T(9)), receipt_line("COLLECT", T(8), status="PUBLISHED",
                                                   attempt=1, published_commit="abc"))
        self.assertEqual((row["evidence"], row["category"], row["position"]),
                         (audit.EV_RECEIPT, "FIRST_ATTEMPT", audit.POS_IN))
        self.assertEqual(row["published_at"], ts(T(8)))
        self.assertFalse(row["evidence_gap"])

    def test_completed_nothing_to_publish_receipt_is_not_a_gap(self):
        row = self.a(run(T(5)), receipt_line("COLLECT", T(5), status="NOTHING_TO_PUBLISH"))
        self.assertEqual(row["category"], "NOTHING_TO_PUBLISH")
        self.assertFalse(row["evidence_gap"])

    def test_green_without_receipt_is_gap_not_publication(self):
        row = self.a(run(T(5), conclusion="success"), "some output\nno receipt here")
        self.assertEqual(row["evidence"], audit.EV_GREEN_NO_RECEIPT)
        self.assertTrue(row["evidence_gap"])
        self.assertNotIn(row["category"], audit.PUBLISHED_CATS)
        self.assertIsNone(row["published_at"])

    def test_logs_unavailable_and_api_error_are_gaps(self):
        for err in (audit.EV_LOGS_UNAVAILABLE, audit.EV_API_ERROR):
            row = self.a(run(T(5)), f"{audit.LOG_UNAVAILABLE} HTTP 404", err=err)
            self.assertEqual(row["evidence"], err)
            self.assertTrue(row["evidence_gap"])
            self.assertEqual(row["category"], "EVIDENCE_GAP")

    def test_receipt_wins_over_partial_log_failure(self):
        log = receipt_line("COLLECT", T(6), status="PUBLISHED", attempt=1)
        row = self.a(run(T(5)), log, err=None)
        self.assertEqual(row["evidence"], audit.EV_RECEIPT)

    def test_in_progress_at_window_close(self):
        row = self.a(run(T(hours=23, minutes=55), status="in_progress", conclusion=None))
        self.assertEqual(row["evidence"], audit.EV_IN_PROGRESS)
        self.assertTrue(row["evidence_gap"])
        # completed after the close without receipt: still "in progress at close"
        row = self.a(run(T(hours=23, minutes=55), T(hours=24, minutes=3)), "")
        self.assertEqual(row["evidence"], audit.EV_IN_PROGRESS)

    def test_unreadable_receipt(self):
        log = f"{ts(T(6))} COLLECT_PUBLISH_RECEIPT {{\"status\": \"PUBLISHED\", trunc"
        row = self.a(run(T(5)), log)
        self.assertEqual(row["evidence"], audit.EV_RECEIPT_UNREADABLE)
        self.assertTrue(row["evidence_gap"])

    def test_other_producer_receipt_is_not_unreadable(self):
        log = receipt_line("LAB_FT", T(6), status="PUBLISHED")
        row = self.a(run(T(5)), log, prefix="FT")
        self.assertEqual(row["evidence"], audit.EV_GREEN_NO_RECEIPT)

    def test_dedup_cycle_with_publish_steps_skipped(self):
        steps = [{"job": "results", "step": "Avoid duplicate queued result cycles",
                  "conclusion": "success"},
                 {"job": "results", "step": "Publish confirmed finals and audit",
                  "conclusion": "skipped"},
                 {"job": "results", "step": "Keep the H1 publication receipt",
                  "conclusion": "skipped"}]
        row = self.a(run(T(5)), "", prefix="H1", steps=steps)
        self.assertEqual(row["evidence"], audit.EV_NO_PUBLISH_ATTEMPT)
        self.assertFalse(row["evidence_gap"])
        self.assertNotIn(row["category"], audit.PUBLISHED_CATS)
        gaps = audit.evidence_gaps({"results.yml": [row]})
        self.assertEqual([(g["kind"], g["blocking"]) for g in gaps],
                         [(audit.EV_NO_PUBLISH_ATTEMPT, False)])

    def test_publish_step_that_ran_without_receipt_stays_a_gap(self):
        steps = [{"job": "results", "step": "Publish confirmed finals and audit",
                  "conclusion": "success"},
                 {"job": "results", "step": "Keep the H1 publication receipt",
                  "conclusion": "skipped"}]
        row = self.a(run(T(5)), "", prefix="H1", steps=steps)
        self.assertEqual(row["evidence"], audit.EV_GREEN_NO_RECEIPT)
        self.assertTrue(row["evidence_gap"])
        # no step data at all (API failure) also stays a gap
        row = self.a(run(T(5)), "", prefix="H1", steps=None)
        self.assertEqual(row["evidence"], audit.EV_GREEN_NO_RECEIPT)

    def test_failed_without_receipt_is_observed_failure_not_gap(self):
        row = self.a(run(T(5), conclusion="failure"), "")
        self.assertEqual(row["evidence"], audit.EV_FAILED_NO_RECEIPT)
        self.assertFalse(row["evidence_gap"])
        self.assertEqual(row["category"], "NO_RECEIPT_WORKFLOW_FAILURE")

    def test_publication_confirmed_outside_window(self):
        row = self.a(run(T(hours=23, minutes=58), T(hours=24, minutes=2)),
                     receipt_line("COLLECT", T(hours=24, minutes=1), status="PUBLISHED",
                                  attempt=1))
        self.assertEqual(row["position"], audit.POS_PUBLISHED_AFTER)
        self.assertEqual(audit.in_window([row]), [])


def lab_empty():
    return {"alerts": []}


class ClassificationTests(unittest.TestCase):
    end = T(hours=24)

    def rows(self, *specs):
        out = []
        for i, (log, conclusion) in enumerate(specs):
            out.append(audit.analyse_run(run(T(5 + i), conclusion=conclusion, rid=100 + i),
                                         "COLLECT", log, START, self.end, now=self.end))
        return out

    def classify(self, rows, probs=(), verif=None, gaps=None):
        per = {"collect.yml": rows}
        gaps = audit.evidence_gaps(per) if gaps is None else gaps
        return audit.classification(per, lab_empty(), list(probs), verif or {}, True, [],
                                    {}, gaps)

    def test_clean_window(self):
        ok = receipt_line("COLLECT", T(6), status="PUBLISHED", attempt=1)
        level, _, gaps = self.classify(self.rows((ok, "success")))
        self.assertEqual(level, "SEM INCIDENTES NÃO RECUPERADOS NA JANELA")
        self.assertEqual(gaps, [])

    def test_green_without_receipt_cannot_be_no_incidents(self):
        ok = receipt_line("COLLECT", T(6), status="PUBLISHED", attempt=1)
        level, reasons, gaps = self.classify(self.rows((ok, "success"), ("", "success")))
        self.assertTrue(level.startswith("INCONCLUSIVO_OPERACIONAL"), level)
        self.assertNotIn("CRÍTICO", level)
        self.assertIn("101", " ".join(reasons))
        self.assertEqual([g["kind"] for g in gaps], [audit.EV_GREEN_NO_RECEIPT])

    def test_verifier_error_is_gap_not_corruption(self):
        level, _, gaps = self.classify([], verif={"archive_error": "boom"})
        self.assertTrue(level.startswith("INCONCLUSIVO_OPERACIONAL"), level)
        self.assertEqual(gaps[0]["kind"], "VERIFIER_ERROR")

    def test_api_listing_error_is_gap(self):
        gaps = [{"kind": audit.EV_API_ERROR, "workflow": "collect.yml", "run_id": None,
                 "detail": "HTTP 502"}]
        level, _, _ = self.classify([], gaps=gaps)
        self.assertTrue(level.startswith("INCONCLUSIVO_OPERACIONAL"), level)

    def test_pages_not_verified_is_listed_but_not_blocking(self):
        ok = receipt_line("COLLECT", T(6), status="PUBLISHED", attempt=1)
        gaps = [{"kind": "PAGES_NOT_VERIFIED", "workflow": "-", "run_id": None,
                 "blocking": False, "detail": "proxy 403"}]
        level, reasons, gap_list = self.classify(self.rows((ok, "success")), gaps=gaps)
        self.assertEqual(level, "SEM INCIDENTES NÃO RECUPERADOS NA JANELA")
        self.assertEqual([g["kind"] for g in gap_list], ["PAGES_NOT_VERIFIED"])
        self.assertIn("informativas=1", reasons[0])

    def test_real_violation_is_critical_and_gaps_still_reported(self):
        level, _, _ = self.classify(self.rows(("", "success")), probs=["FT FINAL alterado: k"])
        self.assertTrue(level.startswith("CRÍTICO"), level)
        self.assertIn("INCONCLUSIVO_OPERACIONAL", level)

    def test_invalid_baseline_blocks_conclusion(self):
        per = {"collect.yml": []}
        level, _, gaps = audit.classification(per, lab_empty(), [], {}, True, [], {}, [],
                                              baseline_problems=["posterior"])
        self.assertTrue(level.startswith("INCONCLUSIVO_OPERACIONAL"), level)
        self.assertEqual(gaps[-1]["kind"], "BASELINE_INVALID")

    def test_lab_gap_marks_starvation_alert_provisional(self):
        end = T(hours=2)
        pub = audit.analyse_run(run(T(1), rid=1), "LAB_V4",
                                receipt_line("LAB_V4", T(2), status="PUBLISHED", attempt=1),
                                START, end, now=end)
        gap = audit.analyse_run(run(T(40), rid=2), "LAB_V4", "", START, end, now=end)
        lab = audit.lab_metrics([pub, gap], START, end)
        self.assertEqual(lab["published"], 1)
        self.assertEqual(lab["evidence_gaps"], 1)
        self.assertEqual(lab["max_gap_evidence_gap_runs"], [2])
        self.assertTrue(any("PROVISÓRIO" in a for a in lab["alerts"]), lab["alerts"])


class WindowBoundaryTests(unittest.TestCase):
    def test_bounds_are_half_open_and_truncated(self):
        for h in (24, 48, 168):
            s, e, complete = audit.window_bounds(START, h, T(hours=h))
            self.assertEqual((s, e, complete), (START, T(hours=h), True))
            s, e, complete = audit.window_bounds(START, h, T(hours=h) - timedelta(seconds=1))
            self.assertFalse(complete)
            self.assertEqual(e, T(hours=h) - timedelta(seconds=1))

    def test_each_milestone_boundary(self):
        P = audit.window_position
        for h in (24, 48, 168):
            end = T(hours=h)
            # created exactly at the start: inside
            self.assertEqual(P(START, START, START, START, end), audit.POS_IN)
            # created exactly at the end: next window
            self.assertEqual(P(end, end, end, START, end), audit.POS_OUTSIDE)
            # started inside, published at/after the end: not this window's publication
            self.assertEqual(P(end - timedelta(seconds=30), end + timedelta(seconds=5),
                               end, START, end), audit.POS_PUBLISHED_AFTER)
            # started inside, published 1 s before the end, concluded after: inside
            self.assertEqual(P(end - timedelta(minutes=5), end + timedelta(minutes=1),
                               end - timedelta(seconds=1), START, end), audit.POS_IN)
            # started before the window, published inside: counted, flagged
            self.assertEqual(P(START - timedelta(minutes=10), T(2), T(1), START, end),
                             audit.POS_STARTED_BEFORE)
            # started and published before the window: excluded
            self.assertEqual(P(START - timedelta(minutes=10), START - timedelta(seconds=1),
                               START - timedelta(seconds=2), START, end), audit.POS_OUTSIDE)

    def test_24h_boundary_run_belongs_to_48h(self):
        r = run(T(hours=24) - timedelta(seconds=20), T(hours=24) + timedelta(seconds=40))
        log = receipt_line("H1", T(hours=24) + timedelta(seconds=10), status="PUBLISHED",
                           attempt=1)
        r24 = audit.analyse_run(r, "H1", log, START, T(hours=24), now=T(hours=24, minutes=12))
        r48 = audit.analyse_run(r, "H1", log, START, T(hours=48), now=T(hours=48))
        self.assertEqual(r24["position"], audit.POS_PUBLISHED_AFTER)
        self.assertEqual(audit.in_window([r24]), [])
        self.assertEqual(r48["position"], audit.POS_IN)
        self.assertEqual(r48["category"], "FIRST_ATTEMPT")


class GitHubErrorTests(unittest.TestCase):
    def test_run_logs_all_jobs_fail(self):
        def fake(path, raw=False, retries=2, **kw):
            if "/jobs?" in path:
                return {"jobs": [{"id": 1, "conclusion": "success"}]}
            raise audit.GhError(path, 410, "gone")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(audit, "gh", fake):
            text, err, _ = audit.run_logs({"id": 9}, Path(d))
            self.assertEqual(err, audit.EV_LOGS_UNAVAILABLE)
            self.assertEqual(list(Path(d).iterdir()), [])  # never cache a failure

    def test_run_logs_jobs_listing_fails(self):
        def fake(path, raw=False, retries=2, **kw):
            raise audit.GhError(path, 502, "bad gateway")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(audit, "gh", fake):
            _, err, _ = audit.run_logs({"id": 9}, Path(d))
            self.assertEqual(err, audit.EV_API_ERROR)

    def test_list_runs_error_recorded(self):
        def fake(path, raw=False, retries=2):
            raise audit.GhError(path, 500, "boom")
        gaps = []
        with mock.patch.object(audit, "gh", fake):
            self.assertEqual(audit.list_runs("collect.yml", START, T(hours=1), gaps), [])
        self.assertTrue(gaps)
        self.assertEqual(gaps[0]["kind"], audit.EV_API_ERROR)


def gh_raw(status, headers, body):
    head = f"HTTP/2.0 {status} X\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return (head + "\r\n").encode() + body.encode()


class ApiBudgetTests(unittest.TestCase):
    def fake_run(self, responses, calls):
        def run(cmd, capture_output=True, **kw):
            calls.append(cmd[-1])
            status, headers, body = responses.pop(0)
            return subprocess.CompletedProcess(cmd, 0 if status < 300 else 1,
                                               gh_raw(status, headers, body), b"")
        return run

    def test_retry_after_is_honoured_and_headers_tracked(self):
        b = audit.ApiBudget(rps=1000, reserve=10)
        calls, waits = [], []
        responses = [(403, {"Retry-After": "7", "X-RateLimit-Remaining": "50"},
                      '{"message":"You have exceeded a secondary rate limit"}'),
                     (200, {"X-RateLimit-Remaining": "49", "X-RateLimit-Reset": "123",
                            "X-RateLimit-Limit": "15000"}, '{"ok": 1}')]
        with mock.patch.object(audit.subprocess, "run", self.fake_run(responses, calls)), \
                mock.patch.object(audit.time, "sleep", lambda s: waits.append(s)):
            self.assertEqual(audit.gh("x", budget=b), {"ok": 1})
        self.assertEqual(len(calls), 2)
        self.assertIn(7.0, waits)
        self.assertEqual((b.remaining, b.limit, b.min_remaining), (49, 15000, 49))

    def test_primary_limit_exhausted_waits_for_reset(self):
        b = audit.ApiBudget(rps=1000, reserve=10)
        waits = []
        reset = int(audit.time.time()) + 30
        responses = [(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)},
                      '{"message":"API rate limit exceeded"}'),
                     (200, {"X-RateLimit-Remaining": "14999"}, "[]")]
        with mock.patch.object(audit.subprocess, "run", self.fake_run(responses, [])), \
                mock.patch.object(audit.time, "sleep", lambda s: waits.append(s)):
            audit.gh("x", budget=b)
        self.assertTrue(any(25 <= w <= 40 for w in waits), waits)

    def test_wait_budget_exhaustion_is_an_error_not_silence(self):
        b = audit.ApiBudget(rps=1000, reserve=10, max_wait_s=5)
        responses = [(429, {"Retry-After": "60"}, "{}")]
        with mock.patch.object(audit.subprocess, "run", self.fake_run(responses, [])), \
                mock.patch.object(audit.time, "sleep", lambda s: None):
            with self.assertRaises(audit.GhError):
                audit.gh("x", budget=b)
        self.assertTrue(b.exhausted)
        with self.assertRaises(audit.GhError):  # every later call fails fast -> gaps
            b.guard()

    def test_low_remaining_pauses_before_request(self):
        b = audit.ApiBudget(rps=1000, reserve=100)
        b.remaining, b.reset = 20, int(audit.time.time()) + 10
        waits = []
        with mock.patch.object(audit.time, "sleep", lambda s: waits.append(s)):
            b.guard()
        self.assertTrue(waits and waits[0] >= 5)


class CoverageAndCacheTests(unittest.TestCase):
    def test_segment_count_mismatch_is_gap(self):
        def fake(path, raw=False, retries=3, budget=None):
            return {"total_count": 3, "workflow_runs": [
                {"id": 1, "created_at": ts(T(1))}, {"id": 2, "created_at": ts(T(2))}]}
        gaps, cov = [], []
        with mock.patch.object(audit, "gh", fake):
            audit.list_runs("collect.yml", START, T(hours=1), gaps, cov)
        self.assertTrue(any(g["kind"] == "SEGMENT_INCOMPLETE" for g in gaps))
        self.assertFalse(cov[0]["complete"])

    def test_full_segment_is_complete(self):
        def fake(path, raw=False, retries=3, budget=None):
            return {"total_count": 1, "workflow_runs": [{"id": 1, "created_at": ts(T(1))}]}
        gaps, cov = [], []
        with mock.patch.object(audit, "gh", fake):
            audit.list_runs("collect.yml", START, T(hours=1), gaps, cov)
        self.assertEqual(gaps, [])
        self.assertTrue(all(c["complete"] for c in cov))

    @staticmethod
    def zip_of(files):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, text in files.items():
                z.writestr(name, text)
        return buf.getvalue()

    RECEIPT = '2026-11-02T10:00:00Z COLLECT_PUBLISH_RECEIPT {"status": "PUBLISHED"}\n'

    def fake_logs(self, calls, files=None, jobs=None, job_log=""):
        files = files if files is not None else {"0_collect.txt": self.RECEIPT + "noise line\n",
                                                 "collect/1_step.txt": "noise"}
        def fake(path, raw=False, retries=3, budget=None, binary=False):
            calls.append(path)
            if "/attempts/" in path:
                self.assertTrue(binary)
                return self.zip_of(files)
            if "/jobs?" in path:
                return {"jobs": jobs or []}
            return job_log
        return fake

    def test_one_request_per_run_and_validated_cache(self):
        r = {"id": 9, "run_attempt": 1, "updated_at": "2026-11-02T10:01:00Z"}
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(audit, "gh", self.fake_logs(calls)):
            text, err, _ = audit.run_logs(r, Path(d))
            self.assertIsNone(err)
            self.assertIn("COLLECT_PUBLISH_RECEIPT", text)
            self.assertNotIn("noise", text)
            self.assertEqual(calls, [f"repos/{audit.REPO}/actions/runs/9/attempts/1/logs"])
            rec = json.loads((Path(d) / "9-a1.json").read_text())
            self.assertEqual(len(rec["logs"][1]["log_sha256"]), 64)
            self.assertEqual(len(rec["logs"]), 2)  # zip + 1 top-level job file
            audit.run_logs(r, Path(d))
            self.assertEqual(len(calls), 1)  # served from validated cache
            rec["lines"] = []  # tampered record -> refetched
            (Path(d) / "9-a1.json").write_text(json.dumps(rec))
            audit.run_logs(r, Path(d))
            self.assertEqual(len(calls), 2)
            audit.run_logs({**r, "run_attempt": 2}, Path(d))  # re-run attempt -> refetched
            self.assertEqual(calls[-1], f"repos/{audit.REPO}/actions/runs/9/attempts/2/logs")

    def test_no_receipt_fetches_steps_for_dedup_proof(self):
        jobs = [{"id": 1, "name": "results", "conclusion": "success",
                 "steps": [{"name": "Publish confirmed finals", "conclusion": "skipped"}]}]
        calls = []
        r = {"id": 7, "run_attempt": 1, "updated_at": "x"}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
                audit, "gh", self.fake_logs(calls, files={"0_results.txt": "quiet"}, jobs=jobs)):
            text, err, steps = audit.run_logs(r, Path(d))
        self.assertEqual(len(calls), 2)
        self.assertTrue(audit.publish_steps_all_skipped(steps))

    def test_zip_missing_a_job_falls_back_to_job_logs(self):
        jobs = [{"id": 1, "name": "a", "conclusion": "success", "steps": []},
                {"id": 2, "name": "b", "conclusion": "success", "steps": []}]
        calls = []
        r = {"id": 8, "run_attempt": 1, "updated_at": "x"}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
                audit, "gh", self.fake_logs(calls, files={"0_a.txt": "quiet"}, jobs=jobs,
                                            job_log=self.RECEIPT)):
            text, err, _ = audit.run_logs(r, Path(d))
        self.assertIsNone(err)
        self.assertIn("COLLECT_PUBLISH_RECEIPT", text)
        self.assertEqual(len(calls), 4)  # zip + jobs + 2 job logs

    def test_coverage_identity(self):
        cov = [{"workflow": "collect.yml", "expected": 5, "retrieved": 5, "complete": True,
                "finished_before_window": 2}]
        rows = [{"position": audit.POS_IN, "evidence": audit.EV_RECEIPT},
                {"position": audit.POS_PUBLISHED_AFTER, "evidence": audit.EV_RECEIPT}]
        ok = audit.coverage_summary({"collect.yml": rows}, cov, {"collect.yml": 1})
        self.assertTrue(ok[0]["identity_ok"])
        bad = audit.coverage_summary({"collect.yml": rows}, cov, {"collect.yml": 0})
        self.assertFalse(bad[0]["identity_ok"])


class ArchiveTests(unittest.TestCase):
    base = {"status": "V6", "lab_files_checked": 72, "largest_file_bytes": 100,
            "replay": {"v6_ft_events": 2232, "v6_memories": {"evidence": 3}},
            "sealed_index_digest": "abc"}

    def test_states(self):
        S = audit.archive_state
        self.assertEqual(S({"error": None})[0], audit.ARCHIVE_INTACT)
        self.assertEqual(S({"error": "ValueError: SEALED_MONTH_MUTATED_OR_MISSING: x"})[0],
                         audit.ARCHIVE_JOURNAL_ALTERED)
        self.assertEqual(S({"error": "ValueError: Archive index is out of sync or missing"})[0],
                         audit.ARCHIVE_INDEX_INCOMPATIBLE)
        self.assertEqual(S({"error": "ValueError: Archive index version changed"})[0],
                         audit.ARCHIVE_INDEX_INCOMPATIBLE)
        self.assertEqual(S({"error": "READ: OSError: x"})[0], audit.ARCHIVE_READ_ERROR)
        self.assertEqual(S(None)[0], audit.ARCHIVE_READ_ERROR)

    def test_stale_vs_inconsistent(self):
        grown = {**self.base, "lab_files_checked": 75,
                 "replay": {"v6_ft_events": 2246, "v6_memories": {"evidence": 3}}}
        raw = {"error": "ValueError: Archive health report replay mismatch",
               "committed": self.base, "fresh": grown}
        state, detail = audit.archive_state(raw)
        self.assertEqual(state, audit.ARCHIVE_STALE)
        self.assertIn("2232→2246", detail)
        shrunk = {**self.base, "replay": {"v6_ft_events": 2000, "v6_memories": {"evidence": 3}}}
        self.assertEqual(audit.archive_state({**raw, "fresh": shrunk})[0],
                         audit.ARCHIVE_INCONSISTENT)
        digest = {**grown, "sealed_index_digest": "zzz"}
        self.assertEqual(audit.archive_state({**raw, "fresh": digest})[0],
                         audit.ARCHIVE_INCONSISTENT)
        self.assertEqual(audit.archive_state({**raw, "fresh": None})[0],
                         audit.ARCHIVE_READ_ERROR)

    def test_classification_mapping(self):
        per = {"collect.yml": []}
        lab = {"alerts": []}
        lvl = lambda a, fa=(): audit.classification(per, lab, [], {}, True, [], {}, [],
                                                    archive=a, freshness_alerts=fa)[0]
        self.assertTrue(lvl((audit.ARCHIVE_JOURNAL_ALTERED, "x")).startswith("CRÍTICO"))
        self.assertTrue(lvl((audit.ARCHIVE_INDEX_INCOMPATIBLE, "x")).startswith("DEGRADADO"))
        self.assertTrue(lvl((audit.ARCHIVE_READ_ERROR, "x")).startswith("INCONCLUSIVO"))
        self.assertTrue(lvl((audit.ARCHIVE_INCONSISTENT, "x")).startswith("INCONCLUSIVO"))
        self.assertEqual(lvl((audit.ARCHIVE_STALE, "x")),
                         "SEM INCIDENTES NÃO RECUPERADOS NA JANELA")
        self.assertTrue(lvl((audit.ARCHIVE_STALE, "x"), ["90 min"]).startswith("DEGRADADO"))

    def test_stale_episodes(self):
        R, J = "docs/lab/v6-archive-health.json", "data/lab/x.jsonl"
        cs = [{"t": T(0), "files": [R]}, {"t": T(1), "files": [J]}, {"t": T(3), "files": [J]},
              {"t": T(6), "files": [R, J]}, {"t": T(7), "files": ["data/lab/v6-archive-index.json"]},
              {"t": T(8), "files": [J]}]
        eps, open_since = audit.stale_episodes(cs)
        self.assertEqual(eps, [(T(1), T(6))])
        self.assertEqual(open_since, T(8))


class BoundaryTests(unittest.TestCase):
    """Snapshot A (pushed before the close) vs snapshot B (pushed at/after the close),
    attributed by GitHub's ref-update time, never by the commit date."""
    END = T(hours=24)
    FIN = {"k": {"status": "FINAL", "score": "2-1"}, "e": {"status": "EXPIRED_UNVERIFIED"}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.patch = mock.patch.object(audit, "telegram_ledgers", lambda rev=None: ["data/tg.json"])
        self.patch.start()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        os.makedirs("data/lab", exist_ok=True)
        self.acts, self.prev = [], None
        self.base = self.commit(self.FIN, pushed=None, msg="base")

    def tearDown(self):
        self.patch.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *a, env=None):
        return subprocess.run(["git", *a], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    def commit(self, ft, pushed, commit_date=None, msg="c", push=True):
        """Create a commit whose COMMIT date may differ from its PUSH time."""
        Path(audit.FT_LEDGER).write_text(json.dumps({"matches": ft}))
        Path("marker.txt").write_text(msg)
        Path(audit.RESULTS_CSV).write_text("match_key,h1\nk1,1-0\n")
        Path("data/tg.json").write_text(json.dumps({"entries": {"m": {"status": "sent"}}}))
        self.git("add", "-A")
        when = ts(commit_date or pushed or START)
        env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
        self.git("commit", "-q", "-m", msg, env=env)
        sha = self.git("rev-parse", "HEAD")
        if pushed is not None and push:
            self.acts.append({"ts": ts(pushed), "type": "push", "before": self.prev,
                              "after": sha})
        self.prev = sha
        return sha

    def audit(self, head, acts=None, end=None):
        return audit.boundary_audit(self.base, head, list(reversed(acts or self.acts)),
                                    end or self.END, is_append_only=lambda p: False)

    def bad(self):
        return {**self.FIN, "k": {"status": "FINAL", "score": "9-9"}}

    def test_one_second_before_exactly_at_and_five_minutes_after(self):
        a = self.commit(self.FIN, self.END - timedelta(seconds=1), msg="a")
        b = self.commit(self.FIN, self.END, msg="b")
        c = self.commit(self.FIN, self.END + timedelta(minutes=5), msg="c")
        r = self.audit(c)
        self.assertEqual(r["cutoff"], a)                # 1 s before -> A
        self.assertEqual(r["commits_A"], [a])
        self.assertEqual(r["commits_B"], [b, c])        # exactly at the close -> B
        self.assertEqual(r["first_push_after_end"], ts(self.END))

    def test_final_changed_and_reverted_inside_window_is_in_A(self):
        bad = self.commit(self.bad(), T(hours=3), msg="bad")
        self.commit(self.FIN, T(hours=4), msg="revert")
        head = self.commit(self.FIN, self.END + timedelta(minutes=5), msg="later")
        r = self.audit(head)
        self.assertTrue(any(f"FT FINAL alterado: k @ {bad[:12]}" in p for p in r["A"]["problems"]))
        self.assertEqual(r["B"]["problems"], [])
        # base-vs-cutoff state alone would not see it
        self.assertEqual(audit.compare_states(audit.snapshot(self.base),
                                              audit.snapshot(r["cutoff"])), [])

    def test_final_changed_after_window_is_only_in_B(self):
        self.commit(self.FIN, T(hours=5), msg="ok")
        bad = self.commit(self.bad(), self.END + timedelta(minutes=5), msg="bad-after")
        r = self.audit(bad)
        self.assertEqual(r["A"]["problems"], [])
        self.assertTrue(any(bad[:12] in p and "FT FINAL alterado" in p
                            for p in r["B"]["problems"]))

    def test_commit_date_is_not_the_publication_time(self):
        # committed (local clock) BEFORE the close but pushed AFTER it -> B
        late = self.commit(self.bad(), self.END + timedelta(minutes=1),
                           commit_date=self.END - timedelta(hours=2), msg="late-push")
        r = self.audit(late)
        self.assertEqual(r["cutoff"], self.base)
        self.assertEqual(r["commits_B"], [late])
        self.assertEqual(r["A"]["problems"], [])
        self.assertTrue(r["B"]["problems"])

    def test_commit_date_after_close_but_pushed_before_is_in_A(self):
        early = self.commit(self.bad(), self.END - timedelta(minutes=2),
                            commit_date=self.END + timedelta(hours=3), msg="skewed")
        r = self.audit(early)
        self.assertEqual(r["cutoff"], early)
        self.assertTrue(any(early[:12] in p for p in r["A"]["problems"]))

    def test_audit_eleven_minutes_after_close(self):
        a = self.commit(self.FIN, self.END - timedelta(minutes=4), msg="a")
        b = self.commit(self.FIN, self.END + timedelta(minutes=1), msg="b")
        c = self.commit(self.FIN, self.END + timedelta(minutes=6), msg="c")
        d = self.commit(self.FIN, self.END + timedelta(minutes=10, seconds=30), msg="d")
        r = self.audit(d)  # audit at END + 11 min sees head d
        self.assertEqual(r["cutoff"], a)
        self.assertEqual(r["commits_B"], [b, c, d])
        self.assertEqual((r["pushes_A"], r["pushes_B"]), (1, 3))
        # every commit attributed exactly once
        self.assertEqual(set(r["commits_A"]) | set(r["commits_B"]), {a, b, c, d})
        self.assertFalse(set(r["commits_A"]) & set(r["commits_B"]))

    def test_multi_commit_push_uses_push_time_for_all(self):
        x = self.commit(self.FIN, None, commit_date=T(hours=1), msg="x")
        y = self.commit(self.FIN, None, commit_date=T(hours=2), msg="y")
        self.acts.append({"ts": ts(self.END + timedelta(seconds=1)), "type": "push",
                          "before": self.base, "after": y})
        r = self.audit(y)
        self.assertEqual(r["commits_B"], [x, y])
        self.assertEqual(r["push_time"][x], ts(self.END + timedelta(seconds=1)))

    def test_missing_push_record_means_no_invented_cutoff(self):
        a = self.commit(self.FIN, T(hours=2), msg="a")
        b = self.commit(self.FIN, None, msg="unrecorded")  # push not in the activity log
        c = self.commit(self.FIN, self.END + timedelta(minutes=5), msg="c")
        self.acts[-1]["before"] = b
        r = self.audit(c)
        self.assertIsNone(r["cutoff"])
        self.assertTrue(any("interrompida" in p for p in r["chain_problems"]))

    def test_force_push_or_non_monotone_or_ambiguous_blocks_cutoff(self):
        a = self.commit(self.FIN, T(hours=2), msg="a")
        acts = [dict(x) for x in self.acts]
        acts[-1]["type"] = "force_push"
        self.assertIsNone(self.audit(a, acts)["cutoff"])
        b = self.commit(self.FIN, T(hours=1), msg="b")  # timestamp goes backwards
        self.assertIsNone(self.audit(b)["cutoff"])
        dup = [dict(x) for x in self.acts] + [{"ts": ts(T(hours=9)), "type": "push",
                                                "before": self.base, "after": b}]
        self.assertIsNone(self.audit(b, dup)["cutoff"])

    def test_chain_not_reaching_head_is_indeterminate(self):
        a = self.commit(self.FIN, T(hours=2), msg="a")
        head = self.commit(self.FIN, None, msg="not-yet-logged")
        self.assertIsNone(self.audit(head)["cutoff"])

    def test_receipt_vs_push_attribution_conflict(self):
        a = self.commit(self.FIN, self.END + timedelta(seconds=30), msg="a")
        r = self.audit(a)
        row = {"published_commit": a, "category": "FIRST_ATTEMPT", "position": audit.POS_IN,
               "run_id": 5, "published_at": ts(self.END - timedelta(seconds=5))}
        conf = audit.attribution_conflicts({"collect.yml": [row]}, r["push_time"], self.END,
                                           set(r["commits_A"]))
        self.assertEqual([c["kind"] for c in conf], ["ATTRIBUTION_CONFLICT"])
        ok = {**row, "position": audit.POS_PUBLISHED_AFTER}
        self.assertEqual(audit.attribution_conflicts({"collect.yml": [ok]}, r["push_time"],
                                                     self.END, set(r["commits_A"])), [])

    def test_activity_pagination_rewrites_cursor(self):
        pages = [
            ([{"timestamp": ts(T(hours=5)), "activity_type": "push", "before": "b", "after": "c"}],
             {"link": '<https://api.github.com/repositories/1/activity?ref=x&after=CUR%3D1>; rel="next"'}),
            ([{"timestamp": ts(START - timedelta(hours=2)), "activity_type": "pr_merge",
               "before": "a", "after": "b"}], {}),
        ]
        seen = []
        def fake(path, raw=False, retries=3, budget=None, binary=False, with_headers=False):
            seen.append(path)
            return pages.pop(0)
        with mock.patch.object(audit, "gh", fake):
            acts = audit.fetch_push_activity(START - timedelta(hours=1))
        self.assertEqual(len(acts), 2)
        self.assertTrue(seen[1].startswith(f"repos/{audit.REPO}/activity"))
        self.assertIn("after=CUR%3D1", seen[1])

    def test_activity_log_not_reaching_window_start_is_gap(self):
        def fake(path, raw=False, retries=3, budget=None, binary=False, with_headers=False):
            return ([{"timestamp": ts(T(hours=5)), "activity_type": "push", "before": "b",
                      "after": "c"}], {})
        with mock.patch.object(audit, "gh", fake):
            with self.assertRaises(audit.EvidenceGap):
                audit.fetch_push_activity(START - timedelta(hours=1))


class TransientIntegrityTests(unittest.TestCase):
    """A FINAL changed and later reverted is invisible base-vs-head but caught per commit."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.patch = mock.patch.object(audit, "telegram_ledgers", lambda rev=None: ["data/tg.json"])
        self.patch.start()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        os.makedirs("data/lab", exist_ok=True)

    def tearDown(self):
        self.patch.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *a):
        return subprocess.run(["git", *a], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, ft, results="match_key,h1\nk1,1-0\n", tg=None, journal=None, msg="c"):
        Path(audit.FT_LEDGER).write_text(json.dumps({"matches": ft}))
        Path(audit.RESULTS_CSV).write_text(results)
        Path("data/tg.json").write_text(json.dumps({"entries": tg or {"m": {"status": "sent"}}}))
        if journal is not None:
            Path("data/lab/events.jsonl").write_text(journal)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def test_reverted_change_detected(self):
        fin = {"k": {"status": "FINAL", "score": "2-1"},
               "e": {"status": "EXPIRED_UNVERIFIED"}}
        base = self.commit(fin, journal="a\n")
        bad = self.commit({**fin, "k": {"status": "FINAL", "score": "9-9"}}, journal="a\n")
        self.commit({**fin, "e": {"status": "PENDING"}}, journal="a\n")
        self.commit(fin, journal="X\n")
        head = self.commit(fin, journal="a\nb\n")
        self.assertEqual(audit.compare_states(audit.snapshot(base), audit.snapshot(head)), [])
        probs, _, summary = audit.history_integrity(
            base, head, is_append_only=lambda p: p.endswith(".jsonl"))
        joined = "\n".join(probs)
        self.assertIn(f"FT FINAL alterado: k @ {bad[:12]}", joined)
        self.assertIn("FT expirado reaberto: e -> PENDING", joined)
        self.assertIn("journal reescrito", joined)
        self.assertEqual(summary["commits_walked"], 4)

    def test_clean_history_and_telegram_rewrite(self):
        fin = {"k": {"status": "FINAL"}}
        base = self.commit(fin)
        self.commit(fin, tg={"m": {"status": "sent", "msg_id": 2}})
        head = self.commit(fin)
        probs, _, _ = audit.history_integrity(base, head, is_append_only=lambda p: False)
        self.assertTrue(any("Recibo Telegram terminal alterado" in p for p in probs), probs)
        clean_head = self.commit({"k": {"status": "FINAL"}, "n": {"status": "PENDING"}})
        probs, _, _ = audit.history_integrity(head, clean_head, is_append_only=lambda p: False)
        self.assertEqual(probs, [])

    def test_missing_history_is_gap(self):
        base = self.commit({"k": {"status": "FINAL"}})
        with self.assertRaises(audit.EvidenceGap):
            audit.history_integrity("0" * 40, base, is_append_only=lambda p: False)


if __name__ == "__main__":
    unittest.main()
