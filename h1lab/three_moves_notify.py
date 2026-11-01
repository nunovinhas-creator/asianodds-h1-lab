"""Telegram: at least three independently evidenced V4 Total-line movements.

This is descriptive pre-match observation, not a validated betting strategy.
Legacy E4/T05 senders and their ledgers remain readable but are never invoked.
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

LEDGER = Path("data/three-total-moves-notifications.json")
SCHEMA_VERSION = 1
RULE_VERSION = "THREE_V4_INDEPENDENT_TOTAL_MOVES_20261031"
MIN_MOVES = 3
# No 12h limit: all known fixtures with kickoff strictly in the future qualify.
# An observed move means an explicit Was->Now line change in ONE V4 message.
# Gaps between messages are NEVER interpreted as observed movements.
AMBIGUOUS_TRANSITIONS = {"SAME_MOVEMENT_REPEAT", "AMBIGUOUS_REPEAT_OR_REVERSAL"}


def _line(value):
    return format(value, ".2f").replace(".", ",")


def candidates(timelines, now):
    """Reject ambiguous fixture identities and deduplicate suspected repeats.

    A dashboard's '3 alertas' is not necessarily three independent movements.
    The canonical trajectory flags related/repeated or ambiguous snapshots.
    """
    if now.tzinfo is None:
        raise ValueError("notification clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    selected, keys = [], set()
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
            raise ValueError("duplicate fixture in three-move Telegram candidates")
        keys.add(key)

        trajectory = (timeline.get("trajectory") or {}).get("total") or {}
        points = trajectory.get("points") or []
        if not points:
            continue
        transition_kinds = {t.get("to"): t.get("line")
                            for t in trajectory.get("transitions") or []}
        # Timeline relations form connected components of possibly identical
        # messages. They bound *independent* movements; never silently delete.
        episodes = {event_id: group[0]
                    for group in timeline.get("movement_episodes") or []
                    for event_id in group}
        redundant = set(timeline.get("possibly_redundant_event_ids") or [])
        event_times = {e.get("event_id"): utc(e.get("observed_at"))
                       for e in timeline.get("events") or []}
        accepted, used_episodes = [], set()
        for point in points:
            event_id = point.get("event_id")
            at = event_times.get(event_id)
            if at is None or at > now or at >= kickoff:
                continue
            if point.get("origin") != "V4_EXPLICIT" or point.get("move") not in ("UP", "DOWN"):
                continue
            if transition_kinds.get(event_id) in AMBIGUOUS_TRANSITIONS or event_id in redundant:
                continue
            episode = episodes.get(event_id, event_id)
            if episode in used_episodes:
                continue
            before, after = point.get("before"), point.get("after")
            if (not isinstance(before, (int, float)) or isinstance(before, bool) or
                    not isinstance(after, (int, float)) or isinstance(after, bool) or
                    before == after):
                continue
            accepted.append({"event_id": event_id, "at": at.isoformat(),
                             "before": before, "after": after,
                             "direction": point["move"]})
            used_episodes.add(episode)
        if len(accepted) < MIN_MOVES:
            continue
        reversals = sum(a["direction"] != b["direction"]
                        for a, b in zip(accepted, accepted[1:]))
        selected.append({
            "match_key": key, "match_label": label, "kickoff_utc": kickoff.isoformat(),
            "observed_through": accepted[-1]["at"], "movements": accepted,
            "movement_count": len(accepted), "reversals": reversals,
            "first_total": accepted[0]["before"],
            "last_total": accepted[-1]["after"],
        })
    return sorted(selected, key=lambda r: (r["kickoff_utc"], r["match_key"]))


def message_for_game(row):
    kickoff = utc(row.get("kickoff_utc"))
    movements = row.get("movements") or []
    if kickoff is None or not row.get("match_label") or len(movements) < MIN_MOVES:
        raise ValueError("invalid three-move Telegram game")
    local = kickoff.astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d/%m %H:%M")
    recent = movements[-3:]
    direction = {"UP": "↑", "DOWN": "↓"}
    sequence = " · ".join(direction[m["direction"]] + " " +
                          _line(m["before"]) + "→" + _line(m["after"])
                          for m in recent)
    heading = "🔄 3+ MOVIMENTOS CONFIRMADOS · TOTAL"
    detail = ("📉 Movimentos V4 distintos: " + str(len(movements)) +
              " · Inversões: " + str(row["reversals"]))
    msg = "\n".join((heading, "⚽ " + row["match_label"],
                     "🕒 " + local + " (Portugal)", detail,
                     "📊 " + ("Últimos 3: " if len(movements) > 3 else "") + sequence))
    if len(msg.encode("utf-8")) > 4096:
        raise ValueError("three-move Telegram message exceeds 4096 bytes")
    return msg


def empty_ledger(now):
    return {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION,
            "activated_at": now.isoformat(timespec="seconds"), "entries": {}}


def process(rows, ledger, now, sender, enabled, *, pace=None, clock=None, persist=None, store=None):
    """One initial message per eligible fixture, all future kickoff dates.

    Ambiguous Telegram deliveries get a persistent review state, not retries.
    """
    if (not isinstance(ledger, dict) or ledger.get("schema_version") != SCHEMA_VERSION or
            ledger.get("rule_version") != RULE_VERSION or not isinstance(ledger.get("entries"), dict)):
        raise ValueError("invalid three-move Telegram ledger; nothing sent")
    if now.tzinfo is None:
        raise ValueError("notification clock must be timezone-aware")
    if clock is None:
        clock = lambda: now
    stats = {"eligible_future": len(rows), "sent": 0, "already_notified": 0,
             "unconfigured": 0, "expired": 0, "uncertain": 0}
    store = store or delivery.default_store()
    delivery.sweep(ledger, clock(), stats)
    attempts = 0
    for row in sorted(rows, key=lambda r: (r["kickoff_utc"], r["match_key"])):
        kickoff = utc(row.get("kickoff_utc"))
        if kickoff is None or kickoff <= now:
            stats["expired"] += 1
            continue
        key = row["match_key"]
        if delivery.gate(ledger, key, kickoff, clock(), stats) == "skip":
            continue
        try:
            paused = delivery.blocked(store, clock())
        except ValueError:
            # Unreadable pause record: nothing is sent (no HTTP), loudly, and the job goes on to store data.
            delivery._bump(stats, "block_unreadable")
            print("TELEGRAM_BLOCK_UNREADABLE", file=sys.stderr)
            break
        if paused:
            delivery._bump(stats, "suspended")
            continue
        if not enabled:
            stats["unconfigured"] += 1
            continue
        if kickoff <= clock():
            stats["expired"] += 1
            continue
        if attempts and pace is not None:
            pace()
        if kickoff <= clock():
            stats["expired"] += 1
            continue
        attempts += 1
        outcome = delivery.deliver(
            ledger, key, sender, message_for_game(row),
            {"kickoff_utc": row["kickoff_utc"], "rule_version": RULE_VERSION,
             "movement_event_ids": [m["event_id"] for m in row["movements"]]}, {"observed_through": row["observed_through"], "movements_at_send": row["movement_count"]}, clock, persist, stats, store)
        if outcome == "stop":
            break
    return ledger, stats


def _rows(root, now):
    alerts, markets, errors = read_sources(root)
    # No data from after this run is allowed to influence a pre-match decision.
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
        print("MASTER_BRAIN_THREE_TOTAL_MOVES_DRY_RUN",
              "eligible_future", len(rows),
              "pending", sum(r["match_key"] not in ledger["entries"] for r in rows),
              "issues", issues, "excluded", excluded)
        for row in rows:
            if row["match_key"] not in ledger["entries"]:
                print("MATCH", row["match_label"], row["kickoff_utc"],
                      "moves", row["movement_count"], "reversals", row["reversals"])
        return ledger
    publish = (delivery.git_publisher(root, lambda: delivery.durable_paths(root, LEDGER),
                              guard=delivery.claim_guard(root, LEDGER), guard_path=str(LEDGER))
               if delivery.durable_enabled() else None)

    def persist(value):
        _write(path, value)
        if publish is not None:
            publish()  # opt-in TG_DURABLE_INTENT=1: intent BEFORE the HTTP call, outcome right after

    ledger, stats = process(rows, ledger, now, sender,
                            configured() if bot_enabled is None else bot_enabled,
                            pace=lambda: time.sleep(1.2),
                            clock=(lambda: datetime.now(timezone.utc)) if realtime else (lambda: now),
                            persist=persist)
    _write(path, ledger)
    print("MASTER_BRAIN_THREE_TOTAL_MOVES_NOTIFY", stats,
          "timeline_issues", issues, "excluded_observations", excluded,
          "receipts", len(ledger["entries"]))
    return ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
