"""BSD LAB-only response compatibility, based on Monte-Carlos settlement parsing.

The BSD docs use a flat list and flat event detail today. The user's already
working Monte-Carlos settlement additionally handles nested data/result detail
and numeric-string regulation scores. Keep this adapter scoped to LAB, to
avoid altering the H1 matching/settlement implementation.

No extra calls, no implicit final state, no guessed score from generic
'post-penalties' totals. Reject all ambiguous or incomplete score fields.
"""
from __future__ import annotations
import re


def _unpack(value):
    if not isinstance(value, dict):
        return value
    for _ in range(2):
        nested = value.get("data")
        if isinstance(nested, dict):
            value = nested
            continue
        nested = value.get("result")
        if (isinstance(nested, dict)
                and not any(f in value for f in ("results", "id", "home_team"))):
            value = nested
            continue
        break
    return value


def _score(value):
    if type(value) is int and 0 <= value <= 99:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,2}", value):
        return int(value)
    return None


def normalized_detail(payload):
    """Conservatively normalize only an already retrieved BSD fixture detail."""
    event = _unpack(payload)
    if not isinstance(event, dict):
        return event
    event = dict(event)
    status = event.get("status")
    if isinstance(status, dict):
        for key in ("type", "code", "name", "short_name", "description"):
            if status.get(key) is not None:
                status = status[key]
                break
    if isinstance(status, str):
        # No automatic AET/PEN normal-time inference.
        if status.strip().casefold() in (
            "finished", "ft", "ended", "completed", "complete",
            "closed", "full-time", "fulltime"):
            event["status"] = "finished"
    ident = event.get("id")
    if isinstance(ident, str) and re.fullmatch(r"[1-9][0-9]{0,13}", ident):
        event["id"] = int(ident)
    home, away = event.get("home_score"), event.get("away_score")
    if home is None and away is None:
        # Only fields explicitly marked FT/regulation; generic score could
        # represent a 120-minute total or penalty shootout.
        for field in ("ft_score", "full_time_score", "scores"):
            part = event.get(field)
            if field == "scores" and isinstance(part, dict):
                part = part.get("fulltime") or part.get("full_time") or part.get("regulation")
            if not isinstance(part, dict):
                continue
            for h,a in (("home","away"),("home_score","away_score"),
                        ("full_time_home","full_time_away")):
                if h in part and a in part:
                    home, away = part.get(h), part.get(a)
                    break
            if home is not None or away is not None:
                break
    if home is not None or away is not None:
        event["home_score"] = _score(home)
        event["away_score"] = _score(away)
    return event


def normalized_payload(payload):
    """Preserve pagination and normalize event items, without guessing completeness."""
    root = _unpack(payload)
    if not isinstance(root, dict):
        return root
    if isinstance(root.get("results"), list):
        root = dict(root)
        root["results"] = [normalized_detail(ev) for ev in root["results"]]
        return root
    return normalized_detail(root)
