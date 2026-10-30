import copy,json,unittest
from pathlib import Path
from h1lab.lab_ft_recovery_audit import audit_pending,classify_reason

class RecoveryAuditTests(unittest.TestCase):
    def test_real_baseline_has_one_row_per_pending_no_false_irrecoverability(self):
        root=Path(__file__).resolve().parents[1]
        def read(p):return json.loads((root/p).read_text())
        ledger=read('data/lab/ft-ledger.json');before=copy.deepcopy(ledger)
        backlog=read('docs/lab/ft-backlog.json')
        r=audit_pending(ledger,backlog,read('data/state.json')['alerts'],read('data/lab/ft-api-audit.json'))
        self.assertEqual(len(r['games']),backlog['classification']['past_due_unverified'])
        self.assertEqual(sum(r['primary_causes_exclusive'].values()),len(r['games']))
        self.assertEqual(len({g['match_key'] for g in r['games']}),len(r['games']))
        self.assertTrue(all(g['technical_irrecoverability'].startswith('NOT_PROVEN') for g in r['games']))
        self.assertEqual(ledger,before)
        for g in r['games']:
            self.assertTrue(all(p['http_requests_for_this_game'] is None for p in g['provider_evidence']))

    def test_categories_do_not_claim_global_coverage_from_one_source(self):
        self.assertEqual(classify_reason('espn_unsupported_competition'),'PROVIDER_DECLARED_UNSUPPORTED_COMPETITION')
        self.assertEqual(classify_reason('goal_identity_no_core_match'),'IDENTITY_OR_COVERAGE_UNRESOLVED')
        self.assertEqual(classify_reason('tsdb_http_429'),'OPERATIONAL_ERROR')
        self.assertEqual(classify_reason('bsd_date_cooldown_deferred'),'QUOTA_COOLDOWN_OR_DISABLED')

    def test_recovery_requires_same_baseline_keys_and_does_not_count_new_finals(self):
        base={'matches':{'a':{'status':'PENDING'},'f':{'status':'FINAL','result':{'home_goals':1}}}}
        after={'matches':{'a':{'status':'FINAL','result':{}},'f':base['matches']['f'],
                          'new':{'status':'FINAL','result':{}}}}
        backlog={'overdue_games':[],'measured_at':'2026-10-30T12:00:00Z','classification':{}}
        r=audit_pending(after,backlog,[],{'runs':[]},baseline=base,baseline_pending_keys={'a'})
        self.assertEqual(r['baseline_delta']['recovered_preexisting_pending_keys'],['a'])
        self.assertEqual(r['baseline_delta']['recovery_rate'],1)
        self.assertEqual(r['baseline_delta']['final_lost_or_changed_keys'],[])
        after['matches']['f']['status']='PENDING'
        self.assertEqual(audit_pending(after,backlog,[],{'runs':[]},baseline={'matches':{'f':{'status':'FINAL','result':{'home_goals':1}}}})['baseline_delta']['final_lost_or_changed_keys'],['f'])

    def test_shared_http_deduplicated_and_unknown_is_not_zero(self):
        b={'overdue_games':[],'classification':{},'measured_at':'2026-10-30T12:00:00Z'}
        run={'run_id':'7','providers':{'api_football':{'requests':2}}}
        r=audit_pending({'matches':{}},b,[],{'runs':[run,run]})
        self.assertEqual(r['http_accounting_documented_runs']['api_football']['documented_http_requests'],2)
        self.assertNotIn('bsd',r['http_accounting_documented_runs'])
