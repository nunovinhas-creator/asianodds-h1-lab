"""Send ONLY the five explicitly selected MASTER BRAIN V5 strategies.

No use of historical match outcomes to determine eligibility. All matching facts
come from V5's actual pre-kickoff message->snapshot->match feature engine.

This is an exploratory watch, NOT a validated prediction, pick, or ROI claim.
The retired generic Pattern Watch notifier has its own untouched legacy ledger.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .bot import BotDeliveryError, configured, send_message
from .pattern_features import FEATURE_VERSION, match_features
from .timeline import collect_timelines, read_sources, utc

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("data/strategy-notifications.json")
RESEARCH = Path("docs/lab/pattern-research.json")
SCHEMA_VERSION = 1
RULE_VERSION = "SELECTED_V5_FIVE_20261029"
MARKETS = {"OVER_2_5": "OVER 2,5 GOLOS", "BTTS_YES": "AMBAS MARCAM"}
MAX_RESEARCH_AGE = timedelta(hours=24)

# Explicit fixed selection. Do NOT re-rank from the exploratory leader board.
# IDs and predicates are taken from the published V5 catalogue on 2026-10-29.
STRATEGIES = (
    {"number": 1, "id": "P5-e9298e23d3", "market": "OVER_2_5",
     "definition": {"op": "HAS", "a": "M_AH_TOWARD_AWAY"},
     "label": "Linha AH sobe: equipa da casa menos favorecida"},
    {"number": 2, "id": "P5-8d66f63e92", "market": "OVER_2_5",
     "definition": {"op": "AND_NOT", "all": ["M_IMPLIED_GOALS_FLAT"], "none": ["G_FIRST_LEAD_LT_6H"]},
     "label": "Golos implícitos estáveis (<0,05) + primeiro alerta há pelo menos 6 horas"},
    {"number": 3, "id": "P5-8d66f63e92", "market": "BTTS_YES",
     "definition": {"op": "AND_NOT", "all": ["M_IMPLIED_GOALS_FLAT"], "none": ["G_FIRST_LEAD_LT_6H"]},
     "label": "Golos implícitos estáveis (<0,05) + primeiro alerta há pelo menos 6 horas"},
    {"number": 4, "id": "P5-d92fc19ce8", "market": "OVER_2_5",
     "definition": {"op": "AND_NOT", "all": ["G_LAST_LINE_HIGH"], "none": ["G_WEAKENING"]},
     "label": "Última linha Total ≥3,25 + sem enfraquecimento do último episódio"},
    {"number": 5, "id": "P5-8bced1b27e", "market": "OVER_2_5",
     "definition": {"op": "AND_NOT", "all": ["G_NET_IMPLIED_SMALL"], "none": ["G_FIRST_LEAD_LT_6H"]},
     "label": "Variação líquida dos golos implícitos <0,10 + primeiro alerta há pelo menos 6 horas"},
)
assert tuple(x["number"] for x in STRATEGIES) == (1, 2, 3, 4, 5)
assert len({(x["id"], x["market"]) for x in STRATEGIES}) == 5


def _definition_matches(definition, hits):
    """Use V5's membership semantics, including NOT for explicitly absent hits."""
    operation = definition.get("op")
    if operation == "HAS":
        return definition["a"] in hits
    if operation == "AND":
        return all(x in hits for x in definition["all"])
    if operation == "AND_NOT":
        return (all(x in hits for x in definition["all"])
                and all(x not in hits for x in definition["none"]))
    raise ValueError("unsupported V5 definition")


def _validate_catalogue(research, now):
    """Prevent a silently changed historical definition being called the same strategy."""
    if not isinstance(research, dict) or not isinstance(research.get("patterns"), list) or not isinstance(research.get("combinations_top"), list):
        raise ValueError("V5 research report missing or malformed")
    generated = utc(research.get("generated_at"))
    if generated is None or generated > now + timedelta(minutes=5) or now - generated > MAX_RESEARCH_AGE:
        raise ValueError("V5 research is missing a recent valid publication timestamp")
    published = research["patterns"] + research["combinations_top"]
    mapping = {}
    for row in published:
        ident = row.get("id")
        if ident in mapping and mapping[ident].get("definition") != row.get("definition"):
            raise ValueError("conflicting V5 pattern definitions")
        mapping[ident] = row
    for rule in STRATEGIES:
        present = mapping.get(rule["id"])
        if present is not None and present.get("definition") != rule["definition"]:
            raise ValueError("selected V5 strategy definition changed: " + rule["id"])
    return mapping


def _observed_explicit(timeline, pattern):
    """The positive market condition must have V4 evidence, not a guessed price."""
    events = timeline.get("events") or []
    if pattern == "M_AH_TOWARD_AWAY":
        return any(e.get("snapshots", {}).get("asian_handicap", {}).get("origin") == "V4_EXPLICIT"
                   and e["snapshots"]["asian_handicap"]["after"]["line"] >
                       e["snapshots"]["asian_handicap"]["before"]["line"]
                   for e in events)
    if pattern == "M_IMPLIED_GOALS_FLAT":
        from .pattern_features import message_metrics
        return any(e.get("snapshots", {}).get("total", {}).get("origin") == "V4_EXPLICIT"
                   and "M_IMPLIED_GOALS_FLAT" in message_metrics(e)["patterns"]
                   for e in events)
    if pattern == "G_LAST_LINE_HIGH":
        totals = [e["snapshots"]["total"] for e in events if "total" in e.get("snapshots", {})]
        return bool(totals and totals[-1]["origin"] == "V4_EXPLICIT"
                    and totals[-1]["after"]["line"] >= 3.25)
    if pattern == "G_NET_IMPLIED_SMALL":
        from .pattern_features import message_metrics
        totals = [e for e in events if "total" in e.get("snapshots", {})]
        if not totals or totals[0]["snapshots"]["total"].get("origin") != "V4_EXPLICIT" or \
                totals[-1]["snapshots"]["total"].get("origin") != "V4_EXPLICIT":
            return False
        first, last = message_metrics(totals[0]), message_metrics(totals[-1])
        return first.get("lam_before") is not None and last.get("lam_after") is not None
    return False


def _sufficient_evidence(timeline, features, rule):
    """Negative episode statement is unknown when lambda for the episodes is missing."""
    if any(x not in features["patterns"] for x in rule["definition"].get("all", ())):
        return False
    positive = rule["definition"].get("a") or rule["definition"]["all"][0]
    if not _observed_explicit(timeline, positive):
        return False
    if "G_WEAKENING" in rule["definition"].get("none", ()):
        from .pattern_features import message_metrics
        episode_of = {eid: n for n, group in enumerate(timeline.get("movement_episodes") or ())
                      for eid in group}
        representatives = {}
        for event in timeline.get("events") or ():
            ep = episode_of.get(event["event_id"], event["event_id"])
            representatives.setdefault(ep, event)
        if len(representatives) >= 2 and any(
                message_metrics(e).get("dlam") is None for e in representatives.values()):
            return False
    return True


def candidate_matches(timelines, now, research):
    """Eligible future games, including those detected earlier today.

    Each candidate is identified by an actual match_key, a frozen list of strategy
    numbers and message timestamps observed no later than this run.
    """
    catalogue = _validate_catalogue(research, now)
    out = []
    used = set()
    for timeline in timelines:
        ko_list = (timeline.get("identity") or {}).get("kickoff_utc") or []
        if len(ko_list) != 1:
            continue
        kickoff = utc(ko_list[0])
        if kickoff is None or kickoff <= now:
            continue  # Never send today's already-started matches as live picks.
        events = timeline.get("events") or []
        if not events or any(utc(e.get("observed_at")) is None or
                             utc(e["observed_at"]) > now or utc(e["observed_at"]) >= kickoff
                             for e in events):
            continue
        f = match_features(timeline)
        if "excluded" in f or f.get("kickoff_utc") != ko_list[0]:
            continue
        key = f["match_key"]
        if key in used:
            raise ValueError("duplicate match_key in MASTER BRAIN strategy notifier")
        used.add(key)
        hits = set(f["patterns"])
        matched = []
        for rule in STRATEGIES:
            if not _definition_matches(rule["definition"], hits):
                continue
            if not _sufficient_evidence(timeline, f, rule):
                continue
            h = catalogue.get(rule["id"])
            observed = h.get("outcomes", {}).get(rule["market"]) if h else None
            # Even if historical top-N catalogue no longer includes this pattern,
            # the FIXED rule remains active, with no invented historical rate.
            history = None
            if isinstance(observed, dict) and all(isinstance(observed.get(k), (int, float)) for k in
                ("rate", "known", "hits", "reference_rate", "reference_known")):
                history = {k: observed[k] for k in ("rate", "known", "hits", "reference_rate", "reference_known")}
            matched.append({**rule, "history": history})
        if matched:
            out.append({
                "match_key": key, "match_label": f["match_label"],
                "kickoff_utc": f["kickoff_utc"], "observed_through": f["decision_at"],
                "feature_version": f["feature_version"], "fingerprint": f["fingerprint"],
                "rules": matched, "research_generated_at": research["generated_at"],
            })
    return sorted(out, key=lambda x: (x["kickoff_utc"], x["match_key"]))


def _pct(n):
    return ("%0.1f" % (100 * n)).replace(".", ",") + "%"


def message_for_game(row, rules):
    """One Telegram message per match with DISTINCT numbered market sections."""
    kickoff = utc(row.get("kickoff_utc"))
    observed = utc(row.get("observed_through"))
    if not kickoff or not observed or observed >= kickoff or not rules or not row.get("match_label"):
        raise ValueError("invalid prospective strategy match")
    when = kickoff.astimezone(ZoneInfo("Europe/Lisbon"))
    lines = [
        "🧠 MASTER BRAIN | 5 ESTRATÉGIAS V5",
        "⚽ " + row["match_label"],
        "🕒 " + when.strftime("%d/%m/%Y %H:%M") + " (Portugal continental)",
        "📍 " + str(len(rules)) + " estratégia(s) identificada(s)",
    ]
    for rule in sorted(rules, key=lambda x: x["number"]):
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━",
            "🎯 ESTRATÉGIA " + str(rule["number"]) + "/5 — " + MARKETS[rule["market"]],
            "🔎 " + rule["label"],
        ])
        h = rule.get("history")
        if h:
            lines.append("📊 Histórico V5: " + str(int(h["hits"])) + "/" + str(int(h["known"]))
                         + " (" + _pct(h["rate"]) + ") vs "
                         + _pct(h["reference_rate"]) + " (" + str(int(h["reference_known"]))
                         + " jogos de comparação)")
        else:
            lines.append("📊 Histórico: dados publicados insuficientes para este cartão.")
        lines.append("🆔 " + rule["id"])
    lines += [
        "",
        "🧾 Observações até " + observed.astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d/%m %H:%M")
        + " (Portugal). As condições podem mudar com novos alertas pré-jogo.",
        "⚠️ Padrões EXPLORATÓRIOS, não validados em novos jogos. Taxas históricas ≠ probabilidade futura/ROI; sem odds de entrada.",
        "🔗 https://nunovinhas-creator.github.io/asianodds-h1-lab/brain-preview.html",
    ]
    result = "\n".join(lines)
    if len(result.encode("utf-8")) > 4096:
        raise ValueError("Telegram strategy message exceeds 4096 bytes")
    return result


def empty_ledger(now):
    return {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION,
            "activated_at": now.isoformat(timespec="seconds"), "entries": {}}


def process(rows, ledger, now, sender, enabled):
    if (not isinstance(ledger, dict) or ledger.get("schema_version") != SCHEMA_VERSION or
            ledger.get("rule_version") != RULE_VERSION or not isinstance(ledger.get("entries"), dict)):
        raise ValueError("invalid V5 strategy notification receipt ledger; no messages sent")
    counts = {"games_with_strategies": len(rows), "strategies_matched": sum(len(r["rules"]) for r in rows),
              "games_sent": 0, "strategy_receipts": 0, "already_notified": 0, "unconfigured": 0,
              "failed": 0, "expired": 0}
    for row in rows:
        if utc(row["kickoff_utc"]) <= now:
            counts["expired"] += 1
            continue
        fresh = [r for r in row["rules"] if row["match_key"] + "|" + str(r["number"]) not in ledger["entries"]]
        counts["already_notified"] += len(row["rules"]) - len(fresh)
        if not fresh:
            continue
        if not enabled:
            counts["unconfigured"] += len(fresh)
            continue
        msg = message_for_game(row, fresh)
        keys = [row["match_key"] + "|" + str(r["number"]) for r in fresh]
        for k, rule in zip(keys, fresh):
            ledger["entries"][k] = {
                "status": "delivery_uncertain", "detected_at": now.isoformat(timespec="seconds"),
                "match_key": row["match_key"], "kickoff_utc": row["kickoff_utc"],
                "observed_through": row["observed_through"], "feature_fingerprint": row["fingerprint"],
                "strategy": rule["number"], "rule_id": rule["id"], "market": rule["market"],
                "rule_version": RULE_VERSION,
            }
        try:
            mid = sender(msg)
            if isinstance(mid, bool) or not isinstance(mid, int):
                raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: missing message ID")
            for k in keys:
                ledger["entries"][k]["status"] = "sent"
                ledger["entries"][k]["telegram_message_id"] = mid
            counts["games_sent"] += 1
            counts["strategy_receipts"] += len(fresh)
        except BotDeliveryError:
            for k in keys:
                ledger["entries"][k]["status"] = "delivery_uncertain_manual_review"
            counts["failed"] += 1
    return ledger, counts


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run(root=ROOT, now=None, sender=send_message, bot_enabled=None):
    root = Path(root)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    research = json.loads((root / RESEARCH).read_text(encoding="utf-8"))
    alerts, markets, errors = read_sources(root)
    # Rebuild timeline AS OF the collection's current clock, so future messages
    # cannot influence a classification. Never reuse post-kickoff outcomes.
    alerts = [a for a in alerts if utc(a.get("observed_at")) and utc(a["observed_at"]) <= now]
    markets = [a for a in markets if utc(a.get("observed_at")) and utc(a["observed_at"]) <= now]
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    rows = candidate_matches(timelines, now, research)
    path = root / LEDGER
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger(now)
    ledger, stats = process(rows, ledger, now, sender, configured() if bot_enabled is None else bot_enabled)
    _write(path, ledger)
    print("MASTER_BRAIN_FIVE_STRATEGIES_NOTIFY", stats,
          "timeline_issues", len(issues), "excluded_observations", len(excluded),
          "historical_receipts", len(ledger["entries"]))
    return ledger


if __name__ == "__main__":
    run()
