"""Frozen, two-source, fixture-specific *manual* reviews of three SportScore quarantines.

Investigated 2026-10-28. Public pages were inspected and explicitly identify
the teams in home/away order, the date and FT score. This is NOT an API or a
real-time lookup. Scores cannot transfer to another match_key or kickoff.
No score is supplied from the unreliable reversed SportScore fixture URL.
Never apply this registry to the H1 production results or picks.
"""
from urllib.parse import urlparse

# (original home, original away, original UTC kickoff, normal-time home goals,
#  normal-time away goals, primary URL, corroborating independent URL)
REVIEWED_PUBLIC_FT = {
    "2026-10-27,10102013,10048381": (
        "Montevideo City Torque Reserve", "Albion FC Reserves",
        "2026-10-27T13:00:00+00:00", 4, 0,
        "https://90sports.live/leagues/7715/reserve-league?lang=no",
        "https://m.aiscore.com/team-albion-fc-reserves/9gklzio4d3b17xd/matches",
    ),
    "2026-10-27,58630,10024258": (
        "Uganda Police FC", "Kigezi Homeboys FC",
        "2026-10-27T13:00:00+00:00", 3, 1,
        "https://upl.co.ug/event/police-fc-vs-kigezi-homeboyz-fc/",
        "https://www.scoresfeed.com/uganda-premier-league/police-uganda-vs-kigezi-homeboyz-2026-10-27/live-scores/",
    ),
    "2026-10-27,70933,35866": (
        "FK Ludogorets Razgrad B", "PFC Dobrudzha Dobrich",
        "2026-10-27T16:00:00+00:00", 5, 1,
        "https://www.fotmob.com/matches/dobrudzha-dobrich-vs-ludogorets-razgrad-ii/2t9em1i5",
        "https://footballfirst.com/football-live-centre/league/bulgaria-second-professional-league/6516/results",
    ),
}


def public_evidence_urls(match_key):
    row = REVIEWED_PUBLIC_FT.get(match_key)
    return [row[5], row[6]] if row else []


def verified_public_ft(signal):
    """Return audited FT only for the unchanged original match identity.

    Two separately operated HTTPS hosts, known at manual verification time,
    are mandatory. The reviewed record is a historical evidence snapshot.
    """
    if not isinstance(signal, dict):
        return None, "reviewed_public_invalid_signal"
    row = REVIEWED_PUBLIC_FT.get(signal.get("match_key"))
    if row is None:
        return None, "reviewed_public_no_fixture"
    if (signal.get("home"), signal.get("away"), signal.get("kickoff_utc")) != row[:3]:
        return None, "reviewed_public_identity_mismatch"
    h, a, primary, secondary = row[3:]
    urls = [urlparse(primary), urlparse(secondary)]
    if (type(h) is not int or type(a) is not int or
            not (0 <= h <= 30 and 0 <= a <= 30) or
            any(p.scheme != "https" or not p.hostname for p in urls) or
            urls[0].hostname == urls[1].hostname):
        return None, "reviewed_public_bad_evidence"
    return ({
        "match_key": signal["match_key"],
        "status": "final",
        "home_goals": h,
        "away_goals": a,
        "source": primary,
        "identity_match": "REVIEWED_PAIR",
    }, "reviewed_two_independent_public_ft")
