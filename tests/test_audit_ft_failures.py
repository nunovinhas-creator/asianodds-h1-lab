"""Issue #107: errors must survive evidence-only retry accounting (no network)."""
import unittest
from datetime import datetime, timezone
from h1lab.lab_results import reconcile

class FailureAuditTests(unittest.TestCase):
    def test_unexpected_provider_failure_is_visible_without_aging_evidence(self):
        game=dict(match_key='2026-10-27,100,200',home='Home FC',away='Away FC',kickoff_utc='2026-10-27T16:00:00+00:00')
        def broken(_): raise RuntimeError('secret must never be persisted')
        ledger, report, _=reconcile({'alerts':[game],'signals':[]},[],{'schema_version':1,'matches':{}},now=datetime(2026,10,29,tzinfo=timezone.utc),bsd_lookup=broken,tsdb_lookup=broken,evidence_retry=True)
        row=ledger['matches'][game['match_key']]
        self.assertEqual(report['execution_health']['status'],'DEGRADED')
        self.assertEqual(report['execution_health']['unexpected_errors'],2)
        self.assertEqual(row['last_provider_visit']['reasons']['bsd'],'provider_unavailable')
        self.assertEqual(row['last_provider_visit']['errors']['bsd'],'RuntimeError')
        self.assertNotIn('secret',str(ledger)+str(report))
        self.assertNotIn('evidence_checked_at',row)
        self.assertEqual(row['attempts'],0)
        self.assertEqual(row['status'],'PENDING')

    def test_no_attempt_is_unknown_not_healthy(self):
        no=lambda _:(None,'no_match')
        _,report,_=reconcile({'alerts':[],'signals':[]},[],{'schema_version':1,'matches':{}},now=datetime(2026,10,29,tzinfo=timezone.utc),bsd_lookup=no,tsdb_lookup=no,max_checks=0)
        self.assertEqual(report['execution_health']['status'],'NOT_ATTEMPTED')

    def test_offline_dual_failure_not_silenced(self):
        game=dict(match_key='2026-10-27,100,200',home='Home FC',away='Away FC',kickoff_utc='2026-10-27T16:00:00+00:00')
        no=lambda _:(None,'no_match')
        def broken(_):raise ValueError('private payload')
        ledger,report,_=reconcile({'alerts':[game],'signals':[]},[],{'schema_version':1,'matches':{}},now=datetime(2026,10,29,tzinfo=timezone.utc),bsd_lookup=no,tsdb_lookup=no,evidence_retry=True,max_checks=0,dual_lookup=broken,dual_postcheck_keys=[game['match_key']])
        self.assertEqual(report['execution_health']['dual_postcheck_errors'],1)
        self.assertEqual(ledger['matches'][game['match_key']]['last_dual_postcheck_error']['type'],'ValueError')
        self.assertNotIn('private',str(ledger))
