"""Pre-call LLM attempt ledger for the autonomous research workflow (no LLM secrets).

Why: the memory-based daily count only sees cycles that were PUBLISHED. A call that was
made but never reached memory (invalid reply, executor error, timeout, push conflict,
cancelled publisher) would be invisible, so extra manual dispatches could exceed the
daily budget. This ledger counts ATTEMPTS from GitHub's own run history instead, which
exists whether or not anything was published.

Counted, per UTC day, across every workflow that can reach the shared Cloudflare account
(``LEDGER_WORKFLOWS``, all in concurrency group ``v6-llm-global``):
  every job step whose name contains an LLM marker and that STARTED (any conclusion
  except ``skipped``; in-progress or unknown counts), over ALL run attempts.
A run touching today in any timestamp (created/started/updated) is examined, so a run
created 23:59 and executed 00:01 counts for the new day. The current run is excluded
(it is the attempt being authorised). Over-counting is accepted (fail closed): a
refused-before-call attempt still consumes a slot.

Any API error, pagination overflow or unexpected shape -> exit 2, no output, and the
discover job is skipped (no LLM call). Uses only GITHUB_TOKEN (actions: read); no paid API.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

from h1lab.research_daily_limit import daily_llm_attempt_limit

API = 'https://api.github.com'
LEDGER_WORKFLOWS = ('v6-llm-autonomous.yml', 'v6-llm-investigator.yml')
# Substrings identifying the step that may contact the provider in each workflow
# (current research workflow, retired autonomous workflow, manual investigator).
LLM_STEP_MARKERS = ('LLM call', 'Cloudflare Workers AI')
MAX_DAILY_LLM_ATTEMPTS = 4          # base rule; dated exception in h1lab.research_daily_limit
PAGE = 100


def _touches(run, day_start):
    stamps = [run.get(k) for k in ('created_at', 'run_started_at', 'updated_at')]
    if not any(isinstance(s, str) for s in stamps):
        return True                                   # unknown -> examine (fail closed)
    for s in stamps:
        if isinstance(s, str):
            try:
                if datetime.fromisoformat(s.replace('Z', '+00:00')) >= day_start:
                    return True
            except ValueError:
                return True
    return False


def step_started(step):
    if not isinstance(step, dict):
        return True
    if step.get('conclusion') == 'skipped':
        return False
    if step.get('status') in ('queued', 'pending', 'waiting') and step.get('conclusion') is None:
        return False
    return True


def attempts_in_jobs(jobs):
    """Number of started LLM steps across the jobs (all attempts) of one run."""
    n = 0
    for job in jobs:
        steps = job.get('steps')
        if not isinstance(steps, list):
            if job.get('status') != 'completed' or job.get('conclusion') not in ('skipped',):
                n += 1                                # job without step data -> count
            continue
        for step in steps:
            name = step.get('name', '') if isinstance(step, dict) else ''
            if any(m in name for m in LLM_STEP_MARKERS) and step_started(step):
                n += 1
    return n


def count_attempts(runs_by_workflow, jobs_by_run, *, now, exclude_run_id):
    """Pure counting core (unit-tested). Returns (total, details)."""
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total, details = 0, []
    for wf, runs in sorted(runs_by_workflow.items()):
        for run in runs:
            rid = run.get('id')
            if str(rid) == str(exclude_run_id) or not _touches(run, day_start):
                continue
            jobs = jobs_by_run.get(rid)
            if jobs is None:
                raise ValueError('LEDGER_JOBS_MISSING_%s' % rid)
            n = attempts_in_jobs(jobs)
            if n:
                total += n
                details.append({'workflow': wf, 'run_id': rid, 'event': run.get('event'), 'attempts': n})
    return total, details


def _get(url, token, opener):
    req = Request(url, headers={'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + token,
                                'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'master-brain-research-budget/1'})
    with opener(req, timeout=20) as resp:
        if resp.status != 200:
            raise ValueError('LEDGER_HTTP_%s' % resp.status)
        return json.loads(resp.read(5_000_000).decode('utf-8'))


def fetch(repo, token, *, now, opener=urlopen):
    since = (now.astimezone(timezone.utc) - timedelta(days=1)).date().isoformat()
    runs_by_wf, jobs_by_run = {}, {}
    for wf in LEDGER_WORKFLOWS:
        data = _get('%s/repos/%s/actions/workflows/%s/runs?per_page=%d&created=%s' % (
            API, repo, wf, PAGE, quote('>=' + since)), token, opener)
        runs = data.get('workflow_runs')
        if not isinstance(runs, list) or not isinstance(data.get('total_count'), int):
            raise ValueError('LEDGER_RUNS_SHAPE')
        if data['total_count'] > len(runs):
            raise ValueError('LEDGER_TOO_MANY_RUNS')    # cannot see everything -> refuse
        runs_by_wf[wf] = runs
        for run in runs:
            jd = _get('%s/repos/%s/actions/runs/%s/jobs?filter=all&per_page=%d' % (API, repo, run['id'], PAGE),
                      token, opener)
            jobs = jd.get('jobs')
            if not isinstance(jobs, list) or jd.get('total_count', 0) > len(jobs):
                raise ValueError('LEDGER_JOBS_SHAPE')
            jobs_by_run[run['id']] = jobs
    return runs_by_wf, jobs_by_run


def main(argv=None, *, env=None, opener=urlopen, now=None):
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', required=True)
    ap.add_argument('--exclude-run', required=True)
    ap.add_argument('--github-output', default=None)
    args = ap.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    try:
        token = env.get('GH_TOKEN', '')
        if not token:
            raise ValueError('LEDGER_TOKEN_MISSING')
        runs, jobs = fetch(args.repo, token, now=now, opener=opener)
        total, details = count_attempts(runs, jobs, now=now, exclude_run_id=args.exclude_run)
    except Exception as exc:  # any doubt -> no output -> discover skipped, no LLM call
        print(json.dumps({'status': 'LEDGER_UNAVAILABLE', 'reason': type(exc).__name__ + ': ' + str(exc)[:200]}))
        return 2
    day = now.astimezone(timezone.utc).date().isoformat()
    limit = daily_llm_attempt_limit(day)
    report = {'status': 'LEDGER_OK', 'utc_day': day,
              'prior_llm_attempts': total, 'limit': limit,
              'remaining': max(0, limit - total), 'counted': details}
    print(json.dumps(report, sort_keys=True))
    if args.github_output:
        with open(args.github_output, 'a', encoding='utf-8') as fh:
            fh.write('prior=%d\n' % total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
