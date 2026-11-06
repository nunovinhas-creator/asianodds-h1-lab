"""Offline proof of the quota rehearsal script against an in-memory GitHub REST double.

The double implements exactly the endpoints the rehearsal touches, with real Contents-API
semantics (blob SHA compare-and-swap -> 409), refs create/delete, compare, and 403s when a
permission is missing. No network, no provider, no real reservation.
"""
import base64
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from h1lab import research_quota as rq  # noqa: E402
from scripts import lab_research_quota_trial as trial  # noqa: E402

REPO = 'owner/repo'
SEED = b'{"schema_version":1,"events":[]}'


def blob_sha(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


class Resp:
    def __init__(self, status, obj):
        self.status, self.body = status, (b'' if obj is None else json.dumps(obj).encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body


class FakeGitHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.commits = {'c0': {'parent': None, 'file': SEED, 'message': 'seed'}}
        self.refs = {'main': 'c0', rq.BRANCH: 'c0'}
        self.write, self.actions = True, True
        self.n = 0
        self.runs = {wf: [] for wf in rq.WORKFLOWS}
        self.requests = []

    def fail(self, req, code):
        raise HTTPError(req.full_url, code, 'x', {}, None)

    def __call__(self, req, timeout):
        url = req.full_url
        self.requests.append((req.get_method(), url))
        assert url.startswith('https://api.github.com/repos/' + REPO), url
        path = url[len('https://api.github.com/repos/' + REPO):]
        m = req.get_method()
        body = json.loads(req.data) if req.data else None
        with self.lock:
            if m == 'GET' and path.startswith('/git/ref/heads/'):
                name = path[len('/git/ref/heads/'):]
                if name not in self.refs:
                    self.fail(req, 404)
                return Resp(200, {'object': {'sha': self.refs[name]}})
            if m == 'POST' and path == '/git/refs':
                if not self.write:
                    self.fail(req, 403)
                name = body['ref'][len('refs/heads/'):]
                if name in self.refs:
                    self.fail(req, 422)
                self.refs[name] = body['sha']
                return Resp(201, {})
            if m == 'DELETE' and path.startswith('/git/refs/heads/'):
                if not self.write:
                    self.fail(req, 403)
                name = path[len('/git/refs/heads/'):]
                if name not in self.refs:
                    self.fail(req, 422)
                del self.refs[name]
                return Resp(204, None)
            if path.startswith('/contents/' + rq.PATH):
                if m == 'GET':
                    ref = re.search(r'\?ref=(.+)$', path).group(1)
                    if ref not in self.refs:
                        self.fail(req, 404)
                    raw = self.commits[self.refs[ref]]['file']
                    return Resp(200, {'encoding': 'base64', 'sha': blob_sha(raw),
                                      'content': base64.b64encode(raw).decode()})
                if not self.write:
                    self.fail(req, 403)
                ref = body['branch']
                if ref not in self.refs:
                    self.fail(req, 404)
                if blob_sha(self.commits[self.refs[ref]]['file']) != body['sha']:
                    self.fail(req, 409)
                raw = base64.b64decode(body['content'])
                self.n += 1
                cid = 'c%d' % self.n
                self.commits[cid] = {'parent': self.refs[ref], 'file': raw, 'message': body['message']}
                self.refs[ref] = cid
                return Resp(200, {'content': {'sha': blob_sha(raw)}})
            if path.startswith('/actions/'):
                if not self.actions:
                    self.fail(req, 403)
                mm = re.match(r'/actions/workflows/([^/]+)/runs', path)
                if mm:
                    runs = self.runs[mm.group(1)]
                    return Resp(200, {'total_count': len(runs), 'workflow_runs': runs})
                return Resp(200, {'total_count': 0, 'jobs': []})
            mm = re.match(r'/compare/([^.]+)\.\.\.(.+)$', path)
            if m == 'GET' and mm:
                base, head = mm.group(1), self.refs[mm.group(2)]
                chain = []
                while head != base:
                    chain.append({'sha': head, 'commit': {'message': self.commits[head]['message']}})
                    head = self.commits[head]['parent']
                    assert head is not None
                return Resp(200, {'behind_by': 0, 'commits': list(reversed(chain))})
        raise AssertionError('unexpected endpoint %s %s' % (m, path))


class Rehearsal(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(rq, 'no_redirect_open', self.gh)
        patch.start()
        self.addCleanup(patch.stop)
        # Trial operates on an in-memory GitHub double and must simulate the pre-activation
        # quota-rehearsal state; live_flag() on the real repository intentionally refuses.
        trial_flag = mock.patch.object(trial, 'live_flag', return_value=False)
        trial_flag.start()
        self.addCleanup(trial_flag.stop)
        self.env = {'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 't', 'GITHUB_RUN_ID': '777',
                    'GITHUB_REF': 'refs/pull/1/merge', 'GITHUB_RUN_ATTEMPT': '1'}

    def run_phase(self, phase, **perms):
        self.gh.write = perms.get('write', True)
        self.gh.actions = perms.get('actions', True)
        with mock.patch.dict(os.environ, self.env, clear=True):
            code = trial.main(['--phase', phase, '--evidence-dir', self.tmp.name])
        return code, json.loads((Path(self.tmp.name) / (phase + '.json')).read_text())

    def full(self):
        out = {}
        for phase, perms in (('setup', {}), ('denied', {'write': False, 'actions': False}),
                             ('granted', {}), ('verify', {'write': False, 'actions': False}), ('cleanup', {})):
            code, out[phase] = self.run_phase(phase, **perms)
            self.assertEqual(code, 0, out[phase])
        return out

    def test_full_rehearsal_isolated_and_fail_closed(self):
        out = self.full()
        d, g, v, c = out['denied'], out['granted'], out['verify'], out['cleanup']
        self.assertEqual(d['cas_without_contents_write'], trial.REFUSED)
        self.assertEqual(d['history_without_actions_read'], trial.REFUSED)
        self.assertEqual(d['reserve_without_permissions'], trial.REFUSED)
        self.assertEqual(g['history_real_api'], 'QUOTA_CURRENT_RUN_NOT_VISIBLE')
        self.assertEqual(g['duplicate_run'], 'QUOTA_DUPLICATE_EXECUTION')
        self.assertEqual(g['stale_sha'], trial.REFUSED)
        self.assertEqual(g['invalid_chain'], 'QUOTA_CHAIN_INVALID')
        self.assertEqual(g['missing_branch'], trial.REFUSED)
        self.assertEqual(g['from_environment_off_main'], 'QUOTA_MAIN_FIRST_ATTEMPT_REQUIRED')
        for race in g['concurrency']:
            self.assertEqual(sorted(race['results'].values()), ['ACCEPTED', trial.REFUSED])
            self.assertEqual(race['events_added'], 1)
        # reserve + settle + reserve(02) + 3 race winners
        self.assertEqual(len(g['cas_branch_final']['events']), 6)
        self.assertTrue(v['operational_unchanged'] and v['chain_valid'])
        self.assertEqual(v['events_persisted'], 6)
        # Operational ledger: never written, still the empty seed on the same commit.
        self.assertEqual(self.gh.refs[rq.BRANCH], 'c0')
        self.assertEqual(self.gh.refs['main'], 'c0')
        self.assertFalse([k for k in self.gh.refs if k.startswith('llm-quota-trial/')])
        self.assertTrue(all(s == 204 for s in c['deleted_status'].values()))
        for phase in out.values():
            self.assertEqual(phase['provider_calls'], 0)
            self.assertIs(phase['llm_live_enabled'], False)

    def test_no_write_ever_targets_operational_ledger_or_main(self):
        writes = []
        orig = FakeGitHub.__call__

        def spy(gh, req, timeout):
            if req.get_method() != 'GET':
                body = json.loads(req.data) if req.data else {}
                writes.append((req.full_url, body.get('branch') or body.get('ref')))
            return orig(gh, req, timeout)
        with mock.patch.object(FakeGitHub, '__call__', spy):
            self.full()
        self.assertTrue(writes)
        for url, target in writes:
            target = target or url.rsplit('/heads/', 1)[-1]
            self.assertRegex(target, r'llm-quota-trial/777-(cas|invalid)$', url)

    def test_phase_fails_if_operational_ledger_moves(self):
        self.run_phase('setup')
        self.gh.refs[rq.BRANCH] = 'c-moved'
        self.gh.commits['c-moved'] = {'parent': 'c0', 'file': SEED, 'message': 'x'}
        code, out = self.run_phase('cleanup')
        self.assertEqual(code, 1)
        self.assertIn('OPERATIONAL_LEDGER_CHANGED', out['error'])

    def test_denied_phase_fails_if_write_unexpectedly_allowed(self):
        self.run_phase('setup')
        code, out = self.run_phase('denied', write=True, actions=False)
        self.assertEqual(code, 1)
        self.assertIn('EXPECTED_REFUSAL_NOT_RAISED', out['error'])

    def test_refuses_when_provider_secret_present(self):
        self.env['MASTER_BRAIN_LLM_API_KEY'] = 'x'
        with mock.patch.dict(os.environ, self.env, clear=True), self.assertRaises(AssertionError):
            trial.main(['--phase', 'setup', '--evidence-dir', self.tmp.name])
        self.assertEqual(self.gh.requests, [])

    def test_trial_branch_name_guard(self):
        with self.assertRaisesRegex(ValueError, 'QUOTA_BRANCH_FORBIDDEN'):
            rq.GitHubStore(REPO, 't', branch='main')
        with self.assertRaisesRegex(ValueError, 'QUOTA_BRANCH_FORBIDDEN'):
            rq.GitHubStore(REPO, 't', branch='llm-quota-trial/../main')
        self.assertEqual(rq.GitHubStore(REPO, 't').branch, rq.BRANCH)


class WorkflowContract(unittest.TestCase):
    TEXT = (ROOT / '.github/workflows/llm-quota-trial.yml').read_text(encoding='utf-8')

    def test_no_provider_secrets_and_no_main_writes(self):
        self.assertNotIn('secrets.', self.TEXT)
        self.assertNotRegex(self.TEXT, r'(?i)cloudflare_account|llm_api_key|git push|schedule:')
        self.assertNotIn('v6-llm-global', self.TEXT)

    def test_permissions_per_job(self):
        try:
            import yaml
        except ImportError:  # secret-job preflight has no PyYAML; must PASS there, not skip
            self.assertEqual(self.TEXT.count('actions: read'), 1)
            self.assertEqual(self.TEXT.count('contents: write'), 3)
            return
        wf = yaml.safe_load(self.TEXT)
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        jobs = wf['jobs']
        self.assertEqual(jobs['denied']['permissions'], {'contents': 'read'})
        self.assertEqual(jobs['verify']['permissions'], {'contents': 'read'})
        self.assertEqual(jobs['granted']['permissions'], {'contents': 'write', 'actions': 'read'})
        self.assertEqual(jobs['setup']['permissions'], {'contents': 'write'})
        self.assertEqual(jobs['cleanup']['permissions'], {'contents': 'write'})


if __name__ == '__main__':
    unittest.main()
