"""Safe API-Football failure diagnostics. Fully offline synthetic HTTP fixtures."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from h1lab.lab_api_football import APIFootballResults, fetch_date, fetch_ids
from h1lab.lab_api_football_errors import APIRequestFailure, scrub_errors

KEY = "secret-synthetic-key"
DAY = "2026-10-27"


class Response:
    status = 200

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, count):
        return self.body[:count]


def blocked(message, status=403):
    raw = json.dumps({"errors": {"plan": message}}).encode()
    return HTTPError("https://provider.invalid/no-credentials", status,
                     "refused", {}, io.BytesIO(raw))


class APIErrorDiagnosticsTests(unittest.TestCase):
    def test_http_rejection_records_code_and_redacts_secret(self):
        msg = "history restricted; api-key=" + KEY + "; details " + ("x" * 400)
        with patch("h1lab.lab_api_football.urlopen", side_effect=blocked(msg)):
            with self.assertRaises(APIRequestFailure) as captured:
                fetch_ids([1612137], KEY)
        d = captured.exception.report()
        self.assertEqual(d["category"], "HTTP_ERROR")
        self.assertEqual(d["http_status"], 403)
        self.assertLessEqual(len(d["provider_errors"]), 200)
        self.assertIn("[redacted]", d["provider_errors"])
        self.assertNotIn(KEY, json.dumps(d))

    def test_http_200_provider_errors_are_not_a_valid_result(self):
        response = {"errors": {"plan": "Not available on this plan"}, "response": []}
        with patch("h1lab.lab_api_football.urlopen", return_value=Response(response)):
            with self.assertRaises(APIRequestFailure) as captured:
                fetch_ids([1612137], KEY)
        d = captured.exception.report()
        self.assertEqual(d["category"], "PROVIDER_ERRORS")
        self.assertEqual(d["http_status"], 200)
        self.assertIn("Not available", d["provider_errors"])

    def test_timeout_is_distinct_from_json_error(self):
        with patch("h1lab.lab_api_football.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(APIRequestFailure) as captured:
                fetch_ids([1612137], KEY)
        self.assertEqual(captured.exception.report()["category"], "TIMEOUT")
        with patch("h1lab.lab_api_football.urlopen", return_value=Response(b"invalid-json")):
            with self.assertRaises(APIRequestFailure) as captured:
                fetch_ids([1612137], KEY)
        self.assertEqual(captured.exception.report()["category"], "INVALID_JSON")

    def test_date_failure_is_available_in_adapter_summary_without_secret(self):
        def fail(_day, _key):
            raise APIRequestFailure("HTTP_ERROR", http_status=403,
                                    errors="api_key=" + KEY + "; historic dates denied", key=KEY)
        a = APIFootballResults(key=KEY, fetch=fail, max_days=1)
        signal = {"match_key": "example", "home": "A", "away": "B",
                  "kickoff_utc": "2026-10-27T18:00:00+00:00"}
        self.assertEqual(a.lookup(signal)[1], "api_football_unavailable")
        self.assertEqual(a.requests, 1)
        info = a.summary()
        self.assertEqual(info["date_errors"][DAY]["http_status"], 403)
        self.assertNotIn(KEY, json.dumps(info))

    def test_id_error_is_one_request_and_persists_code(self):
        def fail(_ids, _key):
            raise APIRequestFailure("HTTP_ERROR", http_status=403,
                                    errors="You do not have access to fixture history")
        approved = {"example": {"provider_fixture_id": 1612137}}
        a = APIFootballResults(key=KEY, max_days=1, reviewed_targets=approved,
                              id_fetch=fail)
        signal = {"match_key": "example"}
        self.assertEqual(a.lookup(signal)[1], "api_football_reviewed_id_unavailable")
        self.assertEqual(a.id_requests, 1)
        self.assertEqual(a.reviewed_outcomes["example"], "api_football_reviewed_id_unavailable")
        self.assertEqual(a.summary()["reviewed_errors"]["example"]["http_status"], 403)
        self.assertEqual(a.summary()["reviewed_errors"]["example"]["category"], "HTTP_ERROR")

    def test_singleton_uses_supported_id_not_plan_specific_ids(self):
        urls = []
        def fake(request, timeout):
            urls.append(request.full_url)
            return Response({"errors": [], "paging": {"total": 1},
                "response": [{"fixture": {"id": 1612137}}]})
        with patch("h1lab.lab_api_football.urlopen", side_effect=fake):
            rows = fetch_ids([1612137], KEY)
        self.assertEqual(list(rows), [1612137])
        self.assertTrue(urls[0].endswith("fixtures?id=1612137"), urls)

    def test_multi_fixture_still_uses_batch_ids_single_request(self):
        urls = []
        def fake(request, timeout):
            urls.append(request.full_url)
            return Response({"errors": [], "paging": {"total": 1},
                "response": [{"fixture": {"id": 1612137}},
                             {"fixture": {"id": 1612139}}]})
        with patch("h1lab.lab_api_football.urlopen", side_effect=fake):
            rows = fetch_ids([1612137, 1612139], KEY)
        self.assertEqual(len(rows), 2)
        self.assertEqual(urls[0].split("?")[1], "ids=1612137-1612139")
        self.assertEqual(len(urls), 1)

    def test_existing_api_success_semantics_are_unchanged(self):
        response = {"errors": [], "paging": {"total": 1},
                    "response": [{"fixture": {"id": 1612137}}]}
        with patch("h1lab.lab_api_football.urlopen", return_value=Response(response)):
            found = fetch_ids([1612137], KEY)
        self.assertEqual(sorted(found), [1612137])

    def test_no_arbitrary_urls_or_bearer_tokens_in_public_error(self):
        msg = "Bearer abcdef1234 URL=https://evil.test/api?token=abcdef api_key=" + KEY
        safe = scrub_errors(msg, KEY)
        self.assertNotIn("abcdef", safe)
        self.assertNotIn(KEY, safe)
        self.assertNotIn("evil.test", safe)


if __name__ == "__main__":
    unittest.main()
