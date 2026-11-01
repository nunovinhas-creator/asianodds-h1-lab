"""Independent Telegram watch: two distinct upward V4 Total-line moves.

Additive channel alongside three_moves_notify; this module does not import or
modify its eligibility, receipt ledger, or notification text.

Descriptive movement pattern only, NOT a validated goal prediction.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import telegram_delivery as delivery
from .bot import BotDeliveryError, configured, send_message
from .strategy_notify import ROOT, _write
from .timeline import collect_timelines, read_sources, utc

LEDGER = Path("data/two-up-total-notifications.json")
SCHEMA_VERSION = 1
RULE_VERSION = "TWO_DISTINCT_V4_TOTAL_UP_NO_REVERSAL_20261031"
MIN_UP_MOVES = 2
MIN_NET_RISE = 0.50
AMBIGUOUS_TRANSITIONS = {"SAME_MOVEMENT_REPEAT", "AMBIGUOUS_REPEAT_OR_REVERSAL"}


def _line(n):
    return format(n, ".2f").replace(".", ",")


def candidates(timelines, now):
    """Two independent V4 Total line rises, +0.5 net, no observed V4 fall.

    A match can have extra flat alerts (like Merlo), but those are NOT counted
    as upward moves. Unobserved inter-message gaps NEVER count as movement.
    """
    if now.tzinfo is None:
        raise ValueError("two-up clock requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    output, keys = [], set()
    for timeline in timelines:
        identity = timeline.get("identity") or {}
        kickoffs = identity.get("kickoff_utc") or []
        if (len(kickoffs) != 1 or
                not identity.get("team_names_consistent") or
                not identity.get("kickoff_consistent") or
                identity.get("per_message_conflicts")):
            continue
        kickoff = utc(kickoffs[0])
        if kickoff is None or kickoff <= now:
            continue
        key, label = timeline.get("match_key"), timeline.get("match_label")
        if not isinstance(key, str) or not key or not isinstance(label, str) or " vs " not in label:
            continue
        if key in keys:
            raise ValueError("duplicate match key in two-up notifier")
        keys.add(key)

        total = (timeline.get("trajectory") or {}).get("total") or {}
        points = total.get("points") or []
        transitions = {t.get("to"): t.get("line")
                       for t in total.get("transitions") or []}
        episodes = {event_id: group[0]
                    for group in timeline.get("movement_episodes") or []
                    for event_id in group}
        redundant = set(timeline.get("possibly_redundant_event_ids") or [])
        at_by_id = {event.get("event_id"): utc(event.get("observed_at"))
                    for event in timeline.get("events") or []}
        ups, used_episodes, observed_down = [], set(), False
        # Capture only explicit, non-ambiguous V4 before→after line changes.
        # Reject a fixture with ANY observed downward Total move, even if
        # the graph reports zero calculated reversals for another reason.
        for point in points:
            eid = point.get("event_id")
            observed_at = at_by_id.get(eid)
            if observed_at is None or observed_at > now or observed_at >= kickoff:
                continue
            if point.get("origin") != "V4_EXPLICIT":
                continue
            movement = point.get("move")
            if movement == "DOWN":
                observed_down = True
                break
            if movement != "UP":
                continue
            if transitions.get(eid) in AMBIGUOUS_TRANSITIONS or eid in redundant:
                continue
            episode = episodes.get(eid, eid)
            if episode in used_episodes:
                continue
            before, after = point.get("before"), point.get("after")
            if (not isinstance(before, (int, float)) or isinstance(before, bool)
                    or not isinstance(after, (int, float)) or isinstance(after, bool)
                    or after <= before):
                continue
            ups.append({"event_id": eid, "at": observed_at.isoformat(),
                        "before": before, "after": after})
            used_episodes.add(episode)
        if observed_down or len(ups) < MIN_UP_MOVES:
            continue
        # The examples show 3.25→3.75 and 1.75→2.25. Require a genuine
        # at-least-half-line net gain, not merely two tiny bumps.
        first, last = ups[0]["before"], ups[-1]["after"]
        if last - first + 1e-9 < MIN_NET_RISE:
            continue
        output.append({
            "match_key": key, "match_label": label,
            "kickoff_utc": kickoff.isoformat(),
            "observed_through": ups[-1]["at"], "movements": ups,
            "up_movements": len(ups), "first_total": first,
            "last_total": last, "net_line_rise": round(last - first, 3),
        })
    return sorted(output, key=lambda row: (row["kickoff_utc"], row["match_key"]))


def message_for_game(row):
    ko = utc(row.get("kickoff_utc"))
    ups = row.get("movements") or []
    if ko is None or not row.get("match_label") or len(ups) < MIN_UP_MOVES:
        raise ValueError("invalid two-up Telegram match")
    if row.get("net_line_rise", 0) + 1e-9 < MIN_NET_RISE:
        raise ValueError("invalid two-up net change")
    time_pt = ko.astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d/%m %H:%M")
    sequence = " · ".join(_line(m["before"]) + "→" + _line(m["after"]) + " ↑"
                          for m in ups[-3:])
    message = "\n".join((
        "📈 2+ SUBIDAS SEGUIDAS · TOTAL (SEM INVERSÃO V4)",
        "⚽ " + row["match_label"],
        "🕒 " + time_pt + " (Portugal)",
        "📊 " + _line(row["first_total"]) + " → " +
        _line(row["last_total"]) + " · +" + _line(row["net_line_rise"]),
        "🔎 " + str(row["up_movements"]) + " subidas distintas: " + sequence,
    ))
    if len(message.encode("utf-8")) > 4096:
        raise ValueError("two-up Telegram message exceeds 4096 bytes")
    return message


def empty_ledger(now):
    return {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION,
            "activated_at": now.isoformat(timespec="seconds"), "entries": {}}


def process(rows, ledger, now, sender, enabled, *, pace=None, clock=None, persist=None, store=None):
    """One message per match for this rule, separately from 3-move receipts."""
    if (not isinstance(ledger, dict) or ledger.get("schema_version") != SCHEMA_VERSION or
            ledger.get("rule_version") != RULE_VERSION or
            not isinstance(ledger.get("entries"), dict)):
        raise ValueError("invalid two-up Telegram ledger; no messages sent")
    if now.tzinfo is None:
        raise ValueError("notification clock must be timezone-aware")
    if clock is None:
        clock = lambda: now
    counts = {"eligible_future": len(rows), "sent": 0, "already_notified": 0,
              "unconfigured": 0, "expired": 0, "uncertain": 0}
    store = store or delivery.default_store()
    delivery.sweep(ledger, clock(), counts)
    attempts = 0
    for row in sorted(rows, key=lambda r: (r["kickoff_utc"], r["match_key"])):
        kickoff = utc(row.get("kickoff_utc"))
        if kickoff is None or kickoff <= now:
            counts["expired"] += 1
            continue
        key = row["match_key"]
        if delivery.gate(ledger, key, kickoff, clock(), counts) == "skip":
            continue
        try:
            paused = delivery.blocked(store, clock())
        except ValueError:
            # Unreadable pause record: nothing is sent (no HTTP), loudly, and the job goes on to store data.
            delivery._bump(counts, "block_unreadable")
            print("TELEGRAM_BLOCK_UNREADABLE", file=sys.stderr)
            break
        if paused:
            delivery._bump(counts, "suspended")
            continue
        if not enabled:
            counts["unconfigured"] += 1
            continue
        if kickoff <= clock():
            counts["expired"] += 1
            continue
        if attempts and pace is not None:
            pace()
        if kickoff <= clock():
            counts["expired"] += 1
            continue
        attempts += 1
        outcome = delivery.deliver(
            ledger, key, sender, message_for_game(row),
            {"kickoff_utc": row["kickoff_utc"], "rule_version": RULE_VERSION,
             "movement_event_ids": [m["event_id"] for m in row["movements"]]}, {"observed_through": row["observed_through"], "up_movements_at_send": row["up_movements"],
             "net_line_rise_at_send": row["net_line_rise"]}, clock, persist, counts, store)
        if outcome == "stop":
            break
    return ledger, counts


def _rows(root, now):
    alerts, markets, errors = read_sources(root)
    alerts = [a for a in alerts if utc(a.get("observed_at")) and utc(a["observed_at"]) <= now]
    markets = [m for m in markets if utc(m.get("observed_at")) and utc(m["observed_at"]) <= now]
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    return candidates(timelines, now), len(issues), len(excluded)


def run(root=ROOT, now=None, sender=send_message, bot_enabled=None, *, dry_run=False):
    root = Path(root)
    realtime = now is None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows, issues, excluded = _rows(root, now)
    path = root / LEDGER
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger(now)
    if dry_run:
        print("MASTER_BRAIN_TWO_UP_TOTAL_DRY_RUN", "eligible_future", len(rows),
              "pending", sum(row["match_key"] not in ledger["entries"] for row in rows),
              "issues", issues, "excluded", excluded)
        for row in rows:
            if row["match_key"] not in ledger["entries"]:
                print("MATCH", row["match_label"], row["kickoff_utc"],
                      "up_moves", row["up_movements"], "net", row["net_line_rise"])
        return ledger
    publish = (delivery.git_publisher(root, lambda: delivery.durable_paths(root, LEDGER),
                              guard=delivery.claim_guard(root, LEDGER), guard_path=str(LEDGER))
               if delivery.durable_enabled() else None)

    def persist(value):
        _write(path, value)
        if publish is not None:
            publish()  # opt-in TG_DURABLE_INTENT=1: intent BEFORE the HTTP call, outcome right after

    ledger, counts = process(rows, ledger, now, sender,
                             configured() if bot_enabled is None else bot_enabled,
                             pace=lambda: time.sleep(1.2),
                             clock=(lambda: datetime.now(timezone.utc)) if realtime else (lambda: now),
                            persist=persist)
    _write(path, ledger)
    print("MASTER_BRAIN_TWO_UP_TOTAL_NOTIFY", counts,
          "timeline_issues", issues, "excluded_observations", excluded,
          "receipts", len(ledger["entries"]))
    return ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
