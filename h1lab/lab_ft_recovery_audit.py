"""Read-only FT evidence audit. Absence of telemetry never proves no HTTP."""
from collections import Counter,defaultdict
from .lab_results import utc
from .lab_ft_crosswalk import providers_from_final

PROVIDERS=('bsd','api_football','goal','openfoot','espn','sportscore','thesportsdb','fotmob')

def classify_reason(reason):
    text=str(reason or '').lower()
    if any(x in text for x in ('429','http_error','unavailable','timeout','provider_error')):
        return 'OPERATIONAL_ERROR'
    if any(x in text for x in ('budget','quota','limited','cooldown','rotation_deferred','disabled','not_configured')):
        return 'QUOTA_COOLDOWN_OR_DISABLED'
    if 'unsupported_competition' in text:
        return 'PROVIDER_DECLARED_UNSUPPORTED_COMPETITION'
    if any(x in text for x in ('conflict','regulation','missing_ft','not_finished','not_final','score_missing')):
        return 'INSUFFICIENT_OR_CONTRADICTORY_FT'
    if any(x in text for x in ('identity','ambiguous','no_exact','no_core','no_event','no_id')):
        return 'IDENTITY_OR_COVERAGE_UNRESOLVED'
    return 'OTHER_OR_UNDOCUMENTED'


def competitions(alerts):
    names=defaultdict(set)
    for row in alerts:
        if isinstance(row,dict) and row.get('match_key') and row.get('competition'):
            names[row['match_key']].add(row['competition'])
    return {key:next(iter(values)) if len(values)==1 else 'CONFLICTING_COMPETITION'
            for key,values in names.items()}


def audit_pending(ledger, backlog, alerts, api_audit, *, baseline=None, baseline_pending_keys=None):
    matches=ledger['matches'];comps=competitions(alerts)
    rows=[];counts=Counter();by_comp=defaultdict(Counter);by_provider=defaultdict(Counter)
    provider_comp=defaultdict(Counter)
    for game in backlog['overdue_games']:
        key=game['match_key'];row=matches[key];comp=comps.get(key,'UNDOCUMENTED_COMPETITION')
        visit=row.get('last_provider_visit') or {}
        latest_reasons=visit.get('reasons') or row.get('provider_reasons') or {}
        signals=[]
        for provider in PROVIDERS:
            reason=latest_reasons.get(provider)
            metric=row.get('provider_attempts',{}).get(provider,{})
            examined=row.get('examined_against',{}).get(provider,{})
            category=classify_reason(reason)
            stats={'pending_games':1,'routine_due_games':int(utc(game.get('next_eligible_at')) is not None and utc(game['next_eligible_at'])<=utc(backlog['measured_at'])),'adapter_invocations_documented':int(metric.get('invocations',0)),
                'effective_day_evidence_documented':int(bool(examined.get('fingerprint'))),
                'identity_or_coverage_unresolved':int(category=='IDENTITY_OR_COVERAGE_UNRESOLVED'),
                'unsupported_competition_documented':int(category=='PROVIDER_DECLARED_UNSUPPORTED_COMPETITION'),
                'operational_error_documented':int(category=='OPERATIONAL_ERROR')}
            by_provider[provider].update(stats);provider_comp[(provider,comp)].update(stats)
            signals.append({'provider':provider,'latest_reason':reason,
                'reason_category':category,'reason_at_utc':visit.get('at'),
                'adapter_invocations_documented':int(metric.get('invocations',0)),
                'effective_day_evidence_documented':bool(examined.get('fingerprint')),
                'http_requests_for_this_game':None})
        no_evidence=game.get('last_checked_at') is None
        categories=sorted({s['reason_category'] for s in signals if s['latest_reason']})
        primary=('NO_EFFECTIVE_CHECK_DOCUMENTED' if no_evidence else
            'OPERATIONAL_ERROR' if 'OPERATIONAL_ERROR' in categories else
            'INSUFFICIENT_OR_CONTRADICTORY_FT' if 'INSUFFICIENT_OR_CONTRADICTORY_FT' in categories else
            'IDENTITY_OR_COVERAGE_UNRESOLVED' if 'IDENTITY_OR_COVERAGE_UNRESOLVED' in categories else
            'QUOTA_COOLDOWN_OR_DISABLED' if 'QUOTA_COOLDOWN_OR_DISABLED' in categories else
            'OTHER_OR_UNDOCUMENTED')
        counts[primary]+=1
        by_comp[comp].update({'overdue':1,'without_effective_check':int(no_evidence),
            'routine_due':int(utc(game.get('next_eligible_at')) is not None and
                utc(game['next_eligible_at'])<=utc(backlog['measured_at']))})
        rows.append({'match_key':key,'home':row['home'],'away':row['away'],
            'competition':comp,'kickoff_utc':row['kickoff_utc'],
            'primary_cause':primary,'without_effective_check_documented':no_evidence,
            'queue_state':game.get('queue_state'),'next_eligible_at':game.get('next_eligible_at'),
            'last_effective_check_at':game.get('last_checked_at'),
            'last_operational_visit_at':visit.get('at'),
            'technical_irrecoverability':'NOT_PROVEN_WITH_AVAILABLE_TELEMETRY',
            'provider_evidence':signals})
    # HTTP accounting is run/provider scoped. A shared date request serves
    # many competitions: do not allocate a fictitious request to each game.
    http=defaultdict(Counter);seen=set()
    for run in api_audit.get('runs',[]):
        ident=run.get('run_id') or run.get('utc')
        if ident in seen:continue
        seen.add(ident)
        values=run.get('http_requests') or {p:v.get('requests')
            for p,v in run.get('providers',{}).items() if isinstance(v,dict)}
        for provider,n in values.items():
            if type(n) is int and n>=0:
                http[provider].update({'instrumented_runs':1,'documented_http_requests':n})
    for provider in PROVIDERS:
        by_provider[provider]['certified_current_population']=sum(
            r.get('status')=='FINAL' and provider in providers_from_final(r)
            for r in matches.values())
    for key,row in matches.items():
        if row.get('status')=='FINAL':
            by_comp[comps.get(key,'UNDOCUMENTED_COMPETITION')]['certified_current_population']+=1
    recovered=[];lost=[];became_checked=[]
    if baseline is not None:
        old=baseline['matches']
        for key,r in old.items():
            current=matches.get(key,{})
            if r.get('status')=='FINAL':
                if current.get('status')!='FINAL' or current.get('result')!=r.get('result'):lost.append(key)
            elif baseline_pending_keys is None or key in baseline_pending_keys:
                if current.get('status')=='FINAL':recovered.append(key)
                if not r.get('evidence_checked_at') and current.get('evidence_checked_at'):became_checked.append(key)
    if baseline_pending_keys is not None:
        for comp,stats in by_comp.items():
            denominator=sum(comps.get(k,'UNDOCUMENTED_COMPETITION')==comp for k in baseline_pending_keys)
            numerator=sum(comps.get(k,'UNDOCUMENTED_COMPETITION')==comp for k in recovered)
            stats['baseline_overdue']=denominator
            stats['recovered_from_baseline']=numerator
            stats['recovery_rate']=numerator/denominator if denominator else None
        for provider,stats in by_provider.items():
            n=sum(provider in providers_from_final(matches[k]) for k in recovered)
            stats['baseline_cohort_recovered_with_source']=n
            stats['fraction_of_all_baseline_pending']=n/len(baseline_pending_keys) if baseline_pending_keys else None
    return {'schema_version':1,'measured_at':backlog['measured_at'],
        'snapshot_counts':backlog['classification'],'primary_causes_exclusive':dict(counts),
        'games':rows,'by_competition':dict(sorted(by_comp.items())),
        'by_provider':dict(by_provider),
        'by_provider_competition':[{'provider':p,'competition':c,**v,
            'http_requests':None,'scope':'shared requests; competition allocation unavailable'}
            for (p,c),v in sorted(provider_comp.items())],
        'http_accounting_documented_runs':dict(http),
        'baseline_delta':{'baseline_overdue_count':len(baseline_pending_keys) if baseline_pending_keys is not None else None,
            'recovered_count':len(recovered),
            'recovery_rate':len(recovered)/len(baseline_pending_keys) if baseline_pending_keys else None,
            'recovered_preexisting_pending_keys':recovered,
            'final_lost_or_changed_keys':lost,'became_effectively_checked_keys':became_checked},
        'limitations':['No effective-check record does not prove no historical HTTP request.',
            'Adapter invocations include cache hits and are not HTTP requests.',
            'No name match cannot distinguish absent coverage from naming differences.',
            'Unsupported competition is provider-specific, never global irrecoverability.',
            'HTTP figures cover only instrumented retained runs, not lifetime quota totals.',
            'HTTP attempts are not independently verified provider billing or quota balances.',
            'No FT score is inferred and no production file is modified.']}
