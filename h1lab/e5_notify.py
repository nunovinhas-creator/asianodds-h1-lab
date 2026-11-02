"""MASTER BRAIN E5 - Over 2,5 golos. The ONLY active Telegram emitter.

Strategy E5, V5 pattern ``P5-8bced1b27e``::

    {"op": "AND_NOT", "all": ["G_NET_IMPLIED_SMALL"], "none": ["G_FIRST_LEAD_LT_6H"]}

A fixture is E5 at the decision instant ``now`` (real UTC clock) when ALL hold:

1. the V5 engine (``pattern_features.match_features``) yields ``G_NET_IMPLIED_SMALL`` and
   NOT ``G_FIRST_LEAD_LT_6H``, and the V5 net implied-goals change (``net_dlam``, first
   observed ``lam_before`` -> last observed ``lam_after``; the V5 formula, not a new one)
   satisfies ``abs(net) < 0.10`` (strict: 0.1000 is NOT eligible);
2. the first real alert of the fixture was observed at least 6 hours before kickoff, proven
   positively from its own timestamp (``kickoff - first_observed_at >= 6h``), not inferred
   from the absence of a later message;
3. every Total snapshot used is an explicit V4 snapshot (``V4_EXPLICIT``) with a valid implied
   lambda before and after - an H1-legacy-only Total, or an unparseable price, excludes the
   fixture (insufficient evidence, never a guess);
4. the identity is unambiguous (one kickoff, consistent names, no per-message conflict), every
   message was observed before both ``now`` and kickoff, and the match has not started.

No result, FT score or message observed after ``now`` is read. Gaps between messages are never
read as movements. E5 is NOT E2: individual messages may move >= 0.05; only the net matters.

Delivery (reuses ``telegram_delivery``): one alert per fixture and rule version; a sent,
uncertain, rejected-final or expired receipt is never resent. A withdrawal is sent once, only
from NEW valid V4 evidence observed after the alert proving ``abs(net) >= 0.10``, and only
before kickoff. Missing or ambiguous data never withdraws anything.

Durability is MANDATORY for real sends (at-most-once): the intent is published on ``main``
through the collector's selective publisher BEFORE each Telegram request; if that cannot be
done, nothing is sent. Historical rates are exploratory descriptions, never probabilities or
proven profitability.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from . import telegram_delivery as delivery
from .bot import configured, send_message
from .pattern_features import SMALL_NET, match_features, message_metrics
from .strategy_notify import STRATEGIES, _definition_matches, _write
from .timeline import V4, collect_timelines, read_sources, utc

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("data/e5-over25-notifications.json")
RESEARCH = Path("docs/lab/pattern-research.json")
SCHEMA_VERSION = 1
STRATEGY = "E5"
PATTERN_ID = "P5-8bced1b27e"
MARKET = "OVER_2_5"
DEFINITION = {"op": "AND_NOT", "all": ["G_NET_IMPLIED_SMALL"], "none": ["G_FIRST_LEAD_LT_6H"]}
RULE_VERSION = "E5_P5-8bced1b27e_OVER_2_5_V1_20261102"
NET_LIMIT = 0.10
MIN_LEAD = timedelta(hours=6)
MAX_RESEARCH_AGE = timedelta(hours=24)
WITHDRAWN = "|WITHDRAWN"
PACE_SECONDS = 3.0                       # <= 20 messages/minute: safe for groups and private chats
# New E5 alerts only for kickoffs within the next 12 hours (user decision 2026-11-02, after the
# initial all-dates batch). Later games stay pending and are alerted once they enter the window.
# Withdrawals of an alert already sent are not restricted by this window (only before kickoff).
MAX_ALERT_LOOKAHEAD = timedelta(hours=12)
SEND_BUDGET = timedelta(minutes=14)      # time budget per run, NOT a game quota (rest: next cycle)
LISBON = ZoneInfo("Europe/Lisbon")

# The fixed V5 selection in strategy_notify is the source of truth for the E5 definition.
_E5 = next(s for s in STRATEGIES if s["number"] == 5)
assert (_E5["id"], _E5["market"], _E5["definition"]) == (PATTERN_ID, MARKET, DEFINITION)
assert NET_LIMIT == SMALL_NET

ELIGIBLE, NOT_E5, EXCLUDED = "ELIGIBLE", "NOT_E5", "EXCLUDED"


# --------------------------------------------------------------------------- evaluation
def _excluded(base, reason):
    return {**base, "state": EXCLUDED, "reason": reason}


def evaluate(timeline, now):
    """Classify one fixture timeline at ``now``: ELIGIBLE, NOT_E5 (proven) or EXCLUDED (unknown)."""
    if now.tzinfo is None:
        raise ValueError("E5 clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    identity = timeline.get("identity") or {}
    key, label = timeline.get("match_key"), timeline.get("match_label")
    kickoffs = identity.get("kickoff_utc") or []
    base = {"match_key": key, "match_label": label,
            "kickoff_utc": kickoffs[0] if len(kickoffs) == 1 else None}
    if not isinstance(key, str) or not key or not isinstance(label, str) or " vs " not in label:
        return _excluded(base, "IDENTIDADE_INCOMPLETA")
    if not identity.get("team_names_consistent") or identity.get("per_message_conflicts"):
        return _excluded(base, "IDENTIDADE_AMBIGUA")
    if len(kickoffs) != 1 or not identity.get("kickoff_consistent"):
        return _excluded(base, "HORARIO_INCONSISTENTE")
    kickoff = utc(kickoffs[0])
    if kickoff is None:
        return _excluded(base, "HORARIO_INCONSISTENTE")
    base["kickoff_utc"] = kickoff.isoformat()
    if kickoff <= now:
        return _excluded(base, "JOGO_INICIADO_OU_TERMINADO")
    events = timeline.get("events") or []
    if not events:
        return _excluded(base, "SEM_MENSAGENS")
    times = [utc(e.get("observed_at")) for e in events]
    if any(t is None or t > now or t >= kickoff for t in times):
        return _excluded(base, "MENSAGEM_POSTERIOR_A_DECISAO")
    features = match_features(timeline)
    if "excluded" in features:
        return _excluded(base, "V5_" + str(features["excluded"]).upper())
    if utc(features.get("kickoff_utc")) != kickoff:
        return _excluded(base, "HORARIO_INCONSISTENTE")
    if features.get("prekickoff_messages") != len(events):
        return _excluded(base, "MENSAGEM_POSTERIOR_A_DECISAO")
    totals = [e for e in sorted(events, key=lambda e: (e["observed_at"], e["event_id"]))
              if "total" in (e.get("snapshots") or {})]
    if not totals:
        return _excluded(base, "SEM_SNAPSHOT_TOTAL_V4")
    if any(e["snapshots"]["total"].get("origin") != V4 for e in totals):
        return _excluded(base, "SNAPSHOT_TOTAL_NAO_V4")
    metrics = [message_metrics(e) for e in totals]
    if any(m.get("lam_before") is None or m.get("lam_after") is None for m in metrics):
        return _excluded(base, "GOLOS_IMPLICITOS_INVALIDOS")
    net = features.get("net_dlam")
    if (isinstance(net, bool) or not isinstance(net, (int, float)) or not math.isfinite(net) or
            round(metrics[-1]["lam_after"] - metrics[0]["lam_before"], 4) != net):
        return _excluded(base, "INCONSISTENCIA_V5")
    first_at = min(times)
    if utc(features.get("first_observed_at")) != first_at:
        return _excluded(base, "INCONSISTENCIA_V5")
    lead = kickoff - first_at
    patterns = set(features.get("patterns") or ())
    net_small = abs(net) < NET_LIMIT
    if net_small != ("G_NET_IMPLIED_SMALL" in patterns):
        return _excluded(base, "INCONSISTENCIA_V5")
    lead_ok = lead >= MIN_LEAD and "G_FIRST_LEAD_LT_6H" not in patterns
    last_total_at = utc(totals[-1]["observed_at"])
    row = {**base,
           "net_dlam": net, "first_observed_at": first_at.isoformat(),
           "lead_minutes": round(lead.total_seconds() / 60, 2),
           "observed_through": max(times).isoformat(),
           "last_total_observed_at": last_total_at.isoformat(),
           "feature_fingerprint": features.get("fingerprint"),
           "event_ids": [e["event_id"] for e in events],
           "total_messages_v4": len(totals)}
    if lead_ok and net_small and _definition_matches(DEFINITION, patterns):
        return {**row, "state": ELIGIBLE, "reason": "PADRAO_E5_CONFIRMADO"}
    reason = ("VARIACAO_LIQUIDA_IGUAL_OU_SUPERIOR_A_0_10" if not net_small
              else "PRIMEIRO_ALERTA_A_MENOS_DE_6H")
    return {**row, "state": NOT_E5, "reason": reason}


def evaluate_all(timelines, now):
    rows, keys = [], set()
    for timeline in timelines:
        row = evaluate(timeline, now)
        if row["match_key"] in keys and row["match_key"]:
            raise ValueError("duplicate match_key in E5 timelines: " + str(row["match_key"]))
        keys.add(row["match_key"])
        rows.append(row)
    return sorted(rows, key=lambda r: (r.get("kickoff_utc") or "", str(r.get("match_key"))))


# --------------------------------------------------------------------------- history
def _pct(rate):
    value = (Decimal(str(rate)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(value).replace(".", ",") + "%"


def history(research, now):
    """Current V5 descriptive sample for E5 / Over 2,5, or None with the reason."""
    if not isinstance(research, dict):
        return None, "relatório V5 indisponível"
    generated = utc(research.get("generated_at"))
    rows = (research.get("patterns") or []) + (research.get("combinations_top") or [])
    match = [r for r in rows if isinstance(r, dict) and r.get("id") == PATTERN_ID]
    if any(r.get("definition") != DEFINITION for r in match):
        raise ValueError("V5 report publishes a different definition for " + PATTERN_ID)
    if generated is None or generated > now + timedelta(minutes=5) or now - generated > MAX_RESEARCH_AGE:
        return None, "relatório V5 desatualizado"
    outcome = (match[0].get("outcomes") or {}).get(MARKET) if match else None
    keys = ("rate", "known", "hits")
    if not isinstance(outcome, dict) or not all(
            isinstance(outcome.get(k), (int, float)) and not isinstance(outcome.get(k), bool)
            for k in keys) or outcome["known"] <= 0:
        return None, "E5 não consta do relatório V5 atual"
    return {"hits": int(outcome["hits"]), "known": int(outcome["known"]), "rate": outcome["rate"],
            "generated_at": generated.isoformat()}, None


# --------------------------------------------------------------------------- messages
def _signed(net):
    text = format(Decimal(str(net)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "+.4f")
    return text.replace(".", ",")


def _hours(minutes):
    value = (Decimal(str(minutes)) / 60).quantize(Decimal("0.1"), rounding=ROUND_FLOOR)
    return str(value).replace(".", ",")


def _local(moment):
    return utc(moment).astimezone(LISBON).strftime("%d/%m/%Y %H:%M")


def message_for_game(row, hist, unavailable=None):
    if row.get("state") != ELIGIBLE or not row.get("match_label") or utc(row.get("kickoff_utc")) is None:
        raise ValueError("invalid E5 alert")
    if hist:
        record = ("📈 Histórico V5: %d/%d (%s) — exploratório, não é probabilidade garantida "
                  "nem rentabilidade comprovada" % (hist["hits"], hist["known"], _pct(hist["rate"])))
    else:
        record = "📈 Histórico V5: indisponível (%s); sem valor certificado" % (
            unavailable or "não publicado")
    lines = ["🧠 MASTER BRAIN | E5 — OVER 2,5", "",
             "⚽ " + row["match_label"],
             "🕒 " + _local(row["kickoff_utc"]) + " (Portugal)", "",
             "🎯 PADRÃO E5 CONFIRMADO", "",
             "📊 Variação dos golos implícitos: " + _signed(row["net_dlam"]),
             "⏱️ Primeiro alerta: " + _hours(row["lead_minutes"]) + " horas antes do jogo",
             record, "",
             "🆔 " + PATTERN_ID]
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > 4096:
        raise ValueError("E5 message exceeds 4096 bytes")
    return text


def withdrawal_message(row):
    if row.get("state") != NOT_E5 or not row.get("match_label"):
        raise ValueError("invalid E5 withdrawal")
    lines = ["🧠 MASTER BRAIN | E5 — OVER 2,5", "",
             "⚽ " + row["match_label"],
             "🕒 " + _local(row["kickoff_utc"]) + " (Portugal)", "",
             "❌ PADRÃO E5 RETIRADO", "",
             "📊 Variação dos golos implícitos: " + _signed(row["net_dlam"]) +
             " (limite E5: inferior a 0,10 em valor absoluto)",
             "🕑 Nova evidência V4: " + _local(row["last_total_observed_at"]) + " (Portugal)", "",
             "🆔 " + PATTERN_ID]
    return "\n".join(lines)


def proven_withdrawal(row, entry):
    """Only fresh, valid V4 evidence observed AFTER the alert proves the pattern left E5."""
    if row.get("state") != NOT_E5 or row.get("reason") != "VARIACAO_LIQUIDA_IGUAL_OU_SUPERIOR_A_0_10":
        return False
    if not isinstance(entry, dict) or entry.get("status") != delivery.SENT:
        return False
    previous = utc(entry.get("observed_through"))
    fresh = utc(row.get("last_total_observed_at"))
    net = row.get("net_dlam")
    return (previous is not None and fresh is not None and fresh > previous and
            isinstance(net, (int, float)) and not isinstance(net, bool) and abs(net) >= NET_LIMIT)


# --------------------------------------------------------------------------- ledger
def empty_ledger(now):
    return {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION,
            "strategy": STRATEGY, "rule_id": PATTERN_ID, "market": MARKET,
            "definition": DEFINITION,
            "activated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "entries": {}}


def _valid_ledger(ledger):
    return (isinstance(ledger, dict) and ledger.get("schema_version") == SCHEMA_VERSION and
            ledger.get("rule_version") == RULE_VERSION and isinstance(ledger.get("entries"), dict))


def process(rows, ledger, now, sender, enabled, *, research=None, pace=None, clock=None,
            persist=None, store=None, budget=SEND_BUDGET):
    """Send every pending E5 alert (all future dates, no game quota) and proven withdrawals."""
    if not _valid_ledger(ledger):
        raise ValueError("invalid E5 ledger; nothing sent")
    if now.tzinfo is None:
        raise ValueError("E5 clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    clock = clock or (lambda: now)
    hist, unavailable = history(research, now)
    eligible = [r for r in rows if r["state"] == ELIGIBLE]
    stats = {"eligible_future": len(eligible), "sent": 0, "withdrawals_sent": 0,
             "already_notified": 0, "unconfigured": 0, "expired": 0, "uncertain": 0,
             "deferred_time_budget": 0, "deferred_beyond_12h": 0}
    store = store or delivery.default_store()
    delivery.sweep(ledger, clock(), stats)
    started, attempts = clock(), 0
    for row in sorted(rows, key=lambda r: (r.get("kickoff_utc") or "", str(r["match_key"]))):
        if row["state"] == ELIGIBLE:
            key, kind = row["match_key"], "ENTERED"
            ko = utc(row["kickoff_utc"])
            if (ko is not None and ko > now + MAX_ALERT_LOOKAHEAD and
                    row["match_key"] not in ledger["entries"]):
                stats["deferred_beyond_12h"] += 1
                continue
        elif proven_withdrawal(row, ledger["entries"].get(row["match_key"])):
            key, kind = row["match_key"] + WITHDRAWN, "WITHDRAWN"
        else:
            continue
        kickoff = utc(row["kickoff_utc"])
        if kickoff is None or kickoff <= now:
            stats["expired"] += 1
            continue
        if delivery.gate(ledger, key, kickoff, clock(), stats) == "skip":
            continue
        try:
            if delivery.blocked(store, clock()):
                delivery._bump(stats, "suspended")
                continue
        except ValueError:
            delivery._bump(stats, "block_unreadable")
            print("TELEGRAM_BLOCK_UNREADABLE", file=sys.stderr)
            break
        if not enabled:
            stats["unconfigured"] += 1
            continue
        if budget is not None and clock() - started >= budget:
            stats["deferred_time_budget"] += 1
            continue
        if attempts and pace is not None:
            pace()
        if kickoff <= clock():          # never alert or withdraw a game that has started
            stats["expired"] += 1
            continue
        attempts += 1
        if kind == "ENTERED":
            text = message_for_game(row, hist, unavailable)
            history_note = ({"history_v5": hist} if hist else
                            {"history_v5_unavailable": unavailable})
        else:
            text = withdrawal_message(row)
            history_note = {"entry_message_id": ledger["entries"][row["match_key"]].get(
                "telegram_message_id")}
        base = {"match_key": row["match_key"], "match_label": row["match_label"],
                "kickoff_utc": row["kickoff_utc"], "rule_version": RULE_VERSION,
                "strategy": STRATEGY, "rule_id": PATTERN_ID, "market": MARKET,
                "transition": kind, "reason": row["reason"], "net_dlam": row["net_dlam"],
                "first_observed_at": row["first_observed_at"],
                "lead_minutes": row["lead_minutes"],
                "observed_through": row["observed_through"],
                "last_total_observed_at": row["last_total_observed_at"],
                "feature_fingerprint": row["feature_fingerprint"],
                "event_ids": row["event_ids"], "decided_at": now.isoformat(timespec="seconds"),
                **history_note}
        outcome = delivery.deliver(ledger, key, sender, text, base, {}, clock, persist, stats, store)
        if outcome == "sent" and kind == "WITHDRAWN":
            stats["sent"] -= 1
            stats["withdrawals_sent"] += 1
        if outcome == "stop":
            break
    return ledger, stats


# --------------------------------------------------------------------------- I/O
def load_rows(root, now):
    alerts, markets, errors = read_sources(root)
    # Nothing observed after the decision instant may influence it.
    alerts = [a for a in alerts if utc(a.get("observed_at")) and utc(a["observed_at"]) <= now]
    markets = [m for m in markets if utc(m.get("observed_at")) and utc(m["observed_at"]) <= now]
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    return evaluate_all(timelines, now), len(issues), len(excluded)


def _research(root):
    try:
        return json.loads((Path(root) / RESEARCH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summary(rows, ledger):
    future = [r for r in rows if r["reason"] != "JOGO_INICIADO_OU_TERMINADO"]
    return {"timelines": len(rows), "future_or_unknown_time": len(future),
            "eligible": sum(r["state"] == ELIGIBLE for r in rows),
            "pending": sum(r["state"] == ELIGIBLE and r["match_key"] not in ledger["entries"]
                           for r in rows),
            "reasons_future": dict(Counter(r["reason"] for r in future)),
            "reasons_all": dict(Counter(r["reason"] for r in rows))}


def print_rows(rows, ledger, tag):
    for row in rows:
        if row["reason"] == "JOGO_INICIADO_OU_TERMINADO":
            continue
        entry = ledger["entries"].get(row["match_key"]) or {}
        print(tag, json.dumps({
            "state": row["state"], "reason": row["reason"], "match": row["match_label"],
            "kickoff_pt": _local(row["kickoff_utc"]) if row.get("kickoff_utc") else None,
            "net_dlam": row.get("net_dlam"),
            "lead_hours": round(row["lead_minutes"] / 60, 2) if row.get("lead_minutes") else None,
            "receipt": entry.get("status")}, ensure_ascii=False))


def run(root=ROOT, now=None, sender=send_message, bot_enabled=None, *, dry_run=False,
        publisher=None):
    root = Path(root)
    realtime = now is None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows, issues, excluded = load_rows(root, now)
    path = root / LEDGER
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger(now)
    research = _research(root)
    head = summary(rows, ledger)
    print("MASTER_BRAIN_E5_EVALUATION", json.dumps({
        "now_utc": now.isoformat(timespec="seconds"), **head, "timeline_issues": issues,
        "excluded_observations": excluded}, ensure_ascii=False, sort_keys=True))
    print_rows(rows, ledger, "E5_DRY_RUN_ROW" if dry_run else "E5_ROW")
    if dry_run:
        hist, unavailable = history(research, now)
        for row in rows:
            if (row["state"] == ELIGIBLE and row["match_key"] not in ledger["entries"] and
                    utc(row["kickoff_utc"]) <= now + MAX_ALERT_LOOKAHEAD):
                print("E5_DRY_RUN_MESSAGE\n" + message_for_game(row, hist, unavailable))
        return ledger, head
    enabled = configured() if bot_enabled is None else bot_enabled
    if publisher is None and enabled:
        from scripts.collect_publish_safe import e5_receipt_publisher
        publisher = e5_receipt_publisher(root)
    if enabled and publisher is None:
        raise RuntimeError("E5_DURABILITY_UNAVAILABLE: no message sent")
    state = {"dirty": False, "last_send": None}

    def pace():
        """At least PACE_SECONDS between two Telegram requests (publication time counts)."""
        if state["last_send"] is not None:
            time.sleep(max(0.0, PACE_SECONDS - (time.monotonic() - state["last_send"])))

    def paced_sender(text):
        try:
            return sender(text)
        finally:
            state["last_send"] = time.monotonic()

    def persist(value):
        _write(path, value)
        if delivery.has_intent(value):
            publisher(final=False)       # intent on main BEFORE the HTTP request (fail closed)
            state["dirty"] = False
        else:
            state["dirty"] = True        # outcome travels with the next intent or the final flush

    ledger, stats = process(rows, ledger, now, paced_sender, enabled, research=research,
                            pace=pace,
                            clock=(lambda: datetime.now(timezone.utc)) if realtime else (lambda: now),
                            persist=persist if publisher is not None else None)
    _write(path, ledger)
    if publisher is not None:            # outcomes and sweeps; a no-op when nothing changed
        try:
            publisher(final=True)
        except delivery.IntentNotDurable as exc:
            delivery._bump(stats, "publish_failed")
            print("E5_FINAL_RECEIPTS_NOT_PUBLISHED", str(exc)[:200], file=sys.stderr)
    print("MASTER_BRAIN_E5_NOTIFY", json.dumps(stats, sort_keys=True),
          "receipts", len(ledger["entries"]))
    for key, entry in sorted(ledger["entries"].items()):
        if entry.get("decided_at") == now.isoformat(timespec="seconds"):
            print("E5_RECEIPT", json.dumps({"key": key, "status": entry.get("status"),
                                            "telegram_message_id": entry.get("telegram_message_id"),
                                            "match": entry.get("match_label"),
                                            "transition": entry.get("transition")},
                                           ensure_ascii=False))
    if stats.get("intent_not_durable") or stats.get("publish_failed"):
        raise SystemExit("E5_RECEIPT_DURABILITY_FAILED: see stats above")
    return ledger, stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="no Telegram, no ledger writes")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
