"""Provider HTTP errors (live run 42038573930: ``HTTPError: HTTP Error 400: Bad Request``).

Fully offline: every "provider" here is a fake opener that raises a simulated
``urllib.error.HTTPError``. Proves that
  * the Cloudflare error code/message is captured, bounded and redacted;
  * exactly one request is attempted (no retry) and nothing is written to memory;
  * the CLI result and the audit artifact carry the diagnostic, never the token,
    the account id, the request body or the prompt;
  * the schema sent to the provider is reduced, while the Python validator still
    rejects everything the reduced schema no longer expresses.
"""
import io
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h1lab import research_llm  # noqa: E402
from h1lab.research_llm import (MAX_ERROR_BODY_BYTES, MAX_ERROR_MESSAGE_CHARS, PROVIDER_SCHEMA_KEYWORDS,  # noqa: E402
                                SYSTEM, ProviderHTTPError, invoke_once, parse_response, provider_schema,
                                response_schema)

ACCOUNT = '0123456789abcdef0123456789abcdef'
KEY = 'cfut_FAKE_TOKEN_for_tests_only_zz'
URL = 'https://api.cloudflare.com/client/v4/accounts/%s/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast' % ACCOUNT


class CountingBody(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, n=-1):
        self.read_sizes.append(n)
        return super().read(n)


class HTTPErrorOpener:
    """Fake provider: records the request, then raises the given HTTP error."""

    def __init__(self, status, body, content_type='application/json'):
        self.calls = []
        self.status, self.body, self.content_type = status, body, content_type
        self.fp = None

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        hdrs = Message()
        hdrs['Content-Type'] = self.content_type
        self.fp = CountingBody(self.body)
        raise HTTPError(req.full_url, self.status, 'Bad Request', hdrs, self.fp)


def cf_body(*errors):
    return json.dumps({'result': None, 'success': False, 'errors': list(errors), 'messages': []}).encode()


def packet():
    from test_research_llm_contract import small_packet
    return small_packet()


def call(opener):
    return invoke_once(packet(), endpoint=URL, model='@cf/meta/llama-3.3-70b-instruct-fp8-fast', api_key=KEY,
                       opener=opener, endpoint_kind='native', json_mode='json_schema')


class DiagnosticCapture(unittest.TestCase):
    def test_cloudflare_400_code_and_message_are_recorded_once(self):
        opener = HTTPErrorOpener(400, cf_body({'code': 5006, 'message': "Error: oneOf at '/' not met, 0 matches"}))
        with self.assertRaises(ProviderHTTPError) as ctx:
            call(opener)
        self.assertEqual(len(opener.calls), 1, 'exactly one request, no retry')
        self.assertEqual(str(ctx.exception), 'LLM_PROVIDER_HTTP_400')
        self.assertIsInstance(ctx.exception, ValueError, 'still caught by the existing fail-closed handlers')
        d = ctx.exception.diagnostic
        self.assertEqual(d['http_status'], 400)
        self.assertEqual(d['content_type'], 'application/json')
        self.assertTrue(d['provider_body_json'])
        self.assertIs(d['provider_success'], False)
        self.assertEqual(d['provider_errors'],
                         [{'source': 'errors', 'code': 5006, 'message': "Error: oneOf at '/' not met, 0 matches"}])
        self.assertEqual((d['llm_calls'], d['json_mode'], d['endpoint_kind']), (1, 'json_schema', 'native'))
        self.assertEqual(d['request_bytes'], len(opener.calls[0].data))
        self.assertRegex(d['schema_sha256'], '^[0-9a-f]{64}$')
        self.assertRegex(d['body_sha256'], '^[0-9a-f]{64}$')

    def test_secrets_and_identifiers_are_redacted_and_messages_bounded(self):
        msg = ('Bearer %s for /accounts/%s/ai/run failed; id %s; key=%s; deadbeef%s; \x00\x1b[31m'
               % (KEY, ACCOUNT, ACCOUNT, KEY, 'f' * 40)) + 'x' * 500
        opener = HTTPErrorOpener(400, cf_body({'code': 7003, 'message': msg}, {'code': True, 'message': 'b'},
                                              {'code': 1, 'message': 'c'}, {'code': 2, 'message': 'd'}))
        with self.assertRaises(ProviderHTTPError) as ctx:
            call(opener)
        dump = json.dumps(ctx.exception.diagnostic)
        for secret in (KEY, ACCOUNT, 'f' * 40, '\\u0000', '\\u001b'):
            self.assertNotIn(secret, dump)
        errs = ctx.exception.diagnostic['provider_errors']
        self.assertEqual(len(errs), 3, 'at most three items')
        self.assertEqual(errs[0]['code'], 7003)
        self.assertIsNone(errs[1]['code'], 'only real integers are kept as codes')
        self.assertLessEqual(len(errs[0]['message']), MAX_ERROR_MESSAGE_CHARS)
        self.assertNotIn(SYSTEM[:40], dump)
        self.assertNotIn('Authorization', dump)

    def test_non_json_body_keeps_only_size_and_hash(self):
        opener = HTTPErrorOpener(400, b'<html><body>Bad request ' + KEY.encode() + b'</body></html>', 'text/html')
        with self.assertRaises(ProviderHTTPError) as ctx:
            call(opener)
        d = ctx.exception.diagnostic
        self.assertFalse(d['provider_body_json'])
        self.assertEqual(d['provider_errors'], [])
        self.assertEqual(d['content_type'], 'text/html')
        self.assertNotIn(KEY, json.dumps(d))

    def test_large_body_is_read_with_a_bound(self):
        opener = HTTPErrorOpener(400, b'{' + b' ' * (MAX_ERROR_BODY_BYTES * 4))
        with self.assertRaises(ProviderHTTPError) as ctx:
            call(opener)
        self.assertEqual(opener.fp.read_sizes, [MAX_ERROR_BODY_BYTES + 1])
        self.assertTrue(ctx.exception.diagnostic['body_truncated'])
        self.assertEqual(ctx.exception.diagnostic['body_bytes_read'], MAX_ERROR_BODY_BYTES)

    def test_other_statuses_and_empty_body(self):
        for status in (401, 413, 429, 500):
            opener = HTTPErrorOpener(status, b'')
            with self.subTest(status=status), self.assertRaises(ProviderHTTPError) as ctx:
                call(opener)
            self.assertEqual(ctx.exception.diagnostic['http_status'], status)
            self.assertIsNone(ctx.exception.diagnostic['body_sha256'])
            self.assertEqual(len(opener.calls), 1)


class CliRecordsTheCause(unittest.TestCase):
    """Real llm-live CLI path, simulated HTTP 400: refusal JSON + audit, no memory, one request."""

    def test_llm_live_http_400_is_logged_without_retry_or_memory_write(self):
        from scripts.lab_research_cycle import SCHEDULE, main
        from test_research_gates import copy_sources
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / 'repo'
            copy_sources(root)
            cfg = root / 'config/research-autonomy.json'
            conf = json.loads(cfg.read_text())
            conf['llm_live_enabled'] = True      # temporary copy only; the repository config is untouched
            conf['llm_schedule_live_enabled'] = True  # cron path explicitly re-enabled in fixture
            cfg.write_text(json.dumps(conf))
            opener = HTTPErrorOpener(400, cf_body({'code': 5006, 'message': 'JSON Mode schema not supported'}))
            env = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
                   'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'CLOUDFLARE_ACCOUNT_ID': ACCOUNT,
                   'MASTER_BRAIN_LLM_API_KEY': KEY, 'GITHUB_RUN_ID': '999', 'RESEARCH_PRIOR_LLM_ATTEMPTS': '0'}
            mem, panel, audit = Path(t) / 'scratch.jsonl', Path(t) / 'panel.json', Path(t) / 'audit.json'
            out = io.StringIO()
            from contextlib import redirect_stderr, redirect_stdout
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(['--root', str(root), '--mode', 'llm-live', '--allow-network', '--memory', str(mem),
                             '--panel', str(panel), '--budget', '0', '--llm-audit', str(audit)],
                            env=env, opener=opener, quota_factory=__import__('quota_fixtures').factory)
            self.assertEqual(code, 2)
            self.assertEqual(len(opener.calls), 1, 'exactly one request, no retry')
            text = out.getvalue()
            result = json.loads(text)
            self.assertEqual(result['status'], 'REFUSED_OR_FAILED')
            self.assertEqual(result['reason'], 'ProviderHTTPError: LLM_PROVIDER_HTTP_400')
            self.assertEqual(result['llm_calls'], 1)
            self.assertEqual(result['provider_error']['provider_errors'][0],
                             {'source': 'errors', 'code': 5006, 'message': 'JSON Mode schema not supported'})
            saved = json.loads(audit.read_text())
            self.assertEqual(saved['provider_error'], result['provider_error'])
            for blob in (text, audit.read_text()):
                for secret in (KEY, ACCOUNT, SYSTEM[:40], 'Bearer'):
                    self.assertNotIn(secret, blob)
            self.assertFalse(mem.exists() and mem.read_text().strip(), 'no cycle is recorded for a failed call')
            self.assertFalse(panel.exists())


class ProviderSchemaIsGuidanceOnly(unittest.TestCase):
    def _walk(self, node):
        yield node
        for sub in node.get('properties', {}).values():
            yield from self._walk(sub)
        if isinstance(node.get('items'), dict):
            yield from self._walk(node['items'])

    def test_only_conservative_keywords_and_same_property_tree(self):
        sent, full = provider_schema(), response_schema()
        for node in self._walk(sent):
            self.assertLessEqual(set(node), PROVIDER_SCHEMA_KEYWORDS)
            self.assertNotIsInstance(node.get('type', ''), list)
        names = lambda s: sorted(json.dumps(sorted(n.get('properties', {}))) for n in self._walk(s))  # noqa: E731
        self.assertEqual(names(sent), names(full))
        plan = sent['properties']['experiments']['items']
        self.assertEqual(plan['required'], full['properties']['experiments']['items']['required'])
        self.assertIs(plan['additionalProperties'], False)
        self.assertEqual(plan['properties']['market']['enum'],
                         full['properties']['experiments']['items']['properties']['market']['enum'])

    def test_full_contract_is_unchanged_and_still_strict(self):
        full = json.dumps(response_schema())
        for kw in ('"pattern"', '"uniqueItems"', '"minLength"', '"maxItems"'):
            self.assertIn(kw, full, 'response_schema() still mirrors the complete contract')

    def test_python_still_rejects_what_the_reduced_schema_no_longer_expresses(self):
        from test_research_llm_contract import VALID, reply
        good = json.loads(reply(VALID[0]))['experiments'][0]
        cases = {
            'lowercase indicator name (was: pattern)': dict(good, indicators=[
                dict(good['indicators'][0], name='x_lower')] + good['indicators'][1:]),
            'duplicate confounders (was: uniqueItems)': dict(good, confounders=['lead_bin', 'lead_bin']),
            'question too short (was: minLength)': dict(good, question='curta'),
            'hypothesis too long (was: maxLength)': dict(good, hypothesis='h' * 601),
            'const of wrong type (was: type union)': dict(good, condition={'op': 'gt', 'args': [
                {'var': 'lambda_net'}, {'const': 'texto'}]}),
        }
        for label, plan in cases.items():
            with self.subTest(label):
                out = parse_response(json.dumps({'schema_version': 1, 'experiments': [plan]}))
                self.assertEqual(out['accepted'], 0, label)
                self.assertEqual(len(out['rejected']), 1)
        too_many = parse_response(json.dumps({'schema_version': 1, 'experiments': [good] * 4}), max_plans=3)
        self.assertEqual(too_many['rejected'][-1]['reason'], 'OVER_PLAN_BUDGET')

    def test_request_body_still_matches_documented_workers_ai_shape(self):
        body = json.loads(research_llm.request_body(packet(), 'M', endpoint_kind='native', json_mode='json_schema'))
        self.assertEqual(sorted(body), ['max_tokens', 'messages', 'response_format', 'temperature'])
        self.assertEqual(sorted(body['response_format']), ['json_schema', 'type'])
        self.assertEqual(body['response_format']['type'], 'json_schema')
        self.assertEqual(body['response_format']['json_schema']['type'], 'object')
        self.assertTrue(0 <= body['temperature'] <= 5)
        self.assertIsInstance(body['max_tokens'], int)
        self.assertEqual([m['role'] for m in body['messages']], ['system', 'user'])


if __name__ == '__main__':
    unittest.main()

