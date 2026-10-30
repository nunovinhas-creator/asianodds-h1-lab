"""Read-only LLM hypothesis evaluation. No network, promotion or betting writes."""
from __future__ import annotations
import copy
import hashlib
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from .timeline import collect_timelines, read_sources
from .pattern_features import PATTERNS, FEATURE_VERSION, match_features
from .v6_features_v2 import build as quality_context
from .v6_shadow import utc, quality, read_journal
from .v6_ft_events import read_events as read_ft, validate_against_ledger
from .v4_revisions import read_events as read_revisions
from .v6_discovery_planner import plan, candidate_id
from .lab_stats import wilson, fisher, bh_qvalues

VERSION = 1
MIN_TRAIN = 20
MIN_TEST = 30
MIN_DAYS = 5
SPACE = 14190  # checked against actual catalogue by build()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def feature_value(code, row):
    """Three-valued membership: missing market evidence is NEVER a control."""
    if code not in PATTERNS:
        raise ValueError('UNKNOWN_FEATURE_CODE:' + code)
    family = PATTERNS[code][1]
    ctx = row['quality_context']
    messages = ctx['messages']
    required = {'TOTAL': 'total', 'OU_PRICE': 'total', 'IMPLIED': 'total',
                '1X2': 'one_x_two', 'AH': 'asian_handicap'}
    market = required.get(family)
    if family == 'CONTEXT':
        market = 'total' if code != 'G_TOTAL_AND_1X2' else None
        if code == 'G_TOTAL_AND_1X2' and not all(any(m.get(k) for m in messages) for k in ('total','one_x_two')):
            return None
    if family == 'SEQUENCE' and code not in ('G_SINGLE_ALERT','G_MULTI_ALERT','G_MULTI_EPISODE'):
        market = 'total'
    if market:
        observed = [m[market] for m in messages if m.get(market) is not None]
        good = {'BOTH_SIDES_USABLE', 'USABLE'}
        if not observed or any(m.get('status') not in good for m in observed):
            return None
    return code in row['features']['patterns']


def hypothesis_value(codes, row):
    values = [feature_value(c, row) for c in codes]
    # Conservative complete-case design, even if another known criterion fails.
    return None if None in values else all(values)


def make_row(timeline, *, known_at=None, lineage=None):
    t = copy.deepcopy(timeline)
    identity=t.get('identity') or {}
    if not identity.get('team_names_consistent',True) or identity.get('per_message_conflicts'):
        return None, 'identity_conflict'
    ko_values = identity.get('kickoff_utc') or []
    if len(ko_values) != 1 or utc(ko_values[0]) is None:
        return None, 'kickoff_unknown_or_conflicting'
    ko = utc(ko_values[0])
    cutoff = utc(known_at) if known_at else ko
    pre = []
    for e in t['events']:
        observed = utc(e.get('observed_at'))
        if observed and observed < ko and observed <= cutoff:
            if 'identity_conflict' in e or any(x.get('status') == 'DIFFER' for x in (e.get('v4_vs_h1_record') or {}).values()):
                return None, 'source_identity_or_quote_conflict'
            e['minutes_to_kickoff'] = (ko-observed).total_seconds()/60
            pre.append(e)
    if not pre:
        return None, 'no_prekickoff_message'
    t['events'] = pre
    # Existing episode/trajectory metadata may include future events; regenerate.
    from .timeline import match_timeline
    t = match_timeline(t['match_key'], pre, near_seconds=120,
                       identities=[{'kickoff_utc': ko_values[0]}])
    f = match_features(t)
    if f.get('excluded'):
        return None, f['excluded']
    freeze = known_at or f['decision_at']
    ctx = quality_context(t, pre, known_at=freeze)
    totals = [e for e in pre if e.get('snapshots', {}).get('total')]
    baseline = quality(totals[-1]['snapshots']['total']) if totals else {}
    return {'match_key':f['match_key'], 'match_label':timeline.get('match_label') or f['match_key'],
            'kickoff_utc':ko_values[0], 'decision_at':freeze,
            'features':f, 'quality_context':ctx,
            'p':baseline.get('p_over_2_5') if baseline.get('status') == 'USABLE' else None,
            'lead_bin': next((c for c in f['patterns'] if c.startswith('G_FIRST_LEAD_')), None),
            'source_event_ids':[e['event_id'] for e in pre], 'lineage':lineage or [],
            'baseline_quality':baseline.get('status', 'NO_TOTAL')}, None


def attach_ft(row, event, now):
    row.update(y=None, ft_status='PENDING_OR_UNVERIFIED', ft_verified_at=None)
    if not event:
        return
    snap = event['snapshot']
    row['ft_status'] = snap['status']
    score = snap.get('score')
    ko, decision = utc(row['kickoff_utc']), utc(row['decision_at'])
    checked, recorded = utc(event.get('source_last_checked_at')), utc(event.get('recorded_at'))
    if snap.get('kickoff_utc') and utc(snap['kickoff_utc']) != ko:
        row['ft_status'] = 'KICKOFF_MISMATCH'; return
    good = {'SINGLE_PROVIDER','MULTI_PROVIDER','REVIEWED_PUBLIC_CORROBORATED',
            'TWO_PROVIDER_FT_CHRONOLOGY_NOT_CERTIFIED'}
    if snap['status'] != 'FINAL' or not score or snap.get('evidence_level') not in good:
        return
    if not checked or not recorded or checked < ko + timedelta(minutes=90) or checked <= decision or recorded < checked or recorded > now:
        row['ft_status'] = 'FT_CHRONOLOGY_UNUSABLE'; return
    h,a = score.get('home'),score.get('away')
    if type(h) is not int or type(a) is not int or min(h,a) < 0:
        raise ValueError('INVALID_FT_SCORE')
    if score.get('identity_match') not in ('EXACT','NORMALIZED','REVIEWED_PAIR',None):
        row['ft_status'] = 'FT_IDENTITY_NOT_ACCEPTED'; return
    row.update(y=int(h+a > 2), ft_status='VERIFIED_FT', ft_verified_at=event['recorded_at'],
               ft_sha256=event['sha256'], score=[h,a], evidence_level=snap['evidence_level'])


def losses(rows, offset=0):
    pairs = [(r['y'], r['p']) for r in rows if r['y'] is not None and r['p'] is not None]
    if not pairs:
        return {'n':0, 'brier':None, 'log_loss':None, 'mean_probability':None}
    ps = [min(1-1e-6,max(1e-6,p+offset)) for y,p in pairs]
    return {'n':len(pairs), 'brier':sum((y-p)**2 for (y,_),p in zip(pairs,ps))/len(pairs),
            'log_loss':sum(-(y*math.log(p)+(1-y)*math.log1p(-p)) for (y,_),p in zip(pairs,ps))/len(pairs),
            'mean_probability':sum(ps)/len(ps)}


def summary(rows):
    ft = [r for r in rows if r['y'] is not None]
    k = sum(r['y'] for r in ft)
    return {'matches':len(rows),'ft':len(ft),'pending':len(rows)-len(ft),
            'hits':k, 'rate':k/len(ft) if ft else None, 'rate_ci95':wilson(k,len(ft)),
            'baseline':losses(rows), 'days':len({r['kickoff_utc'][:10] for r in ft})}


def matched_controls(group, pool):
    """Outcome-blind 1:1 without replacement; explicit unmatched attrition."""
    used, selected, matched = set(), [], []
    for g in sorted(group,key=lambda r:(r['kickoff_utc'],r['match_key'])):
        if g['p'] is None:
            continue
        eligible = [c for c in pool if c['match_key'] not in used and c['p'] is not None
                    and c['lead_bin'] == g['lead_bin'] and abs(c['p']-g['p']) <= .05
                    and abs((utc(c['kickoff_utc'])-utc(g['kickoff_utc'])).total_seconds()) <= 7*86400]
        if eligible:
            c = min(eligible,key=lambda r:(abs(r['p']-g['p']),abs((utc(r['kickoff_utc'])-utc(g['kickoff_utc'])).total_seconds()),r['match_key']))
            selected.append(c); matched.append(g); used.add(c['match_key'])
    return matched, selected


def day_sign_test(rows, offset):
    """Two-sided day-cluster sign randomization of paired log-loss differences."""
    days = defaultdict(list)
    for r in rows:
        if r['y'] is not None and r['p'] is not None:
            days[r['kickoff_utc'][:10]].append(losses([r])['log_loss']-losses([r],offset)['log_loss'])
    sums = [sum(v) for _,v in sorted(days.items())]
    if len(sums)<MIN_DAYS:
        return None
    observed = abs(sum(sums))
    if len(sums)<=16:
        stats = [abs(sum(v*s for v,s in zip(sums,signs))) for signs in itertools.product((-1,1),repeat=len(sums))]
        return sum(s>=observed-1e-12 for s in stats)/len(stats)
    rng = random.Random(0)
    hits = sum(abs(sum(v*rng.choice((-1,1)) for v in sums))>=observed-1e-12 for _ in range(9999))
    return (1+hits)/10000


def evaluate(rows, codes, registered_at, *, prospective=False, trained_offset=None):
    if len({r['match_key'] for r in rows}) != len(rows):
        raise ValueError('DUPLICATE_STATISTICAL_MATCH')
    unknown = [r for r in rows if hypothesis_value(codes,r) is None]
    group = [r for r in rows if hypothesis_value(codes,r) is True]
    controls = [r for r in rows if hypothesis_value(codes,r) is False]
    mg,mc = matched_controls(group,controls)
    # Historical day-level holdout; all fits use only FT known BEFORE first test decision.
    dates = sorted({r['kickoff_utc'][:10] for r in rows
                    if utc(r['kickoff_utc']) < utc(registered_at)})
    split = dates[max(0,int(len(dates)*.7))] if dates else registered_at[:10]
    test = [r for r in group if r['kickoff_utc'][:10]>=split] if not prospective else group
    boundary = min((utc(r['decision_at']) for r in test),default=utc(registered_at))
    training = [r for r in group if r['kickoff_utc'][:10]<split and r['y'] is not None
                and r['p'] is not None and utc(r['ft_verified_at'])<boundary
                and utc(r['ft_verified_at'])<utc(registered_at)] if not prospective else []
    offset = sum(r['y']-r['p'] for r in training)/(len(training)+20) if len(training)>=MIN_TRAIN else None
    if prospective:
        offset = trained_offset
    p = day_sign_test(test,offset) if offset is not None and losses(test)['n']>=MIN_TEST else None
    base, model = losses(test), losses(test,offset) if offset is not None else None
    return {'group':summary(group),'control_pool':summary(controls),'matched_group':summary(mg),
            'matched_control':summary(mc),
            'complete_pairs':{'group':summary([g for g,c in zip(mg,mc) if g['y'] is not None and c['y'] is not None]),
                              'control':summary([c for g,c in zip(mg,mc) if g['y'] is not None and c['y'] is not None])},
            'control_match_keys':[r['match_key'] for r in mc], 'unmatched_group':len(group)-len(mg),
            'unknown_features':len(unknown),'unknown_by_code':{c:sum(feature_value(c,r) is None for r in rows) for c in codes},
            'association_fisher_p_exploratory':fisher(sum(r['y'] or 0 for r in group),sum(r['y'] is not None for r in group),
                                                      sum(r['y'] or 0 for r in controls),sum(r['y'] is not None for r in controls)),
            'temporal':{'kind':'PROSPECTIVE_MONITOR_NOT_PREREGISTERED' if prospective else 'HISTORICAL_DAY_HOLDOUT_EXPLORATORY',
                        'split_day':split,'train_n':len(training),'trained_offset_source':'HISTORICAL_TRAIN_ONLY' if prospective else 'CHRONOLOGICAL_TRAIN', 'training_keys':[r['match_key'] for r in training],
                        'offset':offset, 'test_baseline':base,'test_model':model,
                        'paired_day_randomization_p':p, 'test_keys':[r['match_key'] for r in test]},
            'games':[{'match_key':r['match_key'],'match_label':r['match_label'],'kickoff_utc':r['kickoff_utc'],
                      'decision_at':r['decision_at'],'ft_status':r['ft_status'],'score':r.get('score'),
                      'market_probability':r['p'],'baseline_quality':r['baseline_quality'],
                      'source_event_ids':r['source_event_ids'],'ft_sha256':r.get('ft_sha256'),
                      'ft_verified_at':r['ft_verified_at'],'lineage':r['lineage']} for r in group]}


def catalogue_support(rows):
    """Coverage audit of the WHOLE universe, not 14190 significance tests."""
    masks={c:sum(1<<i for i,r in enumerate(rows) if feature_value(c,r) is True) for c in PATTERNS}
    ft=sum(1<<i for i,r in enumerate(rows) if r['y'] is not None)
    price=sum(1<<i for i,r in enumerate(rows) if r['p'] is not None)
    counts=Counter(); examples=[]
    for size in (2,3):
        for codes in itertools.combinations(sorted(PATTERNS),size):
            if len({PATTERNS[c][1] for c in codes})!=size:continue
            counts['crossings']+=1
            mask=masks[codes[0]]
            for c in codes[1:]:mask &= masks[c]
            n=mask.bit_count(); verified=(mask&ft).bit_count(); baseline=(mask&ft&price).bit_count()
            counts['with_matches']+=bool(n);counts['with_verified_ft']+=bool(verified)
            counts['with_at_least_30_ft_and_baseline']+=baseline>=MIN_TEST
            if verified:
                examples.append({'candidate_id':candidate_id(list(codes)),'feature_codes':list(codes),
                                 'matches':n,'verified_ft':verified,'with_baseline':baseline})
    examples.sort(key=lambda x:x['candidate_id'])
    return {'counts':dict(counts),'examples_hash_order':examples[:20],
            'meaning':'Coverage only, no outcome-ranked selection or evidence of an effect'}


def build(root, *, now):
    root = Path(root)
    if now.tzinfo is None:
        raise ValueError('AWARE_NOW_REQUIRED')
    queue = plan(root,limit=20)  # validates every archive; no outcome-ranked selection
    if sum(queue['distinct_family_space'].values()) != SPACE:
        raise ValueError('SEARCH_SPACE_POLICY_REQUIRES_VERSION_REVIEW')
    archives = [(p,json.loads(p.read_text())) for p in sorted((root/'docs/lab/llm-investigator-runs').glob('*.json'))]
    alerts, markets, errors = read_sources(root)
    timelines, issues, excluded = collect_timelines(alerts,markets,source_errors=errors)
    if issues:
        raise ValueError('SOURCE_COVERAGE_ERRORS:' + json.dumps(issues)[:500])
    ft = read_ft(root)
    ledger = json.loads((root/'data/lab/ft-ledger.json').read_text())
    validate_against_ledger(ft,ledger)
    latest = {e['match_key']:e for e in ft if utc(e['recorded_at'])<=now}
    revisions = read_revisions(root)
    journal = read_journal(root)
    rows, reasons = [], Counter()
    for t in timelines:
        row, reason = make_row(t)
        if reason: reasons[reason]+=1; continue
        if utc(row['decision_at'])>now: reasons['future_observation']+=1;continue
        attach_ft(row,latest.get(row['match_key']),now); rows.append(row)
    by_event = defaultdict(list)
    for e in revisions: by_event[e['event_id']].append(e)
    proposals = {}
    for path,archive in archives:
        when = archive.get('recorded_at_utc')
        if not utc(when) or utc(when)>now:
            raise ValueError('INVALID_PROPOSAL_REGISTRATION_TIME')
        for p in archive['proposals']:
            cid = candidate_id(p['feature_codes'])
            if cid not in proposals or utc(when)<utc(proposals[cid]['registered_at']):
                proposals[cid] = {'candidate_id':cid,'feature_codes':sorted(p['feature_codes']),
                                 'registered_at':when,'archive':path.name,'archive_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    results=[]
    for cid,h in sorted(proposals.items()):
        historical = [r for r in rows if utc(r['decision_at'])<utc(h['registered_at'])]
        history = evaluate(historical,h['feature_codes'],h['registered_at'])
        frozen, skipped, seen = [], Counter(), set()
        for f in sorted(journal,key=lambda r:(utc(r['known_at']),r['event_id'])):
            if f['match_key'] in seen or not utc(h['registered_at'])<utc(f['known_at'])<=now:
                continue
            seen.add(f['match_key'])  # fixed FIRST capture after registration; no outcome-dependent reselection
            ctx=f.get('feature_context_v2') or {}
            ids=ctx.get('source_event_ids') or []
            selected=[]
            for eid in ids:
                ver=[v for v in by_event[eid] if utc(v['known_at'])<=utc(f['known_at'])]
                if ver: selected.append(ver[-1])
            if not ids or len(selected)!=len(ids):skipped['missing_frozen_source_version']+=1;continue
            if any(utc(v['snapshot']['observed_at'])<=utc(h['registered_at']) or
                   utc(by_event[v['event_id']][0]['known_at'])<=utc(h['registered_at']) for v in selected):
                skipped['match_observed_before_hypothesis']+=1;continue
            ts,errs,_=collect_timelines([], [v['snapshot'] for v in selected])
            if errs or len(ts)!=1 or ts[0]['match_key']!=f['match_key']:
                skipped['source_identity_conflict']+=1;continue
            row,reason=make_row(ts[0],known_at=f['known_at'],lineage=[v['sha256'] for v in selected])
            if reason:skipped[reason]+=1;continue
            if utc(row['decision_at'])>=utc(row['kickoff_utc']):
                raise ValueError('POST_KICKOFF_FREEZE')
            row['match_label']=f.get('match_label') or row['match_key']
            attach_ft(row,latest.get(row['match_key']),now);frozen.append(row)
        prospective=evaluate(frozen,h['feature_codes'],h['registered_at'],prospective=True,
                             trained_offset=history['temporal']['offset'])
        blockers=[]
        if history['unknown_features']:blockers.append('MISSING_OR_SUSPECT_FEATURE_MARKETS')
        if history['group']['pending']:blockers.append('VERIFIED_FT_MISSING_FOR_MATCHED_GAMES')
        if history['group']['baseline']['n']<history['group']['ft']:blockers.append('CLEAN_TWO_SIDED_TOTAL_BASELINE_MISSING')
        if history['temporal']['train_n']<MIN_TRAIN:blockers.append('INSUFFICIENT_CHRONOLOGICALLY_AVAILABLE_TRAINING_FT')
        if history['temporal']['test_baseline']['n']<MIN_TEST:blockers.append('INSUFFICIENT_TEMPORAL_HOLDOUT_N')
        g,c=history['matched_group'],history['matched_control']
        if g['matches'] and c['matches'] and abs(g['ft']/g['matches']-c['ft']/c['matches'])>.20:
            blockers.append('UNBALANCED_FT_COVERAGE_MATCHED_GROUPS')
        if history['group']['days']<MIN_DAYS:blockers.append('INSUFFICIENT_INDEPENDENT_CALENDAR_DAYS')
        blockers+=['NO_PREREGISTERED_CONFIRMATORY_PROTOCOL','COMPETITION_CONFOUNDING_NOT_CONTROLLED']
        pval=history['temporal']['paired_day_randomization_p']
        verdict='NAO_TESTAVEL' if not history['group']['ft'] else 'INCONCLUSIVA'
        if (pval is not None and min(1,pval*SPACE)<.05
                and history['complete_pairs']['group']['ft']>=MIN_TEST
                and history['complete_pairs']['control']['ft']>=MIN_TEST):
            base=history['temporal']['test_baseline']['log_loss']
            model=history['temporal']['test_model']['log_loss']
            verdict='MERECE_VALIDACAO_PROSPETIVA' if model<base else 'REJEITADA_EXPLORATORIA'
        results.append(dict(h,historical=history,prospective=prospective,prospective_exclusions=dict(skipped),
                            blockers=blockers,state=verdict,p_bonferroni_search_space=min(1,pval*SPACE) if pval is not None else None,
                            scientifically_proven=False))
    ps=[h['historical']['association_fisher_p_exploratory'] for h in results]
    qs=bh_qvalues([p if p is not None else 1 for p in ps])
    for h,q in zip(results,qs):h['association_bh_q_archived_family']=q
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            sorted((root/'data/lab').glob('*.json*')) if not p.is_symlink()}
    hashes['data/state.json']=hashlib.sha256((root/'data/state.json').read_bytes()).hexdigest()
    return {'schema_version':VERSION,'status':'LLM_OFFLINE_EXPLORATORY_NO_PROMOTION','generated_at':now.isoformat(),
            'source_sha256':hashes,'feature_version':FEATURE_VERSION,'hypotheses':results,
            'coverage':{'timelines':len(timelines),'usable':len(rows),'excluded':dict(reasons),
                        'excluded_source_events':len(excluded),'ft':summary(rows),'ft_states':dict(Counter(r['ft_status'] for r in rows)),'forecasts':len(journal),
                        'v4_revision_events':len(revisions),'ft_events':len(ft)},
            'catalogue_support':catalogue_support(rows),
            'queue_coverage':[{'candidate_id':c['candidate_id'],'feature_codes':c['feature_codes'],
                'matched':sum(hypothesis_value(c['feature_codes'],r) is True for r in rows),
                'verified_ft':sum(hypothesis_value(c['feature_codes'],r) is True and r['y'] is not None for r in rows)}
                for c in queue['queue']],
            'search_space':sum(queue['distinct_family_space'].values()),'llm_calls':0,'validated':0,
            'policy':{'minimum_train':MIN_TRAIN,'minimum_test':MIN_TEST,'minimum_days':MIN_DAYS,
                      'matching':'1:1, no replacement, p caliper 0.05, same lead bin, kickoff within 7 days; outcome blind',
                      'model':'Train-only residual offset sum(y-p)/(n+20); clip [1e-6,1-1e-6]',
                      'multiplicity':'Paired day sign test x full 14190 search space; descriptive Fisher BH across archived hypotheses only'},
            'limitations':['Historical mutable projections are exploratory, never frozen predictions.',
                           'The sample contains observed channel games only; no population-wide inference.',
                           'Poisson market baseline is a model, not a tradable O2.5 price.',
                           'Matched controls do not control competition, team dependence or unmeasured confounding.',
                           'Prospective capture is independent monitoring, not a preregistered confirmatory trial.',
                           'No automatic promotion, rejection as scientific truth, ROI or betting recommendation.']}
