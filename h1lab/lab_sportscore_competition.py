"""Score-free, fixture/competition-locked CORE_NAME locators, never aliases."""
from datetime import timedelta
from .lab_identity import CORE, pair_level, _utc as utc


def anchors(review,competitions,now):
    from .lab_sportscore import _source_url,source_order_conflict
    out={}
    for g in review.get('games',[]) if isinstance(review,dict) else []:
        key=g.get('match_key');comp=competitions.get(key)
        if (not comp or g.get('observed_competition')!=comp or g.get('possible_duplicates')
                or g.get('ft_status') not in ('PENDING','PROVIDER_ERROR')):
            continue
        candidates=[c for c in g.get('candidates',[]) if c.get('provider')=='sportscore']
        if len(candidates)!=1:
            continue
        c=candidates[0];ko=utc(g.get('kickoff_utc'));when=utc(c.get('provider_kickoff_utc'))
        seen=utc(c.get('last_seen_at'))
        if (ko is None or when is None or seen is None or now<seen
                or now-seen>timedelta(days=30) or abs(ko-when)>timedelta(minutes=5)
                or c.get('match_strength')!='STRONG' or c.get('orientation')!='SAME_ORDER'
                or c.get('observed_competition_at_capture')!=comp
                or not c.get('provider_competition') or not _source_url(c.get('reference_url'))
                or pair_level(g.get('home'),g.get('away'),c.get('provider_home'),c.get('provider_away'))!=CORE
                or source_order_conflict(c['reference_url'],c['provider_home'],c['provider_away'])):
            continue
        out[key]={'home':g['home'],'away':g['away'],'kickoff_utc':g['kickoff_utc'],
            'observed_competition':comp,'provider_home':c['provider_home'],
            'provider_away':c['provider_away'],'provider_kickoff_utc':c['provider_kickoff_utc'],
            'provider_competition':c['provider_competition'],'source':c['reference_url']}
    return out
