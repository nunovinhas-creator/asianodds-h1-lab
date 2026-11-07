"""Reconstructed 43/10/601 probes from the received audit descriptions.

Their original Python files were not supplied. The 601-case universe reproduces
both reported 559/553 false SAT counts. The 43/10 scenarios use a separately
produced cohort with complete event certificates. Run the unchanged, recovered
52-probe program separately: scripts/lab_research_b1_original_probes.py.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path


def v(name): return {'var': name}
def c(value): return {'const': value}
def cmp(name, variable, value): return {'op': name, 'args': [v(variable), c(value)]}
def op(name, *args): return {'op': name, 'args': list(args)}
A = cmp('ge', 'lambda_net', .1)


def impossible_paths():
    """The eighteen contradictions explicitly described/proved in the report."""
    return [
        ('sequence_reversal_with_only_up', [cmp('eq','lambda_moves_up',2),cmp('eq','lambda_moves_down',0),cmp('eq','lambda_reversals',1)]),
        ('run_exceeds_available_sign_count', [cmp('eq','total_msgs',2),cmp('eq','lambda_moves_up',1),cmp('eq','lambda_moves_down',1),cmp('eq','lambda_max_run',2)]),
        ('nonzero_movement_with_zero_run', [cmp('eq','lambda_moves_up',1),cmp('eq','lambda_max_run',0)]),
        ('reversal_parity_disagrees_with_endpoints', [cmp('eq','total_msgs',3),cmp('eq','lambda_first_dir',1),cmp('eq','lambda_last_dir',1),cmp('eq','lambda_reversals',1)]),
        ('x12_one_message_reversal', [cmp('eq','x12_msgs',1),cmp('eq','x12_reversals',1)]),
        ('lambda_sd_exceeds_physical_range', [cmp('gt','lambda_sd',6)]),
        ('positive_moves_with_zero_absolute_path', [cmp('eq','lambda_moves_up',1),cmp('eq','lambda_abs_path',0)]),
        ('endpoint_change_exceeds_path_plus_gaps', [cmp('eq','total_msgs',2),cmp('eq','lambda_net',1),cmp('eq','lambda_unobserved_net',0),cmp('eq','lambda_abs_path',.1)]),
        ('unobserved_net_without_unobserved_change', [cmp('eq','total_unobserved_changes',0),cmp('eq','lambda_unobserved_net',1)]),
        ('zero_sd_with_separated_endpoints', [cmp('eq','total_msgs',2),cmp('eq','lambda_first',2),cmp('eq','lambda_last',3),cmp('eq','lambda_sd',0)]),
        ('lead_span_identity', [cmp('eq','lead_first_min',120),cmp('eq','lead_last_min',60),cmp('eq','span_min',10)]),
        ('max_gap_cannot_cover_span', [cmp('eq','n_messages',3),cmp('eq','span_min',60),cmp('eq','max_gap_min',10)]),
        ('trigger_share_not_count_ratio', [cmp('eq','n_messages',2),cmp('eq','trigger_total_share',.3333)]),
        ('market_intersection_pigeonhole', [cmp('eq','n_messages',2),cmp('eq','total_msgs',2),cmp('eq','ah_msgs',2),cmp('eq','total_ah_same_msg',0)]),
        ('velocity_zero_with_material_net', [A,cmp('eq','lambda_velocity_h',0),cmp('le','span_min',60)]),
        ('one_total_no_line_moves_nonzero_net', [cmp('eq','total_msgs',1),cmp('eq','total_line_ups',0),cmp('eq','total_line_downs',0),cmp('eq','total_line_net',.25)]),
        ('one_ah_no_line_moves_nonzero_net', [cmp('eq','ah_msgs',1),cmp('eq','ah_line_moves',0),cmp('eq','ah_line_net',.25)]),
        ('derived_flag_needs_two_total_events', [cmp('eq','total_msgs',1),v('line_up_then_lambda_down')]),
    ]


def signature(seq):
    nz = [x for x in seq if x]
    runs = [list(g) for _, g in itertools.groupby(nz)]
    return seq.count(1), seq.count(-1), max(0,len(runs)-1), max(map(len,runs),default=0)


def sequence_oracle(q):
    result=[]
    for n in range(1,5):
        truth={signature(seq) for seq in itertools.product((-1,0,1),repeat=n)}
        for up in range(n+1):
            for down in range(n+1-up):
                for reversals,run in itertools.product(range(n+1),repeat=2):
                    s=(up,down,reversals,run)
                    terms=[cmp('eq','total_msgs',n)]+[cmp('eq',k,x) for k,x in zip(
                        ('lambda_moves_up','lambda_moves_down','lambda_reversals','lambda_max_run'),s)]
                    rejected,deferred=q._design(op('and',*terms),material=False)
                    status='UNSAT' if 'CONTRADICTORY_SIGNAL_PATH' in rejected else 'UNKNOWN' if deferred else 'SAT'
                    k=up+down; violations=[]
                    if k==0 and (reversals or run):violations.append('EMPTY_NONZERO_SEQUENCE_WITH_RUN_OR_REVERSAL')
                    if k and run==0:violations.append('NONZERO_MOVEMENT_WITH_ZERO_RUN')
                    if reversals and (up==0 or down==0):violations.append('REVERSAL_WITHOUT_BOTH_DIRECTIONS')
                    if k and reversals>=k:violations.append('TOO_MANY_REVERSALS')
                    if run>max(up,down):violations.append('RUN_EXCEEDS_DIRECTION_COUNT')
                    if reversals==0 and up and down:violations.append('BOTH_DIRECTIONS_WITHOUT_REVERSAL')
                    if k>run*(reversals+1):violations.append('INSUFFICIENT_RUN_CAPACITY')
                    if s not in truth and not violations:violations.append('JOINT_RUN_PARTITION_IMPOSSIBLE')
                    result.append({'n':n,'signature':s,'oracle_possible':s in truth,'status':status,
                        'independent_violations':violations,'feasible_with_same_counts':sorted(t[2:] for t in truth if t[:2]==s[:2]),
                        'rejected':sorted(rejected),'deferred':sorted(deferred),
                        **({'evidence':q.prove_path(terms)} if hasattr(q,'prove_path') else {})})
    assert len(result)==601
    return result


def generated_cohort(producer,math_module,*,high_cycles=(0,10,20)):
    anchor=datetime(2026,10,10,12,tzinfo=timezone.utc)
    @lru_cache(maxsize=4)
    def template(positive,line):
        def total(lam):
            p=math_module.fair_over_share(lam,line)
            return {'line':line,'over_price':1/(1.04*p),'under_price':1/(1.04*(1-p))}
        events=[]
        for j in range(2):
            lb,la=2+j*(.1 if positive else 0),2+(j+1)*(.1 if positive else 0)
            pb,pa=.45+j*(.025 if positive else 0),.45+(j+1)*(.025 if positive else 0)
            x12={k:{'before':1/b,'after':1/a} for k,b,a in zip(('1','X','2'),(pb,.25,.75-pb),(pa,.25,.75-pa))}
            ah_before=-.5 if j==0 or not positive else -.75
            ah_after=-.75 if positive else -.5
            events.append({'event_id':'template:'+str(j),'observed_at':(anchor-timedelta(minutes=120-60*j)).isoformat(),
                'trigger_market':'total' if j==0 else '1x2','snapshots':{
                    'total':{'before':total(lb),'after':total(la)},
                    'asian_handicap':{'before':{'line':ah_before,'home_price':2.,'away_price':2.},'after':{'line':ah_after,'home_price':2.,'away_price':2.}},
                    'one_x_two':x12}})
        values=producer.trajectory_variables(events,anchor,'League')
        values['n_episodes']=2  # Both events are sixty minutes apart, beyond episode links.
        return events,values
    result=[]
    for i in range(600):
        ko=anchor+timedelta(days=i%20)
        events,values=template(bool(i%2),4. if i//20 in high_cycles else 2.5)
        events=copy.deepcopy(events)
        for j,e in enumerate(events):
            e.update(event_id=f'report:{i}:{j}',observed_at=(ko-timedelta(minutes=120-60*j)).isoformat())
        dec=events[-1]['observed_at']
        result.append({'match_key':f'REPORT-{i}','kickoff_utc':ko.isoformat(),'decision_at':dec,
            'variables':dict(values),'source_event_ids':[e['event_id'] for e in events],
            'feature_observed_at':dict.fromkeys(values,dec),'feature_frozen_at':dec,
            'ft_verified':True,'ft_source_verified':True,'baseline_available':{'p_over_2_5':True},
            'producer_witness':{'contract':'B1_PRODUCER_1','kickoff_utc':ko.isoformat(),'competition':'League','events':events}})
    return result


def reduce_card(card):
    keys=('design_quality_status','quality_status','reasons','metrics','promotion_eligible','logical_proof')
    return {k:card.get(k) for k in keys if k in card}


def report_cases(q,producer,math_module,validate_plan):
    from h1lab.research_plan import inline
    base=generated_cohort(producer,math_module)
    design={'threshold_origin':'APRIORI','frozen_at':'2026-10-01T00:00:00+00:00'}
    raw={'question':'Can complete produced trajectories support an offline diagnostic?',
         'hypothesis':'Material pregame lambda movements define the signal.',
         'null_hypothesis':'No difference in the target.','market':'TOTAL_GOALS','outcome':'OVER_2_5',
         'indicators':[],'condition':A,'confounders':['line_bin'],'rationale':'Reconstructed audit.',
         'alternative_explanations':['Prices already incorporate the movement.']}
    results=[]
    def record(name,condition=A,*,rows=None,control=None,indicators=None,plan_mutation=None):
        submitted=dict(raw,condition=condition)
        if control is not None:submitted['control_condition']=control
        if indicators is not None:submitted['indicators']=indicators
        plan=validate_plan(submitted)
        if plan_mutation:plan.update(plan_mutation)
        card=q.evaluate_quality(plan,base if rows is None else rows,design=design)
        expr=inline(condition,plan['indicators'])
        r,d=q._design(expr)
        results.append({'name':name,'kind':'RECONSTRUCTED_FROM_REPORT','condition':condition,
            'control':control,'logic_rejected':sorted(r),'logic_deferred':sorted(d),'card':reduce_card(card)})
    for name,terms in impossible_paths():record(name,op('or',A,op('and',A,*terms)))
    terms=impossible_paths()[0][1]
    dead=op('and',A,*terms)
    record('nested_not_reversal',op('not',op('and',op('not',A),op('not',dead))))
    record('derived_reversal_branch',op('or',A,op('and',A,v('X_IMPOSSIBLE_REVERSAL'))),indicators=[{
        'name':'X_IMPOSSIBLE_REVERSAL','description':'Reconstructed impossible reversal','expr':op('and',*terms)}])
    record('historical_overlap_027',control=op('or',cmp('le','lambda_net',.05),op('between',v('lambda_net'),c(.25),c(.30))))
    record('overlap_endpoint_invariant',control=cmp('eq','lambda_last',2.2))
    record('overlap_closed_endpoint',control=cmp('le','lambda_net',.1))
    record('overlap_boolean_nested',control=op('not',op('and',op('not',cmp('ge','lambda_net',.15)),op('not',v('ctx_cup')))))
    record('overlap_approx_grid',cmp('eq','lambda_net',.2),control=cmp('ge','lambda_net',.2))
    record('overlap_discrete_count',control=cmp('eq','total_msgs',2))
    record('open_touch_disjoint',control=cmp('lt','lambda_net',.1))
    record('quantized_gap_disjoint',control=op('between',v('lambda_net'),c(.10001),c(.10009)))
    record('approx_disjoint',control=op('between',v('lambda_net'),c(-.02),c(.02)))
    for name,changes in (
        ('row_lead_not_quantized',{'lead_first_min':120.01}),
        ('row_time_identity_impossible',{'lead_first_min':120,'lead_last_min':60,'span_min':1}),
        ('row_impossible_reversal',{'total_msgs':2,'lambda_moves_up':1,'lambda_moves_down':0,'lambda_reversals':2}),
    ):
        rows=copy.deepcopy(base);rows[1]['variables'].update(changes)
        expr=op('and',A,*[op('is_known',v(k)) for k in changes])
        record(name,expr,rows=rows)
    rows=copy.deepcopy(base);rows[1]['feature_observed_at']['lambda_net']=rows[1]['decision_at'].replace('+00:00','.0000001+00:00')
    record('row_timestamp_submicro',rows=rows)
    rows=copy.deepcopy(base);rows[1]['decision_at']='0001-01-01T00:00:00+01:00'
    record('row_timestamp_extreme',rows=rows)
    rows=copy.deepcopy(base);rows[1]['variables']['lead_last_min']=0
    record('row_lead_after_decision',op('and',A,op('is_known',v('lead_last_min'))),rows=rows)
    for seconds,name in ((3,'row_rounding_tolerance_exact'),(3.000001,'row_rounding_tolerance_beyond')):
        rows=copy.deepcopy(base)
        # A valid producer-grid lead is used, with feature timing as the boundary.
        row=rows[1]
        witness=row['producer_witness']
        for e in witness['events']:
            e['observed_at']=(datetime.fromisoformat(e['observed_at'])-timedelta(seconds=3)).isoformat()
        row.update(decision_at=witness['events'][-1]['observed_at'],feature_frozen_at=witness['events'][-1]['observed_at'])
        row['feature_observed_at']=dict.fromkeys(row['variables'],row['decision_at'])
        row['feature_observed_at']['lead_first_min']=(datetime.fromisoformat(row['kickoff_utc'])-timedelta(minutes=120,seconds=seconds)).isoformat()
        record(name,op('and',A,op('is_known',v('lead_first_min')),op('is_known',v('lead_last_min'))),rows=rows)
    rows=copy.deepcopy(base);rows[1]['extra']=float('nan');record('row_unused_nan',rows=rows)
    rows=generated_cohort(producer,math_module,high_cycles=(0,1,10,20))
    for row in rows:
        if row['variables']['lambda_net']>=.1 and row['variables']['total_line_last']==4:row['ft_source_verified']=False
    record('asymmetric_ft_stratum',rows=rows)
    plan=validate_plan(raw)
    card=q.evaluate_quality(plan,base,design=design,prior_plans=[plan])
    results.append({'name':'identity_prior','kind':'RECONSTRUCTED_FROM_REPORT','card':reduce_card(card)})
    a=q.evaluate_quality(plan,base,design=design);b=q.evaluate_quality(plan,list(reversed(base)),design=design)
    results.append({'name':'metamorphic_row_order','kind':'RECONSTRUCTED_FROM_REPORT','equal_card':a==b,'card':reduce_card(b)})
    record('invalid_plan_fingerprint',plan_mutation={'fingerprint':'forged'})
    shadow=q.shadow_report([dict(raw,unexpected=True)],base,design=design)
    results.append({'name':'invalid_plan_extra','kind':'RECONSTRUCTED_FROM_REPORT','shadow':shadow})
    assert len(results)==43
    supplemental=[]
    for name,mutations in (
        ('whole_signal_arm_impossible_sequences',{'total_msgs':2,'lambda_moves_up':1,'lambda_moves_down':0,'lambda_reversals':2}),
        ('whole_signal_arm_impossible_clock',{'span_min':1}),
    ):
        rows=copy.deepcopy(base)
        for row in rows[1::2]:row['variables'].update(mutations)
        expr=op('and',A,*[op('is_known',v(k)) for k in mutations])
        p=validate_plan(dict(raw,condition=expr))
        supplemental.append({'name':name,'card':reduce_card(q.evaluate_quality(p,rows,design=design))})
    for name,terms in impossible_paths()[:5]:
        r,d=q._design(op('or',A,op('and',A,*terms)),material=False)
        supplemental.append({'name':name+'_control_path','rejected':sorted(r),'deferred':sorted(d)})
    if hasattr(q,'_arm_separation'):
        disjoint=q._arm_separation(op('and',A,cmp('eq','total_msgs',2),cmp('eq','lambda_moves_up',2)),cmp('eq','lambda_reversals',1),{'lambda_net','total_msgs','lambda_moves_up','lambda_reversals'})
    else:disjoint='METHOD_ABSENT_IN_HISTORICAL_COMMIT'
    supplemental.append({'name':'F08_false_intersection','separation':disjoint})
    supplemental.append({'name':'produced_positive_baseline','card':reduce_card(q.evaluate_quality(plan,base,design=design))})
    supplemental.append({'name':'produced_neutral_control','card':reduce_card(q.evaluate_quality(validate_plan(dict(raw,control_condition=op('between',v('lambda_net'),c(-.02),c(.02)))),base,design=design))})
    assert len(supplemental)==10
    return results,supplemental,base,design


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--compare',type=Path,help='Earlier JSON from this same driver; investigate every false SAT')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();repo=args.repo.resolve();out=args.output.resolve()
    if not (out.is_relative_to(repo/'work'/'b1-diagnostics') or out.is_relative_to(Path('/tmp'))):raise ValueError('DIAGNOSTIC_OUTPUT_REQUIRED')
    sys.path.insert(0,str(repo))
    from h1lab import research_quality as q,research_dataset as producer,market_math
    from h1lab.research_plan import validate_plan
    cases43,supplemental,base,design=report_cases(q,producer,market_math,validate_plan)
    oracle=sequence_oracle(q)
    if hasattr(q,'CONTRACT_VERSION'):
        for case in cases43[:20]:
            assert 'CONTRADICTORY_SIGNAL_PATH' in case['card']['reasons'],case['name']
        for case in cases43[29:32]:
            m=case['card']['metrics']
            expected_group=299 if case['name']=='row_lead_not_quantized' else 300
            assert (m['group'],m['control'],m['group_eligible'],m['control_eligible'])==(expected_group,300,299,300),case['name']
            assert m['rows']==600 and m['group']+m['control']+m['unknown']+m['overlap']+m['unassigned']==600
            assert (m['group_pregame'],m['control_pregame'],sum(m['oos'].values()))==(299,300,599),case['name']
        for case in supplemental[:2]:
            m=case['card']['metrics']
            assert (m['group'],m['control'],m['group_pregame'],m['group_eligible'],m['control_eligible'])==(300,300,0,0,300),case['name']
            assert not m['common_support']['pregame'] and not m['common_support']['eligible'] and not m['common_support']['by_period']
        for case in supplemental[-2:]:
            assert case['card']['design_quality_status']=='SCIENTIFICALLY_TESTABLE',case['name']
            assert not case['card']['promotion_eligible']
        assert supplemental[-3]['separation'] is None
        assert cases43[35]['card']['design_quality_status']=='SCIENTIFICALLY_TESTABLE'
        assert cases43[36]['card']['metrics']['group_eligible']==299
        assert cases43[40]['equal_card']
        assert sum(x['oracle_possible'] and x['status']=='SAT' for x in oracle)==42
        assert sum(not x['oracle_possible'] and x['status']=='UNSAT' for x in oracle)==559
    import subprocess
    result={'kind':'RECONSTRUCTED_FROM_RECEIVED_REPORTS_NOT_LITERAL_SCRIPTS',
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'report_scenarios_43':cases43,'supplemental_10':supplemental,
        'generated_metadata_sha256':q.sha(base),'generated_design_sha256':q.sha(design),'sequence_601':oracle,
        'sequence_counts':{key:sum((('possible_' if x['oracle_possible'] else 'impossible_')+x['status'])==key for x in oracle)
            for key in ('possible_SAT','possible_UNSAT','possible_UNKNOWN','impossible_SAT','impossible_UNSAT','impossible_UNKNOWN')}}
    if args.compare:
        prior=json.loads(args.compare.read_text())
        previous={(x['n'],tuple(x['signature'])):x for x in prior['sequence_601']}
        assert set(previous)=={(x['n'],tuple(x['signature'])) for x in oracle}
        investigation=[]
        for current in oracle:
            before=previous[(current['n'],tuple(current['signature']))]
            assert before['oracle_possible']==current['oracle_possible']
            if not before['oracle_possible'] and before['status']=='SAT':
                assert current['independent_violations']
                investigation.append(dict(current,before_status=before['status']))
        result['prior_false_sat_investigation']=investigation
        result['prior_commit']=prior['commit']
        if hasattr(q,'CONTRACT_VERSION'):
            assert all(x['status']=='UNSAT' for x in investigation)
    encoded=(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with out.open('xb') as stream:stream.write(encoded)
    print(json.dumps({'output':str(out),'sha256':hashlib.sha256(encoded).hexdigest(),'sequence_counts':result['sequence_counts'],
                      'report_scenarios_43':len(cases43),'supplemental_10':len(supplemental),
                      'investigated_false_sat':len(result.get('prior_false_sat_investigation',[]))},sort_keys=True))


if __name__=='__main__':main()
