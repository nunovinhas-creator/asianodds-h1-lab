"""Regression: GOAL/OpenFoot date lists refused for MORE PAGES must be visible, not anonymous.

Real case (P0 #107, 2026-11-02): both providers returned UNAVAILABLE for every request of the
weekend dates 2026-10-31 and 2026-11-01 (GOAL 6+7 requests, OpenFoot 8+7) and COMPLETE for every
weekday. Each adapter reads one page only (GOAL limit=500, OpenFoot limit=100) and refuses a list
with more pages; the refusal was swallowed as ``*_unavailable``, indistinguishable from a network
failure. The refusal itself is correct and MUST remain; only its cause is now recorded.
No external requests: ``urlopen`` is replaced by an in-memory response.
"""
import io
import json
import unittest
from unittest import mock

from h1lab import lab_goal, lab_openfoot
from h1lab.lab_goal import GoalResults
from h1lab.lab_openfoot import OpenFootResults

SUNDAY = {"match_key": "2026-11-01,97842,23073", "home": "Home FC", "away": "Away FC",
          "kickoff_utc": "2026-11-01T20:30:00+00:00"}


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(body):
    return mock.patch.object(lab_goal, "urlopen", lambda req, timeout: _Resp(json.dumps(body).encode())), \
        mock.patch.object(lab_openfoot, "urlopen", lambda req, timeout: _Resp(json.dumps(body).encode()))


def _openfoot_page(rows, *, cursor=None, total=None, authenticated=True):
    return {"data": rows, "meta": {"pagination": {"next_cursor": cursor},
                                   "total_count": len(rows) if total is None else total,
                                   "access": {"authenticated": authenticated}}}


def _of_row(i):
    return {"id": "match_x%05d" % i, "homeTeam": {"name": "T%d" % i},
            "awayTeam": {"name": "U%d" % i}, "kickoffAt": "2026-11-01T12:00:00Z"}


class OpenFootDayListErrorTests(unittest.TestCase):
    def lookup(self, body):
        provider = OpenFootResults("secret", allowed_days=["2026-11-01"])
        goal_patch, open_patch = _serve(body)
        with goal_patch, open_patch:
            result, why = provider.lookup(SUNDAY)
        return provider, result, why

    def test_weekend_list_with_next_page_stays_refused_and_is_labelled(self):
        # 100 finished rows on the first page and a cursor: the 2026-11-01 production shape.
        provider, result, why = self.lookup(
            _openfoot_page([_of_row(i) for i in range(100)], cursor="c2", total=180))
        self.assertIsNone(result)
        self.assertEqual(why, "openfoot_unavailable")          # fail-closed behaviour unchanged
        self.assertEqual(provider.summary()["date_errors"], {"2026-11-01": "MORE_PAGES"})
        self.assertEqual(provider.summary()["requests"], 1)    # no extra request, no paging

    def test_other_refusals_get_distinct_labels(self):
        cases = {
            "COUNT_MISMATCH": _openfoot_page([_of_row(1)], total=2),
            "UNAUTHENTICATED": _openfoot_page([_of_row(1)], authenticated=False),
            "INVALID_PAYLOAD": _openfoot_page([_of_row(i) for i in range(101)]),
        }
        for label, body in cases.items():
            with self.subTest(label=label):
                provider, result, why = self.lookup(body)
                self.assertIsNone(result)
                self.assertEqual(why, "openfoot_unavailable")
                self.assertEqual(provider.summary()["date_errors"], {"2026-11-01": label})

    def test_transport_failure_is_not_reported_as_pagination(self):
        provider = OpenFootResults("secret", allowed_days=["2026-11-01"])

        def boom(req, timeout):
            raise OSError("reset")
        with mock.patch.object(lab_openfoot, "urlopen", boom):
            self.assertEqual(provider.lookup(SUNDAY), (None, "openfoot_unavailable"))
        self.assertEqual(provider.summary()["date_errors"],
                         {"2026-11-01": "TRANSPORT_HTTP_OR_UNPARSEABLE"})

    def test_complete_weekday_list_records_no_error(self):
        provider, _, why = self.lookup(_openfoot_page([_of_row(1)]))
        self.assertNotEqual(why, "openfoot_unavailable")
        self.assertEqual(provider.summary()["date_errors"], {})


class GoalDayListErrorTests(unittest.TestCase):
    def lookup(self, body):
        provider = GoalResults("secret", allowed_days=["2026-11-01"])
        goal_patch, open_patch = _serve(body)
        with goal_patch, open_patch:
            result, why = provider.lookup(SUNDAY)
        return provider, result, why

    def test_has_more_stays_refused_and_is_labelled(self):
        rows = [{"apiId": str(1000 + i)} for i in range(500)]
        provider, result, why = self.lookup(
            {"success": True, "data": rows, "pagination": {"hasMore": True, "total": 812}})
        self.assertIsNone(result)
        self.assertEqual(why, "goal_unavailable")
        self.assertEqual(provider.summary()["date_errors"], {"2026-11-01": "MORE_PAGES"})
        self.assertEqual(provider.summary()["date_requests"], 1)

    def test_500_rows_without_pagination_is_possible_truncation(self):
        rows = [{"apiId": str(1000 + i)} for i in range(500)]
        provider, _, why = self.lookup({"success": True, "data": rows})
        self.assertEqual(why, "goal_unavailable")
        self.assertEqual(provider.summary()["date_errors"], {"2026-11-01": "MORE_PAGES"})

    def test_count_mismatch_and_envelope(self):
        provider, _, _ = self.lookup({"success": True, "data": [],
                                      "pagination": {"hasMore": False, "total": 3}})
        self.assertEqual(provider.summary()["date_errors"], {"2026-11-01": "COUNT_MISMATCH"})
        provider, _, _ = self.lookup({"success": False})
        self.assertEqual(provider.summary()["date_errors"], {"2026-11-01": "INVALID_PAYLOAD"})

    def test_summary_never_contains_key_or_url(self):
        provider, _, _ = self.lookup({"success": True, "data": [{"apiId": "1"}] * 500})
        text = json.dumps(provider.summary())
        self.assertNotIn("secret", text)
        self.assertNotIn("http", text)


if __name__ == "__main__":
    unittest.main()
