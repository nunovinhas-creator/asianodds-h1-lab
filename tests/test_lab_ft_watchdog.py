"""FT watchdog is fail-closed, quota-conservative and independent from H1."""
import json
import unittest
from datetime import datetime, timezone

from scripts.lab_ft_watchdog import run, plan, STATUS_DISPATCHED, STATUS_SKIPPED

NOW=datetime(2026,10,28,18,17,tzinfo=timezone.utc)
ENV={"GITHUB_WORKFLOW":"H1 - Collect Telegram",
     "GITHUB_REF":"refs/heads/main",
     "GITHUB_REPOSITORY":"nunovinhas-creator/asianodds-h1-lab",
     "GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_TOKEN":"synthetic-secret"}

class FakeResponse:
    def __init__(self,data=None,status=200):
        self.data=json.dumps(data or {}).encode()
        self.status=status
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,n=-1): return self.data[:n]

def fetcher(at, *, post_status=204, status=200):
    requests=[]
    def opener(req,timeout=None):
        requests.append(req)
        if req.get_method()=="GET":
            return FakeResponse({"workflow_runs":[{"created_at":at}] if at else []},
                                status=status)
        return FakeResponse({},status=post_status)
    return opener,requests


class FTWatchdogTests(unittest.TestCase):
    def test_recent_job_suppresses_new_job_even_if_failed(self):
        fn,calls=fetcher("2026-10-28T17:50:00Z")
        r=run(env=ENV,now=NOW,opener=fn)
        self.assertEqual(r["status"],STATUS_SKIPPED)
        self.assertFalse(r["dispatched"])
        self.assertEqual(len(calls),1)
        self.assertIn("/actions/workflows/lab-ft-results.yml/runs?",calls[0].full_url)

    def test_stale_job_dispatches_once_without_printing_credentials(self):
        fn,calls=fetcher("2026-10-28T17:30:00Z")
        r=run(env=ENV,now=NOW,opener=fn)
        self.assertEqual(r["status"],STATUS_DISPATCHED)
        self.assertTrue(r["dispatched"])
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1].get_method(),"POST")
        self.assertEqual(json.loads(calls[1].data),
                         {"ref":"main","inputs":{"trigger_source":"h1-ft-watchdog"}})
        self.assertNotIn(ENV["GITHUB_TOKEN"],json.dumps(r))

    def test_missing_workflow_run_list_does_not_dispatch(self):
        def invalid(req, timeout=10):
            return FakeResponse({"wrong": []})
        r=run(env=ENV,now=NOW,opener=invalid)
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["status"],"FT_WATCHDOG_GITHUB_UNAVAILABLE")

    def test_no_runs_triggers_one_dispatch(self):
        fn,calls=fetcher(None)
        self.assertTrue(run(env=ENV,now=NOW,opener=fn)["dispatched"])
        self.assertEqual(len(calls),2)

    def test_non_h1_branch_missing_token_and_wrong_repo_skip_without_http(self):
        for changed in ({"GITHUB_REF":"refs/heads/feature/nope"},
                        {"GITHUB_WORKFLOW":"Lab - Audit V4 vs H1 (shadow)"},
                        {"GITHUB_REPOSITORY":"other/repo"},
                        {"GITHUB_TOKEN":None}):
            env={**ENV,**changed}
            r=run(env=env,now=NOW,opener=lambda *a,**k:(
                self.fail("must never issue HTTP")))
            self.assertFalse(r["dispatched"])

    def test_bad_github_timestamp_and_no_naive_time(self):
        with self.assertRaises(ValueError):
            plan([{"created_at":"2026-10-27T20:00:00"}],NOW)
        with self.assertRaises(ValueError):
            plan([{"created_at":"2026-11-01T20:00:00Z"}],NOW)
        with self.assertRaises(ValueError):
            plan([],datetime(2026,10,28,18))

    def test_dispatch_403_is_safe_failure(self):
        fn,calls=fetcher("2026-10-28T17:20:00Z",post_status=403)
        result=run(env=ENV,now=NOW,opener=fn)
        self.assertEqual(result["status"],"FT_WATCHDOG_GITHUB_UNAVAILABLE")
        self.assertEqual(len(calls),2)
