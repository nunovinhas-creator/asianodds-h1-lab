"""LAB-only ESPN scoreboard corroboration for explicitly mapped competitions.

ESPN is a public but unofficial/undocumented scoreboard endpoint. Fail closed:
only an exact ordered pair, corroborated kickoff and explicit full-time
regulation score is accepted. No fuzzy guesses or cup ET scores.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .results import norm_team

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
# Known exact competition -> ESPN league slugs. Never infer a competition
# from a prefix, team name or sport when mapping is absent.
LEAGUES = {
    "England League 1": "eng.3",
    "England Football League Trophy (EFL)": "eng.trophy",
    "England Football League Cup (EFL)": "eng.league_cup",
    "England National League": "eng.5",
    "Scotland FA Cup": "sco.tennents",
    "Spain Copa Del Rey": "esp.copa_del_rey",
    "Germany Cup (DFB Pokal)": "ger.dfb_pokal",
    "Netherlands KNVB Cup": "ned.cup",
    "Italy Serie A": "ita.1",
    "Italy Serie B": "ita.2",
    "Croatia Division 1 (HNL)": "cro.1",
    "Argentina Liga Profesional": "arg.1",
    "AFC Asian Champions League": "afc.champions",
}
# Mapping 'cro.1' isn't in the verified league source; exclude it rather
# than silently treating ESPN aliases as verified.
LEAGUES.pop("Croatia Division 1 (HNL)")
MAX_SCOREBOARDS = 16
NO_ET = re.compile(r"extra.?time|aet|after extra|penalt|shootout|spot kick|\bET\b", re.I)


def _utc(value):
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def _team(competitor):
    if not isinstance(competitor, dict):
        return ""
    team = competitor.get("team") or {}
    return team.get("displayName", "") if isinstance(team, dict) else ""


def _competitors(event):
    comps = event.get("competitions") if isinstance(event, dict) else None
    if not isinstance(comps, list) or len(comps) != 1:
        return None
    participants = comps[0].get("competitors") if isinstance(comps[0], dict) else None
    if not isinstance(participants, list) or len(participants) != 2:
        return None
    sides = {x.get("homeAway"): x for x in participants if isinstance(x, dict)}
    return sides if set(sides) == {"home", "away"} else None


def final_score(signal, event, slug):
    """Verified ESPN-only FT, rejecting ambiguous periods, AET and penalties."""
    if not isinstance(event, dict):
        return None, "invalid_event"
    sides = _competitors(event)
    if sides is None:
        return None, "missing_home_away"
    if not all(norm_team(_team(sides[side])) == norm_team(signal[side])
               for side in ("home", "away")):
        return None, "team_identity_mismatch"
    kickoff = _utc(signal.get("kickoff_utc"))
    when = _utc(event.get("date"))
    if kickoff is None or when is None or abs((kickoff-when).total_seconds()) > 90*60:
        return None, "kickoff_mismatch"
    status = event.get("status") or {}
    typ = status.get("type") if isinstance(status, dict) else None
    if not isinstance(typ, dict):
        return None, "status_unknown"
    if typ.get("completed") is not True:
        return None, "not_finished"
    # ESPN labels regulation as FT/Full Time. Completed alone does not prove
    # normal time, particularly in cup matches.
    descriptor = " ".join(str(typ.get(k) or "") for k in
                          ("name", "description", "detail", "shortDetail"))
    if NO_ET.search(descriptor):
        return None, "extra_time_penalties_unverified"
    if not (re.search(r"\bFT\b|full.?time", descriptor, re.I) and
            status.get("period") in (2, None)):
        return None, "normal_time_not_confirmed"
    try:
        scores = []
        for side in ("home", "away"):
            text = str(sides[side].get("score"))
            if not re.fullmatch(r"[0-9]{1,2}", text):
                return None, "invalid_score"
            scores.append(int(text))
    except (ValueError, TypeError):
        return None, "invalid_score"
    eid = str(event.get("id") or "")
    if not re.fullmatch(r"[0-9]{3,14}", eid):
        return None, "invalid_event_id"
    return {"match_key": signal["match_key"], "status": "final",
            "home_goals": scores[0], "away_goals": scores[1],
            "source": BASE + slug + "/summary?event=" + eid}, "verified_espn_ft"


def fetch_scoreboard(url):
    if not url.startswith(BASE) or "/scoreboard?" not in url:
        raise ValueError("Invalid ESPN URL")
    req = Request(url, headers={"Accept": "application/json",
                "User-Agent": "AsianOdds-LAB-Football-Research/1.0"})
    try:
        with urlopen(req, timeout=12) as response:
            if response.status != 200:
                raise OSError("Unexpected ESPN status")
            data = json.loads(response.read(2000000))
    except (HTTPError, URLError, OSError, ValueError, TimeoutError):
        raise OSError("ESPN scoreboard unavailable") from None
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("Invalid ESPN scoreboard")
    if len(data["events"]) > 150:
        raise ValueError("Unbounded ESPN scoreboard")
    return data["events"]


class ESPNResults:
    def __init__(self, competitions, *, fetch=fetch_scoreboard, max_scoreboards=12):
        if not isinstance(max_scoreboards, int) or not 0 <= max_scoreboards <= MAX_SCOREBOARDS:
            raise ValueError("Unsafe scoreboard budget")
        self.competitions = competitions
        self.fetch = fetch
        self.max_scoreboards = max_scoreboards
        self.cache = {}
        self.requests = 0
        self.reasons = Counter()

    def lookup(self, signal):
        competition = self.competitions.get(signal["match_key"], "")
        slug = LEAGUES.get(competition)
        if not slug:
            self.reasons["unsupported_competition"] += 1
            return None, "espn_unsupported_competition"
        dt = _utc(signal.get("kickoff_utc"))
        if dt is None:
            return None, "espn_invalid_kickoff"
        day = dt.strftime("%Y%m%d")
        key = (slug, day)
        if key not in self.cache:
            if self.requests >= self.max_scoreboards:
                self.reasons["budget_deferred"] += 1
                return None, "espn_budget_deferred"
            self.requests += 1
            try:
                self.cache[key] = self.fetch(BASE + slug + "/scoreboard?" + urlencode({"dates": day, "limit": 150}))
            except (ValueError, OSError):
                self.cache[key] = None
        events = self.cache[key]
        if events is None:
            self.reasons["unavailable"] += 1
            return None, "espn_unavailable"
        plausible = []
        for ev in events:
            sides = _competitors(ev)
            when = _utc(ev.get("date")) if isinstance(ev, dict) else None
            if not sides or not when or abs((when-dt).total_seconds()) > 90*60:
                continue
            if all(norm_team(_team(sides[side])) == norm_team(signal[side])
                   for side in ("home", "away")):
                plausible.append(ev)
        if len(plausible) != 1:
            reason = "espn_no_exact_match" if not plausible else "espn_ambiguous_match"
            self.reasons[reason] += 1
            return None, reason
        result, reason = final_score(signal, plausible[0], slug)
        self.reasons[reason] += 1
        return result, reason

    def summary(self):
        return {"requests": self.requests, "cached_league_days": len(self.cache),
                "confirmed_in_run": self.reasons["verified_espn_ft"],
                "reason_counts": dict(sorted(self.reasons.items()))}
