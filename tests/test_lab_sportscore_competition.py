import copy
import unittest
from datetime import datetime,timezone
from h1lab.lab_sportscore import SportScoreResults
from h1lab.lab_sportscore_competition import anchors

NOW=datetime(2026,10,31,10,tzinfo=timezone.utc)
S={'match_key':'2026-10-30,1,2','home':'AS Roma','away':'AC Milan','kickoff_utc':'2026-10-30T19:00:00+00:00'}
C={'provider':'sportscore','provider_home':'Roma','provider_away':'Milan',
   'provider_kickoff_utc':S['kickoff_utc'],'provider_competition':'Italy Cup',
   'reference_url':'https://sportscore.com/football/match/roma-vs-milan/test123/',
   'observed_competition_at_capture':'Italy Coppa Italia',
   'last_seen_at':'2026-10-30T20:00:00+00:00','match_strength':'STRONG','orientation':'SAME_ORDER'}
E={'home':'Roma','away':'Milan','time':S['kickoff_utc'],'competition':'Italy Cup',
   'url':C['reference_url'],'status':'finished','status_text':'FT','home_score':1,'away_score':0}
COMP={S['match_key']:'Italy Coppa Italia'}

def review():
    return {'games':[{**S,'ft_status':'PENDING','observed_competition':COMP[S['match_key']],
                     'possible_duplicates':[],'candidates':[copy.deepcopy(C)]}]}

def adapter(r=None,rows=None):
    return SportScoreResults(COMP,review=review() if r is None else r,now=NOW,
        getter=lambda e,p:{'matches':[copy.deepcopy(E)] if rows is None else rows},max_requests=1)


class CompetitionCoreTests(unittest.TestCase):
    def test_b_reserves_u21_and_women_categories_cannot_cross(self):
        cases=[('Benfica B','Benfica II',True),
               ('Benfica Reserves','Benfica II',True),
               ('Benfica B','Benfica',False),
               ('Benfica U21','Benfica II',False),
               ('Benfica Women','Benfica Ladies',True),
               ('Benfica Women','Benfica',False),
               ('Benfica U21 Women','Benfica Women',False),
               ('Benfica B','Benfica Women',False)]
        for observed,source,expected in cases:
            with self.subTest(observed=observed,source=source):
                signal=dict(S,home=observed)
                candidate=dict(C,provider_home=source,
                    reference_url='https://sportscore.com/football/match/'+source.lower().replace(' ','-')+'-vs-milan/scoped/')
                row=dict(E,home=source,url=candidate['reference_url'])
                r=review();r['games'][0].update(signal,candidates=[candidate])
                p=SportScoreResults(COMP,review=r,now=NOW,
                    getter=lambda e,q:{'matches':[row]},max_requests=1)
                self.assertEqual(p.lookup(signal)[0] is not None,expected)
                self.assertLessEqual(p.requests,1)

    def test_similarly_named_competitions_do_not_share_captured_identity(self):
        for comp in ('Italy Coppa Italia Women','Italy Coppa Italia U21','Italy Coppa Italia Serie C'):
            changed={S['match_key']:comp}
            self.assertEqual(anchors(review(),changed,NOW),{})
        for comp in ('Italy Cup Women','Italy Super Cup','Italy Cup U21'):
            event=dict(E,competition=comp)
            self.assertIsNone(adapter(rows=[event]).lookup(S)[0])

    def test_weak_stale_or_uncaptured_locator_never_enables_current_ft(self):
        for field,value in [('match_strength','WEAK_REVIEW_ONLY'),
                            ('last_seen_at','2026-09-01T20:00:00Z'),
                            ('observed_competition_at_capture',None),
                            ('orientation','REVERSED_TO_REVIEW')]:
            r=review();r['games'][0]['candidates'][0][field]=value
            self.assertEqual(anchors(r,COMP,NOW),{})
            self.assertIsNone(adapter(r).lookup(S)[0])

    def test_reproduces_old_identity_gap_and_uses_locked_core_without_more_requests(self):
        self.assertEqual(SportScoreResults._plausible(S,[E]),[])
        p=adapter();result,why=p.lookup(S)
        self.assertEqual(why,'verified_sportscore_ft_competition_core')
        self.assertEqual(result['identity_match'],'CORE_NAME')
        self.assertEqual((result['home_goals'],result['away_goals']),(1,0))
        self.assertIsNotNone(p.lookup(S)[0]);self.assertEqual(p.requests,1)

    def test_missing_or_changed_observed_competition_never_builds_an_anchor(self):
        for value in (None,'Other Cup'):
            r=review();r['games'][0]['observed_competition']=value
            self.assertEqual(anchors(r,COMP,NOW),{})
            self.assertIsNone(adapter(r).lookup(S)[0])
        r=review();r['games'][0]['candidates'][0]['observed_competition_at_capture']='Other Cup'
        self.assertEqual(anchors(r,COMP,NOW),{})

    def test_safe_relative_source_url_is_canonicalized_without_changing_source_lock(self):
        event=copy.deepcopy(E);event['url']=event['url'].replace('https://sportscore.com','')
        self.assertIsNotNone(adapter(rows=[event]).lookup(S)[0])

    def test_provider_competition_url_names_time_changes_cannot_reuse_anchor(self):
        for field,value in [('competition','Other Cup'),('url','https://sportscore.com/football/match/other/id/'),
                            ('time','2026-10-30T19:01:00Z'),('away','Milan Women')]:
            event=copy.deepcopy(E);event[field]=value
            self.assertIsNone(adapter(rows=[event]).lookup(S)[0])

    def test_ambiguity_and_side_collision_reject_even_with_locked_source(self):
        other=copy.deepcopy(E);other['url']='https://sportscore.com/football/match/other/id/'
        self.assertIsNone(adapter(rows=[copy.deepcopy(E),other]).lookup(S)[0])
        other['away']='Other Club'
        self.assertIsNone(adapter(rows=[copy.deepcopy(E),other]).lookup(S)[0])

    def test_ft_status_score_and_source_order_gates_remain_unchanged(self):
        for field,value in [('status_text','After Extra Time'),('status_text','finished'),
                            ('status','inprogress'),('home_score',-1)]:
            event=copy.deepcopy(E);event[field]=value
            self.assertIsNone(adapter(rows=[event]).lookup(S)[0])
        r=review();r['games'][0]['candidates'][0]['reference_url']='https://sportscore.com/football/match/milan-vs-roma/id/'
        self.assertEqual(anchors(r,COMP,NOW),{})

    def test_weak_duplicate_quarantined_changed_identity_and_missing_current_response_reject(self):
        for field,value in [('possible_duplicates',[{}]),('ft_status','SCORE_CONFLICT')]:
            r=review();r['games'][0][field]=value
            self.assertEqual(anchors(r,COMP,NOW),{})
        r=review();r['games'][0]['candidates'].append(copy.deepcopy(C))
        self.assertEqual(anchors(r,COMP,NOW),{})
        p=adapter();self.assertIsNone(p.lookup(dict(S,home='Roma Women'))[0])
        self.assertIsNone(adapter(rows=[]).lookup(S)[0])
