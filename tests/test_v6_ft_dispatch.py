"""FT -> V6 explicit request: GitHub does not create workflow_run runs for GITHUB_TOKEN runs.

Evidence (2026-11-03): FT run 41619948275 (watchdog dispatch, triggering actor
``github-actions[bot]``) completed successfully after PR #215 and started no V6 run; over the
last 100 FT runs, the ``workflow_run`` monitor ``ft-operational-integrity.yml`` ran for 26/26
human/schedule/push runs and for 0/74 bot-dispatched runs. github/docs
``data/reusables/actions/actions-do-not-trigger-workflows.md``: events triggered by the
``GITHUB_TOKEN`` do not create workflow runs, except ``workflow_dispatch`` and
``repository_dispatch``.

No network: the Actions API and the dispatch endpoint are in-memory fakes.
"""
import io
import json
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path
from unittest import mock

import yaml

from scripts import v6_activation_gate as g
from scripts import v6_ft_dispatch_request as rq
from tests.test_v6_activation_gate import REPO, T0, attempt, report

ROOT = Path(__file__).resolve().parents[1]
BOT = "github-actions[bot]"


def env(**over):
    base = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ID": "41619948275", "GITHUB_TRIGGERING_ACTOR": BOT,
            "GITHUB_REPOSITORY": REPO, "GITHUB_TOKEN": "t"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def ft_run(run_id=41619948275, *, status="completed", conclusion="success", actor=BOT,
           branch="main", event="workflow_dispatch", repo=REPO, path=g.FT_WORKFLOW_PATH,
           name=g.FT_WORKFLOW_NAME, finished=T0 - timedelta(minutes=1)):
    return {"id": run_id, "name": name, "path": path, "status": status, "conclusion": conclusion,
            "head_branch": branch, "event": event, "head_sha": "f" * 40,
            "head_repository": {"full_name": repo}, "repository": {"full_name": repo},
            "triggering_actor": {"login": actor}, "updated_at": g.iso(finished)}


def dispatch_event(source="41619948275", run_id="2000", actor=BOT, **inputs):
    return {"event_name": "workflow_dispatch", "ref": g.MAIN_REF, "repository": REPO,
            "run_id": run_id, "actor": actor,
            "inputs": dict({"force": False, "reason": "", g.FT_SOURCE_INPUT: source}, **inputs)}


class Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RequesterTests(unittest.TestCase):
    def test_requests_only_when_workflow_run_is_suppressed(self):
        self.assertEqual(rq.plan(env()), (True, "GITHUB_TOKEN_RUN_SUPPRESSES_WORKFLOW_RUN"))
        for actor in ("nunovinhas-creator", "someone"):
            ok, reason = rq.plan(env(GITHUB_TRIGGERING_ACTOR=actor))
            self.assertFalse(ok)
            self.assertTrue(reason.startswith("COVERED_BY_WORKFLOW_RUN"))

    def test_never_requests_outside_main_or_from_pull_requests(self):
        self.assertEqual(rq.plan(env(GITHUB_EVENT_NAME="pull_request"))[0], False)
        self.assertEqual(rq.plan(env(GITHUB_REF="refs/heads/x"))[0], False)
        self.assertEqual(rq.plan(env(GITHUB_RUN_ID="12; rm -rf /"))[0], False)

    def test_payload_never_forces(self):
        body = rq.payload("41619948275")
        self.assertEqual(body, {"ref": "main", "inputs": {"ft_source_run_id": "41619948275"}})
        self.assertNotIn("force", json.dumps(body))
        self.assertNotIn("reason", json.dumps(body))

    def test_one_post_to_the_v6_dispatch_endpoint(self):
        seen = []

        def opener(request, timeout):
            seen.append(request)
            return Response(204)
        receipt = rq.run(env(), opener=opener)
        self.assertEqual(receipt["status"], "REQUESTED")
        self.assertTrue(receipt["requested"])
        self.assertEqual(len(seen), 1)
        req = seen[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://api.github.com/repos/%s/actions/workflows/"
                                       "v6-offline-statistics.yml/dispatches" % REPO)
        self.assertEqual(json.loads(req.data), rq.payload("41619948275"))
        self.assertEqual((receipt["llm_calls"], receipt["provider_requests"],
                          receipt["telegram_requests"]), (0, 0, 0))

    def test_human_run_sends_nothing(self):
        opener = mock.Mock(side_effect=AssertionError("must not be called"))
        receipt = rq.run(env(GITHUB_TRIGGERING_ACTOR="nunovinhas-creator"), opener=opener)
        self.assertEqual(receipt["status"], "NOT_REQUESTED")
        opener.assert_not_called()

    def test_failure_is_reported_but_never_fails_ft(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = rq.main([], env=env(), opener=opener)
        self.assertEqual(code, 0)
        self.assertIn("::warning title=V6_FT_DISPATCH_REQUEST_REQUEST_FAILED", out.getvalue())
        self.assertEqual(rq.run(env(GITHUB_TOKEN=None))["status"], "REQUEST_FAILED")


class SourceValidationTests(unittest.TestCase):
    def check(self, run):
        return g.validate_ft_source(run, repository=REPO, now=T0)

    def test_valid_source(self):
        self.assertIsNone(self.check(ft_run()))

    def test_every_invalid_source_is_refused(self):
        cases = {
            "FT_SOURCE_NOT_COMPLETED": ft_run(status="in_progress", conclusion=None),
            "FT_SOURCE_NOT_SUCCESS": ft_run(conclusion="failure"),
            "FT_SOURCE_COVERED_BY_WORKFLOW_RUN": ft_run(actor="nunovinhas-creator"),
            "FT_SOURCE_NOT_MAIN": ft_run(branch="feature"),
            "FT_SOURCE_FROM_PULL_REQUEST": ft_run(event="pull_request"),
            "FT_SOURCE_FOREIGN_REPOSITORY": ft_run(repo="evil/fork"),
            "FT_SOURCE_NOT_FT_WORKFLOW": ft_run(path=".github/workflows/collect.yml"),
            "FT_SOURCE_STALE_OR_UNDATED": ft_run(finished=T0 - timedelta(hours=3)),
        }
        for reason, run in cases.items():
            with self.subTest(reason=reason):
                self.assertTrue(self.check(run).startswith(reason), self.check(run))
        self.assertTrue(self.check(None).startswith("FT_SOURCE_UNREADABLE"))
        self.assertTrue(self.check(ft_run(name="Other")).startswith("FT_SOURCE_NOT_FT_WORKFLOW"))
        self.assertTrue(self.check(ft_run(finished=T0 + timedelta(hours=1)))
                        .startswith("FT_SOURCE_STALE_OR_UNDATED"))

    def test_trigger_shape(self):
        self.assertIsNone(g.validate_trigger(dispatch_event()))
        self.assertTrue(g.validate_trigger(dispatch_event(source="12a")).startswith("FT_SOURCE_INVALID"))
        self.assertEqual(g.validate_trigger(dispatch_event(force=True, reason="x")),
                         "FT_SOURCE_WITH_FORCE_REFUSED")
        self.assertIsNone(g.validate_trigger(dispatch_event(source="")))   # plain manual dispatch
        self.assertEqual(g.ft_source_id(dispatch_event(source=" 77 ")), "77")


class DecisionTests(unittest.TestCase):
    def decide(self, event=None, *, rep=7, attempts=(), **kw):
        return g.decide(event or dispatch_event(), now=T0, report=report(rep), attempts=list(attempts), **kw)

    def test_valid_ft_request_obeys_the_normal_cadence(self):
        doc = self.decide(ft_source_run=ft_run())
        self.assertEqual((doc["decision"], doc["reason"], doc["run"]), ("RUN", "WINDOW_ELAPSED", True))
        self.assertEqual(doc["ft_source_run_id"], "41619948275")
        self.assertEqual(doc["upstream"]["triggering_actor"], BOT)
        self.assertEqual(self.decide(rep=1, ft_source_run=ft_run())["reason"], "REPORT_FRESH")
        self.assertEqual(self.decide(attempts=[attempt(2)], ft_source_run=ft_run())["reason"],
                         "RECENT_ATTEMPT")
        backoff = self.decide(attempts=[attempt(7, g.FAILED, run_id=2), attempt(8, g.FAILED)],
                              ft_source_run=ft_run())
        self.assertEqual(backoff["reason"], "BACKOFF_AFTER_FAILURES")

    def test_invalid_or_unreadable_source_never_computes(self):
        doc = self.decide(ft_source_run=ft_run(conclusion="failure"),
                          ft_source_error="FT_SOURCE_NOT_SUCCESS:failure")
        self.assertEqual((doc["decision"], doc["run"]), ("SKIPPED", False))
        self.assertEqual(self.decide(ft_source_run=None)["reason"], "FT_SOURCE_UNREADABLE")
        doc = self.decide(ft_source_run=ft_run(), state_error=g.GateStateUnavailable("api"))
        self.assertTrue(doc["reason"].startswith("GATE_STATE_UNAVAILABLE"))

    def test_automation_can_never_force(self):
        doc = self.decide(dispatch_event(force=True, reason="auto"), ft_source_run=ft_run())
        self.assertEqual(doc["reason"], "FT_SOURCE_WITH_FORCE_REFUSED")
        plain = {"event_name": "workflow_dispatch", "ref": g.MAIN_REF, "repository": REPO,
                 "run_id": "1", "actor": BOT, "inputs": {"force": True, "reason": "auto"}}
        self.assertTrue(self.decide(plain)["reason"].startswith("FORCE_BY_AUTOMATION_REFUSED"))

    def test_duplicate_ft_source_is_refused_for_either_trigger(self):
        doc = self.decide(ft_source_run=ft_run(), duplicates=[1999])
        self.assertEqual((doc["reason"], doc["run"]), ("DUPLICATE_FT_SOURCE:1999", False))
        wr = {"event_name": "workflow_run", "ref": g.MAIN_REF, "repository": REPO, "run_id": "2001",
              "actor": "nunovinhas-creator",
              "workflow_run": {"id": 41619948275, "name": g.FT_WORKFLOW_NAME, "conclusion": "success",
                               "head_branch": "main", "event": "schedule",
                               "head_repository": {"full_name": REPO}}}
        self.assertEqual(self.decide(wr, duplicates=[2000])["reason"], "DUPLICATE_FT_SOURCE:2000")


class FakeApi:
    """Actions API stand-in: V6 run listing (with display titles), jobs and the FT run."""

    def __init__(self, ft_states, v6_runs=()):
        self.ft_states = list(ft_states)
        self.v6_runs = list(v6_runs)
        self.calls = []

    def get(self, endpoint, **query):
        self.calls.append(endpoint)
        if endpoint.startswith("actions/workflows/"):
            return {"workflow_runs": self.v6_runs}
        if endpoint.endswith("/jobs"):
            return {"jobs": []}
        if endpoint.startswith("actions/runs/"):
            return self.ft_states.pop(0) if len(self.ft_states) > 1 else self.ft_states[0]
        raise AssertionError(endpoint)


class EndToEndTests(unittest.TestCase):
    def gate(self, api, event_inputs=None, run_id="2000"):
        payload = {"inputs": event_inputs if event_inputs is not None else
                   {"force": False, "reason": "", "ft_source_run_id": "41619948275"}}
        environ = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": g.MAIN_REF,
                   "GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": run_id, "GITHUB_TRIGGERING_ACTOR": BOT}
        sleeps = []
        with mock.patch.object(g, "event_from_env", return_value=dict(
                g.event_from_env({}), event_name="workflow_dispatch", ref=g.MAIN_REF,
                repository=REPO, run_id=run_id, actor=BOT, inputs=payload["inputs"])), \
                mock.patch.object(g, "read_published_report", return_value=report(7)):
            doc = g.run(environ, now=T0, api=api, sleep=sleeps.append, clock=lambda: T0)
        return doc, sleeps

    def test_waits_for_the_requesting_ft_run_to_complete_then_runs(self):
        api = FakeApi([ft_run(status="in_progress", conclusion=None), ft_run()])
        doc, sleeps = self.gate(api)
        self.assertEqual((doc["decision"], doc["reason"]), ("RUN", "WINDOW_ELAPSED"))
        self.assertEqual(sleeps, [g.FT_SOURCE_POLL_SECONDS])
        self.assertIn("actions/runs/41619948275", api.calls)

    def test_wait_is_bounded_and_fails_closed(self):
        api = FakeApi([ft_run(status="in_progress", conclusion=None)])
        doc, sleeps = self.gate(api)
        self.assertEqual(doc["decision"], "SKIPPED")
        self.assertTrue(doc["reason"].startswith("FT_SOURCE_NOT_COMPLETED"))
        self.assertEqual(len(sleeps), g.FT_SOURCE_POLLS - 1)

    def test_second_request_for_the_same_ft_run_is_refused(self):
        earlier = {"id": 1999, "event": "workflow_dispatch", "status": "completed",
                   "conclusion": "success", "created_at": g.iso(T0 - timedelta(minutes=2)),
                   "display_title": "V6 offline statistics (workflow_dispatch ft:41619948275)"}
        doc, _ = self.gate(FakeApi([ft_run()], v6_runs=[earlier]))
        self.assertEqual(doc["reason"], "DUPLICATE_FT_SOURCE:1999")
        other = dict(earlier, display_title="V6 offline statistics (workflow_dispatch ft:41619948270)")
        doc, _ = self.gate(FakeApi([ft_run()], v6_runs=[other]))
        self.assertEqual(doc["decision"], "RUN")

    def test_plain_manual_dispatch_reads_no_ft_source(self):
        api = FakeApi([AssertionError])
        doc, _ = self.gate(api, event_inputs={"force": False, "reason": "", "ft_source_run_id": ""})
        self.assertNotIn("actions/runs/41619948275", api.calls)
        self.assertEqual(doc["decision"], "RUN")


class IncidentReplayTests(unittest.TestCase):
    """The FT runs of 2026-11-03 10:31 and 11:06 (bot) and a schedule FT run."""

    def test_exactly_one_route_per_ft_run(self):
        for actor, workflow_run_fires in ((BOT, False), ("nunovinhas-creator", True)):
            asked, _ = rq.plan(env(GITHUB_TRIGGERING_ACTOR=actor))
            with self.subTest(actor=actor):
                # Either GitHub's workflow_run reaches V6, or the FT requests it: never both,
                # never neither.
                self.assertNotEqual(asked, workflow_run_fires)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.ft_text = (ROOT / ".github/workflows/lab-ft-results.yml").read_text()
        self.ft = yaml.safe_load(self.ft_text)
        self.v6 = yaml.safe_load((ROOT / ".github/workflows/v6-offline-statistics.yml").read_text())

    def test_request_job_runs_only_after_a_fully_successful_ft_on_main_by_the_token(self):
        job = self.ft["jobs"]["request-v6"]
        self.assertEqual(job["needs"], ["reconcile", "integrity"])
        for guard in ("needs.reconcile.result == 'success'", "needs.integrity.result == 'success'",
                      "github.ref == 'refs/heads/main'", "github.event_name != 'pull_request'",
                      "github.triggering_actor == 'github-actions[bot]'"):
            self.assertIn(guard, job["if"])
        self.assertEqual(job["permissions"], {"actions": "write", "contents": "read"})
        self.assertNotIn("continue-on-error", job)
        text = json.dumps(job)
        for forbidden in ("secrets.", "force", "TELEGRAM", "API_KEY", "lab_results"):
            self.assertNotIn(forbidden, text)
        checkout = job["steps"][0]
        self.assertEqual(checkout["with"]["persist-credentials"], False)
        self.assertIn("python3 -m scripts.v6_ft_dispatch_request", job["steps"][1]["run"])

    def test_existing_ft_jobs_and_cadence_untouched(self):
        self.assertEqual(self.ft[True]["schedule"], [{"cron": "12,42 * * * *"}])
        self.assertEqual(self.ft["jobs"]["integrity"]["needs"], "reconcile")
        self.assertEqual(self.ft["permissions"], {"contents": "write"})
        self.assertEqual(self.ft["concurrency"]["group"], "asianodds-lab-ft-results")

    def test_v6_run_name_tags_the_ft_source_for_both_triggers(self):
        name = self.v6["run-name"]
        self.assertIn("github.event.workflow_run.id && format(' ft:{0}'", name)
        self.assertIn("inputs.ft_source_run_id && format(' ft:{0}'", name)
        self.assertEqual(g.FT_SOURCE_TAG.findall("V6 offline statistics (workflow_run ft:41619948275)"),
                         ["41619948275"])
        self.assertEqual(self.v6["concurrency"]["cancel-in-progress"], False)
        self.assertEqual(self.v6["on" if "on" in self.v6 else True]["schedule"],
                         [{"cron": "18 2,8,14,20 * * *"}])


if __name__ == "__main__":
    unittest.main()
