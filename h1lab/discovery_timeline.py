"""MASTER BRAIN discovery chronology (read-only, independent of H1).

Only published V5 patterns are tracked. Events are changes in evidence, not
betting signals. The full event ledger is append-only in monthly JSONL files;
the state and public JSON contain bounded caches for efficient GitHub Pages.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

SCHEMA = 1
TARGETS = ("OVER_2_5", "BTTS_YES")
STATES = {"EXPLORATORIO", "CANDIDATO", "EM_VALIDACAO", "VALIDADO", "REJEITADO"}
IMPORTANT = {"CANDIDATO": "CANDIDATE", "VALIDADO": "VALIDATED", "REJEITADO": "REJECTED"}
MAX_POINTS = 24
MAX_FEED = 90


def _iso(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError, AttributeError):
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:16]


def _round_delta(value):
    return round(value, 4) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _published(report):
    rows = (report.get("patterns") or []) + (report.get("combinations_top") or []) + (report.get("frozen") or [])
    result = {}
    for h in rows:
        if not h.get("id") or not isinstance(h.get("outcomes"), dict):
            continue
        for target in TARGETS:
            o = h["outcomes"].get(target)
            if not isinstance(o, dict):
                continue
            key = h["id"] + "|" + target
            result[key] = {
                "id": h["id"], "label": h.get("label", h["id"]),
                "target": target, "state": h.get("state", "EXPLORATORIO"),
                "definition": h.get("definition"),
                "matches": o.get("matches", h.get("matches")),
                "known": o.get("known", 0), "hits": o.get("hits", 0),
                "misses": o.get("misses", 0), "rate": o.get("rate"),
                "reference_known": o.get("reference_known"),
                "reference_rate": o.get("reference_rate"), "diff": o.get("diff"),
                "ci95": o.get("ci95"), "diff_ci95": o.get("diff_ci95"),
                "p_two_sided": o.get("p_two_sided"), "q_bh": o.get("q_bh"),
                "temporal_stability": o.get("temporal_stability"),
                "ft_coverage": o.get("ft_coverage"), "evidence": o.get("evidence"),
            }
    # A frozen hypothesis may fall out of the limited top-40 ranking. Its
    # discovery sample is fixed and its out-of-sample sample MUST be separate.
    for frozen in report.get("frozen") or []:
        target = frozen.get("outcome")
        if target not in TARGETS or not frozen.get("id"):
            continue
        key = frozen["id"] + "|" + target
        discovery = frozen.get("discovery") or {}
        if key not in result:
            result[key] = {
                "id": frozen["id"], "label": frozen.get("label", frozen["id"]),
                "target": target, "definition": frozen.get("definition"),
                "matches": frozen.get("discovery_matches"),
                "known": discovery.get("known", 0), "hits": discovery.get("hits", 0),
                "misses": None, "rate": discovery.get("rate"),
                "reference_known": discovery.get("reference_known"),
                "reference_rate": discovery.get("reference_rate"),
                "diff": discovery.get("diff"), "ci95": None,
                "diff_ci95": discovery.get("diff_ci95"),
                "p_two_sided": discovery.get("p_two_sided"),
                "q_bh": discovery.get("q_bh"), "temporal_stability": None,
                "ft_coverage": None, "evidence": "FROZEN_DISCOVERY",
                "state": frozen["state"],
            }
        # Replace live discovery stats with the immutable FROZEN discovery sample.
        # Otherwise post-freeze FT would leak into both the in-sample and OOS rows.
        for field in ("known", "hits", "rate", "reference_known", "reference_rate",
                      "diff", "diff_ci95", "p_two_sided", "q_bh"):
            if field in discovery:
                result[key][field] = discovery[field]
        if discovery.get("known") is not None and discovery.get("hits") is not None:
            result[key]["misses"] = discovery["known"] - discovery["hits"]
        result[key]["state"] = frozen["state"]
        result[key]["frozen_at"] = frozen.get("frozen_at")
        result[key]["out_of_sample"] = frozen.get("out_of_sample")
        result[key]["oos_halves"] = frozen.get("oos_halves")
        result[key]["degradation_flag"] = frozen.get("degradation_flag", False)
    return result


def _kind(before, after):
    if before is None:
        return "NEW_PATTERN"
    if before["state"] != after["state"]:
        return IMPORTANT.get(after["state"], "STATE_CHANGE")
    old_oos = (before.get("out_of_sample") or {}).get("known", 0)
    new_oos = (after.get("out_of_sample") or {}).get("known", 0)
    if new_oos < old_oos:
        return "DATA_REVISION"
    if new_oos > old_oos:
        return "NEW_EVIDENCE"
    old_n, new_n = before.get("known", 0), after.get("known", 0)
    if new_n < old_n or after.get("hits", 0) < before.get("hits", 0):
        return "DATA_REVISION"  # requires inspection, never called new evidence
    if new_n > old_n:
        old_diff, new_diff = before.get("diff"), after.get("diff")
        if isinstance(old_diff, (int, float)) and isinstance(new_diff, (int, float)):
            if old_diff * new_diff < 0 and min(abs(old_diff), abs(new_diff)) >= 0.03:
                return "SIGN_REVERSAL"
            change = abs(new_diff) - abs(old_diff)
            # Improvement is a larger ABSOLUTE contrast, not a better ranking.
            # It does not imply statistical significance or profitable odds.
            if change >= 0.05:
                return "IMPROVED"
            if change <= -0.05:
                return "DEGRADED"
        return "NEW_EVIDENCE"
    # Cross-group reference changes with unchanged group FT are not discoveries.
    if before.get("diff") != after.get("diff") or before.get("q_bh") != after.get("q_bh"):
        return "RECALCULATED"
    return "NO_CHANGE"


def _event(before, after, kind, stamp, previous_id=None):
    fields = ("matches", "known", "hits", "misses", "rate", "reference_rate", "diff",
              "ci95", "diff_ci95", "p_two_sided", "q_bh", "temporal_stability", "state",
              "out_of_sample", "frozen_at")
    changes = {k: {"from": before.get(k) if before else None, "to": after.get(k)}
               for k in fields if before is None or before.get(k) != after.get(k)}
    code = _digest([previous_id, after["id"], after["target"], kind, changes])
    notes = {
        "NEW_PATTERN": "Padrão publicado pela primeira vez após a baseline; ainda não validado.",
        "NEW_EVIDENCE": "Entraram novos resultados FT; a associação continua sob investigação.",
        "IMPROVED": "A diferença absoluta observada aumentou pelo menos cinco pontos percentuais após novos FT; não prova vantagem.",
        "DEGRADED": "A diferença absoluta observada diminuiu pelo menos cinco pontos percentuais após novos FT.",
        "SIGN_REVERSAL": "O sinal da diferença entre grupos inverteu-se após novos FT; não classificar como melhoria.",
        "DATA_REVISION": "O universo/resultado observado foi revisto; exige auditoria, não é melhoria.",
        "RECALCULATED": "Mudou a comparação com o grupo de referência, sem novos FT no grupo.",
        "CANDIDATE": "Hipótese passou a candidata segundo as regras V5; requer evidência independente.",
        "VALIDATED": "O motor V5 marcou validação fora da amostra, segundo os critérios congelados.",
        "REJECTED": "O motor V5 rejeitou esta hipótese nos critérios fora da amostra.",
        "STATE_CHANGE": "Mudança de estado atribuída pelo motor V5; consultar o registo congelado.",
    }
    return {
        "event_id": "D5-" + code, "at_utc": stamp, "kind": kind,
        "id": after["id"], "target": after["target"], "label": after["label"],
        "previous": {k: before.get(k) for k in fields} if before else None,
        "current": {k: after.get(k) for k in fields},
        "changes": changes,
        "ft_delta": (after.get("known", 0) - before.get("known", 0)) if before else None,
        "oos_ft_delta": ((after.get("out_of_sample") or {}).get("known", 0) -
                         (before.get("out_of_sample") or {}).get("known", 0)) if before else None,
        "state": after["state"], "explanation": notes[kind],
        "out_of_sample": after.get("out_of_sample"), "frozen_at": after.get("frozen_at"),
        "evidence": "docs/lab/pattern-research.json",
        "provenance": {"source": "V5_PUBLISHED_RESEARCH", "definition": after["definition"],
                       "rule": "absolute_diff_threshold_0.05_only_after_new_ft",
                       "comparison": "previous_published_snapshot"},
    }


def _settled(first_seen, ledger, previous):
    """Immutable prospective FT; no after-kickoff classification or lookahead."""
    stored = dict(previous)
    incoming = {e["match_key"]: e for e in first_seen.get("entries", [])}
    if not set(stored).issubset(incoming):
        raise ValueError("prospective first-detection history was removed")
    for key, value in stored.items():
        first = incoming[key]
        if (first.get("category_at_first_detection") != value["category_at_first_detection"] or
            _iso(first.get("first_detected_at")) != _iso(value["first_detected_at"]) or
            _iso(first.get("kickoff_utc")) != _iso(value["kickoff_utc"])):
            raise ValueError("immutable prospective detection was modified: " + key)
        record = (ledger.get("matches") or {}).get(key, {})
        if record.get("status") == "FINAL":
            result = record.get("result") or {}
            pair = (result.get("home_goals"), result.get("away_goals"))
            if all(isinstance(n, int) and not isinstance(n, bool) for n in pair):
                if pair != (value["home_goals"], value["away_goals"]):
                    raise ValueError("immutable prospective FT conflict: " + key)
    for entry in first_seen.get("entries", []):
        key = entry.get("match_key")
        if not key or key in stored:
            continue
        kickoff = _iso(entry.get("kickoff_utc"))
        detected = _iso(entry.get("first_detected_at"))
        through = _iso(entry.get("observed_through"))
        if not (kickoff and detected and through and detected < kickoff and through < kickoff):
            continue
        match = (ledger.get("matches") or {}).get(key, {})
        if match.get("status") != "FINAL":
            continue
        result = match.get("result") or {}
        h, a = result.get("home_goals"), result.get("away_goals")
        checked = _iso(match.get("checked_at"))
        if (not isinstance(h, int) or isinstance(h, bool) or
            not isinstance(a, int) or isinstance(a, bool) or h < 0 or a < 0 or
            not checked or checked < kickoff + timedelta(minutes=90)):
            continue
        stored[key] = {
            "match_key": key, "match_label": entry.get("match_label"),
            "kickoff_utc": kickoff.isoformat(), "first_detected_at": detected.isoformat(),
            "category_at_first_detection": entry["category_at_first_detection"],
            "rule_version": entry.get("rule_version"),
            "home_goals": h, "away_goals": a, "score": str(h) + "-" + str(a),
            "over_2_5": h + a > 2, "btts_yes": h > 0 and a > 0,
            "ft_checked_at": checked.isoformat(),
            "ft_evidence": result.get("evidence"),
            "ft_source": result.get("source"),
        }
    # A verified result already published is never silently overwritten or deleted.
    assert all(stored[k] == v for k, v in previous.items())
    return stored


def _categories(settled):
    stats = {}
    for v in settled.values():
        cat = v["category_at_first_detection"]
        group = stats.setdefault(cat, {"known_ft": 0, "over_2_5": 0, "btts_yes": 0})
        group["known_ft"] += 1
        group["over_2_5"] += int(v["over_2_5"])
        group["btts_yes"] += int(v["btts_yes"])
    return dict(sorted(stats.items()))


def build(report, first_seen, ledger, old=None):
    """Return (state, public_report, NEW events). Replays are idempotent."""
    if report.get("status") != "LAB_EXPLORATORY_RESEARCH_NOT_BETTING":
        raise ValueError("unexpected research report")
    if old is None:
        stamp = report.get("generated_at")
        if not _iso(stamp):
            raise ValueError("missing source timestamp")
        old = {"schema_version": SCHEMA, "baseline_at": stamp,
               "patterns": {}, "latest_events": [], "prospective_settled": {}}
        baseline = True
    else:
        if old.get("schema_version") != SCHEMA:
            raise ValueError("unsupported discovery state version")
        baseline = False
        stamp = report.get("generated_at")
        if not _iso(stamp):
            raise ValueError("missing source timestamp")

    data = _published(report)
    patterns = dict(old["patterns"])
    feed = list(old["latest_events"])
    new = []
    # A pattern leaving top-40 remains in state, not interpreted as rejected.
    for key, row in sorted(data.items()):
        previous = patterns.get(key)
        before = previous["latest"] if previous else None
        kind = _kind(before, row)
        if not baseline and kind not in ("NO_CHANGE",):
            event = _event(before, row, kind, stamp, feed[-1]["event_id"] if feed else None)
            if kind != "RECALCULATED" or before.get("diff") != row.get("diff"):
                new.append(event)
        points = list(previous["points"]) if previous else []
        if not points or (before != row and kind != "NO_CHANGE"):
            points.append({"at_utc": stamp, "known": row["known"], "hits": row["hits"],
                           "rate": row["rate"], "diff": row["diff"], "q_bh": row["q_bh"],
                           "state": row["state"], "oos_known": (row.get("out_of_sample") or {}).get("known"),
                           "kind": "BASELINE" if not points else kind})
        patterns[key] = {"latest": row, "points": points[-MAX_POINTS:]}
    settled = _settled(first_seen, ledger, old.get("prospective_settled", {}))
    feed = (feed + new)[-MAX_FEED:]
    state = {"schema_version": SCHEMA, "baseline_at": old["baseline_at"],
             "patterns": patterns, "latest_events": feed, "prospective_settled": settled}
    public = {
        "schema_version": SCHEMA, "status": "DISCOVERY_OBSERVATION_NOT_BETTING",
        "baseline_at": old["baseline_at"],
        "scope": "Only patterns published in V5 patterns/combinations_top/frozen; not all 800 tested hypotheses",
        "timeline": list(reversed(feed)),
        "events_total_in_recent_cache": len(feed),
        "historical_archive": "data/lab/discovery-events-YYYY-MM.jsonl (versioned in Git)",
        "patterns": patterns,
        "prospective": {"settled": sorted(settled.values(), key=lambda x: x["ft_checked_at"], reverse=True)[:80],
                        "settled_total": len(settled), "by_first_detection_category": _categories(settled),
                        "detected_total": len(first_seen.get("entries", []))},
        "rules": {"meaningful_diff_pp": 5, "change_is_not_validation": True,
                  "no_ft_is_not_red": True, "no_roi_or_ev_without_executable_odds": True,
                  "frozen_v5_validation_only": True, "recalculated_not_new_discovery": True},
        "limitations": ["A primeira execução cria uma baseline; não reconstrói eventos passados.",
                        "Só são acompanhados os padrões publicados; os restantes não estão neste histórico.",
                        "Cada taxa usa um jogo com FT confirmado por observação, não mensagens ou apostas.",
                        "Amostra de descoberta nunca equivale a validação fora da amostra.",
                        "Últimos 24 pontos por hipótese são cache; eventos completos nos arquivos mensais Git.",
                        "Primeira deteção do jogo preservada antes do início; resultado só depois de FT confirmado."],
    }
    return state, public, new
