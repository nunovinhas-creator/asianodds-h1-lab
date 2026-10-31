import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from h1lab.lab_competition_proof import prepare, review, empty, digest, save


def proposal():
    context={'country_code':'PT','season':'2026-27','division':'2','gender':'MEN','age':'SENIOR','squad':'FIRST'}
    p={'left':dict(context,provider='api_football',competition_id='100'),
       'right':dict(context,provider='bsd',competition_id='200'),'captures':[],'fixture_crosswalk':[]}
    for side,host in [('left','v3.football.api-sports.io'),('right','sports.bzzoiro.com')]:
        fs=[{'fixture_id':side+str(i),'home_team_id':side+'H'+str(i),'away_team_id':side+'A'+str(i),
             'kickoff_utc':'2026-10-28T15:00:00Z'} for i in range(2)]
        document={'identity':p[side],'fixtures':fs}
        p['captures'].append({'url':'https://'+host+'/identity/evidence', 'captured_at':'2026-10-30T00:00:00Z',
                              'document':document,'document_sha256':digest(document)})
    for i in range(2):
        doc={'left_team_ids':['leftH'+str(i),'leftA'+str(i)],'right_team_ids':['rightH'+str(i),'rightA'+str(i)]}
        p['fixture_crosswalk'].append({'left_fixture_id':'left'+str(i),'right_fixture_id':'right'+str(i),
            'team_identity_evidence':{'kind':'OFFICIAL_TEAM_ID_CROSSWALK','document':doc,'sha256':digest(doc),
                                     'source_url':'https://sports.bzzoiro.com/official-crosswalk'}})
    return p


def decision(p):
    return {'decision':'APPROVE','reviewer':'synthetic offline reviewer','rationale':'test verified captures',
            'reviewed_at':'2026-10-31T10:00:00Z','evidence_sha256':p['evidence_sha256']}


class CompetitionProofTests(unittest.TestCase):
    def test_prepare_never_auto_approves_and_explicit_review_still_never_activates(self):
        p=prepare(proposal());self.assertEqual(p['state'],'PROPOSED')
        old=empty();r=review(old,p,decision(p),expected_revision=0)
        self.assertEqual(old,empty());self.assertEqual(r['revision'],1)
        self.assertEqual(r['bindings'][p['binding_id']]['state'],'REVIEWED_OFFLINE_NOT_ACTIVATED')

    def test_equal_names_or_scores_or_ids_without_documents_never_prove_identity(self):
        p=proposal();p['captures']=[];p['name']='Premier League';p['score']='2-1'
        with self.assertRaises(ValueError):prepare(p)
        p=proposal();p['fixture_crosswalk'][0]['team_identity_evidence']={'verified':True}
        with self.assertRaises(ValueError):prepare(p)

    def test_country_tier_season_gender_age_and_reserve_mismatches_reject(self):
        for field,value in [('country_code','ES'),('division','1'),('season','2025-26'),
                            ('gender','WOMEN'),('age','U21'),('squad','B')]:
            with self.subTest(field=field):
                p=proposal();p['right'][field]=value
                with self.assertRaises(ValueError):prepare(p)
        for field in ('country_code','season','division','gender','age','squad','competition_id'):
            p=proposal();del p['left'][field]
            with self.assertRaises(ValueError):prepare(p)

    def test_same_provider_copies_unofficial_urls_credentials_and_corrupt_documents_reject(self):
        p=proposal();p['right']['provider']='api_football'
        with self.assertRaises(ValueError):prepare(p)
        for url in ('https://example.invalid/evidence','https://user:password@v3.football.api-sports.io/e',
                    'https://v3.football.api-sports.io/e?key=hidden','http://v3.football.api-sports.io/e'):
            p=proposal();p['captures'][0]['url']=url
            with self.assertRaises(ValueError):prepare(p)
        p=proposal();p['captures'][0]['document']['fixtures'][0]['home_team_id']='tampered'
        with self.assertRaises(ValueError):prepare(p)

    def test_duplicate_witness_and_changed_home_away_or_kickoff_reject(self):
        p=proposal();p['fixture_crosswalk'][1]=copy.deepcopy(p['fixture_crosswalk'][0])
        with self.assertRaises(ValueError):prepare(p)
        for field,value in [('kickoff_utc','2026-10-28T16:00:00Z'),('home_team_id','wrong')]:
            p=proposal();p['captures'][1]['document']['fixtures'][0][field]=value
            p['captures'][1]['document_sha256']=digest(p['captures'][1]['document'])
            with self.assertRaises(ValueError):prepare(p)

    def test_stale_decision_conflicting_mapping_and_immutable_binding_reject(self):
        p=prepare(proposal());r=review(empty(),p,decision(p),expected_revision=0)
        with self.assertRaises(ValueError):review(r,p,decision(p),expected_revision=0)
        with self.assertRaises(ValueError):review(r,p,decision(p),expected_revision=1)
        d=decision(p);d['evidence_sha256']='0'*64
        with self.assertRaises(ValueError):review(empty(),p,d,expected_revision=0)
        q=proposal();q['right']['competition_id']='another'
        for capture,side in zip(q['captures'],('left','right')):
            capture['document']['identity']=q[side];capture['document_sha256']=digest(capture['document'])
        q=prepare(q)
        with self.assertRaises(ValueError):review(r,q,decision(q),expected_revision=1)

    def test_durable_registry_requires_file_cas_and_roundtrips_evidence(self):
        p=prepare(proposal());r=review(empty(),p,decision(p),expected_revision=0)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'registry.json';save(path,r,expected_file_sha256=None)
            original=path.read_bytes();self.assertEqual(json.loads(original),r)
            with self.assertRaises(ValueError):save(path,empty(),expected_file_sha256=None)
            self.assertEqual(path.read_bytes(),original)
            save(path,r,expected_file_sha256=hashlib.sha256(original).hexdigest())
            self.assertEqual(path.read_bytes(),original)
