import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from h1lab.lab_api_football_id_access import id_batch_policy
from h1lab.lab_api_football import APIFootballResults
from h1lab.lab_ft_index_probe import plan_index_ids, IndexProbe
from test_lab_ft_index_probe import setup, S, NOW
from test_lab_api_football_diagnostics import Response

MESSAGE = 'plan: Free plans do not have access to the Ids parameter.'


def history(message=MESSAGE, category='PROVIDER_ERRORS', status=200, stamp=None):
    return {'schema_version':1, 'runs':[{'utc':stamp or NOW.isoformat(),
        'providers':{'api_football':{'id_errors':{'a':{'category':category,
            'http_status':status,'provider_errors':message}}}}}]}


class IDParameterAccessTests(unittest.TestCase):
    def test_exact_production_denial_limits_plural_parameter_only(self):
        limit, policy = id_batch_policy(history(), NOW)
        self.assertEqual(limit,1)
        self.assertEqual(policy['scope'],'IDS_PARAMETER_ONLY')
        self.assertEqual(policy['singular_id_access'],'NOT_PROVEN')

    def test_date_history_quota_429_and_transport_never_imply_ids_rejection(self):
        for h in (history('Free plans do not have access to this date'),
                  history('Free plan daily quota exhausted'),
                  history(MESSAGE,'HTTP_ERROR',429),history(MESSAGE,'TIMEOUT',None)):
            self.assertEqual(id_batch_policy(h,NOW),(20,None))
        h=history();p=h['runs'][0]['providers']['api_football']
        p['date_errors']=p.pop('id_errors')
        self.assertEqual(id_batch_policy(h,NOW),(20,None))

    def test_carried_proof_preserves_original_timestamp_after_audit_rotation(self):
        _,policy=id_batch_policy(history(),NOW)
        later=NOW+timedelta(days=1)
        h={'runs':[{'utc':later.isoformat(),'providers':{'api_football':{
            'strict_index_probe':{'id_parameter_policy':policy}}}}]}
        self.assertEqual(id_batch_policy(h,later),(1,policy))
        self.assertEqual(id_batch_policy(h,NOW+timedelta(days=46)),(20,None))
        self.assertEqual(id_batch_policy(history(stamp=later.isoformat()),NOW),(20,None))

    def test_real_fetch_boundary_uses_one_singular_request_and_existing_ft_gates(self):
        event,index,matches=setup();limit,_=id_batch_policy(history(),NOW)
        targets=plan_index_ids(list(matches),matches,index,NOW,max_batch=limit)
        urls=[]
        def fetch(request,timeout):
            urls.append(request.full_url)
            self.assertIn('fixtures?id=',request.full_url)
            self.assertNotIn('ids=',request.full_url)
            return Response({'errors':[],'paging':{'total':1},'response':[event]})
        a=APIFootballResults('synthetic',allowed_days=[])
        with patch('h1lab.lab_api_football.urlopen',side_effect=fetch):
            p=IndexProbe(a,targets)
            self.assertIsNotNone(p.lookup(S)[0]);self.assertIsNotNone(p.lookup(S)[0])
        self.assertEqual(len(urls),1);self.assertEqual(a.summary()['requests'],1)

    def test_policy_only_plans_one_of_multiple_strict_targets_without_mutating_index(self):
        from copy import deepcopy
        from h1lab.lab_ft_day_identity import build_index
        event,index,matches=setup();second=deepcopy(event)
        second['fixture']['id']=2000
        second['teams']['home'].update(id=101,name='Other Home')
        second['teams']['away'].update(id=102,name='Other Away')
        signal={**S,'match_key':'other','home':'Other Home','away':'Other Away'}
        matches['other']={**signal,'status':'PENDING'}
        index=build_index({'schema_version':1,'days':{}},{'2026-10-27':[event,second]},NOW)
        before=deepcopy(index)
        self.assertEqual(len(plan_index_ids(list(matches),matches,index,NOW,max_batch=20)),2)
        limit,_=id_batch_policy(history(),NOW)
        self.assertEqual(len(plan_index_ids(list(matches),matches,index,NOW,max_batch=limit)),1)
        self.assertEqual(index,before)
