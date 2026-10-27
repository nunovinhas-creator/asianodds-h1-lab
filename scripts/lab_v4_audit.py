"""Build the V4 report from tracked evidence; inspect collection logs when authorised."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
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


def scan_run(run_id, token):
    """Return an explicitly verifiable result, never raw or private logs."""
    try:
        jobs = api("/actions/runs/" + str(int(run_id)) + "/jobs?per_page=100", token)
        job_items = jobs.get("jobs", [])
        if not job_items or len(job_items) >= 100:
            raise ValueError("job count uncertain")
        failures = 0
        for job in job_items:
            raw = api("/actions/jobs/" + str(job["id"]) + "/logs", token, binary=True)
            failures += len(FAILURE.findall(raw.decode("utf-8", errors="replace")))
        return {"run_id": int(run_id), "status": "clean" if failures == 0 else "fail",
                "error_count": failures}
    except (ValueError, KeyError, TimeoutError, OSError, urllib.error.URLError) as exc:
        return {"run_id": int(run_id), "status": "unverified", "reason": type(exc).__name__}


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
    journal = read_journal(root)
    runs, listing_error = {}, None
    if token:
        try:
            runs = all_window_runs(token)
        except (ValueError, KeyError, TimeoutError, OSError, urllib.error.URLError) as exc:
            listing_error = type(exc).__name__
    todo = []
    if token and run_id:
        todo.append(int(run_id))
    if token and not listing_error:
        # Backfill collector runs that predate the audit deployment; otherwise
        # a 24h log-clean verdict could NEVER be demonstrated.
        todo.extend(rid for rid, run in sorted(runs.items()) if
                    run["status"] == "completed" and
                    journal.get(rid, {}).get("status") != "clean")
    # Prevent a backlog from delaying five-minute H1 collections.
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
    if inspected:
        destination = root / "data" / "lab" / RUN_FILE
        destination.parent.mkdir(parents=True, exist_ok=True)
        valid = {k: v for k, v in journal.items() if isinstance(k, int)}
        destination.write_text("".join(json.dumps(v, sort_keys=True) + "\\n"
                                       for k, v in sorted(valid.items())), encoding="utf-8")
    counts = {"checked": sum(isinstance(k, int) for k in journal),
              "errors_detected": sum(v.get("status") == "fail" for v in journal.values()),
              "unverified_runs": sum(v.get("status") == "unverified" for v in journal.values())}
    info = {"status": "unverified", "summary": counts,
            "reason": "Full first-24h Actions run listing and logs not yet verified"}
    if not token:
        info["reason"] = "GITHUB_TOKEN/actions:read unavailable"
        return info
    if listing_error:
        info["reason"] = "Could not enumerate complete run history: " + listing_error
        return info
    missing = sorted(rid for rid in runs if rid not in journal)
    bad = sorted(rid for rid, item in runs.items()
                 if journal.get(rid, {}).get("status") == "fail" or item["conclusion"] == "failure")
    incomplete = sorted(rid for rid, item in runs.items()
                        if item["status"] != "completed" or
                        journal.get(rid, {}).get("status") != "clean")
    info.update({"runs_in_window": len(runs), "unscanned_run_ids": missing,
                 "failed_run_ids": bad, "unclean_or_pending_run_ids": incomplete})
    from datetime import timedelta
    end = instant(CUTOVER) + timedelta(hours=24)
    if now >= end and runs and not incomplete and not missing:
        info["status"] = "verified_24h_clean"
        info["reason"] = "All collection runs in first 24h checked without V4 errors"
    elif bad:
        info["status"] = "errors_detected"
        info["reason"] = "At least one collection run failed or logged a V4 exception"
    else:
        info["reason"] = "24h window unfinished or runs/logs not all checked"
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
