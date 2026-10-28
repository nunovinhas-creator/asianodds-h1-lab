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
    # Documentary 28/10 batch: match_key + ORIGINAL AsianOdds home/away/KO.
    # Source order is the original game, not the provider's display order.
    # Strict 90-minute score, independently cross-checked, never AET/penalties.
    # CAUTION: Karsspor and Kars 36 Spor are distinct clubs; that candidate
    # is NOT included despite an apparent provider identity match.
    "2026-10-28,30921,29839": (
        "Alianza FC (SLV)", "CD Marathón",
        "2026-10-28T02:00:00+00:00", 0, 0,
        "https://www.concacaf.com/competitions/central-american-cup/news/marathon-clinch-2027-champions-cup-spot",
        "https://futbolcentroamerica.com/noticias/alianza-quedo-eliminado-de-la-copa-centroamericana-y-no-clasifico-a-la-concachampions-2027-aYyN65b5szZs",
    ),
    "2026-10-28,50151,10045457": (
        "Silivrispor", "Beyoglu Yeni Carsiz",
        "2026-10-28T10:30:00+00:00", 3, 2,
        "https://www.tff.org/default.aspx?ftxtID=2966&pageID=600",
        "https://www.kamu1.net/mac/silivrispor-beyoglu-yeni-carsi-fk-28-ekim-2026",
    ),
    "2026-10-28,31269,31927": (
        "Menemen Belediyespor", "Karacabey Belediyespor",
        "2026-10-28T10:30:00+00:00", 0, 1,
        "https://www.tff.org/default.aspx?ftxtID=2966&pageID=600",
        "https://www.canligaste.com/sonuc-menemen-fk-karacabey-birlikspor-90-dakika-tamamlandi-0-1/937732/",
    ),
    "2026-10-28,40595,28192": (
        "FK Teleoptik Zemun", "FK Mladost Lučani",
        "2026-10-28T12:00:00+00:00", 1, 1,
        "https://www.tanjug.rs/sport/fudbal/293293/fudbaleri-teleoptika-posle-penala-izbacili-lucansku-mladost-iz-kupa-srbije/vest",
        "https://hotsport.rs/2026/10/28/teleoptik-mladost-kup-srbije-penali/",
    ),
    "2026-10-28,10055256,84215": (
        "Adana 1954 FK", "Kutahyaspor",
        "2026-10-28T12:00:00+00:00", 1, 1,
        "https://www.tff.org/default.aspx?ftxtID=2966&pageID=600",
        "https://www.kutahyaninsesi.com/haber/29065209/kutahyaspor-uzatmalara-gitti-kritik-dakikalar-basladi",
    ),
    "2026-10-28,33305,10030821": (
        "Balikesirspor", "Arnavutkoy Genclik Spor",
        "2026-10-28T12:00:00+00:00", 1, 0,
        "https://www.tff.org/default.aspx?ftxtID=2966&pageID=600",
        "https://www.canligaste.com/sonuc-balikesirspor-arnavutkoy-belediyespor-90-dakika-tamamlandi-1-0/937834/",
    ),
    # Manual independent public-source review (28/10 evening UTC).
    # The string home/away/kickoff MUST match the original AsianOdds fixture.
    # SOURCE CHECKS: Nagoya 1-1 and Puszcza 1-1 at 90 minutes only;
    # the 117th/109th-minute extra-time winning goals are EXCLUDED.
    # No global alias; no guessed identity; no changed H1 signal.
    "2026-10-28,28717,61795": (
        "FK Viagem Pribram B", "SK Benešov",
        "2026-10-28T09:30:00+00:00", 2, 3,
        "https://www.eurofotbal.cz/souteze/cesko/cfl-a/2026-2027/reportaz/fk-pribram-b-sk-benesov-1092965/",
        "https://futebolmax.org/football/match/pribram-b-vs-benesov-2582090",
    ),
    "2026-10-28,28720,24581": (
        "FC Slovan Liberec II", "FC Zenit Caslav",
        "2026-10-28T10:00:00+00:00", 0, 0,
        "https://www.fcslovanliberec.cz/cz/match/5784-Svatecni-dohravka-branky-nenabidla-B-tym-remizoval-s-Caslavi",
        "https://www.eurofotbal.cz/souteze/cesko/cfl-b/2026-2027/reportaz/slovan-liberec-b-fk-caslav-1093061/",
    ),
    "2026-10-28,799,631": (
        "Nagoya Grampus Eight", "Urawa Red Diamonds",
        "2026-10-28T10:00:00+00:00", 1, 1,
        "https://www.urawa-reds.co.jp/topteamtopics/9029897.html",
        "https://www.redspress.jp/index/reds_report/ARTICLE1/2026102800003",
    ),
    "2026-10-28,55219,22939": (
        "Cigánd SE", "Paksi SE",
        "2026-10-28T11:30:00+00:00", 1, 2,
        "https://nb1.hu/hir/magyar-kupa-4-fordulo-eredmenyek/",
        "https://hatsofuves.nemzetisport.hu/labdarugo-nb-i/2026/10/a-loki-es-a-paks-a-hajraban-a-szpari-a-hosszabbitasban-harcolta-ki-a-tovabbjutast-a-mol-magyar-kupaban",
    ),
    "2026-10-28,10012613,10074748": (
        "Muranga Seal", "Nairobi United",
        "2026-10-28T12:00:00+00:00", 3, 2,
        "https://www.kovascore.com/football/match/sportpesa-premier-league/murang-a-seal-nairobi-united-4883398",
        "https://www.oddsgpt.com/asian-handicap/1629093/murang-a-seal-vs-nairobi-united/en",
    ),
    "2026-10-28,10038000,1142": (
        "OFK Vrsac", "Omladinski FK Beograd",
        "2026-10-28T12:00:00+00:00", 0, 1,
        "https://meridiansport.rs/fudbal/zvezdina-filijala-srusila-superligasa-romanticari-preziveli-odlazak-u-vrsac/",
        "https://www.dnevnik.rs/lat/sport/fudbal/suboticane-eliminisao-srpskoligas-kraj-za-spartak-kupu-superligasi-polozili-koplja-pred-teleoptikom-graficarom-2026-10-28",
    ),
    "2026-10-28,95299,1092": (
        "Marko", "Olympiakos",
        "2026-10-28T13:00:00+00:00", 0, 2,
        "https://www.epo.gr/el/arthra/marko-olympiakos-0-2",
        "https://www.sport24.gr/football/marko-olimpiakos-0-2-me-saliaka-kai-karmo-oi-erithrolefkoi-exoun-to-apolito-sto-superbet-kipello-elladas/",
    ),
    "2026-10-28,35198,74459": (
        "ACF Fiorentina U19", "FC Septemvri Sofia U19",
        "2026-10-28T13:30:00+00:00", 5, 0,
        "https://ng.soccerway.com/match/fiorentina-2TBysB6k/septemvri-sofia-80w3wjhQ/?mid=W8kExAdJ",
        "https://www.nove.firenze.it/primavera-goleada-europea-5-0-al-septemviri-sofia.htm",
    ),
    "2026-10-28,28354,23552": (
        "MKS Znicz Pruszków", "Ruch Chorzow",
        "2026-10-28T16:30:00+00:00", 0, 1,
        "https://pilkanozna.pl/ruch-zwycieski-w-pruszkowie-niebiescy-z-awansem-do-kolejnej-rundy/",
        "https://www.sporx.com/znicz-pruszkow-player1-bu-kulvarda-bu-sezonki-5-maci-anlatim-6280516",
    ),
    "2026-10-28,36192,993": (
        "Puszcza Niepolomice", "Wisła Płock",
        "2026-10-28T16:30:00+00:00", 1, 1,
        "https://www.scorebat.com/puszcza-n-vs-wisla-plock-live-stream/",
        "https://kanalsportowy.pl/relacja/puszcza-niepolomice-wisla-plock-2026-10-28/sklady/",
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
