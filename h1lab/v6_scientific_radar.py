"""V6.2 P2#11: bounded, auditable scientific radar derived from immutable journals.

The V6 source of truth is hash-verified forecast, hypothesis and five-memory
JSONL. FT is joined from the separate verified universal FT event stream and
NEVER treated as a prospective prediction. Outputs are read-only descriptive
views. Missing lineage is explicit; it is never guessed from current V4 odds.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .v6_shadow import read_journal, utc, canonical
from .v6_science_memory import read_stream, rebuild
from .v6_ft_events import read_events as read_ft_events
from .v6_hypotheses import DEFINITION, definition_digest, HYPOTHESIS
from .v4_revisions import read_events as read_v4_events

MAX_ACTIVE = 10
SCHEMA = 1
STATUS = "V6_SCIENTIFIC_RADAR_SHADOW_NOT_VALIDATED"
REPO = "https://github.com/nunovinhas-creator/asianodds-h1-lab/blob/main/"
CODE_LABELS = {
    "F01_EPISODE_INDEPENDENCE": "Episódios independentes",
    "F02_RISING_VS_FLAT": "Subidas vs estabilidade",
    "F03_1X2_AH_CONSISTENCY": "Concordância entre mercados",
    "F04_LEAD_TIME_STRATA": "Antecedência do alerta",
    "F05_COMPETITION_CONTEXT": "Contexto da competição",
    "F06_LEAVE_DAY_OUT_AND_TRIM": "Robustez entre dias",
    "F07_RESIDUAL_VS_MARKET": "Diferença face ao mercado",
    "F08_COMPETING_MARKET_LINE": "Linha como explicação alternativa",
    "F09_MATCHED_MARKET_PEERS": "Jogos comparáveis",
    "F10_PROSPECTIVE_CONFIRMATION": "Validação cronológica",
}


def registration(root):
    p = Path(root) / "data/lab/v6-hypotheses.jsonl"
    entries = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not entries or len(entries) > MAX_ACTIVE:
        raise ValueError("V6 scientific registry has zero or more than 10 active entries")
    from .v6_shadow import canonical
    from .v6_science_memory import digest
    for row in entries:
        h = row.get("sha256")
        if not h or digest({k: v for k, v in row.items() if k != "sha256"}) != h:
            raise ValueError("Unverified formal hypothesis registration")
        if row.get("id") != HYPOTHESIS or row.get("definition") != DEFINITION:
            # Other formal hypotheses require their own versioned validation.
            raise ValueError("Unknown unversioned scientific hypothesis")
        if row.get("definition_sha256") != definition_digest():
            raise ValueError("Modified hypothesis definition")
    if len({r["id"] for r in entries}) != len(entries):
        raise ValueError("Duplicate scientific hypothesis id")
    return entries


def source_projection(root):
    """A V4 snapshot can be shown as historical only if captured before known_at."""
    events = read_v4_events(root)
    by_id = defaultdict(list)
    for e in events:
        by_id[e["event_id"]].append(e)
    return by_id, events


def load_falsification(root, forecast_tail, evidence_tail):
    p = Path(root) / "docs/lab/v6-falsification.json"
    if not p.exists():
        return None, "REPORT_NOT_PUBLISHED"
    report = json.loads(p.read_text(encoding="utf-8"))
    hashes = report.get("data_lineage") or {}
    if (hashes.get("forecast_journal_tail") != forecast_tail or
            hashes.get("memory_evidence_tail") != (evidence_tail or None)):
        return None, "STALE_RELATIVE_TO_IMMUTABLE_JOURNALS"
    if report.get("hypothesis_definition_sha256") != definition_digest():
        raise ValueError("Falsification belongs to another definition")
    return report, "VERIFIED_AGAINST_CURRENT_JOURNAL_TAIL"


def build(root):
    root = Path(root)
    hypotheses = registration(root)
    forecasts = read_journal(root)
    # Rebuild validates the science memory without looking at the mutable FT ledger.
    memory = rebuild(root, frozen=forecasts, registration=hypotheses[0])
    obs = read_stream(root, "observations")
    patterns = read_stream(root, "patterns")
    decisions = read_stream(root, "decisions")
    evidence = read_stream(root, "evidence")
    ft_events = read_ft_events(root)
    v4_by_id, v4_events = source_projection(root)
    if len(obs) != len(forecasts) or len(patterns) != len(forecasts):
        raise ValueError("Incomplete scientific source memory")
    obs_by = {r["event"]["forecast_sha256"]:r for r in obs}
    patterns_by = {r["event"]["forecast_sha256"]:r for r in patterns}
    ft_latest = {r["match_key"]: r for r in ft_events}
    science_ft_latest = {r["event"]["match_key"]: r for r in evidence}
    selected = {}
    snapshot_count = Counter()
    for r in forecasts:
        key = r["match_key"]
        fingerprint = r["sha256"]
        if fingerprint not in obs_by or fingerprint not in patterns_by:
            raise ValueError("Unlinked forecast")
        snapshot_count[key] += 1
        p = selected.get(key)
        if p is None or (r["known_at"],r["event_id"]) > (p["known_at"],p["event_id"]):
            selected[key] = r
    latest_decisions = {r["event"]["hypothesis_id"]:r for r in decisions}
    checks, check_freshness = load_falsification(
        root, forecasts[-1]["sha256"] if forecasts else None,
        evidence[-1]["sha256"] if evidence else None)
    games = []
    coverage = Counter()
    for key, forecast in selected.items():
        h = forecast["sha256"]
        eid = forecast["event_id"]
        known = utc(forecast["known_at"])
        kickoff = utc(forecast["kickoff_utc"])
        if not known or not kickoff or known >= kickoff:
            raise ValueError("Scientific radar cannot publish post-kickoff freeze")
        ver = [x for x in v4_by_id.get(eid, ()) if utc(x["known_at"]) <= known]
        source = ver[-1] if ver else None
        if source and source["snapshot"].get("event_id") != eid:
            raise ValueError("V4 revision event id mismatch")
        # For migrated baseline captured *after* the forecast, no claim of
        # historic capture is made even if Telegram's original date is earlier.
        source_status = (
            "V4_VERSION_VERIFIED_BEFORE_FREEZE" if source is not None
            else "V4_HISTORY_NOT_PROVEN_AT_FREEZE")
        coverage[source_status] += 1
        ft = ft_latest.get(key)
        score = ft["snapshot"].get("score") if ft else None
        checked = utc(ft.get("source_last_checked_at")) if ft else None
        ft_valid = bool(
            ft and ft["snapshot"].get("status") == "FINAL" and
            score is not None and checked is not None and checked >= kickoff and
            checked >= known and score.get("home") is not None and
            score.get("away") is not None)
        ft_state = ("FINAL_WITH_AFTER_KICKOFF_VERIFICATION" if ft_valid else
                    "FINAL_BUT_TEMPORAL_EVIDENCE_MISSING" if score else
                    ft["snapshot"]["status"] if ft else "NOT_REGISTERED_IN_FT_JOURNAL")
        coverage[ft_state] += 1
        v6e = science_ft_latest.get(key)
        science_ft = (
            "SCIENCE_FT_CONFIRMED" if v6e and v6e["event"].get("state") == "CONFIRMED"
            else "SCIENCE_FT_QUARANTINED" if v6e and v6e["event"].get("state") == "QUARANTINED"
            else "NOT_YET_IN_V6_SCIENTIFIC_EVIDENCE")
        # Outcome is displayed only when universal FT is temporally supported.
        # No verdict or ROI is inferred from a single outcome.
        q = forecast.get("price_quality") or {}
        ctx = forecast.get("feature_context_v2") or {}
        games.append({
            "match_key": key, "match_label":forecast.get("match_label") or key,
            "hypothesis_id":forecast["hypothesis_id"],
            "kickoff_utc":forecast["kickoff_utc"],
            "event_id":eid,
            "telegram_original_at":forecast.get("observed_at"),
            "frozen_known_at":forecast["known_at"],
            "snapshot_history_count":snapshot_count[key],
            "forecast": {
                "sha256":h,"memory_observation_sha256":obs_by[h]["sha256"],
                "memory_pattern_sha256":patterns_by[h]["sha256"],
                "quality_status":q.get("status"),
                "quality_flags":q.get("flags") or [],
                "market_total_after":q.get("after"),
                "market_total_before":q.get("before"),
                "market_probability_over_2_5":forecast.get("market_probability_over_2_5"),
                "forecast_kind":forecast.get("forecast_kind"),
                "model_delta_vs_market":forecast.get("model_delta_vs_market"),
                "original_posthoc_condition":bool(forecast["pattern_original_posthoc"]),
                "strict_observation":bool(forecast["pattern_strict_posthoc"]),
                "feature_version":ctx.get("version"),
                "feature_sha256":ctx.get("sha256"),
                "market_co_observation":ctx.get("total_1x2_relation"),
                "competition_heuristic":(ctx.get("competition") or {}).get("category_heuristic"),
            },
            "source_v4":{
                "status":source_status,
                "revision_id":source["revision_id"] if source else None,
                "sha256":source["sha256"] if source else None,
                "known_at":source["known_at"] if source else None,
                "telegram_edit_at":source["telegram_edit_at"] if source else None,
                "markets":source["snapshot"].get("markets") if source else None,
            },
            "ft":{
                "status":ft_state,
                "science_status":science_ft,
                "event_id":ft["id"] if ft else None,
                "sha256":ft["sha256"] if ft else None,
                "evidence_level":ft["snapshot"]["evidence_level"] if ft else None,
                "score":score if ft_valid else None,
                "checked_at":ft["source_last_checked_at"] if ft else None,
                "source_url":score.get("source") if ft_valid else None,
                "scientific_event_sha256":v6e["sha256"] if v6e else None,
            },
        })
    games.sort(key=lambda r:(r["kickoff_utc"],r["match_key"]),reverse=True)
    cards=[]
    for reg in hypotheses[:MAX_ACTIVE]:
        relevant=[g for g in games if g["hypothesis_id"]==reg["id"]]
        last=latest_decisions.get(reg["id"])
        status=last["event"]["state"] if last else "INCONCLUSIVO"
        if status not in ("INCONCLUSIVO",):
            # V6.2 must not silently claim a validated hypothesis until
            # the future production gate permits it, irrespective of V5.
            status="REQUER_VERIFICACAO_HUMANA"
        cards.append({
            "id":reg["id"],"definition":reg["definition"],
            "definition_sha256":reg["definition_sha256"],
            "registered_at":reg["registered_at"],
            "origin":reg["origin"],"selected_at_claimed":reg.get("selected_at_claimed"),
            "outcome":reg["outcome"],"comparison":reg["comparison"],
            "state":status,
            "decision_event_sha256":last["sha256"] if last else None,
            "decision_reason":last["event"]["reason"] if last else "MISSING_DECISION",
            "frozen_matches":len(relevant),
            "condition_original":sum(g["forecast"]["original_posthoc_condition"] for g in relevant),
            "condition_strict":sum(g["forecast"]["strict_observation"] for g in relevant),
            "ft_verified":sum(g["ft"]["score"] is not None for g in relevant),
            "falsification_status":check_freshness,
            "falsification_checks": [
                {"code":x["code"],"name":CODE_LABELS.get(x["code"],x["code"]),
                 "result":x["result"],"n":x["n"],"required":x["required"]}
                for x in checks.get("checks",[])
            ] if checks and checks.get("hypothesis_id")==reg["id"] else [],
            "games":relevant,
        })
    return {
        "schema_version":SCHEMA, "status":STATUS,
        "title":"MASTER BRAIN — Radar Científico V6.2",
        "max_active_hypotheses":MAX_ACTIVE,"active_hypotheses":len(cards),
        "hypotheses":cards,"totals":{
            "frozen_snapshots":len(forecasts),
            "unique_matches":len(selected),
            "ft_universal_events":len(ft_events),
            "v4_revision_events":len(v4_events),
            "evidence_quality":dict(sorted(coverage.items())),
        },
        "source_tails":{
            "forecasts":forecasts[-1]["sha256"] if forecasts else None,
            "observations":obs[-1]["sha256"] if obs else None,
            "patterns":patterns[-1]["sha256"] if patterns else None,
            "decisions":decisions[-1]["sha256"] if decisions else None,
            "science_evidence":evidence[-1]["sha256"] if evidence else None,
            "universal_ft":ft_events[-1]["sha256"] if ft_events else None,
            "v4_revisions":v4_events[-1]["sha256"] if v4_events else None,
        },
        "source_links":{
            "hypotheses":REPO+"data/lab/v6-hypotheses.jsonl",
            "forecasts":REPO+"data/lab/v6-forecasts-2026-10.jsonl",
            "observations":REPO+"data/lab/v6-memory-observations-2026-10.jsonl",
            "patterns":REPO+"data/lab/v6-memory-patterns-2026-10.jsonl",
            "decisions":REPO+"data/lab/v6-memory-decisions-2026-10.jsonl",
            "science_ft":REPO+"data/lab/v6-memory-evidence-2026-10.jsonl",
            "universal_ft":REPO+"data/lab/v6-ft-events-2026-10.jsonl",
            "v4_revisions":REPO+"data/lab/v4-revisions-2026-10.jsonl",
        },
        "memory_validation":memory["status"],
        "limitations":[
            "Only formally registered hypotheses are shown as scientific hypotheses; V5 exploratory rankings are not promoted.",
            "Source of truth is hash-linked JSONL, not the latest dashboard, and never a cached betting record.",
            "FT from the independent LAB ledger may be visible before it appears in the V6 scientific evidence stream; they are labelled separately.",
            "Old V4 edits are not reconstructed retroactively; no V4 source version is claimed unless it was stored before known_at.",
            "Reported market p(Over 2.5) is a model-derived reference, not a tradable O2.5 quote.",
            "No independent winning edge, ROI or scientific validation is claimed.",
            "GitHub links show the current main history; SHA hashes identify the precise immutable observations.",
        ],
    }
