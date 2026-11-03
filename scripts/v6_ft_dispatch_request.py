"""Ask the V6 offline statistics workflow to evaluate after a successful FT reconciliation.

Why this exists
---------------
``v6-offline-statistics.yml`` listens to ``workflow_run`` of the FT workflow. GitHub does not
create workflow runs for events caused by the repository ``GITHUB_TOKEN`` -- the only
exceptions are ``workflow_dispatch`` and ``repository_dispatch`` (github/docs,
``data/reusables/actions/actions-do-not-trigger-workflows.md``). Most FT runs are dispatched
by the H1 watchdog with ``GITHUB_TOKEN`` (triggering actor ``github-actions[bot]``), so their
completion never starts V6: 0 of 74 such runs started the ``workflow_run`` monitor
``ft-operational-integrity.yml``, while 26 of 26 human/schedule/push FT runs did.

What it does
------------
Exactly one ``workflow_dispatch`` of ``v6-offline-statistics.yml`` on ``main`` with the single
input ``ft_source_run_id`` (this FT run). It never sends ``force`` (the gate refuses a forced
dispatch by automation anyway), never computes anything and never touches data. Everything
else -- the six-hour window, failure backoff, mutex, verification of the FT source run and
de-duplication against the ``workflow_run`` trigger -- is decided by the V6 activation gate
inside the V6 workflow mutex.

It only asks when ``workflow_run`` cannot have fired: the FT run was started by
``github-actions[bot]``. Runs started by a person, a schedule or a push are left to
``workflow_run`` (no double request). A failed request is reported (annotation, summary and
receipt) but never fails the FT run: the V6 schedule reserve still covers it.

Network: one POST to ``api.github.com`` with the job's ``GITHUB_TOKEN`` (``actions: write``).
No LLM, sports provider or Telegram request is possible from here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

NAME = "V6_FT_DISPATCH_REQUEST"
V6_WORKFLOW_FILE = "v6-offline-statistics.yml"
MAIN_REF = "refs/heads/main"
TOKEN_ACTOR = "github-actions[bot]"
INPUT = "ft_source_run_id"


def plan(env):
    """Pure decision: (should_request, reason)."""
    run_id = str(env.get("GITHUB_RUN_ID") or "")
    if env.get("GITHUB_EVENT_NAME") == "pull_request":
        return False, "PULL_REQUEST_NEVER_REQUESTS"
    if env.get("GITHUB_REF") != MAIN_REF:
        return False, "NOT_MAIN_REF:%s" % env.get("GITHUB_REF")
    if not run_id.isdigit():
        return False, "INVALID_RUN_ID:%s" % run_id[:40]
    actor = env.get("GITHUB_TRIGGERING_ACTOR") or env.get("GITHUB_ACTOR") or ""
    if actor != TOKEN_ACTOR:
        # A run started by a person, schedule or push emits workflow_run normally.
        return False, "COVERED_BY_WORKFLOW_RUN:%s" % actor
    return True, "GITHUB_TOKEN_RUN_SUPPRESSES_WORKFLOW_RUN"


def payload(run_id):
    """The only body ever sent: no force, no reason, nothing else."""
    return {"ref": "main", "inputs": {INPUT: str(run_id)}}


def dispatch(repository, token, run_id, opener=urllib.request.urlopen,
             base="https://api.github.com"):
    url = "%s/repos/%s/actions/workflows/%s/dispatches" % (base.rstrip("/"), repository,
                                                           V6_WORKFLOW_FILE)
    request = urllib.request.Request(url, data=json.dumps(payload(run_id)).encode("utf-8"),
                                     method="POST", headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json", "User-Agent": "v6-ft-dispatch-request",
        "Authorization": "Bearer %s" % token})
    with opener(request, timeout=20) as response:
        return getattr(response, "status", None) or response.getcode()


def run(env=os.environ, opener=urllib.request.urlopen):
    should, reason = plan(env)
    receipt = {"name": NAME, "schema_version": 1, "ft_run_id": env.get("GITHUB_RUN_ID"),
               "ft_triggering_actor": env.get("GITHUB_TRIGGERING_ACTOR") or env.get("GITHUB_ACTOR"),
               "requested": False, "status": "NOT_REQUESTED", "reason": reason, "http_status": None,
               "target_workflow": V6_WORKFLOW_FILE, "payload": None,
               "llm_calls": 0, "provider_requests": 0, "telegram_requests": 0}
    if not should:
        return receipt
    receipt["payload"] = payload(env["GITHUB_RUN_ID"])
    if not env.get("GITHUB_TOKEN") or not env.get("GITHUB_REPOSITORY"):
        receipt.update(status="REQUEST_FAILED", reason="MISSING_TOKEN_OR_REPOSITORY")
        return receipt
    try:
        status = dispatch(env["GITHUB_REPOSITORY"], env["GITHUB_TOKEN"], env["GITHUB_RUN_ID"],
                          opener=opener)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal for FT
        code = getattr(exc, "code", None)
        receipt.update(status="REQUEST_FAILED", http_status=code,
                       reason="%s:%s" % (type(exc).__name__, str(exc)[:160]))
        return receipt
    receipt["http_status"] = status
    if status == 204:
        receipt.update(requested=True, status="REQUESTED")
    else:
        receipt.update(status="REQUEST_FAILED", reason="UNEXPECTED_HTTP_STATUS")
    return receipt


def main(argv=None, env=os.environ, opener=urllib.request.urlopen):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--receipt", type=Path, help="write the JSON receipt here")
    args = parser.parse_args(argv)
    receipt = run(env, opener=opener)
    text = json.dumps(receipt, sort_keys=True)
    print(NAME, text)
    level = "warning" if receipt["status"] == "REQUEST_FAILED" else "notice"
    print("::%s title=%s_%s::%s" % (level, NAME, receipt["status"], receipt["reason"]))
    if args.receipt:
        args.receipt.write_text(text + "\n", encoding="utf-8")
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("### V6 request after FT\n\n```json\n%s\n```\n" % json.dumps(receipt, indent=2,
                                                                             sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
