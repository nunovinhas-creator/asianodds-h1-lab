import copy
import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from urllib.error import HTTPError
from h1lab.lab_http_cooldown import active,record_429,validate
from scripts.lab_results import PacedTSDB

NOW=datetime(2026,10,31,8,41,tzinfo=timezone.utc)
S={'home':'A','away':'B','kickoff_utc':'2026-10-30T12:00:00+00:00','match_key':'x'}

class DurableHTTP429Tests(unittest.TestCase):
    def test_new_run_skips_without_http_or_renewing_real_attempt(self):
        with patch('h1lab.results.api_events',side_effect=HTTPError('https://provider.invalid',429,'limited',{},None)) as http:
            first=PacedTSDB(interval=0,clock=lambda:NOW)
            self.assertEqual(first.lookup(S)[1],'tsdb_http_429')
            journal=json.loads(json.dumps(first.cooldowns));before=copy.deepcopy(journal)
            for minutes in (1,20,120,239):
                next_run=PacedTSDB(interval=0,cooldowns=journal,clock=lambda:NOW+timedelta(minutes=minutes))
                self.assertEqual(next_run.lookup(S)[1],'tsdb_http_429_cooldown_deferred')
                self.assertEqual(next_run.cooldowns,before);self.assertEqual(next_run.counts['requested'],0)
            self.assertEqual(http.call_count,1)

    def test_deadline_boundary_allows_actual_request_and_only_new_429_extends(self):
        journal=record_429({},'thesportsdb',NOW)
        self.assertFalse(active(journal,'thesportsdb',NOW+timedelta(hours=4)))
        later=NOW+timedelta(hours=4)
        with patch('h1lab.results.api_events',side_effect=HTTPError('https://provider.invalid',429,'limited',{},None)) as http:
            p=PacedTSDB(interval=0,cooldowns=journal,clock=lambda:later)
            self.assertEqual(p.lookup(S)[1],'tsdb_http_429');self.assertEqual(http.call_count,1)
            self.assertEqual(p.cooldowns['thesportsdb']['attempted_at_utc'],later.isoformat(timespec='seconds'))

    def test_retry_after_seconds_date_and_malformed_fallback(self):
        for value,seconds in [('120',120),('Sat, 31 Oct 2026 09:41:00 GMT',3600),('invalid',14400)]:
            r=record_429({},'thesportsdb',NOW,value)['thesportsdb']
            self.assertEqual(datetime.fromisoformat(r['blocked_until_utc']),NOW+timedelta(seconds=seconds))
        self.assertFalse(active(record_429({},'thesportsdb',NOW,'0'),'thesportsdb',NOW))

    def test_fractional_attempt_time_never_rounds_retry_deadline_down(self):
        when=NOW+timedelta(microseconds=500000)
        state=record_429({},'thesportsdb',when,'120')
        self.assertTrue(active(state,'thesportsdb',NOW+timedelta(seconds=120)))
        self.assertFalse(active(state,'thesportsdb',when+timedelta(seconds=120)))

    def test_transport_or_other_http_error_never_creates_429_deadline(self):
        for exc in [OSError('network'),HTTPError('https://provider.invalid',503,'unavailable',{},None)]:
            with patch('h1lab.results.api_events',side_effect=exc):
                p=PacedTSDB(interval=0,clock=lambda:NOW);self.assertIsNone(p.lookup(S)[0])
                self.assertEqual(p.cooldowns,{})

    def test_active_or_corrupt_record_cannot_be_overwritten(self):
        r=record_429({},'thesportsdb',NOW)
        with self.assertRaises(ValueError):record_429(r,'thesportsdb',NOW+timedelta(minutes=5))
        with self.assertRaises(ValueError):validate({'thesportsdb':{'http_status':429}})
        with self.assertRaises(ValueError):active(r,'thesportsdb',NOW-timedelta(days=1))
