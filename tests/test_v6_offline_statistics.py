"""Synthetic unit tests; real replay is separately labelled in CI."""
import copy
import math
from datetime import datetime,timezone
from unittest import TestCase
from h1lab.v6_offline_statistics import (feature_value,hypothesis_value,make_row,attach_ft,
                                         losses,evaluate,matched_controls,day_sign_test)
from h1lab.timeline import collect_timelines

CODES=['G_FIRST_LEAD_LT_6H','M_1X2_HOME_PROB_UP']


def row(key='game',day='2026-01-01',y=1,p=.5):
    return {'match_key':key,'match_label':key,'kickoff_utc':day+'T18:00:00Z',
            'decision_at':day+'T17:00:00Z','ft_verified_at':day+'T21:00:00Z',
            'features':{'patterns':CODES},'quality_context':{'messages':[{'one_x_two':{'status':'USABLE'}}]},
            'lead_bin':'G_FIRST_LEAD_LT_6H','p':p,'y':y,'ft_status':'VERIFIED_FT',
            'source_event_ids':[],'baseline_quality':'USABLE','lineage':[]}


class OfflineStatisticsTests(TestCase):
    def test_missing_market_is_unknown_not_negative_control(self):
        r=row();r['quality_context']['messages']=[{'one_x_two':None}]
        self.assertIsNone(feature_value(CODES[1],r))
        self.assertIsNone(hypothesis_value(CODES,r))
        r['features']['patterns']=[]
        self.assertIsNone(hypothesis_value(CODES,r))

    def test_suspect_market_is_not_evidence(self):
        r=row();r['quality_context']['messages'][0]['one_x_two']['status']='INCOMPLETE_OR_SUSPECT_QUOTE'
        self.assertIsNone(hypothesis_value(CODES,r))

    def test_brier_and_logloss_are_probabilistic_not_hit_rate(self):
        a=losses([row(y=1,p=.8),row(y=0,p=.2)])
        self.assertAlmostEqual(a['brier'],.04)
        self.assertAlmostEqual(a['log_loss'],-math.log(.8))
        self.assertEqual(losses([row(p=None)])['n'],0)

    def test_only_before_kickoff_messages_define_features(self):
        rows=[{'event_id':'x:1','match_key':'game','observed_at':'2026-01-01T17:00:00Z',
               'kickoff_utc':'2026-01-01T18:00:00Z','markets':{},'trigger_market':'total'},
              {'event_id':'x:2','match_key':'game','observed_at':'2026-01-01T18:01:00Z',
               'kickoff_utc':'2026-01-01T18:00:00Z','markets':{},'trigger_market':'total'}]
        ts,_,_=collect_timelines([],rows)
        r,reason=make_row(ts[0]);self.assertIsNone(reason)
        self.assertEqual(r['source_event_ids'],['x:1'])
        self.assertIn('G_SINGLE_ALERT',r['features']['patterns'])

    def test_no_pre_kickoff_data_returns_reason(self):
        ts,_,_=collect_timelines([],[{'event_id':'x:2','match_key':'game',
            'observed_at':'2026-01-01T18:01:00Z','kickoff_utc':'2026-01-01T18:00:00Z','markets':{}}])
        self.assertEqual(make_row(ts[0])[1],'no_prekickoff_message')

    def test_invalid_ft_time_and_quarantine_never_become_outcomes(self):
        r=row();e={'recorded_at':'2026-01-01T21:00:00Z','source_last_checked_at':'2026-01-01T18:30:00Z',
                    'snapshot':{'status':'FINAL','evidence_level':'SINGLE_PROVIDER',
                                'score':{'home':2,'away':1,'identity_match':'EXACT'}},'sha256':'proof'}
        now=datetime(2026,1,2,tzinfo=timezone.utc)
        attach_ft(r,e,now);self.assertIsNone(r['y'])
        e['source_last_checked_at']='2026-01-01T20:00:00Z'
        attach_ft(r,e,now);self.assertEqual(r['y'],1)
        e['snapshot']['status']='SCORE_CONFLICT'
        attach_ft(r,e,now);self.assertIsNone(r['y'])
        e['snapshot']['status']='FINAL';e['recorded_at']='2026-01-03T21:00:00Z'
        attach_ft(r,e,now);self.assertIsNone(r['y'])

    def test_controls_selected_without_outcome_and_without_replacement(self):
        g=[row('g1'),row('g2')];c=[row('c1',p=.51),row('c2',p=.54)]
        _,one=matched_controls(g,c)
        for r in c:r['y']=1-r['y']
        _,two=matched_controls(g,c)
        self.assertEqual([r['match_key'] for r in one],[r['match_key'] for r in two])
        self.assertEqual(len({r['match_key'] for r in one}),2)

    def test_future_known_training_results_cannot_fit_model(self):
        rs=[row(str(i),day='2026-01-01') for i in range(25)]+[row('test',day='2026-01-02')]
        for r in rs[:25]:r['ft_verified_at']='2026-01-03T00:00:00Z'
        out=evaluate(rs,CODES,'2026-01-04T00:00:00Z')
        self.assertEqual(out['temporal']['train_n'],0)
        self.assertIsNone(out['temporal']['test_model'])

    def test_disjoint_day_holdout_fit_uses_only_earlier_known_ft(self):
        rs=[row(str(i),day='2026-01-01') for i in range(25)]+[row('test',day='2026-01-02')]
        out=evaluate(rs,CODES,'2026-01-04T00:00:00Z')['temporal']
        self.assertEqual(out['train_n'],25)
        self.assertFalse(set(out['training_keys'])&set(out['test_keys']))
        self.assertIsNone(out['paired_day_randomization_p']) # small n cannot claim significance

    def test_days_are_clusters_not_messages(self):
        self.assertIsNone(day_sign_test([row(str(i)) for i in range(100)],.1))
        rs=[row(str(i),day='2026-01-0'+str(i)) for i in range(1,6)]
        self.assertAlmostEqual(day_sign_test(rs,.1),2/32)

    def test_prospective_never_fits_on_its_own_results(self):
        out=evaluate([row()],CODES,'2025-12-31T00:00:00Z',prospective=True,trained_offset=.03)['temporal']
        self.assertEqual(out['offset'],.03);self.assertEqual(out['train_n'],0)

    def test_duplicate_match_cannot_inflate_sample(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_STATISTICAL_MATCH'):
            evaluate([row(),row()],CODES,'2026-01-04T00:00:00Z')
