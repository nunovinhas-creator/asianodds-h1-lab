"""Provider timeouts (live run 42054180234: ``TimeoutError: The read operation timed out``).

Fully offline. Fake openers raise simulated transport errors, and a few tests drive the REAL
urllib stack against a deliberately slow HTTP server bound to 127.0.0.1 (no external network,
no provider, no secrets). Proves that
  * the socket timeout handed to the opener is LLM_HTTP_TIMEOUT_S (180 s) and fits the job;
  * timeouts are classified by phase (connect_or_send / awaiting_response / reading_body) and
    distinguished from connection failures;
  * exactly one request is attempted (no retry) and nothing is written to memory;
  * the CLI result and the audit artifact carry the diagnostic, never the token or account id;
  * the HTTP-error diagnostic of PR #236 is unchanged.
"""
import io
import json
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h1lab.research_llm import (DISCOVER_JOB_TIMEOUT_MIN, LLM_HTTP_TIMEOUT_S, MAX_OUTPUT_TOKENS,  # noqa: E402
                                SYSTEM, TRANSPORT_PHASES, ProviderHTTPError, ProviderTransportError,
                                invoke_once)
from test_research_llm_http_error import ACCOUNT, KEY, URL, HTTPErrorOpener, cf_body, packet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL = '@cf/meta/llama-3.3-70b-instruct-fp8-fast'
GOOD = json.dumps({'result': {'response': '{"schema_version":1,"experiments":[],"new_questions":[]}'},
                   'success': True}).encode()


class RaisingOpener:
    """Fake provider: records each request and the timeout it was given, then raises."""

    def __init__(self, exc):
        self.exc, self.calls, self.timeouts = exc, [], []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        self.timeouts.append(timeout)
        raise self.exc


class SlowBody:
    status = 200

    def __init__(self, exc):
        self.exc = exc

    def read(self, n=-1):
        raise self.exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SlowBodyOpener(RaisingOpener):
    def __call__(self, req, timeout=None):
        self.calls.append(req)
        self.timeouts.append(timeout)
        return SlowBody(self.exc)


class FakeClock:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


def call(opener, **kw):
    return invoke_once(packet(), endpoint=URL, model=MODEL, api_key=KEY, opener=opener,
                       endpoint_kind='native', json_mode='json_schema', **kw)


class TimeoutBudget(unittest.TestCase):
    def test_timeout_is_180_seconds_and_reaches_the_opener(self):
        self.assertEqual(LLM_HTTP_TIMEOUT_S, 180)
        opener = RaisingOpener(TimeoutError('The read operation timed out'))
        with self.assertRaises(ProviderTransportError):
            call(opener)
        self.assertEqual(opener.timeouts, [180])

    def test_timeout_covers_worst_case_generation(self):
        # 2400 output tokens must fit at >= 15 tok/s (60 s needed >= 40 tok/s, which failed live).
        self.assertGreaterEqual(LLM_HTTP_TIMEOUT_S * 15, MAX_OUTPUT_TOKENS)

    def test_timeout_fits_the_discover_job(self):
        wf = (ROOT / '.github/workflows/v6-llm-autonomous.yml').read_text()
        job = wf[wf.index('\n  discover:'):wf.index('\n  publish:')]
        minutes = int(re.search(r'timeout-minutes:\s*(\d+)', job).group(1))
        self.assertEqual(minutes, DISCOVER_JOB_TIMEOUT_MIN, 'keep the constant in sync with the workflow')
        # Live run 42054180234: checkout + setup + offline preflight took 121 s before the call.
        # Reserve 240 s for that, plus one timeout per urllib phase that waits on the provider
        # (status line + body) and the artifact upload.
        self.assertLessEqual(240 + 2 * LLM_HTTP_TIMEOUT_S, minutes * 60)

    def test_timeout_cannot_be_raised_or_disabled_by_callers(self):
        for bad in (0, None, True, -1, LLM_HTTP_TIMEOUT_S + 1, 'x'):
            opener = RaisingOpener(AssertionError('must not be called'))
            with self.subTest(timeout=bad), self.assertRaisesRegex(ValueError, 'INVALID_HTTP_TIMEOUT'):
                call(opener, timeout_s=bad)
            self.assertEqual(opener.calls, [])


class PhaseClassification(unittest.TestCase):
    def _diag(self, opener, **kw):
        with self.assertRaises(ProviderTransportError) as ctx:
            call(opener, **kw)
        self.assertEqual(len(opener.calls), 1, 'exactly one request, no retry')
        self.assertIsInstance(ctx.exception, ValueError, 'still caught by the fail-closed handlers')
        self.assertNotIsInstance(ctx.exception, ProviderHTTPError)
        return str(ctx.exception), ctx.exception.diagnostic

    def test_the_live_failure_waiting_for_the_reply(self):
        msg, d = self._diag(RaisingOpener(TimeoutError('The read operation timed out')),
                            clock=FakeClock(1000.0, 1180.4))
        self.assertEqual(msg, 'LLM_PROVIDER_TIMEOUT_AWAITING_RESPONSE')
        self.assertEqual((d['failure'], d['phase'], d['cause_type']), ('timeout', 'awaiting_response', 'TimeoutError'))
        self.assertEqual(d['elapsed_s'], 180.4)
        self.assertEqual(d['timeout_s'], 180)
        self.assertTrue(d['request_may_have_reached_provider'], 'billing must be checked on the dashboard')
        self.assertEqual(d['llm_calls'], 1)
        self.assertEqual(d['message'], 'The read operation timed out')

    def test_socket_timeout_alias(self):
        _, d = self._diag(RaisingOpener(socket.timeout('timed out')))
        self.assertEqual(d['failure'], 'timeout')

    def test_connect_timeout_is_wrapped_by_urllib(self):
        msg, d = self._diag(RaisingOpener(URLError(TimeoutError('timed out'))))
        self.assertEqual(msg, 'LLM_PROVIDER_TIMEOUT_CONNECT_OR_SEND')
        self.assertEqual((d['exception_type'], d['cause_type']), ('URLError', 'TimeoutError'))
        self.assertFalse(d['request_may_have_reached_provider'])

    def test_connection_failures_are_not_timeouts(self):
        for exc in (URLError(ConnectionRefusedError(111, 'Connection refused')),
                    URLError(socket.gaierror(-2, 'Name or service not known'))):
            with self.subTest(exc=exc):
                msg, d = self._diag(RaisingOpener(exc))
                self.assertEqual(msg, 'LLM_PROVIDER_CONNECTION_CONNECT_OR_SEND')
                self.assertEqual(d['failure'], 'connection')
        msg, d = self._diag(RaisingOpener(ConnectionResetError(104, 'Connection reset by peer')))
        self.assertEqual(msg, 'LLM_PROVIDER_CONNECTION_AWAITING_RESPONSE')

    def test_body_read_timeout(self):
        msg, d = self._diag(SlowBodyOpener(TimeoutError('The read operation timed out')))
        self.assertEqual(msg, 'LLM_PROVIDER_TIMEOUT_READING_BODY')
        self.assertTrue(d['request_may_have_reached_provider'])

    def test_phases_are_the_declared_ones(self):
        self.assertEqual(TRANSPORT_PHASES, ('connect_or_send', 'awaiting_response', 'reading_body'))

    def test_secrets_are_redacted_from_the_message(self):
        _, d = self._diag(RaisingOpener(URLError(OSError('fail for %s with %s' % (ACCOUNT, KEY)))))
        blob = json.dumps(d)
        for secret in (KEY, ACCOUNT, 'Bearer'):
            self.assertNotIn(secret, blob)
        self.assertLessEqual(len(d['message']), 200)

    def test_http_errors_keep_the_pr236_diagnostic(self):
        opener = HTTPErrorOpener(400, cf_body({'code': 5006, 'message': 'bad schema'}))
        with self.assertRaises(ProviderHTTPError) as ctx:
            call(opener)
        d = ctx.exception.diagnostic
        self.assertEqual(d['http_status'], 400)
        self.assertEqual(d['provider_errors'][0], {'source': 'errors', 'code': 5006, 'message': 'bad schema'})
        self.assertEqual(len(opener.calls), 1)


class _SlowHandler(BaseHTTPRequestHandler):
    mode = 'slow_headers'

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.server.mode == 'slow_headers':
            time.sleep(2.5)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(GOOD)))
        self.end_headers()
        if self.server.mode == 'slow_body':
            self.wfile.write(GOOD[:10])
            self.wfile.flush()
            time.sleep(2.5)
        try:
            self.wfile.write(GOOD if self.server.mode != 'slow_body' else GOOD[10:])
        except OSError:
            pass


class RealUrllibAgainstLocalSlowServer(unittest.TestCase):
    """The phase mapping is checked against the real urllib/http.client behaviour, on loopback."""

    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _SlowHandler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.local = 'http://127.0.0.1:%d/ai/run/x' % self.server.server_address[1]
        self.calls = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def opener(self, req, timeout=None):
        # Same request, re-targeted at loopback (invoke_once itself only accepts HTTPS).
        self.calls.append(timeout)
        # No proxy: loopback only, whatever the environment says.
        return build_opener(ProxyHandler({})).open(
            Request(self.local, data=req.data, headers=dict(req.header_items()), method='POST'), timeout=timeout)

    def test_slow_reply_times_out_waiting_for_the_status_line(self):
        self.server.mode = 'slow_headers'
        with self.assertRaises(ProviderTransportError) as ctx:
            call(self.opener, timeout_s=1)
        self.assertEqual(str(ctx.exception), 'LLM_PROVIDER_TIMEOUT_AWAITING_RESPONSE')
        self.assertEqual(self.calls, [1])
        self.assertGreaterEqual(ctx.exception.diagnostic['elapsed_s'], 0.9)

    def test_slow_body_times_out_while_reading(self):
        self.server.mode = 'slow_body'
        with self.assertRaises(ProviderTransportError) as ctx:
            call(self.opener, timeout_s=1)
        self.assertEqual(str(ctx.exception), 'LLM_PROVIDER_TIMEOUT_READING_BODY')
        self.assertEqual(self.calls, [1])

    def test_slow_but_within_timeout_succeeds(self):
        self.server.mode = 'slow_headers'
        reply = call(self.opener, timeout_s=10)
        self.assertEqual(reply['llm_calls'], 1)
        self.assertEqual(self.calls, [10])

    def test_refused_connection_is_a_connect_failure(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]   # closed when the block exits -> nothing listens
        self.local = 'http://127.0.0.1:%d/ai/run/x' % port
        with self.assertRaises(ProviderTransportError) as ctx:
            call(self.opener, timeout_s=1)
        self.assertEqual(str(ctx.exception), 'LLM_PROVIDER_CONNECTION_CONNECT_OR_SEND')


class CliRecordsTheTimeout(unittest.TestCase):
    """Real llm-live CLI path, simulated timeout: refusal JSON + audit, no memory, one request."""

    def test_llm_live_timeout_is_logged_without_retry_or_memory_write(self):
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
            opener = RaisingOpener(TimeoutError('The read operation timed out'))
            env = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
                   'GITHUB_EVENT_SCHEDULE': SCHEDULE, 'CLOUDFLARE_ACCOUNT_ID': ACCOUNT,
                   'MASTER_BRAIN_LLM_API_KEY': KEY, 'GITHUB_RUN_ID': '999', 'RESEARCH_PRIOR_LLM_ATTEMPTS': '0'}
            mem, panel, audit = Path(t) / 'scratch.jsonl', Path(t) / 'panel.json', Path(t) / 'audit.json'
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(['--root', str(root), '--mode', 'llm-live', '--allow-network', '--memory', str(mem),
                             '--panel', str(panel), '--budget', '0', '--llm-audit', str(audit)],
                            env=env, opener=opener, quota_factory=__import__('quota_fixtures').factory)
            self.assertEqual(code, 2)
            self.assertEqual(len(opener.calls), 1, 'exactly one request, no retry')
            self.assertEqual(opener.timeouts, [LLM_HTTP_TIMEOUT_S])
            text = out.getvalue()
            result = json.loads(text)
            self.assertEqual(result['status'], 'REFUSED_OR_FAILED')
            self.assertEqual(result['reason'], 'ProviderTransportError: LLM_PROVIDER_TIMEOUT_AWAITING_RESPONSE')
            self.assertEqual(result['llm_calls'], 1)
            self.assertEqual(result['provider_error']['phase'], 'awaiting_response')
            self.assertEqual(json.loads(audit.read_text())['provider_error'], result['provider_error'])
            for blob in (text, audit.read_text()):
                for secret in (KEY, ACCOUNT, SYSTEM[:40], 'Bearer'):
                    self.assertNotIn(secret, blob)
            self.assertFalse(mem.exists() and mem.read_text().strip(), 'no cycle is recorded for a failed call')
            self.assertFalse(panel.exists())


if __name__ == '__main__':
    unittest.main()

