"""Match-level features and individual odds-movement patterns (LAB V5).

Input is one per-match timeline produced by ``timeline.match_timeline`` (the
existing canonical chronology: message -> snapshot -> movement -> match).
Nothing here reads H1 internals, results, or anything observed after the
decision time.

Decision time
-------------
For each match the decision time is the ``observed_at`` of its *last message
before the scheduled kickoff*. Only messages strictly before kickoff are
used. Post-kickoff alerts are counted and flagged, never used as features.

Movement semantics (no invented prices)
---------------------------------------
* Within a message: the channel shows Was -> Now. That is an observed move.
* Between messages: the gap is an *unobserved* change (``timeline`` labels it);
  no intermediate price is interpolated.
* Odds at different lines are not compared directly. Each Total quote is also
  expressed as the Poisson mean ``lam`` (``market_math``); ``IMPLIED_GOALS_*``
  patterns use ``lam``, and price patterns are restricted to unchanged lines.
* Messages that ``timeline`` links as the same movement (identical snapshot or
  same line move seconds apart) form one *episode*; sequence patterns count
  episodes, never raw notifications.

All thresholds are fixed a priori (FEATURE_VERSION) and documented in
``docs/lab/PATTERN-ENGINE.md``. Changing any of them requires a new version.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

from .market_math import implied_lambda, one_x_two_probs, prob_total_over

FEATURE_VERSION = 1
DLAM_EPS = 0.05        # |Δλ| below this is FLAT
BIG_NET = 0.20         # net λ change first->last counted as big
SMALL_NET = 0.10
PROB_EPS = 0.01        # 1X2 de-margined probability change
PRICE_EPS = 0.005      # any 0.01 odds change at an unchanged line
INTENSITY_EPS = 0.03
LATE_MIN = 60
EARLY_MIN = 1440
SHORT_GAP_MIN = 30
LONG_GAP_MIN = 360
LINE_HIGH = 3.25
LINE_LOW = 2.25

# id -> (scope, family, description in Portuguese)
PATTERNS = {
    # --- Total line, within one message
    "M_TOTAL_LINE_UP": ("message", "TOTAL", "Linha Total sobe dentro da mensagem (Was→Now)"),
    "M_TOTAL_LINE_DOWN": ("message", "TOTAL", "Linha Total desce dentro da mensagem"),
    "M_TOTAL_LINE_SAME": ("message", "TOTAL", "Linha Total igual; só os preços mudam"),
    "M_LINE_JUMP_HALF": ("message", "TOTAL", "Linha Total muda ≥ 0,5 numa só mensagem"),
    # --- Over/Under prices, only when the line is unchanged
    "M_OVER_PRICE_UP_SAME_LINE": ("message", "OU_PRICE", "Odd Over sobe com a mesma linha"),
    "M_OVER_PRICE_DOWN_SAME_LINE": ("message", "OU_PRICE", "Odd Over desce com a mesma linha"),
    "M_UNDER_PRICE_UP_SAME_LINE": ("message", "OU_PRICE", "Odd Under sobe com a mesma linha"),
    "M_UNDER_PRICE_DOWN_SAME_LINE": ("message", "OU_PRICE", "Odd Under desce com a mesma linha"),
    "M_BOTH_PRICES_UP_SAME_LINE": ("message", "OU_PRICE", "Over e Under sobem juntos (margem cortada; contraditório)"),
    # --- Implied goals (common space across lines)
    "M_IMPLIED_GOALS_UP": ("message", "IMPLIED", "Golos esperados implícitos sobem ≥ 0,05 na mensagem"),
    "M_IMPLIED_GOALS_DOWN": ("message", "IMPLIED", "Golos esperados implícitos descem ≥ 0,05 na mensagem"),
    "M_IMPLIED_GOALS_FLAT": ("message", "IMPLIED", "Golos esperados implícitos variam < 0,05"),
    "M_LINE_LAMBDA_DISAGREE": ("message", "IMPLIED", "Linha e golos implícitos movem-se em sentidos opostos"),
    # --- 1X2 (de-margined probabilities)
    "M_1X2_HOME_PROB_UP": ("message", "1X2", "Probabilidade sem margem da casa sobe ≥ 1 pp"),
    "M_1X2_HOME_PROB_DOWN": ("message", "1X2", "Probabilidade da casa desce ≥ 1 pp"),
    "M_1X2_DRAW_PROB_UP": ("message", "1X2", "Probabilidade do empate sobe ≥ 1 pp"),
    "M_1X2_DRAW_PROB_DOWN": ("message", "1X2", "Probabilidade do empate desce ≥ 1 pp"),
    "M_1X2_AWAY_PROB_UP": ("message", "1X2", "Probabilidade do visitante sobe ≥ 1 pp"),
    "M_1X2_AWAY_PROB_DOWN": ("message", "1X2", "Probabilidade do visitante desce ≥ 1 pp"),
    # --- Asian handicap (more negative line = home more favoured)
    "M_AH_TOWARD_HOME": ("message", "AH", "Linha AH desce: casa mais favorecida"),
    "M_AH_TOWARD_AWAY": ("message", "AH", "Linha AH sobe: casa menos favorecida"),
    "M_AH_LINE_SAME": ("message", "AH", "Linha AH igual dentro da mensagem"),
    # --- What fired the alert
    "M_TRIGGER_TOTAL": ("message", "TRIGGER", "Alerta disparado pelo mercado Total"),
    "M_TRIGGER_1X2": ("message", "TRIGGER", "Alerta disparado pelo mercado 1X2"),
    "M_TRIGGER_SEL_1": ("message", "TRIGGER", "Disparo 1X2 na seleção casa (1)"),
    "M_TRIGGER_SEL_X": ("message", "TRIGGER", "Disparo 1X2 na seleção empate (X)"),
    "M_TRIGGER_SEL_2": ("message", "TRIGGER", "Disparo 1X2 na seleção visitante (2)"),
    # --- Timing of a message
    "M_LATE": ("message", "TIME", "Mensagem a menos de 60 min do início"),
    "M_EARLY": ("message", "TIME", "Mensagem a mais de 24 h do início"),
    # --- Match-level sequence/aggregate
    "G_SINGLE_ALERT": ("match", "SEQUENCE", "Uma única mensagem antes do início"),
    "G_MULTI_ALERT": ("match", "SEQUENCE", "Duas ou mais mensagens antes do início"),
    "G_MULTI_EPISODE": ("match", "SEQUENCE", "Dois ou mais episódios distintos (não repetições)"),
    "G_REPEAT_SAME_DIRECTION": ("match", "SEQUENCE", "Dois ou mais episódios com golos implícitos no mesmo sentido"),
    "G_OPPOSING_DIRECTIONS": ("match", "SEQUENCE", "Episódios com golos implícitos em sentidos opostos"),
    "G_INTENSIFYING": ("match", "SEQUENCE", "Último episódio com variação maior do que o primeiro"),
    "G_WEAKENING": ("match", "SEQUENCE", "Último episódio com variação menor do que o primeiro"),
    "G_UNOBSERVED_GAP": ("match", "SEQUENCE", "Linha mudou entre mensagens sem ser observada"),
    "G_SHORT_INTERVAL": ("match", "TIME", "Dois episódios com menos de 30 min de intervalo"),
    "G_LONG_INTERVAL": ("match", "TIME", "Dois episódios com mais de 6 h de intervalo"),
    "G_NET_IMPLIED_UP_BIG": ("match", "IMPLIED", "Golos implícitos: 1.ª→última observação sobe ≥ 0,20"),
    "G_NET_IMPLIED_DOWN_BIG": ("match", "IMPLIED", "Golos implícitos: 1.ª→última observação desce ≥ 0,20"),
    "G_NET_IMPLIED_SMALL": ("match", "IMPLIED", "Golos implícitos: variação líquida < 0,10"),
    "G_FIRST_LEAD_LT_6H": ("match", "TIME", "Primeiro alerta a menos de 6 h do início"),
    "G_FIRST_LEAD_6_24H": ("match", "TIME", "Primeiro alerta entre 6 e 24 h antes"),
    "G_FIRST_LEAD_GT_24H": ("match", "TIME", "Primeiro alerta a mais de 24 h"),
    "G_LAST_LINE_HIGH": ("match", "CONTEXT", "Última linha Total ≥ 3,25"),
    "G_LAST_LINE_MID": ("match", "CONTEXT", "Última linha Total entre 2,5 e 3,0"),
    "G_LAST_LINE_LOW": ("match", "CONTEXT", "Última linha Total ≤ 2,25"),
    "G_TOTAL_AND_1X2": ("match", "CONTEXT", "Total e 1X2 observados no mesmo jogo"),
}
MESSAGE_PATTERNS = tuple(k for k, v in PATTERNS.items() if v[0] == "message")
# Patterns that describe *what* moved; ordering (A before B) only among these.
ORDERABLE = tuple(k for k in MESSAGE_PATTERNS if not k.startswith(("M_LATE", "M_EARLY")))
# Groups whose members cannot co-occur at match level (skip combinations).
EXCLUSIVE = [
    {"G_SINGLE_ALERT", "G_MULTI_ALERT"}, {"G_SINGLE_ALERT", "G_MULTI_EPISODE"},
    {"G_FIRST_LEAD_LT_6H", "G_FIRST_LEAD_6_24H", "G_FIRST_LEAD_GT_24H"},
    {"G_LAST_LINE_HIGH", "G_LAST_LINE_MID", "G_LAST_LINE_LOW"},
    {"G_NET_IMPLIED_UP_BIG", "G_NET_IMPLIED_DOWN_BIG", "G_NET_IMPLIED_SMALL"},
    {"G_INTENSIFYING", "G_WEAKENING"},
]


def _utc(v):
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def _dir(delta, eps):
    if delta is None:
        return None
    return "UP" if delta >= eps else "DOWN" if delta <= -eps else "FLAT"


def message_metrics(e):
    """Per-message observed quantities and the message-level patterns it hits."""
    snaps = e.get("snapshots") or {}
    hits = set()
    out = {"event_id": e["event_id"], "observed_at": e["observed_at"],
           "minutes_to_kickoff": e.get("minutes_to_kickoff"), "markets": sorted(snaps)}
    t = snaps.get("total")
    if t:
        b, a = t["before"], t["after"]
        lb = implied_lambda(b["line"], b["over_price"], b["under_price"])
        la = implied_lambda(a["line"], a["over_price"], a["under_price"])
        dline = a["line"] - b["line"]
        dlam = None if lb is None or la is None else round(la - lb, 4)
        out.update({"line_before": b["line"], "line_after": a["line"], "lam_before": lb,
                    "lam_after": la, "dlam": dlam, "total_origin": t.get("origin")})
        hits.add("M_TOTAL_LINE_UP" if dline > 1e-9 else "M_TOTAL_LINE_DOWN" if dline < -1e-9
                 else "M_TOTAL_LINE_SAME")
        if abs(dline) >= 0.5 - 1e-9:
            hits.add("M_LINE_JUMP_HALF")
        if abs(dline) < 1e-9:
            do, du = a["over_price"] - b["over_price"], a["under_price"] - b["under_price"]
            if do > PRICE_EPS:
                hits.add("M_OVER_PRICE_UP_SAME_LINE")
            elif do < -PRICE_EPS:
                hits.add("M_OVER_PRICE_DOWN_SAME_LINE")
            if du > PRICE_EPS:
                hits.add("M_UNDER_PRICE_UP_SAME_LINE")
            elif du < -PRICE_EPS:
                hits.add("M_UNDER_PRICE_DOWN_SAME_LINE")
            if do > PRICE_EPS and du > PRICE_EPS:
                hits.add("M_BOTH_PRICES_UP_SAME_LINE")
        d = _dir(dlam, DLAM_EPS)
        if d:
            hits.add("M_IMPLIED_GOALS_" + d)
        if d in ("UP", "DOWN") and abs(dline) > 1e-9 and (dline > 0) != (d == "UP"):
            hits.add("M_LINE_LAMBDA_DISAGREE")
    x = snaps.get("one_x_two")
    if x:
        pb = one_x_two_probs({k: x[k]["before"] for k in ("1", "X", "2")})
        pa = one_x_two_probs({k: x[k]["after"] for k in ("1", "X", "2")})
        if pb and pa:
            out["p1x2_before"], out["p1x2_after"] = pb, pa
            for sel, name in (("1", "HOME"), ("X", "DRAW"), ("2", "AWAY")):
                d = _dir(pa[sel] - pb[sel], PROB_EPS)
                if d in ("UP", "DOWN"):
                    hits.add("M_1X2_%s_PROB_%s" % (name, d))
    ah = snaps.get("asian_handicap")
    if ah:
        dl = ah["after"]["line"] - ah["before"]["line"]
        out["ah_before"], out["ah_after"] = ah["before"]["line"], ah["after"]["line"]
        hits.add("M_AH_TOWARD_HOME" if dl < -1e-9 else "M_AH_TOWARD_AWAY" if dl > 1e-9 else "M_AH_LINE_SAME")
    trig = e.get("trigger_market")
    if trig == "total":
        hits.add("M_TRIGGER_TOTAL")
    elif trig == "1x2":
        hits.add("M_TRIGGER_1X2")
        sel = e.get("trigger_selection")
        if sel in ("1", "X", "2"):
            hits.add("M_TRIGGER_SEL_" + sel)
    m = e.get("minutes_to_kickoff")
    if isinstance(m, (int, float)) and not isinstance(m, bool):
        if m < LATE_MIN:
            hits.add("M_LATE")
        if m > EARLY_MIN:
            hits.add("M_EARLY")
    out["patterns"] = sorted(hits)
    return out


def _episode_of(timeline):
    ep = {}
    for i, group in enumerate(timeline.get("movement_episodes") or []):
        for eid in group:
            ep[eid] = i
    return ep


def fingerprint(timeline):
    events = [{k: e.get(k) for k in ("event_id", "observed_at", "snapshots", "trigger_market",
                                       "trigger_selection", "minutes_to_kickoff")}
              for e in timeline.get("events", [])]
    payload = {"v": FEATURE_VERSION, "k": timeline.get("match_key"),
               "ko": (timeline.get("identity") or {}).get("kickoff_utc"),
               "ep": timeline.get("movement_episodes"), "e": events,
               "tr": [x.get("line") for x in ((timeline.get("trajectory") or {}).get("total") or {}).get("transitions", [])]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:20]


def match_features(timeline):
    """Decision-time features for one match, or a dict with ``excluded`` reason."""
    key = timeline["match_key"]
    ident = timeline.get("identity") or {}
    kos = ident.get("kickoff_utc") or []
    base = {"match_key": key, "match_label": timeline.get("match_label"),
            "feature_version": FEATURE_VERSION, "fingerprint": fingerprint(timeline)}
    if len(kos) != 1 or _utc(kos[0]) is None:
        return dict(base, excluded="kickoff_unknown_or_inconsistent")
    if not (ident.get("team_names_consistent", True) and not ident.get("per_message_conflicts")):
        return dict(base, excluded="identity_conflict")
    events = sorted(timeline.get("events", []), key=lambda e: (e["observed_at"], e["event_id"]))
    pre = [e for e in events if isinstance(e.get("minutes_to_kickoff"), (int, float))
           and e["minutes_to_kickoff"] > 0]
    post = len(events) - len(pre)
    if not pre:
        return dict(base, kickoff_utc=kos[0], excluded="no_prekickoff_message", post_kickoff_messages=post)
    msgs = [message_metrics(e) for e in pre]
    ep_of = _episode_of(timeline)
    # Episode representatives in chronological order (first message of each episode).
    seen, reps = set(), []
    for m in msgs:
        ep = ep_of.get(m["event_id"], m["event_id"])
        if ep not in seen:
            seen.add(ep)
            reps.append(m)
    hits = {}
    for i, m in enumerate(msgs):
        for p in m["patterns"]:
            hits.setdefault(p, i)  # index of first pre-KO message with p
    g = set(hits)
    g.add("G_SINGLE_ALERT" if len(msgs) == 1 else "G_MULTI_ALERT")
    if len(reps) >= 2:
        g.add("G_MULTI_EPISODE")
    dirs = [_dir(r.get("dlam"), DLAM_EPS) for r in reps]
    nonflat = [d for d in dirs if d in ("UP", "DOWN")]
    if len(nonflat) >= 2 and len(set(nonflat)) == 1:
        g.add("G_REPEAT_SAME_DIRECTION")
    if "UP" in nonflat and "DOWN" in nonflat:
        g.add("G_OPPOSING_DIRECTIONS")
    mags = [abs(r["dlam"]) for r in reps if r.get("dlam") is not None]
    if len(mags) >= 2:
        if mags[-1] > mags[0] + INTENSITY_EPS:
            g.add("G_INTENSIFYING")
        elif mags[-1] < mags[0] - INTENSITY_EPS:
            g.add("G_WEAKENING")
    pre_ids = {m["event_id"] for m in msgs}
    for tr in ((timeline.get("trajectory") or {}).get("total") or {}).get("transitions", []):
        if tr.get("line") == "UNOBSERVED_CHANGE" and tr.get("to") in pre_ids:
            g.add("G_UNOBSERVED_GAP")
    gaps = [(_utc(b["observed_at"]) - _utc(a["observed_at"])).total_seconds() / 60
            for a, b in zip(reps, reps[1:])]
    if any(x < SHORT_GAP_MIN for x in gaps):
        g.add("G_SHORT_INTERVAL")
    if any(x > LONG_GAP_MIN for x in gaps):
        g.add("G_LONG_INTERVAL")
    totals = [m for m in msgs if m.get("lam_before") is not None and m.get("lam_after") is not None]
    net = None
    if totals:
        net = round(totals[-1]["lam_after"] - totals[0]["lam_before"], 4)
        g.add("G_NET_IMPLIED_UP_BIG" if net >= BIG_NET else "G_NET_IMPLIED_DOWN_BIG" if net <= -BIG_NET
              else "G_NET_IMPLIED_SMALL" if abs(net) < SMALL_NET else "_")
        g.discard("_")
    first_lead = msgs[0]["minutes_to_kickoff"]
    g.add("G_FIRST_LEAD_LT_6H" if first_lead < 360 else "G_FIRST_LEAD_6_24H" if first_lead <= 1440
          else "G_FIRST_LEAD_GT_24H")
    with_line = [m for m in msgs if m.get("line_after") is not None]
    last_line = with_line[-1]["line_after"] if with_line else None
    if last_line is not None:
        g.add("G_LAST_LINE_HIGH" if last_line >= LINE_HIGH else "G_LAST_LINE_LOW" if last_line <= LINE_LOW
              else "G_LAST_LINE_MID")
    if any("total" in m["markets"] for m in msgs) and any("one_x_two" in m["markets"] for m in msgs):
        g.add("G_TOTAL_AND_1X2")
    lam_dec = totals[-1]["lam_after"] if totals else None
    first_obs = {p: msgs[i]["observed_at"] for p, i in hits.items()}
    first_ep = {p: ep_of.get(msgs[i]["event_id"], msgs[i]["event_id"]) for p, i in hits.items()}
    max_abs = max(totals, key=lambda m: abs(m["dlam"] or 0)) if totals else None
    vector = {  # used by the similarity engine; decision-time information only
        "net_dlam": net,
        "max_msg_dlam": max_abs["dlam"] if max_abs else None,
        "last_line": last_line, "lam_decision": lam_dec,
        "n_episodes": len(reps),
        "log_lead_first": round(math.log1p(first_lead), 4),
        "log_lead_last": round(math.log1p(msgs[-1]["minutes_to_kickoff"]), 4),
        "has_1x2": int(any("one_x_two" in m["markets"] for m in msgs)),
        "ah_dir": (-1 if "M_AH_TOWARD_HOME" in g else 1 if "M_AH_TOWARD_AWAY" in g else 0
                   if "M_AH_LINE_SAME" in g else None),
        "opposing": int("G_OPPOSING_DIRECTIONS" in g),
        "late": int("M_LATE" in g),
    }
    origins = sorted({m.get("total_origin") for m in msgs if m.get("total_origin")})
    return dict(base, kickoff_utc=kos[0],
                decision_at=msgs[-1]["observed_at"], first_observed_at=msgs[0]["observed_at"],
                prekickoff_messages=len(msgs), episodes=len(reps), post_kickoff_messages=post,
                patterns=sorted(g), pattern_first_at=first_obs, pattern_first_episode=first_ep,
                lam_decision=lam_dec, p_over_2_5_model=prob_total_over(lam_dec),
                net_dlam=net, total_origins=origins, vector=vector,
                last_total=({k: totals[-1][k] for k in ("line_before", "line_after", "lam_before",
                                                          "lam_after", "dlam")} if totals else None))


def outcome(result):
    """Sporting outcome from a confirmed 90-minute score (not a bet settlement)."""
    h, a = result["home_goals"], result["away_goals"]
    tot = h + a
    return {"home_goals": h, "away_goals": a, "total_goals": tot,
            "OVER_2_5": tot >= 3, "UNDER_2_5": tot <= 2,
            "BTTS_YES": h > 0 and a > 0, "BTTS_NO": not (h > 0 and a > 0)}
