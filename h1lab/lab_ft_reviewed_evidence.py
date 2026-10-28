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


# Additional 2026-10-27 overdue fixtures independently corroborated on
# 2026-10-28. Strictly normal-time 90m results, NOT AET/penalties.
# Key -> original home, original away, UTC kickoff, 90m home/away,
#        primary and corroboration URLs. These matches were observed and
#        PENDING before documentary review, not SOURCE_ORDER_CONFLICT.
REVIEWED_PENDING_FT = {
    # 28/10 17:40 UTC manual public comparison; strict original AsianOdds
    # identity, independently corroborated 90-minute result, no fuzzy alias.
    "2026-10-27,10030127,75": (
        "Loughborough University", "Rushden and Diamonds",
        "2026-10-27T19:45:00+00:00", 1, 0,
        "https://lborostudentsfc.co.uk/",
        "https://www.footballwebpages.co.uk/dorchester-town/loughborough-students",
    ),
    "2026-10-27,59193,10052416": (
        "Cerro Largo FC Reserves", "La Luz Reserves",
        "2026-10-27T18:00:00+00:00", 3, 2,
        "https://betimate.com/en/football-predictions/cerro-largo-reserves-vs-la-luz-reserves/2026-10-27/game",
        "https://offsidescores.com/pt/futebol/equipa/cerro-largo-fc-reservas/51da78fd-2f07-4b2d-a089-223d0c583f9b/detalhe",
    ),
    "2026-10-27,23683,747": (
        "FK Fakel Voronezh", "FK Akhmat Grozny",
        "2026-10-27T15:00:00+00:00", 0, 0,
        "https://www.flashfootball.com/match/akhmat-grozny-bJGqkoet/fakel-voronezh-KK7VWueJ/",
        "https://footballnation.eu/match/beker-van-rusland/2026/795294/",
    ),
    "2026-10-27,25153,62798": (
        "Alanyaspor", "12 Bingol spor",
        "2026-10-27T17:30:00+00:00", 4, 1,
        "https://www.alanyaspor.org.tr/Haber/corendon-alanyasporumuz--12-bingolspor-4-1",
        "https://www.fotmob.com/matches/alanyaspor-vs-12-bingolspor/2707wwqp",
    ),
    "2026-10-27,31960,1154": (
        "BVV Barendrecht", "RKC Waalwijk",
        "2026-10-27T19:00:00+00:00", 1, 1,
        "https://www.omroepbrabant.nl/nieuws/6032644/rkc-waalwijk-wint-na-strafschoppen-in-knvb-beker",
        "https://www.reddit.com/r/soccer/comments/1xh3pi4/match_thread_bvv_barendrecht_vs_rkc_waalwijk/",
    ),
    "2026-10-27,38744,1566": (
        "vv Kloetinge", "SC Cambuur Leeuwarden",
        "2026-10-27T19:00:00+00:00", 0, 2,
        "https://www.sofascore.com/it/football/match/vv-kloetinge-sc-cambuur/vjbsNjb",
        "https://omroepleeuwarden.nl/cambuur-bekert-verder-maar-maakt-het-zichzelf-onnodig-moeilijk/",
    ),
    "2026-10-27,327,326": (
        "University College Dublin AFC", "Longford Town FC",
        "2026-10-27T19:45:00+00:00", 2, 0,
        "https://www.rte.ie/sport/soccer/2026/1027/1597020-ucd-dispatch-longford-to-book-semi-final-date-with-bray/",
        "https://www.shannonside.ie/index.php/sport/ucd-finish-off-longford-promotion-hopes-299980",
    ),
    "2026-10-27,10068586,24722": (
        "SPG Wels", "Wolfsberger AC",
        "2026-10-27T17:30:00+00:00", 1, 0,
        "https://www.oefb.at/cup",
        "https://www.ligaportal.at/bundesliga/spielberichte/22780-erster-bundesligist-im-oefb-cup-raus-2-ligist-fc-hertha-wels-besiegt-wac",
    ),
    "2026-10-27,10085234,32260": (
        "Inter Milano U23", "SS Scafatese Calcio 1922",
        "2026-10-27T13:30:00+00:00", 2, 1,
        "https://www.inter.it/en/news/inter-u23-scafatese-serie-c-2026-27",
        "https://flashsportapp.com/en/football/match/inter-u23-scafatese-2026-10-27-1609066/",
    ),
    "2026-10-27,26873,26901": (
        "Al Shamal SC", "Al Hilal (KSA)",
        "2026-10-27T18:15:00+00:00", 3, 1,
        "https://alhilal.com/en/news/al-hilal-loses-to-qatars-al-shamal-in-afc-champions-league-elite",
        "https://www.365scores.com/football/match/afc-champions-league-elite-623/al-hilal-riyadh-al-shamal-5457-7081-623",
    ),
    "2026-10-27,29242,53546": (
        "CA Peñarol", "CA Torque",
        "2026-10-27T22:30:00+00:00", 0, 2,
        "https://www.elpais.com.uy/ovacion/futbol/penarol-vs-city-torque-en-vivo-por-la-copa-auf-uruguay-segui-el-minuto-a-minuto-y-como-va-el-partido",
        "https://www.besoccer.com/match/penarol-montevideo/torque/2027247946",
    ),
    "2026-10-27,39759,696": (
        "ACD Virtus Entella", "Calcio Avellino SSD",
        "2026-10-27T19:00:00+00:00", 1, 1,
        "https://www.legab.it/seriebkt/calendario/2026-2027/stagione-regolare/v-entella",
        "https://www.fotmob.com/en-GB/matches/avellino-vs-virtus-entella/aokhvwn",
    ),
}


def public_evidence_urls(match_key):
    row = REVIEWED_PUBLIC_FT.get(match_key) or REVIEWED_PENDING_FT.get(match_key)
    return [row[5], row[6]] if row else []


def verified_public_ft(signal):
    """Return audited FT only for the unchanged original match identity.

    Two separately operated HTTPS hosts, known at manual verification time,
    are mandatory. The reviewed record is a historical evidence snapshot.
    """
    if not isinstance(signal, dict):
        return None, "reviewed_public_invalid_signal"
    row = (REVIEWED_PUBLIC_FT.get(signal.get("match_key")) or
           REVIEWED_PENDING_FT.get(signal.get("match_key")))
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
