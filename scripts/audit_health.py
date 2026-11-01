"""Read-only, zero-network health checks. JSON on stdout; never publishes/dispatches.

Exit 0 means only that the checks listed here passed, not global stability.
Missing evidence is UNKNOWN; invalid data is FAILED; stale publication is STALE.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def latest_result_checked_at(audit):
    """Return latest valid instant, not lexically greatest timestamp string.

    Invalid present timestamps are reported separately: a fresh valid record
    must not silently erase malformed producer evidence.
    """
    times, invalid = [], 0
    for entry in audit.values():
        if not isinstance(entry, dict):
            continue
        raw = entry.get('checked_at')
        if raw is None:
            continue
        if not isinstance(raw, str):
            invalid += 1
            continue
        try:
            stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                invalid += 1
            else:
                times.append(stamp.astimezone(timezone.utc))
        except ValueError:
            invalid += 1
    return (max(times).isoformat() if times else None), invalid



def h1_first_check_coverage(signals, resolved, audit, now):
    """Offline H1 queue health; no provider calls. Uses the H1 retry horizon (24h, policy v2).

    A first check is missing only if the fixture is unresolved and no valid
    audit timestamp exists. Cooldown and retries are tracked separately.
    """
    from h1lab.results import H1_RETRY_HORIZON
    if not isinstance(signals, list) or not isinstance(audit, dict) or now.tzinfo is None:
        raise ValueError("Invalid H1 first-check inputs")
    known = set()
    counts = dict(first_checks_due=0, retries_due=0, in_cooldown=0,
                  first_overdue_12h=0, first_overdue_24h=0,
                  expired_without_first_check=0, future_or_grace=0)
    oldest_wait = 0.0
    for signal in signals:
        if not isinstance(signal, dict):
            raise ValueError("Invalid H1 fixture")
        key = signal.get("match_key")
        if not isinstance(key, str) or not key or key in known:
            raise ValueError("Duplicate/invalid H1 match key")
        known.add(key)
        if key in resolved:
            continue
        raw = signal.get("kickoff_utc")
        if not isinstance(raw, str):
            raise ValueError("Invalid H1 kickoff")
        try:
            kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Invalid H1 kickoff") from exc
        if kickoff.tzinfo is None:
            raise ValueError("Naive H1 kickoff")
        eligible_at = kickoff + timedelta(hours=3)
        if now < eligible_at:
            counts["future_or_grace"] += 1
            continue
        previous = audit.get(key)
        stamp = previous.get("checked_at") if isinstance(previous, dict) else None
        checked = None
        if isinstance(stamp, str):
            try:
                checked = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if checked.tzinfo is None or checked > now + timedelta(minutes=2):
                    checked = None
            except ValueError:
                checked = None
        if now > kickoff + H1_RETRY_HORIZON:
            if checked is None:
                counts["expired_without_first_check"] += 1
            continue
        if checked is None:
            counts["first_checks_due"] += 1
            wait = max(0.0, (now - eligible_at).total_seconds() / 3600)
            oldest_wait = max(oldest_wait, wait)
            if wait > 12:
                counts["first_overdue_12h"] += 1
            if wait > 24:
                counts["first_overdue_24h"] += 1
        elif now < checked + timedelta(hours=4):
            counts["in_cooldown"] += 1
        else:
            counts["retries_due"] += 1
    counts["deferred_if_one_cycle"] = max(
        0, counts["first_checks_due"] + counts["retries_due"] - 20)
    counts["oldest_first_wait_hours"] = round(oldest_wait, 2)
    counts["first_check_cycles_at_20"] = (
        counts["first_checks_due"] + 19) // 20
    return counts


def ft_report_generation_at(ft):
    """Generation clock != last FT ledger mutation.

    A routine push can republish new diagnostics without changing a single
    result. When execution metadata exists, its measured_at is authoritative
    and MUST be valid; do not silently fall back to an older ledger stamp.
    Historical reports without execution metadata remain readable.
    """
    execution = ft.get('execution_health')
    if execution is not None:
        if not isinstance(execution, dict):
            raise ValueError('Invalid FT execution metadata')
        raw = execution.get('measured_at')
    else:
        raw = ft.get('last_updated_at')
    if not isinstance(raw, str):
        raise ValueError('Missing FT report generation timestamp')
    try:
        stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Malformed FT report generation timestamp') from exc
    if stamp.tzinfo is None:
        raise ValueError('FT report generation must be timezone-aware')
    return stamp.isoformat()


def verify_ft_backlog(ledger, ft, backlog):
    """Validate one-game partitions; 'never checked' is a SUBSET of overdue."""
    if not isinstance(backlog,dict) or backlog.get('status')!='FT_BACKLOG_AUDIT_OBSERVATION_ONLY':
        raise ValueError('Invalid FT backlog status/schema')
    if backlog.get('schema_version')!=1:
        raise ValueError('Invalid FT backlog schema')
    classifications=backlog.get('classification')
    if not isinstance(classifications,dict):
        raise ValueError('FT backlog classification missing')
    if any(type(v) is not int or v<0 for v in classifications.values()):
        raise ValueError('FT backlog non-integer/negative classification')
    matches=ledger['matches']
    n=len(matches)
    if (backlog.get('total_matches')!=n or ft.get('matches')!=n
            or classifications.get('verified_ft',0)!=ft.get('final_recorded')):
        raise ValueError('FT backlog vs ledger/report mismatch')
    exclusive=('verified_ft','future','in_3h_grace','past_due_unverified',
               'closed_unverified','quarantined_or_identity_review','unknown_kickoff')
    if any(k not in (*exclusive,'past_due_never_checked','past_due_expired')
           for k in classifications):
        raise ValueError('FT backlog unexpected classification')
    if sum(classifications.get(k,0) for k in exclusive)!=n:
        raise ValueError('FT backlog nonexclusive partition')
    # EXPIRED_UNVERIFIED is a terminal, never-retried unproven outcome.
    # It is neither an overdue retry nor a verified final.
    closed=classifications.get('closed_unverified',0)
    if closed!=sum(item.get('status')=='EXPIRED_UNVERIFIED'
                   for item in matches.values()):
        raise ValueError('FT closed-unverified ledger partition mismatch')
    diag=ft.get('coverage_diagnostics')
    if (not isinstance(diag,dict)
            or diag.get('closed_unverified',0)!=closed):
        raise ValueError('FT closed-unverified coverage mismatch')
    overdue=classifications.get('past_due_unverified',0)
    if (classifications.get('past_due_never_checked',0)>overdue
            or classifications.get('past_due_expired',0)>overdue):
        raise ValueError('FT backlog subset exceeds overdue')
    if (not isinstance(backlog.get('overdue_games'),list)
            or type(backlog.get('overdue_omitted')) is not int
            or backlog['overdue_omitted']<0
            or len(backlog['overdue_games'])+backlog['overdue_omitted']!=overdue):
        raise ValueError('FT backlog displayed overdue count mismatch')
    seen=set()
    for row in backlog['overdue_games']:
        if not isinstance(row,dict):
            raise ValueError('FT backlog overdue game invalid')
        key=row.get('match_key')
        if not isinstance(key,str) or key not in matches or key in seen:
            raise ValueError('FT backlog duplicate/unknown fixture identity')
        if matches[key].get('status') in ('FINAL','EXPIRED_UNVERIFIED'):
            raise ValueError('FT backlog terminal match reported overdue')
        seen.add(key)
    diag=ft.get('coverage_diagnostics')
    if (not isinstance(diag,dict)
            or diag.get('past_unverified_eligible')!=overdue):
        raise ValueError('FT backlog differs from coverage diagnostics')
    queue=backlog.get('queue_plan')
    if not isinstance(queue,dict):
        raise ValueError('FT backlog queue plan missing')
    for key in ('eligible','selected','deferred_by_capacity'):
        if type(queue.get(key)) is not int or queue[key]<0:
            raise ValueError('FT backlog invalid queue count')
    if queue['selected']+queue['deferred_by_capacity']!=queue['eligible']:
        raise ValueError('FT backlog queue capacity mismatch')
    if queue['selected']>30:
        raise ValueError('FT backlog exceeds batch limit')
    if not isinstance(backlog.get('measured_at'),str):
        raise ValueError('FT backlog timestamp missing')
    backlog_at=datetime.fromisoformat(backlog['measured_at'].replace('Z','+00:00'))
    report_at=datetime.fromisoformat(ft_report_generation_at(ft))
    if backlog_at.tzinfo is None or report_at.tzinfo is None:
        raise ValueError('FT backlog timestamp without timezone')
    if abs((backlog_at-report_at).total_seconds())>120:
        raise ValueError('FT backlog and FT report are different generations')
    return {'matches':n,'final':classifications.get('verified_ft',0),
            'overdue':overdue,'never_checked_subset':classifications.get('past_due_never_checked',0),
            'omitted':backlog['overdue_omitted']}


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
        freshness('ft_publication',ft_report_generation_at(ft),90)
        execution=ft.get('execution_health')
        if execution is not None:
            if not isinstance(execution,dict):raise ValueError('Invalid FT execution health')
            execution_status=execution.get('status')
            record('ft_execution','DEGRADED' if execution_status=='DEGRADED' else
                   'UNKNOWN' if execution_status in ('ATTEMPTED','NOT_ATTEMPTED') else 'FAILED',
                   execution_status if execution_status in ('DEGRADED','ATTEMPTED','NOT_ATTEMPTED') else 'invalid_execution_status')
        from h1lab.v6_ft_events import read_events,validate_against_ledger
        validate_against_ledger(read_events(root),ledger)
        record('ft_journal','OK','hash_lineage_and_current_ledger_agree')
        try:
            backlog=read('docs/lab/ft-backlog.json')
            details=verify_ft_backlog(ledger,ft,backlog)
            record('ft_backlog','OK',details)
            freshness('ft_backlog_publication',backlog.get('measured_at'),90)
        except FileNotFoundError:
            record('ft_backlog','UNKNOWN','backlog_file_missing')
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            record('ft_backlog','FAILED',dict(reason='backlog_invalid',error_type=type(exc).__name__))
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        record('ft_integrity','FAILED',type(exc).__name__)
    try:
        state=read('data/state.json');published=read('docs/data.json')
        from h1lab.core import public_data,load_results
        confirmed=load_results(root/'data/results.csv')
        replay=public_data(state,confirmed,now)
        if any(replay[k]!=published[k] for k in ('singles','triples')):raise ValueError('H1 replay differs')
        record('h1_replay','OK','singles_and_fifo_metrics_agree')
        freshness('collector',state.get('collector',{}).get('last_poll_at'),90)
        audit=read('data/result_audit.json')
        coverage=h1_first_check_coverage(state.get('signals'),confirmed,audit,now)
        coverage_degraded=(coverage['first_overdue_12h']>0 or
                           coverage['expired_without_first_check']>0)
        record('h1_first_check_coverage',
               'DEGRADED' if coverage_degraded else 'OK',coverage)
        # Compare instants, not strings: offset/DST changes invert lexical order.
        latest, invalid = latest_result_checked_at(audit)
        # A latest attempted fixture is evidence of activity, never delivery proof.
        freshness('h1_result_activity',latest,120)
        if invalid:
            record('h1_result_timestamp_integrity','DEGRADED',
                   dict(reason='invalid_checked_at',invalid_entries=invalid))
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
