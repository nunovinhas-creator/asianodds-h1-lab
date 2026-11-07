from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
import json, hashlib, tempfile
from h1lab.research_quality import _design,_logic_paths,shadow_report,evaluate_quality,raw_plan,sha
from h1lab.research_dsl import evaluate
from test_research_quality_blockers import BlockerTests, A, var, const, op, cmp

f=BlockerTests(); f.setUp()
def result(name, data):
    print(name,json.dumps(data,sort_keys=True))
def report(p=None,m=None,**kw):
    return shadow_report([raw_plan(p or f.plan)],f.meta if m is None else m,design=f.design,**kw)
def card(p=None,m=None,**kw):
    return report(p,m,**kw)['agenda'][0]
def brief(q):
    m=q['metrics']
    return [q['design_quality_status'],q['reasons'],{k:m.get(k) for k in ('rows','group','control','unknown','rows_excluded','group_eligible','control_eligible','split_day','oos')}]

neg=lambda x:op('not',x)
both=lambda *xs:op('and',*xs)
either=lambda *xs:op('or',*xs)
cases={
 'positive_net_same_endpoints': both(cmp('eq','lambda_first',2),cmp('eq','lambda_last',2)),
 'zero_messages': cmp('eq','n_messages',0),
 'total_exceeds_all': both(cmp('eq','n_messages',1),cmp('ge','total_msgs',2)),
 'up_exceeds_total': both(cmp('eq','total_msgs',1),cmp('ge','lambda_moves_up',2)),
 'no_up_positive_first_dir': both(cmp('eq','lambda_moves_up',0),cmp('eq','lambda_first_dir',1)),
 'both_competitions_no_stratum':both(var('ctx_cup'),var('ctx_league_other')),
 'impossible_rounded_move':both(cmp('gt','lambda_net',.10001),cmp('lt','lambda_net',.10002)),
 'unobservable_branch':neg(op('is_known',var('lambda_first'))),
 'reversed_exact_bound':op('le',const(.1),var('lambda_net')),
 'tiny_eq_known':both(cmp('eq','lambda_first',0),cmp('le','lambda_first',5e-10)),
 'discrete_hole':both(cmp('gt','lambda_first_dir',0),cmp('ne','lambda_first_dir',1)),
 'opaque_known':op('is_known',op('div',var('lambda_first'),const(0))),
 'double_negation':neg(neg(cmp('le','lambda_net',.8))),
 'nested_redundant_false':neg(either(const(False),neg(A))),
}
for name, x in cases.items():
    expr=either(A,both(A,x)) if name not in ('reversed_exact_bound','double_negation','nested_redundant_false','tiny_eq_known') else both(A,x)
    out=[]
    for e in (expr,dict(expr,args=list(reversed(expr['args'])))):
        r,d=_design(e); q=card(f.plan_with(e,confounders=['line_bin']))
        out.append([sorted(r),sorted(d),q['design_quality_status'],q['reasons']])
    assert out[0]==out[1], (name,out)
    result(name,out[0])
for n in (6,7):
    expr=both(A,*[either(A,A) for _ in range(n)])
    try: paths=len(_logic_paths(expr))
    except ValueError as e: paths=str(e)
    result('paths_'+str(n),[paths,[sorted(x) for x in _design(expr)]])
result('baseline',brief(card()))
for v,value in [('lead_last_min',0),('kickoff_hour_utc',23),('total_msgs',0),('n_messages',0)]:
    p=f.plan_with(both(A,cmp('ge',v,0)),confounders=['line_bin'])
    m=deepcopy(f.meta)
    for r in m:
        r['variables'][v]=value
        r['feature_observed_at'][v]=r['decision_at']
    result('eligible_'+v,brief(card(p,m)))
p=f.plan_with(both(A,cmp('ge','lead_first_min',0)),confounders=['line_bin'])
for delta in (2.99,3,3.01):
    m=deepcopy(f.meta); r=m[1]
    r['variables']['lead_first_min']=(datetime.fromisoformat(r['kickoff_utc'])-datetime.fromisoformat(r['decision_at'])).total_seconds()/60-delta/60
    result('lead_round_'+str(delta),brief(card(p,m)))
for field,value in [('decision_at','2026-11-01T01:00:00'),('feature_frozen_at','0001-01-01T00:00:00+23:59'),('feature_observed_at',[])]:
    m=deepcopy(f.meta); m[1][field]=value
    result('timestamp_'+field,brief(card(m=m)))
for j,value in enumerate((float('nan'),float('inf'),-float('inf'),True,'0.2',None,{})):
    m=deepcopy(f.meta);m[j]['variables']['lambda_net']=value
    rr=report(m=m);result('invalid_'+repr(value),[rr['input_sha256'],brief(rr['agenda'][0])])
m=deepcopy(f.meta); m[0]['variables']['unused']=float('nan')
result('direct_unserializable',brief(evaluate_quality(f.plan,m,design=f.design)))
result('shadow_unserializable',brief(card(m=m)))
rr1=report();rr2=report(prior_plans=[f.plan]);rr3=report(m=list(reversed(f.meta)))
assert rr1==report()
assert rr1['agenda']==rr3['agenda']
result('hash_prior_order',[rr1['input_sha256'],rr2['input_sha256'],rr3['input_sha256'],rr1['agenda'][0]['design_quality_status'],rr2['agenda'][0]['design_quality_status']])
m=deepcopy(f.meta)
for r in m[1::2]:
    r['ft_source_verified']=False
result('asymmetric_ft',[brief(card(m=m)),card(m=m)['metrics']['common_support']])
p=f.plan_with(A,confounders=['line_bin','competition_type','lead_bin'])
m=deepcopy(f.meta)
for r in m[1::2]: r['variables']['total_line_last']=4
result('new_strata',[brief(card(p,m)),card(p,m)['metrics']['common_support']])
m=deepcopy(f.meta);r=m[1];r['feature_observed_at']['lambda_net']=r['decision_at'].replace('+00:00','.0000001+00:00')
result('submicrosecond',brief(card(m=m)))
p=deepcopy(f.plan); p['fingerprint']='forged'
result('fingerprint',[evaluate_quality(p,f.meta,design=f.design)['design_quality_status'],shadow_report([p],f.meta,design=f.design)['agenda'][0]['design_quality_status']])
# Explicit arms overlap in (.2,.3); the sample contains only 0 and .2.
p=f.plan_with(A,control_condition=cmp('le','lambda_net',.05),confounders=['line_bin'])
result('neutral_explicit',brief(card(p)))
p=f.plan_with(A,control_condition=either(cmp('le','lambda_net',.05),
                  both(cmp('gt','lambda_net',.25),cmp('lt','lambda_net',.3))),confounders=['line_bin'])
result('latent_overlap',[evaluate(p['condition'],{'lambda_net':.27}),evaluate(p['control_condition'],{'lambda_net':.27}),brief(card(p))])
# Both FT arms continue to have eligible and period support despite attrition.
m=deepcopy(f.meta)
for r in m[1::4]: r['ft_source_verified']=False
q=card(m=m)
result('asymmetric_ft_support_preserved',[brief(q),q['metrics']['common_support'],q['metrics']['attrition']])
# Exact 0.1 is a witness; the additional threshold only restricts direction.
p=f.plan_with(both(A,cmp('ge','lambda_abs_path',0)),confounders=['line_bin'])
m=deepcopy(f.meta)
for r in m:
    r['variables']['lambda_abs_path']=abs(r['variables']['lambda_net'])
    r['feature_observed_at']['lambda_abs_path']=r['decision_at']
result('redundant_nonnegative_motion',[brief(card(p,m)),evaluate(p['condition'],{'lambda_net':.2,'lambda_abs_path':.2})])
for ix in (0,299,599):
    m=deepcopy(f.meta);m[ix]=[]
    q=card(m=m)
    assert q['metrics']['rows']==600 and q['metrics']['unknown']==1 and q['metrics']['rows_excluded']==1
    assert q['metrics']['exclusions'][0]['row_index']==ix
    result('malformed_row_'+str(ix),brief(q))
m=deepcopy(f.meta);m[1]['variables']['total_line_last']=-.25
q=card(m=m);assert q['metrics']['group']==300 and q['metrics']['group_eligible']==299
result('negative_stratum',brief(q))
raw=raw_plan(f.plan)
raw['indicators']=[
 {'name':'X_DEN','description':'Denominator from early inferred goals','expr':var('lambda_first')},
 {'name':'X_RATIO','description':'Diagnostic division by inferred goals','expr':op('div',const(1),var('X_DEN'))}
]
raw['condition']=both(A,op('is_known',var('X_RATIO')))
from h1lab.research_plan import validate_plan
p=validate_plan(raw)
m=deepcopy(f.meta);m[1]['variables']['lambda_first']=0
q=card(p,m);assert q['metrics']['unknown']==1 and q['metrics']['control']==300
result('zero_divisor_indirect',[brief(q),q['metrics']['exclusions']])
m=deepcopy(f.meta);r=m[1]
r['feature_observed_at']['lambda_first']=(datetime.fromisoformat(r['decision_at'])+timedelta(seconds=1)).isoformat()
q=card(p,m);assert q['metrics']['group']==300 and q['metrics']['group_eligible']==299
result('late_indicator_dependency',[brief(q),q['metrics']['exclusions']])
p=f.plan_with(A,control_condition=either(cmp('le','lambda_net',.05),
    both(cmp('le','lambda_net',.05),cmp('eq','n_messages',1),cmp('ge','total_msgs',2))),
    confounders=['line_bin'])
# Avoid incidental activation of the impossible term in the synthetic fixture.
m=deepcopy(f.meta)
for r in m:
    r['variables']['n_messages']=max(r['variables']['total_msgs'],1)
q=card(p,m)
result('impossible_explicit_control_branch',brief(q))
