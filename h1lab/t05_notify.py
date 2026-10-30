"""T05 research-only Telegram: frozen V5 crossing, strictly pre-kickoff.

Separate from E4 and all H1 settlement. Never reads FT to select matches.
One historical RECAP of the three visible 28–29 Oct examples on activation;
prospective entries are restricted to the next 12h and have separate receipts.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .bot import BotDeliveryError, configured, send_message
from .pattern_features import FEATURE_VERSION, message_metrics
from .strategy_notify import MAX_ALERT_LOOKAHEAD, ROOT, _write
from .timeline import collect_timelines, read_sources, utc
from .v6_offline_statistics import make_row, hypothesis_value

LEDGER = Path("data/t05-notifications.json")
SCHEMA = 1
RULE_VERSION = "T05_20261030_FROZEN_EXPLORATION"
CODES = ("G_FIRST_LEAD_LT_6H", "M_1X2_HOME_PROB_UP", "M_TOTAL_LINE_UP")
CANDIDATE_ID = "7d7275b4a862fec6cd7f5b54ee1a006bce840edb72e3e9645668f5fdacc4c548"
EXAMPLES = (
    ("Anadolu Üniversitesi – 68 Aksaray", "3–1"),
    ("Olimpia – Cartaginés", "2–2"),
    ("Kasımpaşa – Çorluspor", "3–1"),
)


def empty_ledger(now):
    return {"schema_version": SCHEMA, "rule_version": RULE_VERSION,
            "activated_at": now.isoformat(timespec="seconds"), "entries": {}}


def historical_message():
    lines = ["📚 T05 · HISTÓRICO (NÃO É ALERTA PRÉ-JOGO)",
             "🎯 Over 2,5 · primeiro alerta <6h + prob. casa 1X2 ↑ + linha Total ↑"]
    lines.extend("⚽ " + name + " · " + result for name, result in EXAMPLES)
    lines.append("📊 3/3 Over 2,5 observados; amostra retrospetiva de 3 jogos, NÃO validada.")
    return "\n".join(lines)


def message_for_game(row):
    ko = utc(row.get("kickoff_utc"))
    if ko is None or not row.get("match_label"):
        raise ValueError("INVALID_T05_MATCH")
    when = ko.astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d/%m %H:%M")
    return "\n".join((
        "🔵 T05 · OVER 2,5 · EXPERIMENTAL",
        "⚽ " + row["match_label"],
        "🕒 " + when + " (Portugal)",
        "🔎 1.º alerta <6h · prob. casa 1X2 ↑ · linha Total ↑",
        "📊 Histórico observado: 3/3 (retrospectivo, não validado)",
    ))


def _has_explicit_v4(timeline, now, kickoff):
    """Only genuine V4 before→after moves can establish BOTH positive markets."""
    required = {"M_1X2_HOME_PROB_UP": "one_x_two",
                "M_TOTAL_LINE_UP": "total"}
    found = set()
    for event in timeline.get("events", []):
        at = utc(event.get("observed_at"))
        if at is None or at > now or at >= kickoff:
            continue
        patterns = set(message_metrics(event).get("patterns") or [])
        for code, market in required.items():
            snapshot = (event.get("snapshots") or {}).get(market)
            if code in patterns and isinstance(snapshot, dict) and snapshot.get("origin") == "V4_EXPLICIT":
                found.add(code)
    return len(found) == len(required)


def candidates(timelines, now):
    """Identical complete-case feature predicate as offline T05; zero outcome data."""
    if now.tzinfo is None:
        raise ValueError("T05 clock must be timezone aware")
    now = now.astimezone(timezone.utc)
    selected, keys = [], set()
    for timeline in timelines:
        identity = timeline.get("identity") or {}
        ko_times = identity.get("kickoff_utc") or []
        if len(ko_times) != 1:
            continue
        ko = utc(ko_times[0])
        if ko is None or not now < ko <= now + MAX_ALERT_LOOKAHEAD:
            continue
        if not _has_explicit_v4(timeline, now, ko):
            continue
        row, reason = make_row(timeline, known_at=now.isoformat())
        if reason is not None or row is None:
            continue
        if row["features"].get("feature_version") != FEATURE_VERSION:
            raise ValueError("T05_FEATURE_VERSION_DRIFT")
        if hypothesis_value(CODES, row) is not True:
            continue
        key = row["match_key"]
        if key in keys:
            raise ValueError("T05_DUPLICATE_MATCH_KEY")
        keys.add(key)
        selected.append({"match_key":key, "match_label":row["match_label"],
                         "kickoff_utc":row["kickoff_utc"], "detected_at":now.isoformat(timespec="seconds"),
                         "observed_through":row["features"]["decision_at"],
                         "fingerprint":row["features"]["fingerprint"],
                         "candidate_id":CANDIDATE_ID})
    return sorted(selected, key=lambda v: (v["kickoff_utc"], v["match_key"]))


def process(rows, ledger, now, sender, enabled, *, pace=None, clock=None):
    if (not isinstance(ledger, dict) or ledger.get("schema_version") != SCHEMA
            or ledger.get("rule_version") != RULE_VERSION or
            not isinstance(ledger.get("entries"), dict)):
        raise ValueError("INVALID_T05_TELEGRAM_LEDGER")
    stats = {"future_eligible_12h":0, "future_sent":0, "historical_sent":0,
             "duplicate":0, "expired":0, "unconfigured":0, "uncertain":0}
    if clock is None:
        clock = lambda: now
    entries = ledger["entries"]

    # Distinct, once-only retrospective proof requested by the user. Never
    # masquerades as a prospective prediction or contributes to hit rate.
    if "historical:2026-10-28-29" not in entries:
        if not enabled:
            stats["unconfigured"] += 1
        else:
            try:
                mid = sender(historical_message())
                if isinstance(mid,bool) or not isinstance(mid,int):
                    raise BotDeliveryError("T05_TELEGRAM_UNCERTAIN_ID")
                entries["historical:2026-10-28-29"] = {
                    "status":"sent", "telegram_message_id":mid,
                    "at":now.isoformat(timespec="seconds"),"kind":"HISTORICAL_ONLY"}
                stats["historical_sent"] = 1
            except BotDeliveryError:
                entries["historical:2026-10-28-29"] = {
                    "status":"delivery_uncertain_manual_review",
                    "at":now.isoformat(timespec="seconds"),"kind":"HISTORICAL_ONLY"}
                stats["uncertain"] += 1
    for row in sorted(rows, key=lambda x:(x["kickoff_utc"],x["match_key"])):
        ko = utc(row.get("kickoff_utc"))
        if ko is None or not now < ko <= now + MAX_ALERT_LOOKAHEAD:
            continue
        stats["future_eligible_12h"] += 1
        key = "T05|" + row["match_key"]
        if key in entries:
            stats["duplicate"] += 1
            continue
        if not enabled:
            stats["unconfigured"] += 1
            continue
        if ko <= clock():
            stats["expired"] += 1
            continue
        if pace is not None:
            pace()
        if ko <= clock():
            stats["expired"] += 1
            continue
        try:
            mid = sender(message_for_game(row))
            if isinstance(mid,bool) or not isinstance(mid,int):
                raise BotDeliveryError("T05_TELEGRAM_UNCERTAIN_ID")
            entries[key] = {
                "status":"sent", "telegram_message_id":mid,
                "at":now.isoformat(timespec="seconds"),
                "kickoff_utc":row["kickoff_utc"],
                "observed_through":row["observed_through"],
                "candidate_id":CANDIDATE_ID, "rule_version":RULE_VERSION}
            stats["future_sent"] += 1
        except BotDeliveryError:
            # The provider may have delivered despite timeout. NEVER retry
            # automatically; this is an operational/manual delivery review.
            entries[key] = {"status":"delivery_uncertain_manual_review",
                            "at":now.isoformat(timespec="seconds"),
                            "kickoff_utc":row["kickoff_utc"],"rule_version":RULE_VERSION}
            stats["uncertain"] += 1
    return ledger,stats


def _rows(root,now):
    alerts,markets,errors=read_sources(root)
    alerts=[a for a in alerts if utc(a.get("observed_at")) and utc(a["observed_at"])<=now]
    markets=[m for m in markets if utc(m.get("observed_at")) and utc(m["observed_at"])<=now]
    timelines,issues,excluded=collect_timelines(alerts,markets,source_errors=errors)
    return candidates(timelines,now),len(issues),len(excluded)


def run(root=ROOT,now=None,sender=send_message,bot_enabled=None,*,dry_run=False):
    root=Path(root)
    real_clock=now is None
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows,issues,excluded=_rows(root,now)
    path=root/LEDGER
    ledger=json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger(now)
    if dry_run:
        print("MASTER_BRAIN_T05_DRY_RUN","eligible_12h",len(rows),
              "historical_recap_pending","historical:2026-10-28-29" not in ledger["entries"],
              "issues",issues,"excluded",excluded)
        for r in rows:
            print("MATCH",r["match_key"],r["match_label"],r["kickoff_utc"])
        return ledger
    ledger,stats=process(rows,ledger,now,sender,
                          configured() if bot_enabled is None else bot_enabled,
                          pace=lambda:time.sleep(1.2),
                          clock=(lambda:datetime.now(timezone.utc)) if real_clock else (lambda:now))
    _write(path,ledger)
    print("MASTER_BRAIN_T05_EXPERIMENTAL_NOTIFY",stats,
          "timeline_issues",issues,"excluded",excluded,"receipts",len(ledger["entries"]))
    return ledger


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    run(dry_run=args.dry_run)
