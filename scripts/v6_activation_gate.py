"""V6 offline statistics activation gate: at most one computation per rolling six hours.

``v6-offline-statistics.yml`` is started by three automatic sources and one manual one:

* ``workflow_run``: after every completed ``lab-ft-results.yml`` run (FT is the input
  that actually changes the report);
* ``schedule``: the historical 02/08/14/20 h cron, kept as a reserve if FT stops;
* ``workflow_dispatch``: manual, optionally ``force`` with an audited ``reason``;
* ``pull_request``: CI only (never publishes, never gated).

Mutual exclusion
----------------
This gate is the FIRST job of the workflow and the workflow-level ``concurrency`` group
(``v6-offline-statistics-main``, ``cancel-in-progress: false``) covers every job of the run,
so the eligibility decision, the computation and the publication of one run complete
before the gate of the next run starts. The decision is made on state read INSIDE that
protected section: ``origin/main`` is fetched again (never the possibly stale
``github.sha`` of a run that waited for the lock) and the attempt history is read from the
Actions API after every earlier run has completed. A second line of defence refuses when
an earlier non-PR attempt is still in progress (``CONCURRENT_ATTEMPT_IN_PROGRESS``).

Cadence
-------
An attempt is any earlier non-PR run of this workflow whose ``evaluate`` job was not
skipped, whatever its trigger and outcome (published, failed, cancelled or
``SUPERSEDED``). An automatic or unforced manual trigger runs only when

* the report on ``main`` is at least six hours old (``generated_at`` and the commit that
  published it), and
* the last attempt started at least ``6 h x min(2^(k-1), 4)`` ago, ``k`` being the number of
  consecutive FAILED attempts (6 h, 12 h, 24 h, 24 h ...): bounded, observable recovery
  instead of one retry per FT run (48/day). A ``SUPERSEDED`` or otherwise unpublished
  but successful run is not a failure; it still consumes its six-hour window.

A ``workflow_dispatch`` with ``force=true`` and a non-empty ``reason`` by a human actor is
the only exception (``RUN_FORCED_MANUAL``); it is announced as a warning annotation and in
the job summary, and it counts as an attempt for the next windows.

Security
--------
Only a ``workflow_run`` of the FT workflow that concluded ``success``, on ``main`` of this
repository and not started by a pull request, is eligible. The gate never checks out,
downloads or executes anything produced by the upstream run: it only reads that event's
metadata. Network use is limited to ``api.github.com`` with the workflow's own read-only
token; no LLM, sports provider or Telegram request is possible from here. When the
attempt history cannot be read, automatic triggers are refused (fail closed).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAME = "V6_ACTIVATION_GATE"
FT_WORKFLOW_NAME = "Lab - Reconcile FT for all observed matches"
WORKFLOW_FILE = "v6-offline-statistics.yml"
EVALUATE_JOB = "evaluate"
REPORT = "docs/lab/llm-statistics.json"
MAIN_REF = "refs/heads/main"
WINDOW = timedelta(hours=6)
MAX_BACKOFF_FACTOR = 4
LOOKBACK = timedelta(hours=72)          # sees 3 failures spaced 6/12/24 h plus the 24 h gap
BACKOFF_CAP_FAILURES = 3                # k >= 3 always means a 24 h gap: no need to count further
RUNS_PER_PAGE = 100
MAX_PAGES = 3
MAX_JOB_LOOKUPS = 120                   # bounded API use (GITHUB_TOKEN quota is shared)
FAILED = "FAILED"
SUCCEEDED = "SUCCEEDED"
IN_PROGRESS = "IN_PROGRESS"


class GateStateUnavailable(RuntimeError):
    """The attempt history or the published report could not be read."""


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat() if value else None


def hours(delta):
    return None if delta is None else round(delta.total_seconds() / 3600.0, 3)


def required_gap(consecutive_failures):
    """6 h normally and after one failure; 12 h after two; 24 h from three on."""
    if consecutive_failures <= 1:
        return WINDOW
    return WINDOW * min(2 ** (consecutive_failures - 1), MAX_BACKOFF_FACTOR)


def attempt_outcome(run_status, run_conclusion):
    if run_status != "completed":
        return IN_PROGRESS
    return SUCCEEDED if run_conclusion == "success" else FAILED


def executed(job):
    """The evaluate job actually started computing (not skipped, not cancelled in queue)."""
    if job.get("conclusion") == "skipped" or not job.get("started_at"):
        return False
    return any(step.get("conclusion") not in (None, "skipped") or step.get("status") == "in_progress"
               for step in job.get("steps") or [])


def consecutive_failures(attempts):
    count = 0
    for attempt in attempts:                       # newest first
        if attempt["outcome"] != FAILED:
            break
        count += 1
    return count


def _truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def validate_trigger(event):
    """None when the trigger may be considered, else the SKIP reason."""
    name = event.get("event_name")
    if name == "pull_request":
        return None
    if event.get("ref") != MAIN_REF:
        return "NOT_MAIN_REF:%s" % event.get("ref")
    if name == "workflow_run":
        upstream = event.get("workflow_run") or {}
        if upstream.get("name") != FT_WORKFLOW_NAME:
            return "UPSTREAM_NOT_FT_WORKFLOW:%s" % upstream.get("name")
        if upstream.get("conclusion") != "success":
            return "UPSTREAM_NOT_SUCCESS:%s" % upstream.get("conclusion")
        if upstream.get("head_branch") != "main":
            return "UPSTREAM_NOT_MAIN:%s" % upstream.get("head_branch")
        if upstream.get("event") == "pull_request":
            return "UPSTREAM_FROM_PULL_REQUEST"
        repo = (upstream.get("head_repository") or {}).get("full_name")
        if repo != event.get("repository"):
            return "UPSTREAM_FOREIGN_REPOSITORY:%s" % repo
        return None
    if name in ("schedule", "workflow_dispatch"):
        return None
    return "UNSUPPORTED_EVENT:%s" % name


def decide(event, *, now, report, attempts, state_error=None, history_truncated=False):
    """Pure decision. ``report``: {generated_at, published_at, published_commit, sha256}.
    ``attempts``: earlier non-PR attempts, newest first, each {run_id, event, started_at,
    outcome, conclusion}. Returns the full, auditable decision document."""
    name = event.get("event_name")
    doc = {
        "gate": NAME, "schema_version": 1, "trigger": name, "now": iso(now),
        "run_id": event.get("run_id"), "actor": event.get("actor"), "ref": event.get("ref"),
        "upstream": None, "force": False, "force_reason": None,
        "report_generated_at": None, "report_published_at": None,
        "last_published_commit": None, "last_published_report_sha256": None,
        "last_published_age_h": None, "last_attempt": None, "last_attempt_age_h": None,
        "consecutive_failures": None, "required_gap_h": None, "attempts_considered": None,
        "last_attempt_unpublished": None, "mode": None,
        "llm_calls": 0, "provider_requests": 0, "telegram_requests": 0,
    }
    if name == "workflow_run":
        up = event.get("workflow_run") or {}
        doc["upstream"] = {k: up.get(k) for k in ("id", "name", "conclusion", "head_branch",
                                                    "head_sha", "event")}
        doc["upstream"]["repository"] = (up.get("head_repository") or {}).get("full_name")
    report = report or {}
    generated = parse_time(report.get("generated_at"))
    published = parse_time(report.get("published_at"))
    fresh_anchor = max([t for t in (generated, published) if t], default=None)
    doc.update({"report_generated_at": iso(generated), "report_published_at": iso(published),
                "last_published_commit": report.get("published_commit"),
                "last_published_report_sha256": report.get("sha256"),
                "last_published_age_h": hours(now - fresh_anchor) if fresh_anchor else None})

    def finish(decision, reason, run):
        doc.update({"decision": decision, "reason": reason, "run": bool(run)})
        return doc

    if name == "pull_request":
        return finish("RUN_PR_CI", "PULL_REQUEST_CI_NEVER_PUBLISHES", True)
    invalid = validate_trigger(event)
    if invalid:
        return finish("SKIPPED", invalid, False)

    inputs = event.get("inputs") or {}
    if name == "workflow_dispatch" and _truthy(inputs.get("force")):
        reason = (inputs.get("reason") or "").strip()
        actor = event.get("actor") or ""
        doc.update({"force": True, "force_reason": reason[:300] or None})
        if not reason:
            return finish("SKIPPED", "FORCE_WITHOUT_REASON", False)
        if not actor or actor.endswith("[bot]"):
            return finish("SKIPPED", "FORCE_BY_AUTOMATION_REFUSED:%s" % actor, False)
        doc["mode"] = "FORCED_MANUAL_EXCEPTION"
        return finish("RUN_FORCED_MANUAL", "MANUAL_FORCE_BY:%s" % actor, True)

    if state_error is not None:
        return finish("SKIPPED", "GATE_STATE_UNAVAILABLE:%s" % str(state_error)[:200], False)

    attempts = list(attempts or [])
    doc["attempts_considered"] = len(attempts)
    if any(a["outcome"] == IN_PROGRESS for a in attempts):
        return finish("SKIPPED", "CONCURRENT_ATTEMPT_IN_PROGRESS", False)
    failures = consecutive_failures(attempts)
    if history_truncated and failures and failures == len(attempts):
        # Older failures may exist beyond the bounded scan: assume the longest backoff.
        failures = max(failures, BACKOFF_CAP_FAILURES)
    gap = required_gap(failures)
    doc.update({"consecutive_failures": failures, "required_gap_h": hours(gap)})
    last = attempts[0] if attempts else None
    if last:
        started = parse_time(last["started_at"])
        doc["last_attempt"] = {k: last.get(k) for k in ("run_id", "event", "outcome",
                                                         "conclusion", "started_at")}
        doc["last_attempt_age_h"] = hours(now - started)
        doc["last_attempt_unpublished"] = bool(
            last["outcome"] == SUCCEEDED and (fresh_anchor is None or fresh_anchor < started))

    if fresh_anchor is not None and now - fresh_anchor < WINDOW:
        return finish("SKIPPED", "REPORT_FRESH", False)
    if last and now - parse_time(last["started_at"]) < gap:
        return finish("SKIPPED", "BACKOFF_AFTER_FAILURES" if failures >= 2 else
                      ("RECENT_FAILED_ATTEMPT" if failures == 1 else "RECENT_ATTEMPT"), False)
    doc["mode"] = "RECOVERY_AFTER_FAILURE" if failures else (
        "RECOVERY_AFTER_UNPUBLISHED" if doc["last_attempt_unpublished"] else "NORMAL")
    return finish("RUN", "WINDOW_ELAPSED", True)


# --------------------------------------------------------------------------- I/O layer

class GitHubApi:
    """Minimal read-only REST client (api.github.com only, workflow token)."""

    def __init__(self, repository, token, base="https://api.github.com", opener=None):
        self.repository, self.token, self.base = repository, token, base.rstrip("/")
        self.opener = opener or urllib.request.urlopen

    def get(self, endpoint, **query):
        url = "%s/repos/%s/%s" % (self.base, self.repository, endpoint.lstrip("/"))
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "v6-activation-gate", **(
                {"Authorization": "Bearer %s" % self.token} if self.token else {})})
        try:
            with self.opener(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - any failure closes the gate
            raise GateStateUnavailable("%s %s" % (endpoint, type(exc).__name__)) from exc


def list_runs(api, *, since, workflow=WORKFLOW_FILE):
    runs = []
    for page in range(1, MAX_PAGES + 1):
        data = api.get("actions/workflows/%s/runs" % workflow, branch="main", per_page=RUNS_PER_PAGE,
                       page=page, created=">=" + since)
        if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
            raise GateStateUnavailable("runs listing malformed")
        runs += data["workflow_runs"]
        if len(data["workflow_runs"]) < RUNS_PER_PAGE:
            break
    return sorted(runs, key=lambda r: int(r.get("id") or 0), reverse=True)


def read_attempts(api, *, now, current_run_id, workflow=WORKFLOW_FILE, meta=None):
    """Earlier non-PR attempts on main within LOOKBACK, newest first.

    The newest attempt is always found first (it alone fixes the 6 h rule). Scanning stops at
    the first successful attempt or at the backoff cap; ``meta`` records truncation."""
    meta = meta if meta is not None else {}
    since = (now - LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = list_runs(api, since=since, workflow=workflow)
    attempts, lookups = [], 0
    meta.update({"runs_listed": len(runs), "job_lookups": 0, "history_truncated": False})
    current = int(current_run_id) if str(current_run_id or "").isdigit() else None
    for run in runs:
        if str(run.get("id")) == str(current_run_id) or run.get("event") == "pull_request":
            continue
        if current is not None and int(run.get("id") or 0) > current:
            # Newer runs queue behind this one on the concurrency group and decide after it.
            continue
        if run.get("status") != "completed":
            # An OLDER run still active inside the mutex window: never treat as absent.
            attempts.append({"run_id": run["id"], "event": run.get("event"),
                             "started_at": run.get("run_started_at") or run.get("created_at"),
                             "outcome": IN_PROGRESS, "conclusion": None})
            continue
        if lookups >= MAX_JOB_LOOKUPS:
            meta["history_truncated"] = True
            break
        lookups += 1
        meta["job_lookups"] = lookups
        jobs = api.get("actions/runs/%s/jobs" % run["id"], filter="latest", per_page=50)
        evaluate = [j for j in (jobs or {}).get("jobs", []) if j.get("name") == EVALUATE_JOB]
        if not evaluate or not executed(evaluate[0]):
            continue          # gate said SKIPPED, or the run was cancelled before computing
        job = evaluate[0]
        attempts.append({"run_id": run["id"], "event": run.get("event"),
                         "started_at": job.get("started_at") or run.get("run_started_at"),
                         "outcome": attempt_outcome(run.get("status"), run.get("conclusion")),
                         "conclusion": run.get("conclusion")})
        if attempts[-1]["outcome"] == SUCCEEDED or \
                consecutive_failures(attempts) >= BACKOFF_CAP_FAILURES:
            break
    return attempts


def read_published_report(root, api=None):
    """The report as it is on main NOW (fetched inside the protected section)."""
    import hashlib
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    try:
        git("fetch", "--quiet", "--no-tags", "--depth=1", "origin", "main")
        head = git("rev-parse", "FETCH_HEAD").decode().strip()
        blob = git("show", "FETCH_HEAD:" + REPORT)
    except subprocess.CalledProcessError as exc:
        raise GateStateUnavailable("git %s" % (exc.stderr or b"").decode()[:120]) from exc
    try:
        generated_at = json.loads(blob).get("generated_at")
    except ValueError:
        generated_at = None
    doc = {"main_head": head, "generated_at": generated_at, "published_at": None,
           "published_commit": None, "sha256": hashlib.sha256(blob).hexdigest()}
    if api is not None:
        commits = api.get("commits", sha=head, path=REPORT, per_page=1)
        if isinstance(commits, list) and commits:
            doc["published_commit"] = commits[0].get("sha")
            doc["published_at"] = ((commits[0].get("commit") or {}).get("committer") or {}).get("date")
    return doc


def event_from_env(env=os.environ):
    payload = {}
    path = env.get("GITHUB_EVENT_PATH")
    if path and Path(path).is_file():
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"event_name": env.get("GITHUB_EVENT_NAME"), "ref": env.get("GITHUB_REF"),
            "repository": env.get("GITHUB_REPOSITORY"), "run_id": env.get("GITHUB_RUN_ID"),
            "actor": env.get("GITHUB_TRIGGERING_ACTOR") or env.get("GITHUB_ACTOR"),
            "workflow_run": payload.get("workflow_run"), "inputs": payload.get("inputs")}


def summary_markdown(doc):
    rows = [("decision", doc["decision"]), ("reason", doc["reason"]), ("trigger", doc["trigger"]),
            ("mode", doc.get("mode")), ("last published report age (h)", doc["last_published_age_h"]),
            ("last published commit", doc["last_published_commit"]),
            ("last published report sha256", doc["last_published_report_sha256"]),
            ("last attempt", json.dumps(doc["last_attempt"]) if doc["last_attempt"] else None),
            ("consecutive failures", doc["consecutive_failures"]),
            ("required gap (h)", doc["required_gap_h"]),
            ("forced reason", doc["force_reason"]), ("upstream", json.dumps(doc["upstream"]))]
    lines = ["### V6 activation gate", "", "| field | value |", "|---|---|"]
    lines += ["| %s | `%s` |" % (k, v) for k, v in rows]
    return "\n".join(lines) + "\n"


def run(env=os.environ, root=Path.cwd(), now=None, api=None, dry_run_event=None):
    event = event_from_env(env)
    if dry_run_event:
        # Non-binding preview (PR CI): what this gate would decide right now on main.
        event.update({"event_name": dry_run_event, "ref": MAIN_REF, "inputs": {}})
    now = now or datetime.now(timezone.utc)
    api = api or GitHubApi(env.get("GITHUB_REPOSITORY", ""), env.get("GITHUB_TOKEN"))
    report, attempts, error, meta = {}, [], None, {}
    if event["event_name"] != "pull_request" and validate_trigger(event) is None:
        try:
            report = read_published_report(root, api)
            attempts = read_attempts(api, now=now, current_run_id=event["run_id"], meta=meta)
        except GateStateUnavailable as exc:
            error = exc
        except Exception as exc:  # noqa: BLE001 - unexpected state: fail closed, auditable
            error = GateStateUnavailable("%s: %s" % (type(exc).__name__, str(exc)[:120]))
    doc = decide(event, now=now, report=report, attempts=attempts, state_error=error,
                 history_truncated=bool(meta.get("history_truncated")))
    doc["main_head_at_decision"] = report.get("main_head")
    doc["history"] = meta or None
    doc["dry_run"] = bool(dry_run_event)
    return doc


def main(argv=None, env=os.environ):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run-as", choices=("schedule", "workflow_dispatch"),
                        help="preview the decision for this trigger; never sets outputs")
    args = parser.parse_args(argv)
    doc = run(env, args.root, dry_run_event=args.dry_run_as)
    print(NAME, json.dumps(doc, sort_keys=True))
    level = "warning" if doc["decision"] == "RUN_FORCED_MANUAL" or (
        doc.get("consecutive_failures") or 0) >= 1 or "UNAVAILABLE" in doc["reason"] else "notice"
    print("::%s title=%s_%s::%s (trigger=%s, report_age_h=%s, failures=%s)" % (
        level, NAME, doc["decision"], doc["reason"], doc["trigger"], doc["last_published_age_h"],
        doc["consecutive_failures"]))
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(("_dry run (non-binding)_\n\n" if args.dry_run_as else "") + summary_markdown(doc))
    if env.get("GITHUB_OUTPUT") and not args.dry_run_as:
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("run=%s\ndecision=%s\nreason=%s\n" % (
                "true" if doc["run"] else "false", doc["decision"], doc["reason"].replace("\n", " ")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
