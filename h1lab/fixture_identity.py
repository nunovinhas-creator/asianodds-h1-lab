"""Conservative H1 admission: preserve contradictory observations outside picks.

Quarantine is permanent evidence, not an alias or a calendar correction. V4
continues to journal the source observations independently.
"""
FIELDS = ("home", "away", "kickoff_utc")
REASON = "FIXTURE_IDENTITY_CONFLICT"


def identity(alert):
    return tuple(alert.get(k) for k in FIELDS)


def blocked_keys(state):
    return {q["alert"]["match_key"] for q in state.get("fixture_quarantine", [])}


def established(state, alert):
    return sorted({r.get("event_id", r.get("signal_id"))
                   for field in ("alerts", "signals") for r in state[field]
                   if r["match_key"] == alert["match_key"]
                   and identity(r) != identity(alert)})


def quarantine(state, alert, known_at):
    against = established(state, alert)
    if not against:
        return False
    state.setdefault("fixture_quarantine", []).append({
        "event_id": alert["event_id"], "reason": REASON, "known_at": known_at,
        "against_event_ids": against, "alert": alert})
    return True


def validate(state):
    rows = state.get("fixture_quarantine", [])
    if not isinstance(rows, list):
        raise ValueError("Invalid fixture quarantine")
    active = {a["event_id"] for a in state["alerts"]}
    seen = set()
    for q in rows:
        a = q["alert"]
        eid = q["event_id"]
        if (not isinstance(eid, str) or eid != a["event_id"] or eid in seen
                or eid in active or q["reason"] != REASON or not q["known_at"]
                or any(not isinstance(v, str) or not v for v in identity(a))
                or not q["against_event_ids"]
                or not set(q["against_event_ids"]) <= set(established(state, a))):
            raise ValueError("Invalid fixture quarantine evidence")
        seen.add(eid)
