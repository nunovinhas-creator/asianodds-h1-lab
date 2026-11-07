"""Additional read-only B1 oracle, independent of the report-specific 601 cases.

Run this SAME file with --repo pointing at each historical/corrected checkout.
Only --output under /tmp or the checkout's work/b1-diagnostics is written.
No executor, outcome, network, LLM, memory, publication or operational gate calls.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def var(name): return {'var': name}
def const(value): return {'const': value}
def cmp(name, variable, value): return {'op': name, 'args': [var(variable), const(value)]}
def op(name, *args): return {'op': name, 'args': list(args)}


def signature(sequence):
    nz = [d for d in sequence if d]
    runs = [list(g) for _, g in itertools.groupby(nz)]
    return sequence.count(1), sequence.count(-1), max(0, len(runs)-1), max(map(len, runs), default=0), nz[0] if nz else 0, nz[-1] if nz else 0


def sequence_cases():
    rng, result = random.Random(601), []
    for n in range(1, 5):
        truth = {signature(seq) for seq in itertools.product((-1, 0, 1), repeat=n)}
        result.extend((n, s, True) for s in sorted(truth))
        candidates = list(itertools.product(range(n+1), range(n+1), range(n+1), range(n+1), (-1, 0, 1), (-1, 0, 1)))
        rng.shuffle(candidates)
        result.extend((n, s, False) for s in candidates[:160] if s not in truth)
    return sorted(result, key=lambda x: (not x[2], x[0], x[1]))[:601]


def reconstructed_paths():
    result = []
    def add(f, *terms): result.append({'family': f, 'terms': terms})
    add('F01', cmp('eq', 'lambda_moves_up', 1), cmp('eq', 'lambda_max_run', 0))
    add('F01', cmp('eq', 'lambda_moves_down', 1), cmp('eq', 'lambda_max_run', 0))
    add('F01', cmp('eq', 'lambda_moves_up', 0), cmp('eq', 'lambda_moves_down', 0), cmp('ge', 'lambda_max_run', 1))
    add('F01', cmp('eq', 'lambda_moves_up', 2), cmp('eq', 'lambda_moves_down', 0), cmp('eq', 'lambda_reversals', 1))
    add('F01', cmp('eq', 'lambda_moves_down', 2), cmp('eq', 'lambda_moves_up', 0), cmp('eq', 'lambda_reversals', 1))
    add('F01', cmp('eq', 'total_msgs', 2), cmp('eq', 'lambda_moves_up', 2), cmp('eq', 'lambda_reversals', 1))
    add('F01', cmp('eq', 'lambda_moves_up', 2), cmp('eq', 'lambda_moves_down', 1), cmp('eq', 'lambda_reversals', 0))
    add('F01', cmp('eq', 'lambda_moves_up', 2), cmp('eq', 'lambda_moves_down', 2), cmp('eq', 'lambda_reversals', 1), cmp('eq', 'lambda_max_run', 1))
    add('F01', cmp('eq', 'lambda_reversals', 1), cmp('eq', 'lambda_first_dir', 1), cmp('eq', 'lambda_last_dir', 1), cmp('eq', 'total_msgs', 3))
    add('F01', cmp('eq', 'lambda_reversals', 2), cmp('eq', 'lambda_first_dir', 1), cmp('eq', 'lambda_last_dir', -1), cmp('eq', 'total_msgs', 3))
    for sd in (6, 6.1, 12): add('F02', cmp('gt', 'lambda_sd', sd))
    add('F02', cmp('eq', 'total_msgs', 1), cmp('eq', 'lambda_net', .2), cmp('eq', 'lambda_sd', 0))
    add('F02', cmp('eq', 'total_msgs', 1), cmp('eq', 'lambda_net', .2), cmp('eq', 'lambda_abs_path', .1))
    add('F02', cmp('eq', 'total_msgs', 2), cmp('gt', 'lambda_abs_path', 23.9))
    add('F02', cmp('eq', 'total_msgs', 2), cmp('eq', 'lambda_sd', 0), cmp('ge', 'lambda_abs_path', .1))
    for drift in (1, -1, .0001): add('F03', cmp('eq', 'total_unobserved_changes', 0), cmp('eq', 'lambda_unobserved_net', drift))
    add('F03', cmp('eq', 'total_msgs', 1), cmp('eq', 'lambda_unobserved_net', 1))
    add('F03', cmp('eq', 'total_unobserved_changes', 1), cmp('gt', 'lambda_unobserved_net', 12))
    add('F03', cmp('eq', 'total_msgs', 2), cmp('eq', 'lambda_net', 1), cmp('eq', 'lambda_unobserved_net', 0), cmp('eq', 'lambda_abs_path', .1))
    add('F03', cmp('eq', 'total_msgs', 2), cmp('eq', 'lambda_moves_up', 0), cmp('eq', 'lambda_moves_down', 0), cmp('eq', 'lambda_net', 1), cmp('eq', 'lambda_unobserved_net', 0))
    for n, share in ((2,.3333),(3,.5),(1,.5),(4,.2),(3,.3334),(7,.1234)):
        add('F04', cmp('eq', 'n_messages', n), cmp('eq', 'trigger_total_share', share))
    add('F05', cmp('ge', 'lambda_net', .1), cmp('eq', 'lambda_velocity_h', 0), cmp('le', 'span_min', 60))
    add('F05', cmp('le', 'lambda_net', -.1), cmp('eq', 'lambda_velocity_h', 0), cmp('le', 'span_min', 60))
    add('F05', cmp('ge', 'lambda_net', .1), cmp('le', 'lambda_velocity_h', -.1))
    add('F05', cmp('le', 'lambda_net', -.1), cmp('ge', 'lambda_velocity_h', .1))
    add('F05', cmp('eq', 'n_messages', 1), cmp('ge', 'lambda_velocity_h', .1))
    add('F05', cmp('eq', 'total_msgs', 2), cmp('ge', 'lambda_accel_h', .1))
    add('F06', cmp('eq', 'lead_first_min', 120), cmp('eq', 'lead_last_min', 60), cmp('eq', 'span_min', 1))
    add('F07', cmp('eq', 'lead_first_min', 120.01))
    add('F07', cmp('eq', 'lead_last_min', 60.01))
    add('F06', cmp('eq', 'n_messages', 3), cmp('eq', 'span_min', 60), cmp('eq', 'max_gap_min', 10))
    add('F06', cmp('eq', 'n_messages', 2), cmp('eq', 'span_min', 60), cmp('eq', 'max_gap_min', 30))
    add('F06', cmp('eq', 'n_messages', 1), cmp('gt', 'span_min', 0))
    add('F06', cmp('eq', 'span_min', 10), cmp('eq', 'max_gap_min', 11))
    assert len(result) == 43
    return result


def metadata(producer, math_module, count=200):
    rows = []
    for i in range(count):
        ko = datetime(2026,10,10,12,tzinfo=timezone.utc)+timedelta(days=i%20)
        dec = ko-timedelta(minutes=60)
        net = .2 if i%2 else 0
        def quote(lam):
            share = math_module.fair_over_share(lam,2.5)
            return {'line':2.5,'over_price':1/share,'under_price':1/(1-share)}
        events = [{'event_id':f'probe:{i}:{j}', 'observed_at':(dec-timedelta(minutes=60*(1-j))).isoformat(),
                   'trigger_market':'total','snapshots':{'total':{'before':quote(2.5+j*net/2), 'after':quote(2.5+(j+1)*net/2)}}} for j in range(2)]
        variables=producer.trajectory_variables(events,ko,'League')
        variables['n_episodes']=2
        rows.append({'match_key':f'probe:{i}','kickoff_utc':ko.isoformat(),'decision_at':dec.isoformat(),
                     'variables':variables,'feature_observed_at':dict.fromkeys(variables,dec.isoformat()),
                     'feature_frozen_at':dec.isoformat(),'source_event_ids':[e['event_id'] for e in events],
                     'ft_verified':True,'ft_source_verified':True,'baseline_available':{'p_over_2_5':True},
                     'producer_witness':{'contract':'B1_PRODUCER_1','kickoff_utc':ko.isoformat(),'competition':'League','events':events}})
    return rows


def run(repo):
    import subprocess
    sys.path.insert(0,str(repo))
    from h1lab import research_quality as q, research_dataset as producer, market_math
    from h1lab.research_plan import validate_plan
    def proof(terms):
        # The audited private branch is exercised even if design materiality or
        # other admission rules would prevent reaching it through the outer API.
        if hasattr(q,'prove_path'):
            p=q.prove_path(list(terms)); p.pop('witness',None)
            return p
        impossible,unproven,_=q._path_constraints(list(terms))
        return {'status':'UNSAT' if impossible else 'UNKNOWN' if unproven else 'SAT'}
    paths=[]
    for i,case in enumerate(reconstructed_paths()):
        terms=list(case['terms'])
        result=proof(terms)
        reverse=proof(list(reversed(terms)))
        paths.append(dict(case,id=i+1,result=result,order_invariant=result==reverse))
    sequence=[]
    fields=('lambda_moves_up','lambda_moves_down','lambda_reversals','lambda_max_run','lambda_first_dir','lambda_last_dir')
    for n,s,possible in sequence_cases():
        terms=[cmp('eq','n_messages',n),cmp('eq','total_msgs',n)]+[cmp('eq',k,x) for k,x in zip(fields,s)]
        result=proof(terms)
        sequence.append({'n':n,'signature':s,'oracle_possible':possible,'result':result})
    base=metadata(producer,market_math)
    plan=validate_plan({'question':'Do produced upward movements differ from a neutral control?',
        'hypothesis':'Material lambda movements can be compared before kickoff.',
        'null_hypothesis':'No difference in the target.', 'market':'TOTAL_GOALS','outcome':'OVER_2_5',
        'indicators':[],'condition':cmp('ge','lambda_net',.1),'confounders':['line_bin'],
        'rationale':'Offline structural audit.', 'alternative_explanations':['Prices already reflect the movement.']})
    import copy
    design={'threshold_origin':'APRIORI','frozen_at':'2026-10-01T00:00:00+00:00'}
    mutations=[{},dict(lead_first_min=120,lead_last_min=60,span_min=1),dict(n_messages=3,span_min=60,max_gap_min=10),
               dict(lead_first_min=120.01),dict(lambda_moves_up=1,lambda_max_run=0),dict(lambda_sd=6.1),
               dict(total_unobserved_changes=0,lambda_unobserved_net=1),dict(trigger_total_share=.3333),
               dict(lambda_velocity_h=0),dict(lambda_first=2.5,lambda_last=2.5,lambda_net=.2)]
    supplemental=[]
    for mutation in mutations:
        data=copy.deepcopy(base)
        data[1]['variables'].update(mutation)
        card=q.evaluate_quality(plan,data,design=design)
        metrics=card['metrics']
        supplemental.append({'mutation':mutation,'status':card['design_quality_status'],'reasons':card['reasons'],
            'metrics':{k:metrics.get(k) for k in ('rows','group','control','rows_excluded','group_pregame','control_pregame','group_eligible','control_eligible','oos')}})
    f08=[cmp('ge','lambda_net',.1),cmp('eq','total_msgs',2),cmp('eq','lambda_moves_up',2)]
    control=cmp('eq','lambda_reversals',1)
    return {'kind':'RECONSTRUCTED_NOT_LITERAL_AUDITOR_REPRODUCTION',
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'implementation_sha256':{str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (repo/'h1lab'/'research_quality.py', repo/'h1lab'/'research_contract.py') if p.exists()},
        'original_artifacts':{'52_probes':'UNAVAILABLE','43_scenarios':'UNAVAILABLE','10_supplemental':'UNAVAILABLE','601_exact_inputs':'UNAVAILABLE','553_exact_cases':'UNAVAILABLE'},
        'paths_43':paths,'supplemental_10':supplemental,'sequence_601':sequence,
        'sequence_counts':{'total':len(sequence),'possible':sum(x['oracle_possible'] for x in sequence),
            'impossible_sat':sum(not x['oracle_possible'] and x['result']['status']=='SAT' for x in sequence),
            'possible_unsat':sum(x['oracle_possible'] and x['result']['status']=='UNSAT' for x in sequence),
            'possible_sat':sum(x['oracle_possible'] and x['result']['status']=='SAT' for x in sequence)},
        'F08':{'intersection':proof([*f08,control]),'separation':q._arm_separation(op('and',*f08),control,set()) if hasattr(q,'_arm_separation') else 'METHOD_ABSENT_IN_HISTORICAL_COMMIT'},
        'safety':{'b1_executions':0,'promotions':0,'llm_calls':0}}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    repo,out=args.repo.resolve(),args.output.resolve()
    if not (out.is_relative_to(Path('/tmp')) or out.is_relative_to(repo/'work'/'b1-diagnostics')):
        raise ValueError('DIAGNOSTIC_OUTPUT_REQUIRED')
    result=run(repo)
    encoded=(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with out.open('xb') as f:f.write(encoded)
    print(json.dumps({'output':str(out),'sha256':hashlib.sha256(encoded).hexdigest(),'sequence_counts':result['sequence_counts'],'F08':result['F08']},sort_keys=True))


if __name__=='__main__':main()
