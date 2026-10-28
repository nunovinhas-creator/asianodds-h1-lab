"""Per-match chronology of observed Telegram alerts (read-only, shadow LAB).

Layers kept separate on purpose:

    Telegram message -> odds snapshot(s) -> market movement -> match trajectory
                                                       -> (eventual result, not here)

* Every input alert is preserved. Nothing is deleted or merged; a suspected
  redundancy is an annotation for analysis only.
* Values explicitly parsed by V4 (``V4_EXPLICIT``) are never mixed with values
  that exist only in the H1 legacy record (``H1_LEGACY_ONLY``). When both exist
  for the same message, agreement is reported, never averaged.
* No price is invented between two alerts. A line difference between the
  ``after`` of one alert and the ``before`` of the next is an *unobserved*
  change, not a continuous price history.
* The unit for any later betting evaluation is the match, not the message.

This module imports nothing from the H1 production modules.
"""
from __future__ import annotations
from .lab_archive import monthly_paths

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
STATUS = "DESCRIPTIVE_SHADOW_AUDIT_NOT_CERTIFIED"
V4 = "V4_EXPLICIT"
LEGACY = "H1_LEGACY_ONLY"
TABLES = {
    "total": ("line", "over_price", "under_price"),
    "asian_handicap": ("line", "home_price", "away_price"),
}
SELECTIONS = ("1", "X", "2")
MARKETS = ("total", "asian_handicap", "one_x_two")
DEFAULT_NEAR_SECONDS = 120
DEFAULT_MAX_TIMELINES = 400


# --------------------------------------------------------------------------
# Small validated primitives

def utc(value):
    """Timezone-aware ISO timestamp -> aware UTC datetime, else None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def number(value, kind):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v):
        return None
    if kind == "line":
        return v if abs(v * 4 - round(v * 4)) < 1e-7 else None
    return v if 1 < v < 1000 else None


def message_number(event_id):
    tail = event_id.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


# --------------------------------------------------------------------------
# Message -> snapshots

def _table(before, after, fields):
    out = {"before": {}, "after": {}}
    for side, src in (("before", before), ("after", after)):
        if not isinstance(src, dict):
            return None
        for f in fields:
            v = number(src.get(f), "line" if f == "line" else "price")
            if v is None:
                return None
            out[side][f] = v
    return out


def _one_x_two(raw):
    if not isinstance(raw, dict):
        return None
    out = {}
    for sel in SELECTIONS:
        pair = raw.get(sel)
        if not isinstance(pair, dict):
            return None
        b, a = number(pair.get("before"), "price"), number(pair.get("after"), "price")
        if b is None or a is None:
            return None
        out[sel] = {"before": b, "after": a}
    return out


def v4_snapshots(row):
    markets = row.get("markets") if isinstance(row, dict) else None
    if not isinstance(markets, dict):
        return {}
    found = {}
    for kind, fields in TABLES.items():
        t = markets.get(kind)
        if isinstance(t, dict):
            snap = _table(t.get("before"), t.get("after"), fields)
            if snap:
                found[kind] = snap
    x = _one_x_two(markets.get("one_x_two"))
    if x:
        found["one_x_two"] = x
    return found


def legacy_snapshots(alert):
    """Values present in the H1 record only (never independent validation)."""
    found = {}
    total = _table({"line": alert.get("total_before"), "over_price": alert.get("over_before"),
                    "under_price": alert.get("under_before")},
                   {"line": alert.get("total_after"), "over_price": alert.get("over_after"),
                    "under_price": alert.get("under_after")}, TABLES["total"])
    if total:
        found["total"] = total
    ah = alert.get("asian_handicap")
    if isinstance(ah, dict):
        conv = {}
        for side in ("before", "after"):
            src = ah.get(side) if isinstance(ah.get(side), dict) else {}
            conv[side] = {"line": src.get("line"), "home_price": src.get("home_odds"),
                          "away_price": src.get("away_odds")}
        snap = _table(conv["before"], conv["after"], TABLES["asian_handicap"])
        if snap:
            found["asian_handicap"] = snap
    x = _one_x_two(alert.get("one_x_two"))
    if x:
        found["one_x_two"] = x
    return found


def signature(kind, snap):
    if kind == "one_x_two":
        return tuple(snap[s][side] for s in SELECTIONS for side in ("before", "after"))
    return tuple(snap[side][f] for side in ("before", "after") for f in TABLES[kind])


def differing_fields(kind, a, b):
    if kind == "one_x_two":
        return [s + "." + side for s in SELECTIONS for side in ("before", "after")
                if not math.isclose(a[s][side], b[s][side], abs_tol=1e-9)]
    return [side + "." + f for side in ("before", "after") for f in TABLES[kind]
            if not math.isclose(a[side][f], b[side][f], abs_tol=1e-9)]


def build_observation(event_id, alert, v4_row):
    """One Telegram message with its snapshots and their explicit origin."""
    legacy = legacy_snapshots(alert) if alert else {}
    explicit = v4_snapshots(v4_row) if v4_row else {}
    snapshots, agreement = {}, {}
    for kind in MARKETS:
        if kind in explicit:
            snapshots[kind] = {"origin": V4, **explicit[kind]}
            if kind in legacy:
                diff = differing_fields(kind, explicit[kind], legacy[kind])
                agreement[kind] = {"status": "AGREE" if not diff else "DIFFER",
                                   "fields": diff}
        elif kind in legacy:
            snapshots[kind] = {"origin": LEGACY, **legacy[kind]}
    trigger = (v4_row or {}).get("trigger") if v4_row else None
    trigger_market = ((v4_row or {}).get("trigger_market") if v4_row else None) or \
        (alert or {}).get("market") or "unknown"
    keys = {k for k in ((alert or {}).get("match_key"), (v4_row or {}).get("match_key"))
            if isinstance(k, str) and k}
    kickoffs = {iso(t) for t in (utc((alert or {}).get("kickoff_utc")),
                                  utc((v4_row or {}).get("kickoff_utc"))) if t}
    obs = {
        "event_id": event_id,
        "message_id": message_number(event_id),
        "sources": (["H1_RECORD"] if alert else []) + (["V4_RECORD"] if v4_row else []),
        "trigger_market": "1x2" if trigger_market == "1x2" else
                          "total" if trigger_market == "total" else "unknown",
        "snapshots": snapshots,
    }
    if isinstance(trigger, dict) and trigger.get("market") == "1x2":
        obs["trigger_selection"] = trigger.get("selection")
        # Shown by Telegram; formula not validated. Never a predictive variable.
        obs["trigger_displayed_pct_unvalidated"] = trigger.get("pct")
    if agreement:
        obs["v4_vs_h1_record"] = agreement
    if len(keys) > 1:
        obs["identity_conflict"] = {"match_keys": sorted(keys)}
    if len(kickoffs) > 1:
        obs.setdefault("identity_conflict", {})["kickoff_utc"] = sorted(kickoffs)
    return obs, (sorted(keys)[0] if keys else None), (sorted(kickoffs)[0] if kickoffs else None)


# --------------------------------------------------------------------------
# Snapshots over time -> movements and trajectory

def _direction(delta):
    return "UP" if delta > 1e-9 else "DOWN" if delta < -1e-9 else "FLAT"


def line_trajectory(events, kind, related=frozenset()):
    """Observed line points only. Gaps are explicit, never interpolated.

    ``related`` holds frozensets of event-id pairs suspected to describe the
    same movement; such a pair is a re-observation, not a new move.
    """
    seq = [e for e in events if kind in e["snapshots"]]
    if not seq:
        return None
    points, moves, transitions = [], [], []
    for i, e in enumerate(seq):
        s = e["snapshots"][kind]
        b, a = s["before"]["line"], s["after"]["line"]
        points.append({"event_id": e["event_id"], "before": b, "after": a,
                       "origin": s["origin"], "move": _direction(a - b)})
        prev = seq[i - 1] if i else None
        p = prev["snapshots"][kind] if prev else None
        repeat = bool(prev) and frozenset((prev["event_id"], e["event_id"])) in related
        same_lines = bool(prev) and (p["before"]["line"], p["after"]["line"]) == (b, a)
        if prev:  # the gap precedes this message's own before->after move
            pa = p["after"]["line"]
            item = {"from": prev["event_id"], "to": e["event_id"],
                    "previous_after_line": pa, "next_before_line": b}
            if repeat:
                item["line"] = "SAME_MOVEMENT_REPEAT"
            elif pa == b:
                item["line"] = "CONTINUOUS"
                same = all(math.isclose(p["after"][f], s["before"][f], abs_tol=1e-9)
                           for f in TABLES[kind][1:])
                item["prices_at_line"] = "UNCHANGED" if same else "CHANGED_UNOBSERVED"
            elif same_lines and a != b:
                # Same before->after lines again, outside the redundancy rule:
                # overlapping report windows or a back-and-forth; undecidable.
                item["line"] = "AMBIGUOUS_REPEAT_OR_REVERSAL"
            else:
                item["line"] = "UNOBSERVED_CHANGE"
                item["unobserved_direction"] = _direction(b - pa)
                moves.append((e["event_id"], "gap", b - pa))
            transitions.append(item)
        if a != b and not repeat and not same_lines:
            moves.append((e["event_id"], "intra", a - b))
    reversals = []
    for (e1, k1, d1), (e2, k2, d2) in zip(moves, moves[1:]):
        if (d1 > 0) != (d2 > 0):
            reversals.append({"after_event": e1, "at_event": e2,
                              "from": _direction(d1), "to": _direction(d2),
                              "evidence": k2})
    first, last = points[0]["before"], points[-1]["after"]
    return {"observations": len(points), "points": points, "transitions": transitions,
            "reversals": reversals, "first_observed_line": first,
            "last_observed_line": last, "net_observed_change": last - first,
            "origins": dict(Counter(p["origin"] for p in points))}


def one_x_two_trajectory(events):
    seq = [e for e in events if "one_x_two" in e["snapshots"]]
    if not seq:
        return None
    points, transitions = [], []
    for i, e in enumerate(seq):
        s = e["snapshots"]["one_x_two"]
        points.append({"event_id": e["event_id"], "origin": s["origin"],
                       **{sel: [s[sel]["before"], s[sel]["after"]] for sel in SELECTIONS}})
        if i:
            p = seq[i - 1]["snapshots"]["one_x_two"]
            changed = [sel for sel in SELECTIONS
                       if not math.isclose(p[sel]["after"], s[sel]["before"], abs_tol=1e-9)]
            transitions.append({"from": seq[i - 1]["event_id"], "to": e["event_id"],
                                "prices": "UNCHANGED" if not changed else "CHANGED_UNOBSERVED",
                                "changed_selections": changed})
    return {"observations": len(points), "points": points, "transitions": transitions,
            "origins": dict(Counter(p["origin"] for p in points))}


def relate(a, b, near_seconds):
    """Classify how two messages of one match relate. Never a deletion rule."""
    seconds = (utc(b["observed_at"]) - utc(a["observed_at"])).total_seconds()
    shared = [k for k in MARKETS if k in a["snapshots"] and k in b["snapshots"]]
    identical = [k for k in shared if signature(k, a["snapshots"][k]) ==
                 signature(k, b["snapshots"][k])]
    if "total" not in shared or seconds > near_seconds:
        return None
    ta, tb = a["snapshots"]["total"], b["snapshots"]["total"]
    same_lines = (ta["before"]["line"], ta["after"]["line"]) == \
                 (tb["before"]["line"], tb["after"]["line"])
    if "total" in identical:
        strength = "IDENTICAL_TOTAL_SNAPSHOT"
    elif same_lines and ta["before"]["line"] != ta["after"]["line"]:
        # Same line move reported again seconds later with slightly different
        # prices: plausibly one movement, but NOT a redundant snapshot.
        strength = "SAME_TOTAL_LINE_MOVE_DIFFERENT_PRICES"
    else:
        return None
    same_trigger = a["trigger_market"] == b["trigger_market"]
    return {
        "events": [a["event_id"], b["event_id"]],
        "separation_seconds": seconds,
        "evidence": strength,
        "identical_markets": identical,
        "shared_markets": shared,
        "total_fields_differing": differing_fields("total", ta, tb),
        "trigger_markets": [a["trigger_market"], b["trigger_market"]],
        "classification": ("REPEATED_SNAPSHOT_SAME_TRIGGER" if same_trigger else
                           "SAME_MOVEMENT_DIFFERENT_MESSAGE"),
        "possibly_redundant_snapshot": strength == "IDENTICAL_TOTAL_SNAPSHOT",
        "mixed_origin": ta["origin"] != tb["origin"],
        "action": "ANNOTATE_ONLY_NEVER_DELETE",
    }


def episodes(events, relations):
    """Connected components of 'possibly the same movement'. Upper bound only."""
    parent = {e["event_id"]: e["event_id"] for e in events}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in relations:
        a, b = map(root, r["events"])
        if a != b:
            parent[b] = a
    groups = {}
    for e in events:
        groups.setdefault(root(e["event_id"]), []).append(e["event_id"])
    return list(groups.values())


def match_timeline(match_key, events, *, near_seconds, identities):
    events.sort(key=lambda e: (e["observed_at"], e["message_id"] or 0, e["event_id"]))
    relations = []
    for i, cur in enumerate(events):
        for prev in reversed(events[:i]):
            gap = (utc(cur["observed_at"]) - utc(prev["observed_at"])).total_seconds()
            if gap > near_seconds:
                break
            r = relate(prev, cur, near_seconds)
            if r:
                relations.append(r)
                break  # link to nearest qualifying predecessor only
    groups = episodes(events, relations)
    related = frozenset(frozenset(r["events"]) for r in relations)
    names = sorted({(i.get("home") or "", i.get("away") or "") for i in identities})
    kickoffs = sorted({k for k in (i.get("kickoff_utc") for i in identities) if k})
    gaps = [(utc(b["observed_at"]) - utc(a["observed_at"])).total_seconds()
            for a, b in zip(events, events[1:])]
    first_ko = utc(kickoffs[0]) if kickoffs else None
    for e in events:
        if first_ko:
            e["minutes_to_kickoff"] = round((first_ko - utc(e["observed_at"])).total_seconds() / 60, 1)
    out = {
        "match_key": match_key,
        "match_label": (names[0][0] + " vs " + names[0][1]) if names else match_key,
        "event_count": len(events),
        "event_ids": [e["event_id"] for e in events],
        "first_observed_at": events[0]["observed_at"],
        "last_observed_at": events[-1]["observed_at"],
        "seconds_between_messages": gaps,
        "identity": {"team_names_consistent": len(names) <= 1,
                     "kickoff_consistent": len(kickoffs) <= 1,
                     "kickoff_utc": kickoffs,
                     "per_message_conflicts": [e["event_id"] for e in events
                                               if "identity_conflict" in e]},
        "events": events,
        "trajectory": {k: v for k, v in (
            ("total", line_trajectory(events, "total", related)),
            ("asian_handicap", line_trajectory(events, "asian_handicap", related)),
            ("one_x_two", one_x_two_trajectory(events))) if v},
        "related_messages": relations,
        "possibly_redundant_event_ids": sorted({r["events"][1] for r in relations
                                                if r["possibly_redundant_snapshot"]}),
        "movement_episodes": groups,
        "movement_episodes_upper_bound": len(groups),
        "post_kickoff_messages": sum(1 for e in events
                                     if e.get("minutes_to_kickoff") is not None
                                     and e["minutes_to_kickoff"] < 0),
    }
    return out


# --------------------------------------------------------------------------
# Whole report

def collect_timelines(alerts, market_rows, *, near_seconds=DEFAULT_NEAR_SECONDS, source_errors=()):
    """Every match timeline (single-message matches included) plus issues.

    Shared by the published chronology and by the LAB pattern engine, so both
    use exactly the same message -> snapshot -> movement -> match logic.
    """
    if not isinstance(near_seconds, (int, float)) or isinstance(near_seconds, bool) or near_seconds < 0:
        raise ValueError("near_seconds must be a non-negative number")
    issues = list(source_errors)
    legacy, v4 = {}, {}
    for source, rows, target in (("h1_state", alerts, legacy), ("v4", market_rows, v4)):
        for row in rows:
            eid = row.get("event_id") if isinstance(row, dict) else None
            if not isinstance(eid, str) or not eid:
                issues.append({"type": "missing_event_id", "source": source})
                continue
            if eid in target:
                issues.append({"type": "duplicate_event_id", "source": source, "event_id": eid,
                               "identical": target[eid] == row})
                continue
            target[eid] = row
    groups, identities = {}, {}
    excluded = []
    for eid in sorted(set(legacy) | set(v4)):
        alert, row = legacy.get(eid), v4.get(eid)
        when = utc((alert or {}).get("observed_at")) or utc((row or {}).get("observed_at"))
        if alert and row and utc(alert.get("observed_at")) != utc(row.get("observed_at")):
            issues.append({"type": "observed_at_conflict", "event_id": eid})
        obs, key, kickoff = build_observation(eid, alert, row)
        if when is None or key is None:
            excluded.append(eid)
            issues.append({"type": "excluded_unusable_identity_or_time", "event_id": eid})
            continue
        obs["observed_at"] = iso(when)
        if alert and alert.get("match_key"):
            key = alert["match_key"]  # H1 identity is the stable production key
        groups.setdefault(key, []).append(obs)
        identities.setdefault(key, []).append({"home": (alert or {}).get("home"),
                                               "away": (alert or {}).get("away"),
                                               "kickoff_utc": kickoff})
    timelines = [match_timeline(k, v, near_seconds=near_seconds, identities=identities[k])
                 for k, v in groups.items()]
    return timelines, issues, excluded


def build_report(alerts, market_rows, *, near_seconds=DEFAULT_NEAR_SECONDS,
                 max_timelines=DEFAULT_MAX_TIMELINES, source_errors=()):
    if not isinstance(near_seconds, (int, float)) or isinstance(near_seconds, bool) or near_seconds < 0:
        raise ValueError("near_seconds must be a non-negative number")
    if not isinstance(max_timelines, int) or max_timelines < 0:
        raise ValueError("max_timelines must be a non-negative integer")
    timelines, issues, excluded = collect_timelines(
        alerts, market_rows, near_seconds=near_seconds, source_errors=source_errors)
    repeated = [t for t in timelines if t["event_count"] > 1]
    repeated.sort(key=lambda t: (t["last_observed_at"], t["match_key"]), reverse=True)
    published = repeated[:max_timelines]
    relations = [r for t in timelines for r in t["related_messages"]]
    obs_all = [e for t in timelines for e in t["events"]]
    origin_counts = Counter(s["origin"] for e in obs_all for s in e["snapshots"].values())
    agreement = Counter((k, v["status"]) for e in obs_all
                        for k, v in (e.get("v4_vs_h1_record") or {}).items())
    total_traj = [t["trajectory"]["total"] for t in repeated if "total" in t["trajectory"]]
    transitions = Counter(x["line"] for tr in total_traj for x in tr["transitions"])
    summary = {
        "messages": len(obs_all),
        "messages_excluded": len(excluded),
        "matches": len(timelines),
        "repeated_matches": len(repeated),
        "messages_on_repeated_matches": sum(t["event_count"] for t in repeated),
        "max_messages_per_match": max((t["event_count"] for t in timelines), default=0),
        "related_message_pairs": len(relations),
        "related_pairs_by_class": dict(Counter(r["classification"] for r in relations)),
        "related_pairs_by_evidence": dict(Counter(r["evidence"] for r in relations)),
        "possibly_redundant_snapshots": sum(r["possibly_redundant_snapshot"] for r in relations),
        "related_pairs_mixed_origin": sum(r["mixed_origin"] for r in relations),
        "movement_episodes_upper_bound": sum(t["movement_episodes_upper_bound"] for t in timelines),
        "snapshots_by_origin": dict(origin_counts),
        "messages_with_v4": sum("V4_RECORD" in e["sources"] for e in obs_all),
        "messages_h1_only": sum(e["sources"] == ["H1_RECORD"] for e in obs_all),
        "messages_v4_only": sum(e["sources"] == ["V4_RECORD"] for e in obs_all),
        "v4_vs_h1_record_agreement": {k + ":" + s: n for (k, s), n in sorted(agreement.items())},
        "total_line_transitions_on_repeated": dict(transitions),
        "total_line_reversals_on_repeated": sum(len(t["reversals"]) for t in total_traj),
        "matches_with_identity_inconsistency": sum(
            1 for t in timelines if not (t["identity"]["team_names_consistent"] and
                                         t["identity"]["kickoff_consistent"])
            or t["identity"]["per_message_conflicts"]),
        "post_kickoff_messages": sum(t["post_kickoff_messages"] for t in timelines),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "evaluation_unit": "match (match_key); messages and snapshots are not independent trials",
        "parameters": {"near_seconds": near_seconds, "max_timelines": max_timelines,
                       "redundancy_rule": "same match_key, identical six Total cells, "
                                          "separation <= near_seconds; annotate only"},
        "summary": summary,
        "sampling": {"timelines_published": len(published),
                     "timelines_omitted": len(repeated) - len(published),
                     "order": "most recent last_observed_at first",
                     "single_message_matches_detail": "counted, not listed"},
        "timelines": published,
        "issues": issues[:200],
        "issue_count": len(issues),
        "issue_counts": dict(Counter(i["type"] for i in issues)),
        "limitations": [
            "Only messages published by the Telegram channel are observed; no continuous price feed.",
            "A line difference between two alerts is an unobserved change, never interpolated.",
            "Identical Total snapshots seconds apart are a redundancy suspicion, not proof.",
            "1X2 and Total messages about one move are correlated; do not count them as independent trials.",
            "H1_LEGACY_ONLY values are not independent validation of the V4 parser.",
            "Telegram's displayed 1X2 percentage has an unvalidated formula; not a predictive variable.",
            "No Telegram text, screenshots or credentials are stored in this report.",
            "No betting recommendation, ROI or profitability follows from this report.",
        ],
    }


def read_jsonl(path):
    rows, errors = [], []
    for n, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("not an object")
            rows.append(value)
        except (UnicodeDecodeError, ValueError):
            errors.append({"type": "invalid_jsonl", "source": path.name, "line": n})
    return rows, errors


def read_sources(root):
    """(alerts, V4 rows, source errors) from the tracked repository files."""
    root = Path(root)
    state = json.loads((root / "data" / "state.json").read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("alerts"), list):
        raise ValueError("state.json must contain an alerts list")
    rows, errors = [], []
    for path in monthly_paths(root, "markets"):
        r, e = read_jsonl(path)
        rows += r
        errors += e
    return state["alerts"], rows, errors


def generate(root, **options):
    alerts, rows, errors = read_sources(root)
    return build_report(alerts, rows, source_errors=errors, **options)
