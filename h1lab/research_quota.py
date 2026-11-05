"""Central internal neuron budget. Durable reservation BEFORE any provider request.

The dedicated llm-quota-ledger branch must be provisioned from the merged main once.
Never auto-create/reset missing state. Contents API SHA compare-and-swap serializes
writers; a conflict, lost acknowledgement, corrupt history or API failure aborts.
Events are append-only; pending/unmetered reservations carry across UTC days until
reconciled. Token-derived usage is an estimate, never Cloudflare account quota.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

DAILY_NEURON_BUDGET = 8_000
MAX_NEURONS_PER_CALL = 1_000
FREE_NEURONS_PER_DAY = 10_000
BRANCH = 'llm-quota-ledger'
PATH = 'data/research/quota-ledger.json'
MAX_BYTES = 900_000
WORKFLOWS = ('v6-llm-autonomous.yml', 'v6-llm-investigator.yml')
MARKERS = ('LLM call', 'Cloudflare Workers AI')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def no_redirect_open(req, timeout):
    """Never replay a request or forward credentials through an HTTP redirect."""
    return build_opener(_NoRedirect()).open(req, timeout=timeout)


def stamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise ValueError('QUOTA_INVALID_TIMESTAMP') from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def append(state, event):
    event = dict(event, previous=state['events'][-1]['sha256'] if state['events'] else '0' * 64)
    event['sha256'] = hashlib.sha256(canonical(event).encode()).hexdigest()
    state['events'].append(event)


def validate(state):
    if not isinstance(state, dict) or state.get('schema_version') != 1 or not isinstance(state.get('events'), list):
        raise ValueError('QUOTA_STATE_INVALID')
    prev, reservations, settlements = '0' * 64, {}, {}
    for raw in state['events']:
        if not isinstance(raw, dict):
            raise ValueError('QUOTA_EVENT_INVALID')
        e = dict(raw)
        digest = e.pop('sha256', None)
        if e.get('previous') != prev or hashlib.sha256(canonical(e).encode()).hexdigest() != digest:
            raise ValueError('QUOTA_CHAIN_INVALID')
        prev = digest
        key, kind = e.get('id'), e.get('kind')
        if not isinstance(key, str) or not key or len(key) > 200:
            raise ValueError('QUOTA_ID_INVALID')
        start = stamp(e.get('at'))
        if kind in ('reserve', 'historical'):
            if key in reservations or e.get('reserved') != MAX_NEURONS_PER_CALL:
                raise ValueError('QUOTA_DUPLICATE_OR_INVALID_RESERVATION')
            reservations[key] = e
            if kind == 'historical':
                end = stamp(e.get('end'))
                if end < start:
                    raise ValueError('QUOTA_HISTORY_TIME_INVALID')
        elif kind == 'settle':
            n = e.get('estimated_neurons')
            if key not in reservations or key in settlements or type(n) is not int or n < 0:
                raise ValueError('QUOTA_SETTLEMENT_INVALID')
            if start < stamp(reservations[key]['at']):
                raise ValueError('QUOTA_CLOCK_REVERSED')
            settlements[key] = e
        else:
            raise ValueError('QUOTA_EVENT_KIND_INVALID')
    return reservations, settlements


def summary(state, now):
    if now.tzinfo is None:
        raise ValueError('QUOTA_UTC_REQUIRED')
    day = now.astimezone(timezone.utc).date()
    reservations, settlements = validate(state)
    used, unresolved = 0, 0
    for key, r in reservations.items():
        start = stamp(r['at']).date()
        if start > day:
            raise ValueError('QUOTA_CLOCK_REVERSED')
        s = settlements.get(key)
        if s and s['estimated_neurons'] > MAX_NEURONS_PER_CALL:
            raise ValueError('QUOTA_MEASUREMENT_EXCEEDS_BOUND')  # permanent latch, requires human audit
        if r['kind'] == 'historical':
            # Legacy calls have no trustworthy meter: charge full reserve on every
            # UTC date the step occupied, plus the next day for ambiguous completion.
            end = (stamp(r['end']) + timedelta(days=1)).date()
            charge = MAX_NEURONS_PER_CALL if start <= day <= end else 0
        elif s:
            end = stamp(s['at']).date()
            charge = s['estimated_neurons'] if start <= day <= end else 0
        else:
            charge = MAX_NEURONS_PER_CALL  # unknown provider completion; never silently expire
            unresolved += 1
        used += charge
    return {'utc_day': day.isoformat(), 'operational_budget_neurons': DAILY_NEURON_BUDGET,
            'charged_estimated_neurons': used, 'remaining_internal_neurons': max(0, DAILY_NEURON_BUDGET - used),
            'unresolved_reservations': unresolved, 'reservation_per_call': MAX_NEURONS_PER_CALL,
            'account_quota_verified': False, 'cloudflare_remaining_neurons': None,
            'free_allocation_neurons': FREE_NEURONS_PER_DAY, 'accounting': 'INTERNAL_ESTIMATE_NOT_PROVIDER_QUOTA'}


class GitHubStore:
    """No retry, no redirects, no fallback to empty state, no writes to main."""
    def __init__(self, repo, token, opener=urlopen, clock=lambda: datetime.now(timezone.utc)):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo or '') or not token:
            raise ValueError('QUOTA_GITHUB_IDENTITY_REQUIRED')
        self.base = 'https://api.github.com/repos/' + repo
        self.token, self.clock = token, clock
        self.opener = no_redirect_open if opener is urlopen else opener

    def api(self, path, data=None):
        body = None if data is None else canonical(data).encode()
        req = Request(self.base + path, data=body, method='GET' if data is None else 'PUT',
                      headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                               'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.opener(req, timeout=20) as resp:
                if resp.status not in (200, 201):
                    raise ValueError('QUOTA_HTTP_FAILURE')
                raw = resp.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError('QUOTA_RESPONSE_TOO_LARGE')
                return json.loads(raw)
        except (HTTPError, OSError) as exc:
            # Never expose token, endpoint credentials or server response body.
            raise ValueError('QUOTA_API_UNAVAILABLE_OR_CAS_CONFLICT') from None

    def read(self):
        obj = self.api('/contents/' + PATH + '?ref=' + BRANCH)
        if obj.get('encoding') != 'base64' or not re.fullmatch('[a-f0-9]{40}', obj.get('sha', '')):
            raise ValueError('QUOTA_STORE_INVALID')
        raw = base64.b64decode(obj['content'])
        if len(raw) > MAX_BYTES:
            raise ValueError('QUOTA_STORE_TOO_LARGE')
        state = json.loads(raw)
        validate(state)
        return state, obj['sha']

    def cas(self, old, new, sha):
        validate(new)
        if new['events'][:len(old['events'])] != old['events'] or len(new['events']) <= len(old['events']):
            raise ValueError('QUOTA_NOT_APPEND_ONLY')
        raw = canonical(new).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError('QUOTA_STORE_FULL')
        result = self.api('/contents/' + PATH, {'branch': BRANCH, 'sha': sha,
                          'message': 'data(quota): append accounting events [skip ci]',
                          'content': base64.b64encode(raw).decode()})
        expected = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if result.get('content', {}).get('sha') != expected:
            raise ValueError('QUOTA_WRITE_UNCONFIRMED')

    def history(self, current_run):
        """All run pages, all attempts. Old-created reruns are NOT filtered out.

        Bounded pagination, fail closed if full history cannot be established. A
        stable second listing guards against a changing list during pagination.
        Only started steps are imported; the current run is never imported here.
        """
        def pages(path, key):
            result, expected = [], None
            for page in range(1, 101):
                obj = self.api(path + ('&' if '?' in path else '?') + 'per_page=100&page=' + str(page))
                total, items = obj.get('total_count'), obj.get(key)
                if type(total) is not int or total < 0 or not isinstance(items, list):
                    raise ValueError('QUOTA_HISTORY_SHAPE')
                if expected is not None and total != expected:
                    raise ValueError('QUOTA_HISTORY_CHANGED')
                expected = total
                result.extend(items)
                if len(result) == total:
                    return result
                if not items or len(result) > total:
                    break
            raise ValueError('QUOTA_HISTORY_INCOMPLETE')
        records, seen, current_seen = [], set(), False
        for wf in WORKFLOWS:
            runs = pages('/actions/workflows/' + wf + '/runs', 'workflow_runs')
            for run in runs:
                rid = run.get('id')
                if type(rid) is not int or rid in seen:
                    raise ValueError('QUOTA_HISTORY_DUPLICATE_RUN')
                seen.add(rid)
                if str(rid) == str(current_run):
                    current_seen = True
                    if run.get('run_attempt') != 1:
                        raise ValueError('QUOTA_RERUN_FORBIDDEN')
                    continue
                # Preserve older attempts in GitHub, import anything that can affect
                # this UTC day (including reruns of runs created months earlier).
                if stamp(run.get('updated_at')) < self.clock().astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1):
                    continue
                jobs = pages('/actions/runs/%s/jobs?filter=all' % rid, 'jobs')
                for job in jobs:
                    if job.get('conclusion') == 'skipped':
                        continue
                    steps = job.get('steps')
                    if not isinstance(steps, list):
                        raise ValueError('QUOTA_HISTORY_STEPS_MISSING')
                    for step in steps:
                        if not isinstance(step, dict) or not isinstance(step.get('name'), str):
                            raise ValueError('QUOTA_HISTORY_STEP_INVALID')
                        if not any(m in step['name'] for m in MARKERS) or step.get('conclusion') == 'skipped':
                            continue
                        if not step.get('started_at') and step.get('status') in ('queued', 'pending', 'waiting'):
                            continue
                        # In-flight OTHER executions cannot be safely reconciled with old writers.
                        if not step.get('completed_at'):
                            raise ValueError('QUOTA_OTHER_EXECUTION_UNRESOLVED')
                        start, end = stamp(step.get('started_at')), stamp(step['completed_at'])
                        jid, num = job.get('id'), step.get('number')
                        if type(jid) is not int or type(num) is not int:
                            raise ValueError('QUOTA_HISTORY_ID_MISSING')
                        records.append({'kind': 'historical', 'id': 'legacy:%s:%s:%s' % (rid, jid, num),
                                        'run_id': str(rid), 'at': start.isoformat(), 'end': end.isoformat(),
                                        'reserved': MAX_NEURONS_PER_CALL, 'workflow': wf})
            check = pages('/actions/workflows/' + wf + '/runs', 'workflow_runs')
            if [(r.get('id'), r.get('run_attempt'), r.get('updated_at')) for r in runs] != [
                    (r.get('id'), r.get('run_attempt'), r.get('updated_at')) for r in check]:
                raise ValueError('QUOTA_HISTORY_CHANGED')
        if not current_seen:
            raise ValueError('QUOTA_CURRENT_RUN_NOT_VISIBLE')
        return records


class Controller:
    def __init__(self, store, clock=lambda: datetime.now(timezone.utc)):
        self.store, self.clock = store, clock
        self.sent = False
        self.http_used = False
        self.key = None

    def reserve(self, run_id, model, estimated_bound):
        if not re.fullmatch(r'[0-9]+', run_id or ''):
            raise ValueError('QUOTA_RUN_ID_REQUIRED')
        if not isinstance(estimated_bound, (int, float)) or isinstance(estimated_bound, bool) or not math.isfinite(estimated_bound) or not 0 < estimated_bound <= MAX_NEURONS_PER_CALL:
            raise ValueError('QUOTA_CALL_BOUND_UNSAFE')
        if self.key is not None:
            raise ValueError('QUOTA_ONE_CALL_PER_EXECUTION')
        old, sha = self.store.read()
        new = copy.deepcopy(old)
        reservations, _ = validate(new)
        key = 'run:' + run_id  # attempt deliberately excluded: reruns cannot call again
        if key in reservations or any(r.get('run_id') == run_id for r in reservations.values()):
            raise ValueError('QUOTA_DUPLICATE_EXECUTION')
        controlled_runs = {r.get('run_id') for r in reservations.values() if r['kind'] == 'reserve'}
        for e in self.store.history(run_id):
            if e['id'] not in reservations and e['run_id'] not in controlled_runs:
                append(new, e)
                reservations[e['id']] = e
        now = self.clock()
        report = summary(new, now)
        if report['remaining_internal_neurons'] < MAX_NEURONS_PER_CALL:
            # Preserve imported evidence even when the request is denied.
            if new != old:
                self.store.cas(old, new, sha)
            raise ValueError('QUOTA_DAILY_BUDGET_EXHAUSTED')
        append(new, {'kind': 'reserve', 'id': key, 'run_id': run_id, 'at': now.isoformat(),
                     'reserved': MAX_NEURONS_PER_CALL, 'model': model, 'estimated_bound': estimated_bound})
        self.store.cas(old, new, sha)  # failure/lost response: absolutely NO provider request
        self.key, self.reserved_at, self.model = key, now, model
        return summary(new, now)

    def send(self, callback):
        now = self.clock()
        if self.key is None or self.sent:
            raise ValueError('QUOTA_RESERVATION_REQUIRED_OR_ALREADY_USED')
        self.sent = True  # consumed even if callback raises or the clock check fails
        age = (now - self.reserved_at).total_seconds()
        if not 0 <= age <= 60 or now.date() != self.reserved_at.date():
            raise ValueError('QUOTA_RESERVATION_STALE')
        return callback()  # exactly once; errors leave the entire durable reservation charged

    def consume_http(self, model, request_bytes):
        if not self.sent or self.key is None or self.http_used:
            raise ValueError('QUOTA_HTTP_ALREADY_USED_OR_UNRESERVED')
        self.http_used = True
        now = self.clock()
        if not 0 <= (now - self.reserved_at).total_seconds() <= 60 or now.date() != self.reserved_at.date():
            raise ValueError('QUOTA_RESERVATION_STALE')
        if model != self.model:
            raise ValueError('QUOTA_MODEL_CHANGED')
        from .research_llm import neuron_bound
        neuron_bound(model, request_bytes)

    def settle(self, estimated_neurons):
        if not self.sent or self.key is None:
            raise ValueError('QUOTA_CALL_NOT_SENT')
        if estimated_neurons is None:
            return  # missing/invalid usage is NOT zero
        if not isinstance(estimated_neurons, (int, float)) or isinstance(estimated_neurons, bool) or not math.isfinite(estimated_neurons) or estimated_neurons < 0:
            raise ValueError('QUOTA_USAGE_INVALID')
        old, sha = self.store.read()
        new = copy.deepcopy(old)
        append(new, {'kind': 'settle', 'id': self.key, 'at': self.clock().isoformat(),
                     'estimated_neurons': math.ceil(estimated_neurons)})
        self.store.cas(old, new, sha)
        return summary(new, self.clock())


def from_environment(env):
    if env.get('GITHUB_REF') != 'refs/heads/main' or env.get('GITHUB_RUN_ATTEMPT') != '1':
        raise ValueError('QUOTA_MAIN_FIRST_ATTEMPT_REQUIRED')
    return Controller(GitHubStore(env.get('GITHUB_REPOSITORY'), env.get('GH_TOKEN')))
