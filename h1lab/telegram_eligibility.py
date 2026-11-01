"""Read-only explanations for Telegram eligibility, using the live sender rules.

This is not a second alert engine: classifications are checked against the
actual senders' candidate sets and fail closed on any discrepancy.
Never sends Telegram messages or alters H1 / FT / notification ledgers.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import three_moves_notify, two_up_notify
from .timeline import (DEFAULT_MAX_TIMELINES, collect_timelines,
                       read_sources, utc)

SCHEMA = 1
MAX_REPORT_BYTES = 250_000
AMBIGUOUS = {"SAME_MOVEMENT_REPEAT", "AMBIGUOUS_REPEAT_OR_REVERSAL"}


def evidence(timeline, now):
    """Classify each observation with the exact filters used by both senders."""
    key = timeline["match_key"]
    identity = timeline.get("identity") or {}
    ko_list = identity.get("kickoff_utc") or []
    identity_ok = (len(ko_list) == 1 and identity.get("team_names_consistent")
                   and identity.get("kickoff_consistent")
                   and not identity.get("per_message_conflicts"))
    ko = utc(ko_list[0]) if len(ko_list) == 1 else None
    future = bool(identity_ok and ko and ko > now)
    total = (timeline.get("trajectory") or {}).get("total") or {}
    transitions = {x.get("to"): x.get("line") for x in total.get("transitions") or []}
    episodes = {event_id: group[0]
                for group in timeline.get("movement_episodes") or []
                for event_id in group}
    redundant = set(timeline.get("possibly_redundant_event_ids") or [])
    times = {e.get("event_id"): utc(e.get("observed_at"))
             for e in timeline.get("events") or []}
    three_accepted, two_ups = [], []
    used_three, used_two = set(), set()
    rejected = Counter()
    raw_nonflat = raw_ups = 0
    down_observed = False
    for point in total.get("points") or []:
        eid = point.get("event_id")
        at = times.get(eid)
        direction = point.get("move")
        if not at or at > now or (ko and at >= ko):
            rejected["outside_decision_window"] += 1
            continue
        if point.get("origin") != "V4_EXPLICIT":
            rejected["not_explicit_v4"] += 1
            continue
        if direction == "FLAT":
            rejected["flat_total_line"] += 1
            continue
        if direction not in ("UP", "DOWN"):
            rejected["invalid_direction"] += 1
            continue
        raw_nonflat += 1
        if direction == "UP":
            raw_ups += 1
        if direction == "DOWN":
            down_observed = True
        if transitions.get(eid) in AMBIGUOUS:
            rejected["ambiguous_transition"] += 1
            continue
        if eid in redundant:
            rejected["suspected_duplicate"] += 1
            continue
        before, after = point.get("before"), point.get("after")
        if (not isinstance(before, (int, float)) or isinstance(before, bool)
                or not isinstance(after, (int, float)) or isinstance(after, bool)
                or before == after):
            rejected["invalid_line"] += 1
            continue
        episode = episodes.get(eid, eid)
        # The two senders deduplicate independently: a DOWN in an episode
        # must not consume an UP candidate for the separate two-rise rule.
        if direction == "UP" and episode not in used_two:
            two_ups.append(point)
            used_two.add(episode)
        if episode in used_three:
            rejected["same_episode"] += 1
            continue
        used_three.add(episode)
        three_accepted.append(point)

    count_three = len(three_accepted)
    count_up = len(two_ups)
    net_up = (two_ups[-1]["after"] - two_ups[0]["before"]) if two_ups else 0
    three_ok = future and bool(key) and " vs " in (timeline.get("match_label") or "") and count_three >= 3
    two_ok = (future and bool(key) and " vs " in (timeline.get("match_label") or "")
              and not down_observed and count_up >= 2 and net_up + 1e-9 >= .50)
    if not identity_ok:
        cause = "Identidade ou hora de início incoerente"
    elif not ko:
        cause = "Hora de início não comprovada"
    elif not future:
        cause = "Jogo já iniciado; não são emitidos alertas retroativos"
    elif not total.get("points"):
        cause = "Sem observações da linha Total"
    elif count_three < 3 and count_up < 2:
        cause = "Movimentos V4 independentes insuficientes"
    elif not two_ok and down_observed:
        cause = "A regra das subidas exclui descidas V4 observadas"
    elif not two_ok and count_up >= 2:
        cause = "Subida líquida inferior a 0,50"
    else:
        cause = "Elegibilidade avaliada separadamente por regra"
    # Review priority is a potential false negative, NOT proof of independence.
    review = bool(future and ((raw_nonflat >= 3 and count_three < 3) or
                              (raw_ups >= 2 and count_up < 2)))
    return {
        "match_key": key, "match_label": timeline.get("match_label"),
        "kickoff_utc": ko.isoformat() if ko else None,
        "observed_messages": timeline.get("event_count", 0),
        "v4_moves_observed": raw_nonflat, "valid_three_moves": count_three,
        "v4_up_observed": raw_ups, "valid_up_moves": count_up,
        "net_up": round(net_up, 3), "v4_down_observed": down_observed,
        "three_eligible": bool(three_ok), "two_eligible": bool(two_ok),
        "rejects": dict(rejected), "reason": cause,
        "review_possible_false_negative": review,
        "review_note": ("Repetição/ambiguidade requer prova adicional; não é "
                        "autorização para enviar" if review else None),
    }


def _ledger(root, path, version):
    file = root / path
    if not file.exists():
        return {}
    data = json.loads(file.read_text(encoding="utf-8"))
    if (data.get("schema_version") != 1 or data.get("rule_version") != version
            or not isinstance(data.get("entries"), dict)):
        raise ValueError("Telegram receipt ledger is invalid: " + str(path))
    return data["entries"]


def build(timelines, now, receipts_three=None, receipts_two=None,
          *, published_limit=DEFAULT_MAX_TIMELINES, source_errors=0, source_commit="unknown"):
    if now.tzinfo is None:
        raise ValueError("Audit clock requires timezone")
    now = now.astimezone(timezone.utc)
    receipts_three = receipts_three or {}
    receipts_two = receipts_two or {}
    actual_three = {x["match_key"] for x in three_moves_notify.candidates(timelines, now)}
    actual_two = {x["match_key"] for x in two_up_notify.candidates(timelines, now)}
    statuses = {}
    repeated = [x for x in timelines if x.get("event_count", 0) > 1]
    repeated.sort(key=lambda x: (x["last_observed_at"], x["match_key"]), reverse=True)
    for t in timelines:
        row = evidence(t, now)
        key = row["match_key"]
        if row["three_eligible"] != (key in actual_three) or row["two_eligible"] != (key in actual_two):
            raise ValueError("Telegram eligibility parity mismatch for match " + str(key))
        if t.get("event_count", 0) <= 1:
            continue
        delivered = {}
        for label, ledger in (("three", receipts_three), ("two", receipts_two)):
            entry = ledger.get(key)
            if entry is not None:
                status = entry.get("status")
                if status not in ("sent", "delivery_uncertain_manual_review"):
                    raise ValueError("Unknown receipt status: " + str(status))
                delivered[label] = {"status": status,
                                    "telegram_message_id": entry.get("telegram_message_id")}
        row["receipts"] = delivered
        statuses[key] = row
    games = {t["match_key"]: statuses[t["match_key"]] for t in repeated[:published_limit]}
    summary = {
        "future_three_eligible": len(actual_three),
        "future_two_eligible": len(actual_two),
        "visible_games": len(games),
        "future_visible_exclusions": sum(
            bool(x["kickoff_utc"] and utc(x["kickoff_utc"]) > now
                 and not x["three_eligible"] and not x["two_eligible"])
            for x in games.values()),
        "review_possible_false_negative": sum(x["review_possible_false_negative"]
                                               for x in games.values()),
        "v4_source_errors": source_errors,
    }
    return {
        "schema_version": SCHEMA, "status": "READ_ONLY_PARITY_VERIFIED_NOT_DELIVERY_PROOF",
        "generated_at": now.isoformat(timespec="seconds"),
        "source_commit": source_commit,
        "rules": {"three": three_moves_notify.RULE_VERSION,
                  "two": two_up_notify.RULE_VERSION},
        "summary": summary, "games": games,
        "limitations": ("Apenas informação observada até à geração; recibos não "
                        "certificam a receção no dispositivo. Histórico não é "
                        "reconstituído como previsão retroativa."),
    }


def publish(root, now=None, source_commit="unknown"):
    root = Path(root)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    alerts, markets, errors = read_sources(root)
    alerts = [x for x in alerts if utc(x.get("observed_at")) and utc(x["observed_at"]) <= now]
    markets = [x for x in markets if utc(x.get("observed_at")) and utc(x["observed_at"]) <= now]
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    if excluded:
        # Explicitly report exclusions; never silently treat corrupt source as zero.
        print("TELEGRAM_ELIGIBILITY_EXCLUDED_SOURCE", len(excluded))
    report = build(
        timelines, now,
        _ledger(root, three_moves_notify.LEDGER, three_moves_notify.RULE_VERSION),
        _ledger(root, two_up_notify.LEDGER, two_up_notify.RULE_VERSION),
        source_errors=len(issues) + len(excluded), source_commit=source_commit,
    )
    encoded = (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Telegram eligibility report exceeds 250 KB; refuse truncation")
    output = root / "docs/lab/telegram-eligibility.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".tmp").write_text(encoded, encoding="utf-8")
    output.with_suffix(".tmp").replace(output)
    print("TELEGRAM_ELIGIBILITY_AUDIT", report["summary"])
    return report
