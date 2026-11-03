"""V6 activation gate: mutual exclusion, rolling six-hour cadence, failure backoff, security.

No network: the Actions API is a thread-safe in-memory fake that behaves like the REST
endpoints the gate reads; GitHub's workflow-level ``concurrency`` group is modelled by a
lock held for the whole run (gate -> evaluate -> publish), exactly its documented scope.
"""
import io
import json
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

from scripts import v6_activation_gate as g

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
REPO = "owner/repo"


def ft_event(conclusion="success", branch="main", upstream_event="schedule", repo=REPO,
             name=g.FT_WORKFLOW_NAME, run_id="1000"):
    return {"event_name": "workflow_run", "ref": g.MAIN_REF, "repository": REPO, "run_id": run_id,
            "actor": "github-actions[bot]",
            "workflow_run": {"id": 9, "name": name, "conclusion": conclusion, "head_branch": branch,
                             "event": upstream_event, "head_sha": "f" * 40,
                             "head_repository": {"full_name": repo}}}


def simple(event_name, run_id="1000", **inputs):
    return {"event_name": event_name, "ref": g.MAIN_REF, "repository": REPO, "run_id": run_id,
            "actor": inputs.pop("actor", "nunovinhas"), "inputs": inputs or None}


def attempt(hours_ago, outcome=g.SUCCEEDED, now=T0, run_id=1):
    return {"run_id": run_id, "event": "workflow_run", "outcome": outcome,
            "conclusion": {"SUCCEEDED": "success", "FAILED": "failure"}.get(outcome),
            "started_at": g.iso(now - timedelta(hours=hours_ago))}


def report(hours_ago, now=T0):
    t = g.iso(now - timedelta(hours=hours_ago))
    return {"generated_at": t, "published_at": t, "published_commit": "c" * 40, "sha256": "s" * 64,
            "main_head": "d" * 40}


class DecisionTests(unittest.TestCase):
    def test_fresh_report_skips_every_automatic_trigger(self):
        for event in (ft_event(), simple("schedule"), simple("workflow_dispatch")):
            doc = g.decide(event, now=T0, report=report(2), attempts=[attempt(2)])
            self.assertEqual((doc["decision"], doc["reason"], doc["run"]),
                             ("SKIPPED", "REPORT_FRESH", False), event["event_name"])
            self.assertEqual(doc["last_published_age_h"], 2.0)
            self.assertEqual(doc["last_published_commit"], "c" * 40)

    def test_window_elapsed_runs(self):
        doc = g.decide(ft_event(), now=T0, report=report(6.01), attempts=[attempt(6.02)])
        self.assertEqual((doc["decision"], doc["mode"]), ("RUN", "NORMAL"))
        self.assertEqual(doc["upstream"]["conclusion"], "success")

    def test_exactly_six_hours_is_eligible_and_just_under_is_not(self):
        self.assertTrue(g.decide(simple("schedule"), now=T0, report=report(6), attempts=[])["run"])
        self.assertFalse(g.decide(simple("schedule"), now=T0, report=report(5.99), attempts=[])["run"])

    def test_recent_attempt_blocks_even_when_the_report_is_old(self):
        # An attempt that did not publish (failure or SUPERSEDED) still consumes its window.
        for outcome, reason in ((g.FAILED, "RECENT_FAILED_ATTEMPT"), (g.SUCCEEDED, "RECENT_ATTEMPT")):
            doc = g.decide(ft_event(), now=T0, report=report(20), attempts=[attempt(1, outcome)])
            self.assertEqual((doc["decision"], doc["reason"]), ("SKIPPED", reason))

    def test_superseded_attempt_is_reported_as_unpublished_and_recovered_after_window(self):
        doc = g.decide(ft_event(), now=T0, report=report(13), attempts=[attempt(6.5)])
        self.assertEqual((doc["decision"], doc["mode"]), ("RUN", "RECOVERY_AFTER_UNPUBLISHED"))
        self.assertTrue(doc["last_attempt_unpublished"])

    def test_backoff_grows_and_is_capped(self):
        self.assertEqual([g.hours(g.required_gap(k)) for k in range(6)], [6, 6, 12, 24, 24, 24])
        fails = [attempt(7, g.FAILED, run_id=3), attempt(13, g.FAILED, run_id=2)]
        doc = g.decide(ft_event(), now=T0, report=report(30), attempts=fails)
        self.assertEqual((doc["decision"], doc["reason"], doc["consecutive_failures"]),
                         ("SKIPPED", "BACKOFF_AFTER_FAILURES", 2))
        doc = g.decide(ft_event(), now=T0, report=report(30),
                       attempts=[attempt(12.1, g.FAILED, run_id=3), attempt(20, g.FAILED, run_id=2)])
        self.assertEqual((doc["decision"], doc["mode"]), ("RUN", "RECOVERY_AFTER_FAILURE"))

    def test_truncated_history_of_failures_assumes_the_longest_backoff(self):
        fails = [attempt(13, g.FAILED, run_id=3)]
        self.assertTrue(g.decide(ft_event(), now=T0, report=report(30), attempts=fails)["run"])
        doc = g.decide(ft_event(), now=T0, report=report(30), attempts=fails, history_truncated=True)
        self.assertEqual((doc["consecutive_failures"], doc["required_gap_h"], doc["run"]), (3, 24.0, False))
        ok = [attempt(13, g.FAILED, run_id=3), attempt(20, g.SUCCEEDED, run_id=2)]
        self.assertTrue(g.decide(ft_event(), now=T0, report=report(20), attempts=ok,
                                 history_truncated=True)["run"])

    def test_success_resets_the_failure_count(self):
        attempts = [attempt(7, g.FAILED, run_id=3), attempt(14, g.SUCCEEDED, run_id=2),
                    attempt(20, g.FAILED, run_id=1)]
        doc = g.decide(ft_event(), now=T0, report=report(14), attempts=attempts)
        self.assertEqual((doc["consecutive_failures"], doc["decision"]), (1, "RUN"))

    def test_older_attempt_in_progress_refuses(self):
        doc = g.decide(simple("schedule"), now=T0, report=report(9),
                       attempts=[attempt(0.1, g.IN_PROGRESS)])
        self.assertEqual(doc["reason"], "CONCURRENT_ATTEMPT_IN_PROGRESS")

    def test_unavailable_state_fails_closed_for_automatic_triggers(self):
        for event in (ft_event(), simple("schedule"), simple("workflow_dispatch")):
            doc = g.decide(event, now=T0, report={}, attempts=[],
                           state_error=g.GateStateUnavailable("api down"))
            self.assertFalse(doc["run"])
            self.assertTrue(doc["reason"].startswith("GATE_STATE_UNAVAILABLE"))

    def test_first_ever_run_without_report_or_history_runs(self):
        self.assertEqual(g.decide(simple("schedule"), now=T0, report={}, attempts=[])["decision"], "RUN")

    def test_report_from_the_future_never_triggers_a_compute(self):
        doc = g.decide(simple("schedule"), now=T0, report=report(-1), attempts=[])
        self.assertEqual(doc["reason"], "REPORT_FRESH")


class SecurityTests(unittest.TestCase):
    def test_only_successful_ft_on_main_of_this_repository(self):
        cases = {
            "UPSTREAM_NOT_SUCCESS:failure": ft_event(conclusion="failure"),
            "UPSTREAM_NOT_SUCCESS:cancelled": ft_event(conclusion="cancelled"),
            "UPSTREAM_NOT_SUCCESS:None": ft_event(conclusion=None),
            "UPSTREAM_NOT_MAIN:feature": ft_event(branch="feature"),
            "UPSTREAM_FROM_PULL_REQUEST": ft_event(upstream_event="pull_request"),
            "UPSTREAM_FOREIGN_REPOSITORY:evil/fork": ft_event(repo="evil/fork"),
            "UPSTREAM_NOT_FT_WORKFLOW:Other": ft_event(name="Other"),
        }
        for reason, event in cases.items():
            # Even with a stale report and no history, nothing runs.
            doc = g.decide(event, now=T0, report=report(48), attempts=[])
            self.assertEqual((doc["decision"], doc["reason"], doc["run"]), ("SKIPPED", reason, False))

    def test_non_main_ref_never_runs_automatically_or_forced(self):
        for event in (simple("schedule"), simple("workflow_dispatch", force="true", reason="x")):
            event["ref"] = "refs/heads/other"
            self.assertFalse(g.decide(event, now=T0, report={}, attempts=[])["run"])

    def test_pull_request_runs_ci_only(self):
        doc = g.decide(simple("pull_request"), now=T0, report=report(1), attempts=[attempt(0.5)])
        self.assertEqual(doc["decision"], "RUN_PR_CI")

    def test_upstream_failure_reads_no_state_at_all(self):
        api = mock.Mock(side_effect=AssertionError("no API call for an ineligible trigger"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "event.json"
            path.write_text(json.dumps({"workflow_run": ft_event(conclusion="failure")["workflow_run"]}))
            env = {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REF": g.MAIN_REF,
                   "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "5", "GITHUB_EVENT_PATH": str(path)}
            with mock.patch.object(g, "read_published_report", api), \
                    mock.patch.object(g, "read_attempts", api):
                doc = g.run(env, Path(tmp), now=T0, api=object())
        self.assertEqual(doc["reason"], "UPSTREAM_NOT_SUCCESS:failure")


class ManualExceptionTests(unittest.TestCase):
    def test_force_with_reason_is_an_explicit_audited_exception(self):
        doc = g.decide(simple("workflow_dispatch", force=True, reason="republish after fix #213"),
                       now=T0, report=report(0.5), attempts=[attempt(0.5)])
        self.assertEqual((doc["decision"], doc["mode"]), ("RUN_FORCED_MANUAL", "FORCED_MANUAL_EXCEPTION"))
        self.assertEqual(doc["force_reason"], "republish after fix #213")
        self.assertEqual(doc["reason"], "MANUAL_FORCE_BY:nunovinhas")

    def test_force_requires_reason_and_a_human(self):
        doc = g.decide(simple("workflow_dispatch", force="true", reason="  "), now=T0,
                       report=report(0.5), attempts=[])
        self.assertEqual(doc["reason"], "FORCE_WITHOUT_REASON")
        doc = g.decide(simple("workflow_dispatch", force="true", reason="x", actor="github-actions[bot]"),
                       now=T0, report=report(0.5), attempts=[])
        self.assertTrue(doc["reason"].startswith("FORCE_BY_AUTOMATION_REFUSED"))

    FORCE = dict(force="true", reason="republish after fix")

    def test_force_bypasses_window_and_backoff_when_state_is_valid(self):
        backoff = [attempt(1, g.FAILED, run_id=3), attempt(7, g.FAILED, run_id=2),
                   attempt(19, g.FAILED, run_id=1)]
        doc = g.decide(simple("workflow_dispatch", **self.FORCE), now=T0, report=report(0.2),
                       attempts=backoff)
        self.assertEqual((doc["decision"], doc["mode"], doc["run"]),
                         ("RUN_FORCED_MANUAL", "FORCED_MANUAL_EXCEPTION", True))
        self.assertEqual(doc["consecutive_failures"], 3)        # still fully observed
        self.assertEqual(doc["last_attempt"]["run_id"], 3)

    def test_force_never_bypasses_unavailable_api(self):
        doc = g.decide(simple("workflow_dispatch", **self.FORCE), now=T0, report=report(9),
                       attempts=[], state_error=g.GateStateUnavailable("actions/runs HTTPError"))
        self.assertEqual((doc["decision"], doc["run"]), ("SKIPPED", False))
        self.assertEqual(doc["reason"], "GATE_STATE_UNAVAILABLE:actions/runs HTTPError")
        self.assertTrue(doc["force"])                           # the refused request stays audited

    def test_force_never_bypasses_inaccessible_history_end_to_end(self):
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": g.MAIN_REF,
               "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "5", "GITHUB_ACTOR": "nunovinhas"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "event.json"
            path.write_text(json.dumps({"inputs": self.FORCE}))
            env["GITHUB_EVENT_PATH"] = str(path)

            def no_history(*a, **k):
                raise OSError("connection reset")
            api = g.GitHubApi(REPO, "t", opener=no_history)
            with mock.patch.object(g, "read_published_report", return_value=report(9)):
                doc = g.run(env, Path(tmp), now=T0, api=api)
            self.assertEqual((doc["decision"], doc["force"]), ("SKIPPED", True))
            self.assertTrue(doc["reason"].startswith("GATE_STATE_UNAVAILABLE:actions/workflows/"))
            with mock.patch.object(g, "read_published_report", side_effect=ValueError("bad")):
                doc = g.run(env, Path(tmp), now=T0, api=api)
            self.assertEqual(doc["reason"], "GATE_STATE_UNAVAILABLE:ValueError: bad")

    def test_force_requires_main_verified_now(self):
        doc = g.decide(simple("workflow_dispatch", **self.FORCE), now=T0, report={}, attempts=[])
        self.assertEqual(doc["reason"], "GATE_STATE_UNAVAILABLE:MAIN_NOT_VERIFIED")

    def test_force_never_bypasses_an_earlier_run_still_active(self):
        doc = g.decide(simple("workflow_dispatch", **self.FORCE), now=T0, report=report(9),
                       attempts=[attempt(0.1, g.IN_PROGRESS)])
        self.assertEqual((doc["decision"], doc["reason"]), ("SKIPPED", "CONCURRENT_ATTEMPT_IN_PROGRESS"))

    def test_force_never_bypasses_security(self):
        event = simple("workflow_dispatch", **self.FORCE)
        event["ref"] = "refs/heads/feature"
        self.assertEqual(g.decide(event, now=T0, report=report(9), attempts=[])["reason"],
                         "NOT_MAIN_REF:refs/heads/feature")

    def test_unforced_dispatch_obeys_the_window(self):
        doc = g.decide(simple("workflow_dispatch", force=False, reason=""), now=T0,
                       report=report(0.5), attempts=[])
        self.assertEqual(doc["reason"], "REPORT_FRESH")


# ----------------------------------------------------------------- GitHub simulation

class FakeActions:
    """Thread-safe stand-in for the runs/jobs/commits endpoints and for ``main``."""

    def __init__(self, report_hours_ago=None, now=T0):
        self.lock = threading.Lock()
        self.runs = {}
        self.next_id = 100
        self.computes = []
        self.report = report(report_hours_ago, now) if report_hours_ago is not None else {}

    def create_run(self, event, at):
        with self.lock:
            self.next_id += 1
            self.runs[self.next_id] = {"id": self.next_id, "event": event, "status": "queued",
                                       "conclusion": None, "created_at": g.iso(at),
                                       "run_started_at": g.iso(at), "jobs": []}
            return self.next_id

    def get(self, path, **query):
        with self.lock:
            if path.startswith("actions/workflows/"):
                since = g.parse_time(query["created"][2:])
                if query.get("page", 1) > 1:
                    return {"workflow_runs": []}
                return {"workflow_runs": [
                    {k: v for k, v in r.items() if k != "jobs"} for r in self.runs.values()
                    if g.parse_time(r["created_at"]) >= since]}
            if path.startswith("actions/runs/"):
                return {"jobs": [dict(j) for j in self.runs[int(path.split("/")[2])]["jobs"]]}
        raise AssertionError(path)

    freshness_only = False          # the originally proposed gate: report age only

    def gate(self, run_id, event, now):
        meta = {}
        attempts = [] if self.freshness_only else g.read_attempts(self, now=now, current_run_id=run_id,
                                                                  meta=meta)
        with self.lock:
            rep = dict(self.report)
        self.last_meta = meta
        return g.decide(event, now=now, report=rep, attempts=attempts,
                        history_truncated=bool(meta.get("history_truncated")))

    def compute(self, run_id, now, *, publishes=True, conclusion="success"):
        with self.lock:
            self.computes.append((run_id, now))
            self.runs[run_id]["jobs"].append({"name": "evaluate", "conclusion": conclusion,
                                              "started_at": g.iso(now),
                                              "steps": [{"name": "Set up job", "status": "completed",
                                                         "conclusion": "success"}]})
            if publishes:
                self.report = report(0, now)

    def complete(self, run_id, conclusion="success", skipped=False):
        with self.lock:
            if skipped:
                self.runs[run_id]["jobs"].append({"name": "evaluate", "conclusion": "skipped",
                                                  "started_at": None, "steps": []})
            self.runs[run_id].update(status="completed", conclusion=conclusion)

    def workflow(self, event, now, *, mutex, v6_fails=False, publishes=True, hold=None):
        """One run of the workflow. ``mutex`` is the workflow-level concurrency group."""
        run_id = self.create_run(event["event_name"], now)
        event = dict(event, run_id=str(run_id))
        with mutex:
            with self.lock:
                self.runs[run_id]["status"] = "in_progress"
            decision = self.gate(run_id, event, now)
            if hold:
                hold()
            if decision["run"]:
                self.compute(run_id, now, publishes=publishes and not v6_fails,
                             conclusion="failure" if v6_fails else "success")
                self.complete(run_id, "failure" if v6_fails else "success")
            else:
                self.complete(run_id, skipped=True)
        return decision


class NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ConcurrencyProofTests(unittest.TestCase):
    def two_ft_events(self, mutex, gate_outside, freshness_only=False):
        gh = FakeActions(report_hours_ago=7)
        gh.freshness_only = freshness_only
        barrier = threading.Barrier(2, timeout=5)
        results = []

        def one():
            if gate_outside:
                # The rejected proposal: both gates evaluate before either computes.
                results.append(gh.workflow(ft_event(), T0, mutex=mutex, hold=barrier.wait))
            else:
                barrier.wait()          # both FT completions arrive at the same instant
                results.append(gh.workflow(ft_event(), T0 + timedelta(seconds=1), mutex=mutex))

        threads = [threading.Thread(target=one) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        return gh, results

    def test_two_near_simultaneous_ft_events_compute_exactly_once(self):
        for _ in range(25):                                  # repeat to shake out interleavings
            gh, results = self.two_ft_events(threading.Lock(), gate_outside=False)
            self.assertEqual(len(gh.computes), 1)
            self.assertEqual(sorted(r["decision"] for r in results), ["RUN", "SKIPPED"])
            skipped = [r for r in results if not r["run"]][0]
            self.assertEqual(skipped["reason"], "REPORT_FRESH")      # revalidated inside the mutex

    def test_negative_control_original_proposal_computes_twice(self):
        # Freshness-only gate evaluated outside the protected section: both pass.
        gh, results = self.two_ft_events(NoLock(), gate_outside=True, freshness_only=True)
        self.assertEqual(len(gh.computes), 2, "reproduces the race the mutex placement prevents")
        self.assertEqual([r["decision"] for r in results], ["RUN", "RUN"])

    def test_defence_in_depth_alone_still_computes_once_without_the_mutex(self):
        gh, results = self.two_ft_events(NoLock(), gate_outside=True)
        self.assertEqual(len(gh.computes), 1)
        self.assertIn("CONCURRENT_ATTEMPT_IN_PROGRESS", [r["reason"] for r in results])

    def test_failed_compute_inside_the_mutex_still_blocks_the_queued_event(self):
        gh = FakeActions(report_hours_ago=7)
        mutex = threading.Lock()
        first = gh.workflow(ft_event(), T0, mutex=mutex, v6_fails=True)
        second = gh.workflow(ft_event(), T0 + timedelta(minutes=2), mutex=mutex)
        self.assertEqual((first["decision"], second["reason"]), ("RUN", "RECENT_FAILED_ATTEMPT"))
        self.assertEqual(len(gh.computes), 1)

    def test_older_active_run_refuses_defence_in_depth(self):
        gh = FakeActions(report_hours_ago=7)
        older = gh.create_run("workflow_run", T0)           # still queued/in progress, smaller id
        doc = gh.workflow(ft_event(), T0, mutex=threading.Lock())
        self.assertEqual(doc["reason"], "CONCURRENT_ATTEMPT_IN_PROGRESS")
        self.assertEqual(gh.computes, [])
        self.assertEqual(gh.runs[older]["status"], "queued")

    def test_newer_queued_run_does_not_block_the_current_one(self):
        gh = FakeActions(report_hours_ago=7)
        current = gh.create_run("workflow_run", T0)
        gh.create_run("workflow_run", T0)                   # queued behind ``current``
        decision = gh.gate(current, ft_event(run_id=str(current)), T0)
        self.assertEqual(decision["decision"], "RUN")


class CadenceSimulationTests(unittest.TestCase):
    def simulate(self, hours, *, ft=True, schedule=True, v6_fails=lambda t: False,
                 publishes=lambda t: True, report_hours_ago=7):
        gh, mutex, events = FakeActions(report_hours_ago=report_hours_ago), threading.Lock(), []
        start = T0.replace(hour=0, minute=0)
        gh.report = report(report_hours_ago, start) if report_hours_ago is not None else {}
        for minute in range(0, hours * 60):
            now = start + timedelta(minutes=minute)
            if ft and now.minute in (12, 42):               # FT cadence '12,42 * * * *' (+~10 min)
                events.append(("ft", now + timedelta(minutes=10)))
            if schedule and now.minute == 18 and now.hour in (2, 8, 14, 20):
                events.append(("schedule", now))
        events.sort(key=lambda e: e[1])
        decisions = []
        for kind, now in events:
            event = ft_event() if kind == "ft" else simple("schedule")
            doc = gh.workflow(event, now, mutex=mutex, v6_fails=v6_fails(now),
                              publishes=publishes(now))
            decisions.append((kind, now, doc))
        return gh, decisions

    def assert_rolling_window(self, computes):
        times = [t for _, t in computes]
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, g.WINDOW)

    def test_at_most_one_compute_per_rolling_six_hours_over_three_days(self):
        gh, decisions = self.simulate(72)
        self.assertGreater(len(decisions), 140)
        self.assertLessEqual(len(gh.computes), 72 // 6 + 1)
        self.assert_rolling_window(gh.computes)
        triggers = {d["trigger"] for _, _, d in decisions if d["run"]}
        self.assertEqual(triggers, {"workflow_run"})        # FT drives; schedule only reserve

    def test_schedule_reserve_computes_when_ft_is_silent(self):
        gh, decisions = self.simulate(48, ft=False)
        runs = [(k, t) for k, t, d in decisions if d["run"]]
        self.assertTrue(runs and all(k == "schedule" for k, _ in runs))
        self.assert_rolling_window(gh.computes)
        self.assertGreaterEqual(len(runs), 4)               # every 6-12 h without FT

    def test_failure_storm_is_bounded_with_backoff(self):
        gh, decisions = self.simulate(48, v6_fails=lambda t: True)
        self.assertGreater(len(decisions), 90)              # ~96 FT completions + reserve
        computes = [t for _, t in gh.computes]
        self.assertLessEqual(len(computes), 4)              # 0 h, 6 h, 18 h, 42 h ... not ~100
        gaps = [round((b - a).total_seconds() / 3600) for a, b in zip(computes, computes[1:])]
        self.assertEqual(gaps, [6, 12, 24])
        gh, decisions = self.simulate(96, v6_fails=lambda t: True)
        computes = [t for _, t in gh.computes]
        gaps = [round((b - a).total_seconds() / 3600) for a, b in zip(computes, computes[1:])]
        self.assertEqual(gaps, [6, 12, 24, 24, 24])         # capped at 1/day, never silent
        reasons = {d["reason"] for _, _, d in decisions if not d["run"]}
        self.assertIn("BACKOFF_AFTER_FAILURES", reasons)

    def test_recovery_after_failures_resumes_normal_cadence(self):
        recovered = T0.replace(hour=0, minute=0) + timedelta(hours=20)
        gh, decisions = self.simulate(72, v6_fails=lambda t: t < recovered)
        modes = [d["mode"] for _, _, d in decisions if d["run"]]
        self.assertIn("RECOVERY_AFTER_FAILURE", modes)
        self.assertEqual(modes[-1], "NORMAL")
        self.assert_rolling_window(gh.computes)

    def test_superseded_without_publication_does_not_storm(self):
        gh, decisions = self.simulate(24, publishes=lambda t: False)
        self.assertLessEqual(len(gh.computes), 4)
        self.assert_rolling_window(gh.computes)
        self.assertIn("RECOVERY_AFTER_UNPUBLISHED", [d["mode"] for _, _, d in decisions if d["run"]])

    def test_failed_ft_never_triggers_v6(self):
        gh, mutex = FakeActions(report_hours_ago=48), threading.Lock()
        for minutes in range(0, 600, 30):
            doc = gh.workflow(ft_event(conclusion="failure"), T0 + timedelta(minutes=minutes), mutex=mutex)
            self.assertEqual(doc["reason"], "UPSTREAM_NOT_SUCCESS:failure")
        self.assertEqual(gh.computes, [])


class ForcedConcurrencyTests(unittest.TestCase):
    def test_forced_dispatch_with_an_older_run_active_does_not_compute(self):
        gh = FakeActions(report_hours_ago=0.5)
        gh.report["main_head"] = "d" * 40
        gh.create_run("workflow_run", T0)                   # older run still active
        doc = gh.workflow(simple("workflow_dispatch", force="true", reason="fix"), T0,
                          mutex=threading.Lock())
        self.assertEqual(doc["reason"], "CONCURRENT_ATTEMPT_IN_PROGRESS")
        self.assertEqual(gh.computes, [])

    def test_forced_dispatch_runs_inside_the_mutex_when_state_is_valid(self):
        gh = FakeActions(report_hours_ago=0.5)
        gh.report["main_head"] = "d" * 40
        doc = gh.workflow(simple("workflow_dispatch", force="true", reason="fix"), T0,
                          mutex=threading.Lock())
        self.assertEqual(doc["decision"], "RUN_FORCED_MANUAL")
        self.assertEqual(len(gh.computes), 1)


class PaginationTruncationTests(unittest.TestCase):
    class PagedApi:
        def __init__(self, total, failed_every=1):
            self.total, self.calls = total, []

        def get(self, endpoint, **query):
            self.calls.append((endpoint, query))
            if endpoint.startswith("actions/workflows/"):
                start = (query["page"] - 1) * query["per_page"]
                ids = list(range(self.total, 0, -1))[start:start + query["per_page"]]
                return {"workflow_runs": [{"id": i, "event": "workflow_run", "status": "completed",
                                           "conclusion": "failure", "created_at": g.iso(T0)}
                                          for i in ids]}
            run_id = int(endpoint.split("/")[2])
            executed = run_id % 50 == 0                     # a failed compute every 50 runs
            return {"jobs": [{"name": "evaluate", "conclusion": "failure" if executed else "skipped",
                              "started_at": g.iso(T0 - timedelta(minutes=10 * (self.total - run_id)))
                              if executed else None,
                              "steps": [{"conclusion": "failure"}] if executed else []}]}

    def test_page_limit_is_detected_as_truncation(self):
        api = self.PagedApi(total=g.RUNS_PER_PAGE * g.MAX_PAGES + 40)
        meta = {}
        g.list_runs(api, since="x", meta=meta)
        self.assertTrue(meta["pagination_truncated"])
        self.assertEqual(sum(1 for e, _ in api.calls if e.startswith("actions/workflows/")), g.MAX_PAGES)

    def test_short_last_page_is_not_truncation(self):
        for total in (0, 5, g.RUNS_PER_PAGE * g.MAX_PAGES - 1):
            meta = {}
            g.list_runs(self.PagedApi(total=total), since="x", meta=meta)
            self.assertFalse(meta["pagination_truncated"], total)

    def test_truncated_pagination_never_reduces_the_backoff(self):
        api = self.PagedApi(total=g.RUNS_PER_PAGE * g.MAX_PAGES + 40)
        meta = {}
        with mock.patch.object(g, "MAX_JOB_LOOKUPS", 10_000), \
                mock.patch.object(g, "BACKOFF_CAP_FAILURES", 99):
            attempts = g.read_attempts(api, now=T0, current_run_id=str(10 ** 6), meta=meta)
        self.assertTrue(meta["pagination_truncated"] and meta["history_truncated"])
        self.assertTrue(attempts and all(a["outcome"] == g.FAILED for a in attempts))
        doc = g.decide(ft_event(), now=T0 + timedelta(hours=13), report=report(40),
                       attempts=attempts[:1], history_truncated=meta["history_truncated"])
        self.assertEqual((doc["consecutive_failures"], doc["required_gap_h"], doc["run"]),
                         (g.BACKOFF_CAP_FAILURES, 24.0, False))
        untruncated = g.decide(ft_event(), now=T0 + timedelta(hours=13), report=report(40),
                               attempts=attempts[:1])
        self.assertTrue(untruncated["run"])                 # the same history without truncation

    def test_run_records_truncation_in_the_audit_document(self):
        api = self.PagedApi(total=g.RUNS_PER_PAGE * g.MAX_PAGES + 40)
        env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": g.MAIN_REF, "GITHUB_REPOSITORY": REPO,
               "GITHUB_RUN_ID": str(10 ** 6)}
        with mock.patch.object(g, "read_published_report", return_value=report(40)):
            doc = g.run(env, ROOT, now=T0, api=api)
        self.assertTrue(doc["history"]["pagination_truncated"])
        self.assertTrue(doc["history"]["history_truncated"])


class AttemptReaderTests(unittest.TestCase):
    def test_cancelled_in_queue_and_skipped_runs_are_not_attempts(self):
        gh = FakeActions()
        r1 = gh.create_run("workflow_run", T0 - timedelta(hours=1))
        gh.runs[r1]["jobs"].append({"name": "evaluate", "conclusion": "cancelled", "started_at": None,
                                    "steps": []})
        gh.complete(r1, "cancelled")
        r2 = gh.create_run("schedule", T0 - timedelta(minutes=50))
        gh.complete(r2, skipped=True)
        r3 = gh.create_run("pull_request", T0 - timedelta(minutes=40))
        gh.runs[r3]["status"] = "in_progress"               # PR runs never count
        self.assertEqual(g.read_attempts(gh, now=T0, current_run_id="999"), [])

    def test_api_errors_close_the_gate(self):
        def boom(*a, **k):
            raise OSError("network")
        api = g.GitHubApi(REPO, "t", opener=boom)
        with self.assertRaises(g.GateStateUnavailable):
            g.read_attempts(api, now=T0, current_run_id="1")

    def test_api_client_targets_only_the_repository_endpoints(self):
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, request.headers.get("Authorization")))
            return io.BytesIO(b'{"workflow_runs": []}')
        g.read_attempts(g.GitHubApi(REPO, "tok", opener=opener), now=T0, current_run_id="1")
        self.assertTrue(seen[0][0].startswith("https://api.github.com/repos/owner/repo/actions/"
                                              "workflows/v6-offline-statistics.yml/runs?"))
        self.assertEqual(seen[0][1], "Bearer tok")


class FailClosedTests(unittest.TestCase):
    def test_unexpected_error_skips_with_reason(self):
        env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": g.MAIN_REF, "GITHUB_REPOSITORY": REPO,
               "GITHUB_RUN_ID": "5"}
        with mock.patch.object(g, "read_published_report", side_effect=KeyError("x")):
            doc = g.run(env, ROOT, now=T0, api=object())
        self.assertEqual(doc["decision"], "SKIPPED")
        self.assertTrue(doc["reason"].startswith("GATE_STATE_UNAVAILABLE:KeyError"))

    def test_commit_lookup_passes_path_as_query(self):
        calls = []

        class Api:
            def get(self, endpoint, **query):
                calls.append((endpoint, query))
                return [{"sha": "a" * 40, "commit": {"committer": {"date": "2026-11-03T09:00:00Z"}}}]
        with mock.patch.object(g.subprocess, "run", return_value=mock.Mock(stdout=b"{}")):
            doc = g.read_published_report(ROOT, Api())
        self.assertEqual(calls[0][0], "commits")
        self.assertEqual(calls[0][1]["path"], g.REPORT)
        self.assertEqual(doc["published_commit"], "a" * 40)


class PublishedReportTests(unittest.TestCase):
    def test_reads_main_as_it_is_now_not_the_checked_out_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            run = lambda *a, cwd: subprocess.run(a, cwd=cwd, check=True, capture_output=True)
            run("git", "init", "-q", "--bare", "-b", "main", str(tmp / "origin.git"), cwd=tmp)
            run("git", "clone", "-q", str(tmp / "origin.git"), "w", cwd=tmp)
            w = tmp / "w"
            run("git", "config", "user.email", "t@t", cwd=w)
            run("git", "config", "user.name", "t", cwd=w)
            (w / "docs/lab").mkdir(parents=True)
            (w / g.REPORT).write_text(json.dumps({"generated_at": "2026-11-03T00:00:00+00:00"}))
            run("git", "add", ".", cwd=w)
            run("git", "commit", "-qm", "old", cwd=w)
            run("git", "push", "-q", "origin", "HEAD:main", cwd=w)
            run("git", "clone", "-q", str(tmp / "origin.git"), "stale", cwd=tmp)
            (w / g.REPORT).write_text(json.dumps({"generated_at": "2026-11-03T11:00:00+00:00"}))
            run("git", "commit", "-qam", "new", cwd=w)
            run("git", "push", "-q", "origin", "HEAD:main", cwd=w)
            doc = g.read_published_report(tmp / "stale")          # stale checkout, fresh main
        self.assertEqual(doc["generated_at"], "2026-11-03T11:00:00+00:00")
        self.assertEqual(len(doc["sha256"]), 64)


class MainOutputTests(unittest.TestCase):
    def test_outputs_summary_and_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, summary = tmp / "out", tmp / "summary"
            env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/1/merge",
                   "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "7",
                   "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}
            with mock.patch("sys.stdout", io.StringIO()):
                g.main([], env=env)
            self.assertIn("run=true\ndecision=RUN_PR_CI\n", out.read_text())
            self.assertIn("V6 activation gate", summary.read_text())
            out.write_text("")
            with mock.patch.object(g, "read_published_report", return_value=report(1)), \
                    mock.patch.object(g, "read_attempts", return_value=[]), \
                    mock.patch("sys.stdout", io.StringIO()):
                g.main(["--dry-run-as", "schedule"], env=env)
            self.assertEqual(out.read_text(), "")                # a preview never sets outputs
            self.assertIn("dry run", summary.read_text())


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.wf = yaml.safe_load((ROOT / ".github/workflows/v6-offline-statistics.yml").read_text())
        self.text = (ROOT / ".github/workflows/v6-offline-statistics.yml").read_text()
        self.ft = yaml.safe_load((ROOT / ".github/workflows/lab-ft-results.yml").read_text())

    def test_triggers(self):
        on = self.wf[True]
        self.assertEqual(on["workflow_run"], {"workflows": [self.ft["name"]], "types": ["completed"]})
        self.assertEqual(self.ft["name"], g.FT_WORKFLOW_NAME)
        self.assertEqual(on["schedule"], [{"cron": "18 2,8,14,20 * * *"}])   # reserve unchanged
        self.assertIn("pull_request", on)
        self.assertEqual(set(on["workflow_dispatch"]["inputs"]), {"force", "reason"})
        self.assertIs(on["workflow_dispatch"]["inputs"]["force"]["default"], False)

    def test_gate_is_inside_the_workflow_level_mutex(self):
        self.assertEqual(self.wf["concurrency"]["cancel-in-progress"], False)
        self.assertIn("'main'", self.wf["concurrency"]["group"])
        jobs = self.wf["jobs"]
        self.assertEqual(list(jobs)[0], "gate")
        for job in jobs.values():
            self.assertNotIn("concurrency", job)            # one lock for the whole run
        self.assertEqual(jobs["evaluate"]["needs"], "gate")
        self.assertIn("needs.gate.outputs.run == 'true'", jobs["evaluate"]["if"])
        for guard in ("workflow_run.conclusion == 'success'", "workflow_run.head_branch == 'main'",
                      "head_repository.full_name == github.repository",
                      "workflow_run.event != 'pull_request'"):
            self.assertIn(guard, jobs["evaluate"]["if"])
        self.assertEqual(jobs["publish"]["needs"], "evaluate")

    def test_gate_permissions_and_no_untrusted_inputs(self):
        gate = self.wf["jobs"]["gate"]
        self.assertEqual(gate["permissions"], {"contents": "read", "actions": "read"})
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        self.assertNotIn("workflow_run.head_sha", self.text)
        self.assertNotIn("run-id:", self.text)              # never downloads upstream artifacts
        self.assertNotIn("github-token:", self.text)
        for step in gate["steps"]:
            if "uses" in step and step["uses"].startswith("actions/checkout"):
                self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
        self.assertIn("python3 -m scripts.v6_activation_gate", self.text)

    def test_ft_and_other_cadences_untouched(self):
        self.assertEqual(self.ft[True]["schedule"], [{"cron": "12,42 * * * *"}])


if __name__ == "__main__":
    unittest.main()
