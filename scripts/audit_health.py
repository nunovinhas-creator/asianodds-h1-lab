"""Read-only, zero-network health checks. JSON on stdout; never publishes/dispatches.

Exit 0 means only that the checks listed here passed, not global stability.
Missing evidence is UNKNOWN; invalid data is FAILED; stale publication is STALE.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def check(root, now):
    root=Path(root)
    if now.tzinfo is None: raise ValueError('aware clock required')
    checks=[]
    def record(name,status,reason):checks.append(dict(name=name,status=status,reason=reason))
    def read(path):return json.loads((root/path).read_text(encoding='utf-8'))
    def freshness(name,stamp,minutes):
        try:
            t=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if t.tzinfo is None:raise ValueError()
            age=(now-t).total_seconds()/60
            record(name,'UNKNOWN' if age < -2 else 'STALE' if age>minutes else 'OK',dict(age_minutes=round(age,2),limit_minutes=minutes))
        except (AttributeError,TypeError,ValueError):record(name,'UNKNOWN','missing_or_invalid_timestamp')
    try:
        ledger=read('data/lab/ft-ledger.json');ft=read('docs/lab/ft-results.json')
        rows=ledger['matches'];final=sum(r.get('status')=='FINAL' for r in rows.values())
        timing=ft['timing_counts']
        if (len(rows)!=ft['matches'] or final!=ft['final_recorded'] or
            final+ft['unverified']!=ft['matches'] or
            any(type(v) is not int or v<0 for v in timing.values()) or
            sum(timing.values())!=ft['matches']):raise ValueError('FT counters disagree')
        record('ft_counts','OK','ledger_report_timing_agree')
        freshness('ft_publication',ft.get('last_updated_at'),90)
        execution=ft.get('execution_health')
        if execution is not None:
            if not isinstance(execution,dict):raise ValueError('Invalid FT execution health')
            execution_status=execution.get('status')
            record('ft_execution','DEGRADED' if execution_status=='DEGRADED' else 'UNKNOWN',
                   execution_status if execution_status in ('DEGRADED','ATTEMPTED','NOT_ATTEMPTED') else 'invalid_execution_status')
        from h1lab.v6_ft_events import read_events,validate_against_ledger
        validate_against_ledger(read_events(root),ledger)
        record('ft_journal','OK','hash_lineage_and_current_ledger_agree')
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        record('ft_integrity','FAILED',type(exc).__name__)
    try:
        state=read('data/state.json');published=read('docs/data.json')
        from h1lab.core import public_data,load_results
        replay=public_data(state,load_results(root/'data/results.csv'),now)
        if any(replay[k]!=published[k] for k in ('singles','triples')):raise ValueError('H1 replay differs')
        record('h1_replay','OK','singles_and_fifo_metrics_agree')
        freshness('collector',state.get('collector',{}).get('last_poll_at'),90)
        audit=read('data/result_audit.json')
        times=[v.get('checked_at') for v in audit.values() if isinstance(v,dict) and isinstance(v.get('checked_at'),str)]
        # A latest attempted fixture is evidence of activity, never delivery proof.
        freshness('h1_result_activity',max(times) if times else None,120)
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        record('h1_integrity','FAILED',type(exc).__name__)
    for name,path in [('research','docs/lab/pattern-research.json'),('watch','docs/lab/pattern-watch.json'),('v4','docs/lab/v4-audit.json')]:
        try:freshness(name,read(path).get('generated_at'),120)
        except (OSError,ValueError,AttributeError):record(name,'UNKNOWN','report_unavailable')
    status='FAILED' if any(c['status']=='FAILED' for c in checks) else 'DEGRADED' if any(c['status']!='OK' for c in checks) else 'OK'
    return dict(schema_version=1,measured_at=now.isoformat(),status=status,checks=checks,
        limitations=['Local committed snapshots only; Pages/Telegram/Cloudflare delivery NOT VERIFIED.',
                    'No traffic-rate assumption; freshness uses publication/checkpoint timestamps.',
                    'Provider availability, full pipeline health and global stability NOT certified.'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default='.');p.add_argument('--now')
    a=p.parse_args();now=datetime.fromisoformat(a.now.replace('Z','+00:00')) if a.now else datetime.now(timezone.utc)
    r=check(a.root,now);print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='OK' else 1

if __name__=='__main__':raise SystemExit(main())
