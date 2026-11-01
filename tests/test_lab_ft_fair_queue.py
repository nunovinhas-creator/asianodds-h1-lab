"""P0 queue regression: synthetic fixtures, no network or credentials."""
import unittest
from datetime import datetime, timedelta, timezone

from h1lab.lab_results import reconcile, retry_wait


NOW = datetime(2026, 10, 28, 20, 13, tzinfo=timezone.utc)


def fixture(key):
    return {"match_key": key, "home": "Team Home " + key,
            "away": "Team Away " + key,
            "kickoff_utc": "2026-10-27T13:00:00+00:00"}


def no_result(signal):
    return None, "no_exact_match"


def call(alerts, previous=None, limit=30, **kwargs):
    return reconcile(
        {"alerts": alerts, "signals": []}, [],
        previous or {"schema_version": 1, "matches": {}},
        now=kwargs.pop("now", NOW), max_checks=limit,
        bsd_lookup=kwargs.pop("bsd_lookup", no_result),
        tsdb_lookup=no_result, **kwargs)


class FairQueueTests(unittest.TestCase):
    def test_first_real_visit_precedes_old_visited_without_provider_evidence(self):
        old=fixture('old');new=fixture('new')
        new['kickoff_utc']='2026-10-28T13:00:00+00:00'
        previous={'schema_version':1,'matches':{'old':{
            **old,'status':'PENDING','lookup_source_version':11,
            'queue_visited_at':'2026-10-28T10:00:00+00:00'}}}
        _,report,count=call([old,new],previous,limit=1,evidence_retry=True,
                            lookup_source_version=11)
        self.assertEqual(count,1)
        self.assertEqual(report['ft_queue']['selected_keys'],['new'])
        # An old visit without a complete authenticated source is still
        # unverified, but its repeat must NOT starve a younger first visit.
        self.assertEqual(report['ft_queue']['never_checked_eligible'],2)
        self.assertEqual(report['ft_queue']['never_checked_deferred'],1)
        # It must wait when its independent four-hour visit gate is active.
        previous['matches']['old']['queue_visited_at']='2026-10-28T19:00:00+00:00'
        _,report,count=call([old,new],previous,limit=1,evidence_retry=True,
                            lookup_source_version=11)
        self.assertEqual(report['ft_queue']['selected_keys'],['new'])

        # On the following cycle, the first visit is now covered as a real
        # queue visit, so the older revisit is no longer starved.
        first,_,_=call([old,new],previous,limit=1,evidence_retry=True,
                       lookup_source_version=11)
        second,report,count=call([old,new],first,limit=1,evidence_retry=True,
                                 lookup_source_version=11,now=NOW+timedelta(minutes=1))
        self.assertEqual(count,1)
        self.assertEqual(report['ft_queue']['selected_keys'],['old'])
        self.assertIn('queue_visited_at',second['matches']['old'])
        self.assertNotIn('evidence_checked_at',second['matches']['old'])

    def test_never_queried_is_not_starved_by_30_retries_or_research_hints(self):
        alerts = [fixture(f"old-{i}") for i in range(35)]
        alerts.append(fixture("first-check"))
        previous = {"schema_version": 1, "matches": {}}
        for row in alerts[:-1]:
            previous["matches"][row["match_key"]] = {
                **row, "status": "PENDING", "attempts": 2,
                "checked_at": "2026-10-28T01:00:00+00:00",
                "lookup_source_version": 11}
        called = []
        def probe(s):
            called.append(s["match_key"])
            return no_result(s)
        ledger, report, count = call(
            alerts, previous, bsd_lookup=probe,
            priority_hints={f"old-{i}": 3 for i in range(35)})
        self.assertEqual(count, 30)
        self.assertEqual(called[0], "first-check")
        self.assertEqual(ledger["matches"]["first-check"]["attempts"], 1)
        self.assertEqual(report["ft_queue"]["never_checked_deferred"], 0)
        self.assertEqual(report["ft_queue"]["deferred_by_capacity"], 6)
        self.assertEqual(report["ft_queue"]["selected"], 30)

    def test_high_attempt_backoff_keeps_difficult_match_for_later(self):
        item = fixture("old-hard")
        previous = {"schema_version": 1, "matches": {
            "old-hard": {**item, "status": "PENDING", "attempts": 11,
                         "checked_at": "2026-10-28T17:33:10+00:00",
                         "lookup_source_version": 11}}}
        self.assertEqual(retry_wait(previous["matches"]["old-hard"]),
                         timedelta(hours=24))
        ledger, _, checked = call([item], previous)
        self.assertEqual(checked, 0)
        self.assertEqual(ledger['matches']['old-hard']['attempts'], 11)
        self.assertEqual(ledger['matches']['old-hard']['checked_at'], '2026-10-28T17:33:10+00:00')
        ledger2, _, checked2 = call(
            [item], previous, now=NOW + timedelta(days=1))
        self.assertEqual(checked2, 1)
        self.assertEqual(ledger2["matches"]["old-hard"]["attempts"], 12)

    def test_source_version_never_downgrades_on_uncredentialed_push(self):
        item = fixture("versioned")
        previous = {"schema_version": 1, "matches": {
            "versioned": {**item, "status": "PENDING", "attempts": 1,
                          "checked_at": "2026-10-27T16:00:00+00:00",
                          "lookup_source_version": 11}}}
        ledger, _, count = call([item], previous, lookup_source_version=9)
        self.assertEqual(count, 1)
        row = ledger["matches"]["versioned"]
        self.assertEqual(row["lookup_source_version"], 11)
        self.assertEqual(row["provider_attempts"]["bsd"]["invocations"], 1)
        self.assertEqual(row["provider_attempts"]["bsd"]["last_reason"],
                         "no_exact_match")
        self.assertNotIn("result", row)

    def test_no_early_first_check(self):
        item = fixture("future")
        item["kickoff_utc"] = "2026-10-28T18:00:00+00:00"
        _, report, count = call([item])
        self.assertEqual(count, 0)
        self.assertEqual(report["ft_queue"]["never_checked_eligible"], 0)


if __name__ == "__main__":
    unittest.main()
