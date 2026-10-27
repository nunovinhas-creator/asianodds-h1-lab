"""Build the V4 report from tracked evidence; inspect collection logs when authorised."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v4_audit import CUTOVER, generate, instant

ROOT = Path(__file__).resolve().parents[1]
REPO = "nunovinhas-creator/asianodds-h1-lab"
ENDPOINT = "https://api.github.com/repos/" + REPO
FAILURE = re.compile(r"LAB_MARKET_V4_[A-Z_]*FAILED")
RUN_FILE = "v4-runchecks.jsonl"


def api(path, token, *, binary=False):
    request = urllib.request.Request(
        ENDPOINT + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "asianodds-h1-v4-audit"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    return raw if binary else json.loads(raw)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose GitHub's signed log-download redirect without forwarding auth."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_job_logs(job_id, token):
    """Fetch GitHub job logs without forwarding the GitHub token off-site.

    The Jobs Logs REST endpoint returns HTTP 302 to a temporary signed storage
    URL. urllib's default redirect handler forwards Authorization to that host,
    which can produce HTTP 401. Handle the redirect explicitly and strip all
    credential headers. No URL or raw log contents are persisted.
    """
    req = urllib.request.Request(
        ENDPOINT + "/actions/jobs/" + str(int(job_id)) + "/logs",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "asianodds-h1-v4-audit"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=20) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location:
            raise ValueError("log_redirect_missing")
        url = urllib.parse.urlsplit(location)
        host = (url.hostname or "").lower()
        # Signed GitHub Actions storage; never send a GitHub credential here.
        allowed = (".actions.githubusercontent.com", ".blob.core.windows.net",
                   ".githubusercontent.com")
        if url.scheme != "https" or not any(host.endswith(suffix) for suffix in allowed):
            raise ValueError("log_redirect_untrusted_host")
        redirect_req = urllib.request.Request(
            location, headers={"User-Agent": "asianodds-h1-v4-audit"})
        with urllib.request.urlopen(redirect_req, timeout=20) as response:
            return response.read()


def scan_run(run_id, token):
    """Verify complete collected-job logs. Never publish downloaded log text."""
    stage = "list_jobs"
    try:
        jobs = api("/actions/runs/" + str(int(run_id)) + "/jobs?per_page=100", token)
        job_items = jobs.get("jobs", [])
        if not job_items or len(job_items) >= 100 or jobs.get("total_count", len(job_items)) != len(job_items):
            raise ValueError("job_count_uncertain")
        failures = 0
        for job in job_items:
            stage = "download_job_logs"
            raw = download_job_logs(job["id"], token)
            failures += len(FAILURE.findall(raw.decode("utf-8", errors="replace")))
        return {"run_id": int(run_id), "status": "clean" if failures == 0 else "fail",
                "error_count": failures}
    except urllib.error.HTTPError as exc:
        # Only publish HTTP status and stage, never URLs, headers, tokens or log text.
        return {"run_id": int(run_id), "status": "unverified",
                "reason": "http_" + str(exc.code), "stage": stage}
    except (ValueError, KeyError, TimeoutError, OSError, urllib.error.URLError) as exc:
        return {"run_id": int(run_id), "status": "unverified",
                "reason": type(exc).__name__, "stage": stage}


def read_journal(root):
    file = root / "data" / "lab" / RUN_FILE
    if not file.exists():
        return {}
    rows = {}
    for n, line in enumerate(file.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line.decode("utf-8"))
            if not isinstance(obj, dict) or not isinstance(obj.get("run_id"), int):
                raise ValueError()
            rows[obj["run_id"]] = obj
        except (ValueError, UnicodeDecodeError):
            rows["invalid_" + str(n)] = {"status": "unverified", "reason": "journal_corrupt"}
    return rows


def all_window_runs(token):
    since = instant(CUTOVER)
    from datetime import timedelta
    until = since + timedelta(hours=24)
    dates = since.strftime("%Y-%m-%dT%H:%M:%SZ") + ".." + until.strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    for page in range(1, 12):
        query = urllib.parse.urlencode({"per_page": 100, "page": page, "created": dates})
        data = api("/actions/workflows/collect.yml/runs?" + query, token)
        batch = data.get("workflow_runs", [])
        for run in batch:
            if run.get("head_branch") != "main":
                continue
            created = instant(run.get("created_at"))
            if created and since <= created < until:
                found[run["id"]] = {"status": run.get("status"), "conclusion": run.get("conclusion")}
        if len(batch) < 100:
            return found
    raise ValueError("too many runs to certify fully")


def log_evidence(root, token, run_id, now):
    """Judge V4 markers, not overall Telegram/collector success.

    Cancelled runs are reported as not executed (not errors, not clean logs).
    Completed runs with unreadable logs remain unverified, never PASS.
    """
    journal = read_journal(root)
    runs, listing_error = {}, None
    if token:
        try:
            runs = all_window_runs(token)
        except (ValueError, KeyError, TimeoutError, OSError, urllib.error.URLError) as exc:
            listing_error = type(exc).__name__

    if token and not listing_error:
        for rid, run in runs.items():
            if run["status"] == "completed" and run["conclusion"] in ("cancelled", "skipped"):
                journal[rid] = {"run_id": rid, "status": "not_executed",
                                "reason": run["conclusion"]}
    todo = []
    if token and run_id and runs.get(int(run_id), {}).get("status") == "completed":
        if runs[int(run_id)]["conclusion"] not in ("cancelled", "skipped"):
            if journal.get(int(run_id), {}).get("status") not in ("clean", "fail"):
                todo.append(int(run_id))
    if token and not listing_error:
        todo.extend(rid for rid, run in sorted(runs.items()) if
                    run["status"] == "completed" and
                    run["conclusion"] not in ("cancelled", "skipped") and
                    journal.get(rid, {}).get("status") not in ("clean", "fail"))

    inspected = set()
    for rid in todo:
        if rid in inspected:
            continue
        if len(inspected) >= 8:
            break
        inspected.add(rid)
        item = scan_run(rid, token)
        item["checked_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        journal[rid] = item

    if inspected or any(x.get("status") == "not_executed" for x in journal.values()):
        destination = root / "data" / "lab" / RUN_FILE
        destination.parent.mkdir(parents=True, exist_ok=True)
        valid = {k: v for k, v in journal.items() if isinstance(k, int)}
        destination.write_text("".join(json.dumps(v, sort_keys=True) + "\n"
                                       for k, v in sorted(valid.items())), encoding="utf-8")

    counts = {"checked": sum(v.get("status") in ("clean", "fail") for v in journal.values()),
              "v4_errors_detected": sum(v.get("status") == "fail" for v in journal.values()),
              "unverified_runs": sum(v.get("status") == "unverified" for v in journal.values()),
              "not_executed": sum(v.get("status") == "not_executed" for v in journal.values())}
    info = {"status": "unverified", "summary": counts,
            "reason": "Complete collection log evidence still pending"}
    if not token:
        info["reason"] = "GITHUB_TOKEN/actions:read unavailable"
        return info
    if listing_error:
        info["reason"] = "Could not enumerate complete run history: " + listing_error
        return info

    cancelled = sorted(rid for rid, run in runs.items()
                       if run["conclusion"] in ("cancelled", "skipped"))
    unrelated = sorted(rid for rid, run in runs.items()
                       if run["conclusion"] in ("failure", "timed_out") and
                       journal.get(rid, {}).get("status") == "clean")
    v4_bad = sorted(rid for rid in runs if journal.get(rid, {}).get("status") == "fail")
    pending = sorted(rid for rid, run in runs.items() if
                     run["status"] != "completed" or
                     (run["conclusion"] not in ("cancelled", "skipped") and
                      journal.get(rid, {}).get("status") not in ("clean", "fail")))
    info.update({"runs_in_window": len(runs), "v4_failed_run_ids": v4_bad,
                 "collector_non_v4_failed_run_ids": unrelated,
                 "not_executed_run_ids": cancelled,
                 "unclean_or_pending_run_ids": pending,
                 "unscanned_run_ids": sorted(rid for rid in runs if rid not in journal)})
    from datetime import timedelta
    end = instant(CUTOVER) + timedelta(hours=24)
    if v4_bad:
        info["status"] = "v4_errors_detected"
        info["reason"] = "At least one collection run logged LAB_MARKET_V4_*_FAILED"
    elif now >= end and runs and not pending:
        info["status"] = "verified_24h_clean"
        info["reason"] = "All executed collect runs inspected; cancelled runs excluded and listed"
    else:
        info["reason"] = "24h window unfinished or executed runs not all verified"
    return info


def main():
    now = datetime.now(timezone.utc)
    run_id = os.environ.get("LAB_COLLECT_RUN_ID")
    token = os.environ.get("GITHUB_TOKEN")
    logs = log_evidence(ROOT, token, run_id, now)
    report = generate(ROOT, now=now, source_commit=os.environ.get("LAB_SOURCE_SHA", "unknown"),
                      log_evidence=logs)
    target = ROOT / "docs" / "lab" / "v4-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print("LAB_V4_AUDIT", report["status"], "coverage",
          report["phase_coverage"]["first_24h"], "issues", len(report["issues"]),
          "logs", logs["status"])


if __name__ == "__main__":
    main()
