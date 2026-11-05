"""Controlled rehearsal of the central LLM quota controller against the REAL GitHub API.

Scope (deliberately narrow):
- Exercises h1lab.research_quota.GitHubStore / Controller with the workflow GITHUB_TOKEN:
  contents:write (Contents API SHA compare-and-swap) and actions:read (run/job history).
- All writes go to disposable, run-scoped branches ``llm-quota-trial/<run_id>-<suffix>``
  created from the operational ledger tip and deleted at the end. The operational
  ``llm-quota-ledger`` branch is only READ (before/after snapshot); any change aborts.
- Zero LLM / Cloudflare traffic: no provider secret is available to this workflow, no
  provider module is imported, and send() receives a local stub. Reservations recorded
  on trial branches are TEST data (model TRIAL-NO-PROVIDER) and never touch real quota.

Phases (one per workflow job): setup, denied, granted, verify, cleanup.
Each phase prints one JSON evidence document and exits non-zero on any unexpected result.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

from h1lab import research_quota as rq

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'TRIAL-NO-PROVIDER'
SUFFIXES = ('cas', 'invalid')
REFUSED = 'QUOTA_API_UNAVAILABLE_OR_CAS_CONFLICT'


class TrialFailure(AssertionError):
    pass


def check(cond, code, **detail):
    if not cond:
        raise TrialFailure(code + ' ' + json.dumps(detail, sort_keys=True, default=str))


def trial_branch(run_id, suffix):
    branch = 'llm-quota-trial/%s-%s' % (run_id, suffix)
    check(branch != rq.BRANCH and re.fullmatch(rq.TRIAL_BRANCH, branch), 'TRIAL_BRANCH_UNSAFE', branch=branch)
    return branch


def raw(store, method, path, data=None):
    """Minimal REST helper (refs only) reusing the store's no-redirect opener. Returns (status, obj)."""
    body = None if data is None else json.dumps(data).encode()
    req = Request(store.base + path, data=body, method=method,
                  headers={'Authorization': 'Bearer ' + store.token, 'Accept': 'application/vnd.github+json',
                           'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with store.opener(req, timeout=20) as resp:
            text = resp.read(2_000_000)
            return resp.status, (json.loads(text) if text else None)
    except HTTPError as exc:
        return exc.code, None


def ledger_snapshot(repo, token):
    """Read-only fingerprint of the operational ledger (branch tip + blob + event count)."""
    op = rq.GitHubStore(repo, token)  # default branch = operational ledger; read() only
    status, ref = raw(op, 'GET', '/git/ref/heads/' + rq.BRANCH)
    check(status == 200, 'OPERATIONAL_LEDGER_BRANCH_UNREADABLE', status=status)
    state, blob = op.read()
    return {'branch': rq.BRANCH, 'commit': ref['object']['sha'], 'blob': blob, 'events': len(state['events'])}


def expect_refusal(fn, codes):
    try:
        fn()
    except ValueError as exc:
        check(str(exc) in codes, 'UNEXPECTED_REFUSAL_CODE', got=str(exc), expected=codes)
        return str(exc)
    raise TrialFailure('EXPECTED_REFUSAL_NOT_RAISED %s' % (codes,))


class TrialStore(rq.GitHubStore):
    """Real read/cas against a trial branch. history() is the ONLY substitution: the real
    history() is exercised separately (and must refuse, because a trial run is not one of
    the two LLM workflows). ``gate`` lets the race test park both writers after read()."""
    gate = None

    def history(self, current_run):
        if self.gate is not None:
            self.gate.wait(timeout=30)
        return []


def env():
    e = {k: os.environ.get(k, '') for k in ('GITHUB_REPOSITORY', 'GH_TOKEN', 'GITHUB_RUN_ID')}
    check(all(e.values()), 'TRIAL_ENV_MISSING', missing=[k for k, v in e.items() if not v])
    check(re.fullmatch(r'[0-9]+', e['GITHUB_RUN_ID']), 'TRIAL_RUN_ID_INVALID')
    for forbidden in ('CLOUDFLARE_ACCOUNT_ID', 'MASTER_BRAIN_LLM_API_KEY'):
        check(not os.environ.get(forbidden), 'PROVIDER_SECRET_PRESENT', name=forbidden)
    return e


def live_flag():
    cfg = json.loads((ROOT / 'config/research-autonomy.json').read_text(encoding='utf-8'))
    check(cfg.get('llm_live_enabled') is False, 'LLM_LIVE_NOT_DISABLED', value=cfg.get('llm_live_enabled'))
    return False


# ---------------------------------------------------------------- phases

def phase_setup(e, ev):
    store = rq.GitHubStore(e['GITHUB_REPOSITORY'], e['GH_TOKEN'])
    snap = ledger_snapshot(e['GITHUB_REPOSITORY'], e['GH_TOKEN'])
    out = {'operational_before': snap, 'branches': {}}
    for suffix in SUFFIXES:
        branch = trial_branch(e['GITHUB_RUN_ID'], suffix)
        status, _ = raw(store, 'POST', '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': snap['commit']})
        check(status == 201, 'TRIAL_BRANCH_CREATE_REFUSED', branch=branch, status=status)
        state, blob = rq.GitHubStore(e['GITHUB_REPOSITORY'], e['GH_TOKEN'], branch=branch).read()
        out['branches'][suffix] = {'name': branch, 'from_commit': snap['commit'], 'blob': blob,
                                   'events': len(state['events'])}
    return out


def phase_denied(e, ev):
    """Token WITHOUT contents:write / actions:read: every mutation and history read must fail closed."""
    branch = ev['setup']['branches']['cas']['name']
    store = TrialStore(e['GITHUB_REPOSITORY'], e['GH_TOKEN'], branch=branch)
    real = rq.GitHubStore(e['GITHUB_REPOSITORY'], e['GH_TOKEN'], branch=branch)
    state, blob = store.read()  # contents:read still allows reading
    new = copy.deepcopy(state)
    rq.append(new, {'kind': 'reserve', 'id': 'run:%s90' % e['GITHUB_RUN_ID'], 'run_id': e['GITHUB_RUN_ID'] + '90',
                    'at': '2026-01-01T00:00:00+00:00', 'reserved': rq.MAX_NEURONS_PER_CALL, 'model': MODEL})
    cas_code = expect_refusal(lambda: store.cas(state, new, blob), (REFUSED,))
    # Without actions:read the listing is refused (private repo) or, on a public repo, readable
    # anonymously; either way history() never admits this run. Recorded as observed.
    hist_code = expect_refusal(lambda: real.history(e['GITHUB_RUN_ID']), (REFUSED, 'QUOTA_CURRENT_RUN_NOT_VISIBLE'))
    # Full controller path up to the CAS (history stubbed empty): the write itself is refused.
    reserve_code = expect_refusal(lambda: rq.Controller(store).reserve(e['GITHUB_RUN_ID'] + '91', MODEL, 900), (REFUSED,))
    after, blob_after = store.read()
    check(blob_after == blob and after == state, 'DENIED_TOKEN_CHANGED_STATE')
    return {'branch': branch, 'cas_without_contents_write': cas_code, 'history_without_actions_read': hist_code,
            'reserve_without_permissions': reserve_code, 'state_unchanged': True, 'blob': blob}


def phase_granted(e, ev):
    rid, repo, tok = e['GITHUB_RUN_ID'], e['GITHUB_REPOSITORY'], e['GH_TOKEN']
    cas_branch = ev['setup']['branches']['cas']['name']
    bad_branch = ev['setup']['branches']['invalid']['name']
    out = {}

    # 1. actions:read — real history() paginates both LLM workflows and all job attempts,
    #    then refuses because THIS run is not one of them (proves full read, no admission).
    hist = rq.GitHubStore(repo, tok)
    out['history_real_api'] = expect_refusal(lambda: hist.history(rid), (
        'QUOTA_CURRENT_RUN_NOT_VISIBLE', 'QUOTA_OTHER_EXECUTION_UNRESOLVED'))
    totals = {}
    for wf in rq.WORKFLOWS:
        status, obj = raw(hist, 'GET', '/actions/workflows/%s/runs?per_page=1' % wf)
        check(status == 200, 'ACTIONS_READ_DENIED', workflow=wf, status=status)
        totals[wf] = obj['total_count']
    out['actions_read_run_totals'] = totals

    # 2. Full reserve -> send(stub) -> settle on a trial branch, two durable CAS commits.
    calls = []
    store = TrialStore(repo, tok, branch=cas_branch)
    q = rq.Controller(store)
    r = q.reserve(rid + '01', MODEL, 900)
    check(r['unresolved_reservations'] == 1 and r['account_quota_verified'] is False, 'RESERVE_SUMMARY_WRONG', r=r)
    q.send(lambda: calls.append('LOCAL_STUB_NO_NETWORK'))
    expect_refusal(lambda: q.send(lambda: calls.append('SECOND')), ('QUOTA_RESERVATION_REQUIRED_OR_ALREADY_USED',))
    s = q.settle(123)
    check(calls == ['LOCAL_STUB_NO_NETWORK'] and s['charged_estimated_neurons'] == 123, 'SETTLE_WRONG', s=s)
    out['reserve_send_settle'] = {'reserve': r, 'settle': s, 'stub_calls': len(calls)}

    # 3. Duplicate execution refused without a write.
    _, before = store.read()
    out['duplicate_run'] = expect_refusal(lambda: rq.Controller(store).reserve(rid + '01', MODEL, 900),
                                          ('QUOTA_DUPLICATE_EXECUTION',))
    check(store.read()[1] == before, 'DUPLICATE_WROTE')

    # 4. Stale SHA: a writer holding an old SHA loses after someone else committed.
    stale_state, stale_sha = store.read()
    rq.Controller(store).reserve(rid + '02', MODEL, 900)
    fresh_state, fresh_sha = store.read()
    forged = copy.deepcopy(stale_state)
    rq.append(forged, {'kind': 'reserve', 'id': 'run:%s03' % rid, 'run_id': rid + '03',
                       'at': fresh_state['events'][-1]['at'], 'reserved': rq.MAX_NEURONS_PER_CALL, 'model': MODEL})
    out['stale_sha'] = expect_refusal(lambda: store.cas(stale_state, forged, stale_sha), (REFUSED,))
    check(store.read() == (fresh_state, fresh_sha), 'STALE_SHA_WROTE')

    # 5. Real concurrency: two writers read the SAME sha, then CAS simultaneously.
    races = []
    for rnd in range(3):
        gate = threading.Barrier(2)
        results = {}
        base_state, base_sha = store.read()

        def contender(tag, run):
            s2 = TrialStore(repo, tok, branch=cas_branch)
            s2.gate = gate
            try:
                rq.Controller(s2).reserve(run, MODEL, 900)
                results[tag] = 'ACCEPTED'
            except ValueError as exc:
                results[tag] = str(exc)
        runs = {'A': '%s1%d' % (rid, rnd), 'B': '%s2%d' % (rid, rnd)}
        threads = [threading.Thread(target=contender, args=(t, r)) for t, r in runs.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        after_state, after_sha = store.read()
        winners = [t for t, v in results.items() if v == 'ACCEPTED']
        check(len(winners) <= 1, 'CAS_DOUBLE_ACCEPT', results=results)
        check(all(v in ('ACCEPTED', REFUSED) for v in results.values()), 'RACE_UNEXPECTED', results=results)
        added = after_state['events'][len(base_state['events']):]
        check(after_state['events'][:len(base_state['events'])] == base_state['events'], 'RACE_NOT_APPEND_ONLY')
        check([x['run_id'] for x in added] == [runs[w] for w in winners], 'RACE_STATE_MISMATCH',
              added=[x['id'] for x in added], winners=winners)
        races.append({'round': rnd, 'results': results, 'base_sha': base_sha, 'after_sha': after_sha,
                      'events_added': len(added)})
    out['concurrency'] = races

    # 6. Invalid state: tamper a COPY on the second trial branch; controller must refuse, no write.
    bad = rq.GitHubStore(repo, tok, branch=bad_branch)
    seed, seed_sha = bad.read()
    broken = copy.deepcopy(seed)
    rq.append(broken, {'kind': 'reserve', 'id': 'run:%s50' % rid, 'run_id': rid + '50',
                       'at': '2026-01-01T00:00:00+00:00', 'reserved': rq.MAX_NEURONS_PER_CALL, 'model': MODEL})
    broken['events'][-1]['reserved'] = 1  # hash no longer matches -> chain invalid
    content = base64.b64encode(rq.canonical(broken).encode()).decode()
    status, put = raw(bad, 'PUT', '/contents/' + rq.PATH, {
        'branch': bad_branch, 'sha': seed_sha, 'content': content,
        'message': 'test(quota-trial): deliberately corrupted COPY on disposable branch [skip ci]'})
    check(status in (200, 201), 'TAMPER_WRITE_FAILED', status=status)
    tampered_sha = put['content']['sha']
    out['invalid_chain'] = expect_refusal(lambda: TrialStore(repo, tok, branch=bad_branch).read(), ('QUOTA_CHAIN_INVALID',))
    out['invalid_reserve'] = expect_refusal(
        lambda: rq.Controller(TrialStore(repo, tok, branch=bad_branch)).reserve(rid + '51', MODEL, 900),
        ('QUOTA_CHAIN_INVALID',))
    status, cur = raw(bad, 'GET', '/contents/%s?ref=%s' % (rq.PATH, bad_branch))
    check(status == 200 and cur['sha'] == tampered_sha, 'INVALID_STATE_WAS_REWRITTEN')

    # 7. Missing state: never auto-created.
    ghost = trial_branch(rid, 'missing')
    out['missing_branch'] = expect_refusal(
        lambda: rq.Controller(TrialStore(repo, tok, branch=ghost)).reserve(rid + '60', MODEL, 900), (REFUSED,))
    check(raw(bad, 'GET', '/git/ref/heads/' + ghost)[0] == 404, 'MISSING_BRANCH_WAS_CREATED')

    # 8. Production entry point refuses outside main / first attempt; forbidden branches refused.
    out['from_environment_off_main'] = expect_refusal(lambda: rq.from_environment(dict(os.environ)),
                                                     ('QUOTA_MAIN_FIRST_ATTEMPT_REQUIRED',))
    out['forbidden_branch'] = expect_refusal(lambda: rq.GitHubStore(repo, tok, branch='main'), ('QUOTA_BRANCH_FORBIDDEN',))

    final_state, final_sha = store.read()
    out['cas_branch_final'] = {'blob': final_sha, 'events': [
        {k: x[k] for k in ('kind', 'id', 'at', 'sha256')} for x in final_state['events']]}
    return out


def phase_verify(e, ev):
    """Fresh runner, read-only: what the granted job wrote must still be there, intact."""
    branch = ev['setup']['branches']['cas']['name']
    store = TrialStore(e['GITHUB_REPOSITORY'], e['GH_TOKEN'], branch=branch)
    state, blob = store.read()  # read() re-validates the full hash chain
    expected = ev['granted']['cas_branch_final']
    check(blob == expected['blob'], 'PERSISTED_BLOB_MISMATCH', got=blob, expected=expected['blob'])
    check([x['sha256'] for x in state['events']] == [x['sha256'] for x in expected['events']], 'PERSISTED_EVENTS_MISMATCH')
    status, cmp = raw(store, 'GET', '/compare/%s...%s' % (ev['setup']['operational_before']['commit'], branch))
    check(status == 200, 'COMPARE_FAILED', status=status)
    commits = [{'sha': c['sha'], 'message': c['commit']['message'].splitlines()[0]} for c in cmp['commits']]
    check(cmp['behind_by'] == 0 and all('[skip ci]' in c['message'] for c in commits), 'TRIAL_HISTORY_NOT_LINEAR')
    snap = ledger_snapshot(e['GITHUB_REPOSITORY'], e['GH_TOKEN'])
    check(snap == ev['setup']['operational_before'], 'OPERATIONAL_LEDGER_CHANGED', before=ev['setup']['operational_before'], after=snap)
    return {'branch': branch, 'events_persisted': len(state['events']), 'chain_valid': True,
            'commits_on_trial_branch': commits, 'operational_after': snap, 'operational_unchanged': True}


def phase_cleanup(e, ev):
    store = rq.GitHubStore(e['GITHUB_REPOSITORY'], e['GH_TOKEN'])
    deleted = {}
    for suffix in SUFFIXES:
        branch = trial_branch(e['GITHUB_RUN_ID'], suffix)
        status, _ = raw(store, 'DELETE', '/git/refs/heads/' + branch)
        deleted[branch] = status
    snap = ledger_snapshot(e['GITHUB_REPOSITORY'], e['GH_TOKEN'])
    before = (ev.get('setup') or {}).get('operational_before')
    check(before is None or snap == before, 'OPERATIONAL_LEDGER_CHANGED', before=before, after=snap)
    check(all(s in (204, 404, 422) for s in deleted.values()), 'TRIAL_BRANCH_DELETE_FAILED', deleted=deleted)
    return {'deleted_status': deleted, 'operational_after': snap, 'operational_unchanged': before is not None}


PHASES = {'setup': phase_setup, 'denied': phase_denied, 'granted': phase_granted,
          'verify': phase_verify, 'cleanup': phase_cleanup}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--phase', choices=sorted(PHASES), required=True)
    ap.add_argument('--evidence-dir', required=True, help='folder with earlier phase JSON (phase.json)')
    args = ap.parse_args(argv)
    folder = Path(args.evidence_dir)
    folder.mkdir(parents=True, exist_ok=True)
    ev = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in folder.glob('*.json')}
    e = env()
    try:
        result = {'phase': args.phase, 'ok': True, 'llm_live_enabled': live_flag(), 'provider_calls': 0,
                  'scope': 'REHEARSAL_ON_DISPOSABLE_BRANCHES_NO_LLM_NO_REAL_RESERVATIONS',
                  **PHASES[args.phase](e, ev)}
        code = 0
    except (TrialFailure, ValueError) as exc:
        result, code = {'phase': args.phase, 'ok': False, 'error': str(exc)}, 1
    (folder / (args.phase + '.json')).write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf-8')
    print(('QUOTA_TRIAL_%s_OK ' if code == 0 else 'QUOTA_TRIAL_%s_FAILED ') % args.phase.upper()
          + json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
